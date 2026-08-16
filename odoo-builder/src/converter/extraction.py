"""Lire un module Odoo existant et en extraire une spécification.

C'est l'inverse exact du générateur, et c'est ce qui rend l'Atelier utile sur
l'existant : un module de v12 devient une spécification, que le générateur
rend ensuite en 17, 18 ou 19 — sans que personne réécrive le métier à la main.

DEUX RÈGLES TIENNENT CE FICHIER.

1. On ne fait jamais tourner le code lu. Pas d'« import », pas d'« exec » :
   « ast.parse » et rien d'autre. Un module converti vient d'ailleurs ; le
   convertir ne doit pas être une façon de l'exécuter.

2. Ce qu'on ne sait pas porter, on le NOMME. Un convertisseur qui laisse
   tomber une méthode en silence produit un module qui s'installe et se
   comporte mal — on l'apprend en production, sur le cas particulier que la
   méthode traitait. Le rapport est la sortie principale, pas un accessoire.

CE QUE LE CONVERTISSEUR N'INFÈRE PAS : les cycles de vie. Reconnaître
« def action_valider(self) » et en déduire une transition fonctionne sur les
cas simples et fabrique du faux sur les autres. Les méthodes sont donc
signalées une par une, avec l'état qu'elles écrivent quand on sait le lire, et
c'est à l'Atelier qu'on redécrit le circuit. Perdre visiblement vaut mieux que
gagner par hasard.
"""

from __future__ import annotations

import ast
import csv
import io
import os
import re
from xml.etree import ElementTree

from converter.rapport import COMPORTEMENT, OBSOLETE, STRUCTURE, RapportConversion
from spec.module_spec import (
    Acces, Action, Champ, Menu, Modele, ModuleSpec, Vue,
)

# Les constructeurs de champs que la spécification sait décrire.
TYPES_CHAMPS = {
    "Char": "char", "Text": "text", "Html": "html", "Integer": "integer",
    "Float": "float", "Monetary": "monetary", "Boolean": "boolean",
    "Date": "date", "Datetime": "datetime", "Selection": "selection",
    "Many2one": "many2one", "One2many": "one2many", "Many2many": "many2many",
    "Binary": "binary", "Image": "image",
}

# Le premier argument positionnel n'a pas le même sens selon le champ. C'est
# l'écriture courante avant Odoo 13 — « fields.Char('Nom') », « fields.Many2one
# ('res.partner', 'Client') » — et la manquer donnerait un comodèle nommé
# « Client ».
POSITIONNELS = {
    "many2one": ["comodel", "string"],
    "one2many": ["comodel", "inverse_name", "string"],
    "many2many": ["comodel"],
    "selection": ["selection", "string"],
}

# Les arguments qu'on sait reprendre tels quels.
ARGUMENTS_PORTES = {
    "string", "required", "readonly", "help", "default",
    "comodel_name", "inverse_name", "selection",
}
# Ceux qui ne changent rien d'observable : les signaler noierait le rapport.
ARGUMENTS_MUETS = {"index", "copy", "translate", "store", "size", "sanitize"}
# Ceux dont la valeur est du Python : ils ne peuvent pas entrer dans une
# spécification qui s'interdit le code libre.
ARGUMENTS_DE_CODE = {"compute", "related", "inverse", "search", "_compute"}

# Tournures disparues, à signaler pour elles-mêmes : elles auraient dû être
# réécrites de toute façon.
#
# SOURCE. Ces entrées ne viennent pas de la mémoire : elles sont relevées dans
# le journal officiel de l'ORM (dépôt odoo/documentation, branche 19.0,
# content/developer/reference/backend/orm/changelog.rst) puis vérifiées dans le
# code de la version concernée. Une différence supposée est pire qu'une
# différence ignorée — elle produit du code qui a l'air juste.
OBSOLETES_PYTHON = {
    "_columns": "déclaration de champs d'avant Odoo 8",
    "_defaults": "valeurs par défaut d'avant Odoo 8",
    "_track": "suivi de champs d'avant Odoo 12",
}

# Arguments de champ renommés par Odoo. Les signaler par leur nouveau nom vaut
# mieux que « argument inconnu » : c'est la différence entre une information et
# un haussement d'épaules.
ARGUMENTS_RENOMMES = {
    # odoo/documentation 19.0, orm/changelog.rst, « Odoo Online version 17.2 » :
    # « The group_operator attribute of Field is renamed into aggregator ».
    "group_operator": "renommé « aggregator » en Odoo 17.2",
    "track_visibility": "remplacé par « tracking » depuis Odoo 12",
    "oldname": "supprimé en Odoo 13",
    "digits_compute": "supprimé en Odoo 9, remplacé par « digits »",
}

# Méthodes de l'ORM dont le nom a changé, ou qui ont disparu. Le convertisseur
# ne porte aucune méthode ; mais dire « celle-ci n'existe plus » vaut mieux que
# « à réécrire », parce que la réécrire à l'identique ne marcherait pas.
METHODES_DISPARUES = {
    "name_get": "déprécié en Odoo 16.4 : lire le champ « display_name ».",
    "read_group": "déprécié en Odoo 18.2 au profit de « _read_group » "
                  "et « formatted_read_group ».",
    "_flush_search": "déprécié en Odoo 17.1.",
    "fields_view_get": "supprimé en Odoo 13 au profit de « get_view ».",
}
DECORATEURS_OBSOLETES = {
    "one": "@api.one a disparu en Odoo 13",
    "multi": "@api.multi a disparu en Odoo 13",
    "returns": "@api.returns n'a plus cours dans ce contexte",
    "cr": "signature « cr, uid, ids » d'avant Odoo 8",
    "cr_uid_ids": "signature « cr, uid, ids » d'avant Odoo 8",
}

VERSION_MANIFESTE = re.compile(r"^(\d+\.\d+)\.(\d+\.\d+(?:\.\d+)?)$")


class ConversionImpossible(Exception):
    """Le dossier fourni n'est pas un module Odoo lisible."""


# --------------------------------------------------------------------- outils


def _litteral(noeud):
    """La valeur d'un noeud s'il est littéral, « _CODE » sinon.

    On ne devine pas : « default=lambda self: ... » n'a pas de valeur, et en
    inventer une serait pire que de le signaler.
    """
    try:
        return ast.literal_eval(noeud)
    except (ValueError, SyntaxError, TypeError):
        return _CODE


class _Code:
    def __repr__(self):
        return "<expression Python>"


_CODE = _Code()


def _selection_lisible(valeur):
    """Une sélection n'est portable que si ses valeurs sont écrites en clair."""
    if valeur is _CODE or not isinstance(valeur, (list, tuple)):
        return None
    couples = []
    for element in valeur:
        if not isinstance(element, (list, tuple)) or len(element) != 2:
            return None
        cle, libelle = element
        if not isinstance(cle, str) or not isinstance(libelle, str):
            return None
        couples.append((cle, libelle))
    return couples or None


# --------------------------------------------------------------- extraction


class Extracteur:
    """Lit un dossier de module et produit (spécification, rapport)."""

    def __init__(self, racine: str, cible: str):
        self.racine = os.path.abspath(racine)
        self.cible = cible
        self.rapport = RapportConversion()
        self.modeles: dict[str, Modele] = {}
        # Les champs qu'on n'a pas su porter. Les vues qui les citent doivent
        # les oublier aussi : une vue qui référence un champ absent fait
        # échouer l'installation, et l'échec arriverait loin d'ici.
        self.champs_abandonnes: set[tuple[str, str]] = set()
        # Les modèles qu'on a sciemment écartés (assistants, modèles
        # abstraits). Tout ce qui les vise doit partir avec eux.
        self.modeles_ecartes: set[str] = set()
        self.vues: list[Vue] = []
        self.actions: list[Action] = []
        self.menus: list[Menu] = []
        self.acces: list[Acces] = []

    # ------------------------------------------------------------ entrée

    def convertir(self) -> tuple[ModuleSpec, RapportConversion]:
        if not os.path.isdir(self.racine):
            raise ConversionImpossible(f"« {self.racine} » n'est pas un dossier.")
        manifeste, chemin_manifeste = self._lire_manifeste()

        nom_technique = os.path.basename(self.racine)
        self.rapport.module = nom_technique

        for chemin in self._fichiers(".py"):
            self._lire_python(chemin)
        for chemin in self._fichiers(".xml"):
            self._lire_xml(chemin)
        for chemin in self._fichiers(".csv"):
            if os.path.basename(chemin) == "ir.model.access.csv":
                self._lire_acces(chemin)

        self._consolider()

        version_origine, version_fonctionnelle = self._versions(
            manifeste.get("version"), chemin_manifeste
        )
        self.rapport.version_origine = version_origine

        spec = ModuleSpec(
            technical_name=nom_technique,
            name=manifeste.get("name") or nom_technique,
            summary=manifeste.get("summary") or "",
            description=manifeste.get("description") or "",
            category=manifeste.get("category") or "Uncategorized",
            cible=self.cible,
            version=version_fonctionnelle,
            license=self._licence(manifeste, chemin_manifeste),
            depends=list(manifeste.get("depends") or ["base"]),
            application=bool(manifeste.get("application", False)),
            models=list(self.modeles.values()),
            views=self.vues,
            actions=self.actions,
            menus=self.menus,
            access=self.acces,
        )
        for quoi, combien in (
            ("modèles", len(spec.models)),
            ("champs", sum(len(m.fields) for m in spec.models)),
            ("vues", len(spec.views)),
            ("actions", len(spec.actions)),
            ("menus", len(spec.menus)),
            ("droits d'accès", len(spec.access)),
        ):
            if combien:
                self.rapport.compter(quoi, combien)
        return spec, self.rapport

    # ------------------------------------------------------------ manifeste

    def _lire_manifeste(self) -> tuple[dict, str]:
        for nom in ("__manifest__.py", "__openerp__.py"):
            chemin = os.path.join(self.racine, nom)
            if os.path.isfile(chemin):
                if nom == "__openerp__.py":
                    self.rapport.noter(
                        OBSOLETE, nom, 0, "manifeste « __openerp__.py »",
                        "ce nom de fichier n'est plus reconnu depuis Odoo 10.",
                        "le module converti porte « __manifest__.py ».",
                    )
                with open(chemin, encoding="utf-8") as f:
                    texte = f.read()
                try:
                    donnee = ast.literal_eval(texte[texte.index("{"):])
                except (ValueError, SyntaxError) as erreur:
                    raise ConversionImpossible(f"{nom} illisible : {erreur}")
                if not isinstance(donnee, dict):
                    raise ConversionImpossible(f"{nom} ne contient pas un dictionnaire.")
                return donnee, nom
        raise ConversionImpossible(
            "aucun manifeste : ni « __manifest__.py », ni « __openerp__.py »."
        )

    def _versions(self, brute, fichier) -> tuple[str, str]:
        """Sépare la série d'Odoo de la version fonctionnelle du module.

        C'est ici que la séparation « cible / version » paie : la série
        d'origine part au rapport, la version fonctionnelle survit à la
        conversion. Sans elle, un module 12.0.1.3.0 deviendrait 19.0.12.0.1.3.0
        ou perdrait son historique.
        """
        if not brute:
            self.rapport.noter(
                STRUCTURE, fichier, 0, "pas de version au manifeste",
                "Odoo lui donnerait « 1.0 » par défaut.",
                "le module converti part en 1.0.0.",
            )
            return "", "1.0.0"
        brute = str(brute)
        correspondance = VERSION_MANIFESTE.match(brute)
        if correspondance:
            return brute, correspondance.group(2)
        # Une version sans série (« 1.3.0 ») : rien à retrancher.
        return brute, brute

    def _licence(self, manifeste, fichier) -> str:
        licence = manifeste.get("license")
        if licence:
            return licence
        self.rapport.noter(
            STRUCTURE, fichier, 0, "pas de licence au manifeste",
            "Odoo suppose LGPL-3, ce qui n'est pas forcément votre intention.",
            "choisir explicitement la licence du module converti.",
        )
        return "LGPL-3"

    # ------------------------------------------------------------- fichiers

    def _fichiers(self, extension: str) -> list[str]:
        trouves = []
        for dossier, sous, noms in os.walk(self.racine):
            sous[:] = [s for s in sous if s not in ("__pycache__", ".git", "static")]
            for nom in sorted(noms):
                if nom.endswith(extension):
                    trouves.append(os.path.join(dossier, nom))
        return sorted(trouves)

    def _relatif(self, chemin: str) -> str:
        return os.path.relpath(chemin, self.racine)

    # --------------------------------------------------------------- Python

    def _lire_python(self, chemin: str) -> None:
        nom = os.path.basename(chemin)
        if nom in ("__init__.py", "__manifest__.py", "__openerp__.py"):
            return
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        try:
            arbre = ast.parse(source)
        except SyntaxError as erreur:
            self.rapport.noter(
                COMPORTEMENT, self._relatif(chemin), erreur.lineno or 0,
                "fichier Python illisible", f"erreur de syntaxe : {erreur.msg}",
                "ce fichier n'a pas pu être analysé du tout.",
            )
            return

        if re.search(r"^\s*from\s+openerp\b|^\s*import\s+openerp\b", source, re.M):
            self.rapport.noter(
                OBSOLETE, self._relatif(chemin), 1, "import « openerp »",
                "le paquet s'appelle « odoo » depuis la version 10.",
            )

        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.ClassDef):
                self._lire_classe(noeud, chemin)

    def _base_odoo(self, classe: ast.ClassDef) -> str | None:
        """Le genre de modèle : « model », « transient », « abstract »…"""
        for base in classe.bases:
            nom = ""
            if isinstance(base, ast.Attribute):
                nom = base.attr
            elif isinstance(base, ast.Name):
                nom = base.id
            if nom in ("Model", "TransientModel", "AbstractModel"):
                return nom
            if nom in ("osv", "Model_osv", "osv_memory"):
                return "osv"
        return None

    def _lire_classe(self, classe: ast.ClassDef, chemin: str) -> None:
        genre = self._base_odoo(classe)
        if genre is None:
            return
        fichier = self._relatif(chemin)

        if genre == "osv":
            self.rapport.noter(
                OBSOLETE, fichier, classe.lineno, f"classe « {classe.name} » sur osv.osv",
                "l'ancienne couche « osv » a disparu en Odoo 10.",
            )
        entetes = self._entetes(classe, fichier)

        if genre in ("TransientModel", "AbstractModel"):
            # Le modèle est écarté — mais il faut retenir SON NOM. Ses vues,
            # actions et droits sont dans le même module ; les laisser passer
            # produirait un module qui décrit des écrans pour un modèle
            # inexistant, et l'installation échouerait loin d'ici.
            nom_ecarte = entetes.get("_name") or entetes.get("_inherit")
            if isinstance(nom_ecarte, list):
                nom_ecarte = nom_ecarte[0] if nom_ecarte else None
            if nom_ecarte:
                self.modeles_ecartes.add(nom_ecarte)
            quoi = ("assistant" if genre == "TransientModel" else "modèle abstrait")
            self.rapport.noter(
                STRUCTURE, fichier, classe.lineno, f"{quoi} « {classe.name} »",
                "la spécification ne décrit que des modèles concrets et leurs "
                "extensions.",
                "à refaire dans l'Atelier une fois ce vocabulaire disponible.",
            )
            return

        nom = entetes.get("_name")
        heritage = entetes.get("_inherit")
        if isinstance(heritage, list):
            # « _inherit = ['mail.thread', 'x.y'] » : mélange d'héritage et de
            # mixins. La spécification ne connaît qu'une extension simple.
            self.rapport.noter(
                STRUCTURE, fichier, classe.lineno,
                f"héritage multiple {heritage} sur « {classe.name} »",
                "la spécification n'exprime qu'une extension d'un seul modèle.",
                "les mixins (mail.thread…) sont à redemander dans l'Atelier.",
            )
            heritage = heritage[0] if heritage else None

        if not nom and not heritage:
            return
        if not nom:
            nom = heritage

        modele = self.modeles.get(nom)
        if modele is None:
            modele = Modele(
                name=nom,
                description=entetes.get("_description") or "",
                inherit=heritage if (heritage and not entetes.get("_name")) else None,
                rec_name=entetes.get("_rec_name"),
            )
            self.modeles[nom] = modele

        for corps in classe.body:
            if isinstance(corps, ast.Assign):
                self._lire_assignation(corps, modele, fichier)
            elif isinstance(corps, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._lire_methode(corps, modele, fichier)

    def _entetes(self, classe: ast.ClassDef, fichier: str) -> dict:
        """Les attributs de classe d'Odoo : _name, _inherit, _description…"""
        trouves = {}
        for corps in classe.body:
            if not isinstance(corps, ast.Assign) or len(corps.targets) != 1:
                continue
            cible = corps.targets[0]
            if not isinstance(cible, ast.Name) or not cible.id.startswith("_"):
                continue
            valeur = _litteral(corps.value)
            if cible.id in ("_name", "_inherit", "_description", "_rec_name"):
                trouves[cible.id] = None if valeur is _CODE else valeur
            elif cible.id in OBSOLETES_PYTHON:
                self.rapport.noter(
                    OBSOLETE, fichier, corps.lineno, f"« {cible.id} »",
                    OBSOLETES_PYTHON[cible.id],
                )
            elif cible.id in ("_sql_constraints", "_constraints"):
                # Odoo 19 ne les applique PLUS. Il se contente d'un
                # avertissement dans le journal (odoo/orm/model_classes.py,
                # 19.0 l. 162) : « Model attribute '_sql_constraints' is no
                # longer supported, please define models.Constraint on the
                # model. » Le module s'installe, la ligne défile, et une
                # contrainte d'unicité qui protégeait les données depuis des
                # années cesse d'exister sans que rien ne le signale à
                # l'utilisateur. C'est pourquoi le message ne parle pas
                # seulement de conversion : garder ce code tel quel ne
                # sauverait pas la contrainte non plus.
                self.rapport.noter(
                    COMPORTEMENT, fichier, corps.lineno, f"« {cible.id} »",
                    "Odoo 19 ne l'applique plus : il journalise un "
                    "avertissement et la contrainte disparaît sans erreur. "
                    "La recopier telle quelle dans le module converti ne la "
                    "rétablirait donc pas.",
                    "à redemander dans l'Atelier comme contrainte, ou à "
                    "réécrire en « models.Constraint » pour Odoo 19.",
                )
            elif cible.id == "_inherits":
                self.rapport.noter(
                    COMPORTEMENT, fichier, corps.lineno, "« _inherits » (délégation)",
                    "la délégation crée un champ et une jointure implicites que "
                    "la spécification ne décrit pas.",
                )
            elif cible.id in ("_order", "_check_company_auto", "_parent_name",
                              "_parent_store", "_log_access"):
                self.rapport.noter(
                    STRUCTURE, fichier, corps.lineno, f"« {cible.id} »",
                    "attribut de modèle absent du vocabulaire de la spécification.",
                )
        return trouves

    # ---------------------------------------------------------------- champs

    def _lire_assignation(self, noeud: ast.Assign, modele: Modele, fichier: str) -> None:
        if len(noeud.targets) != 1 or not isinstance(noeud.targets[0], ast.Name):
            return
        nom = noeud.targets[0].id
        if nom.startswith("_"):
            return
        appel = noeud.value
        if not isinstance(appel, ast.Call) or not isinstance(appel.func, ast.Attribute):
            return
        conteneur = appel.func.value
        if not (isinstance(conteneur, ast.Name) and conteneur.id == "fields"):
            return
        constructeur = appel.func.attr

        if constructeur not in TYPES_CHAMPS:
            self.rapport.noter(
                STRUCTURE, fichier, noeud.lineno, f"champ « {nom} » de type {constructeur}",
                "ce type de champ n'est pas au vocabulaire de la spécification.",
                "les vues qui le citaient l'oublieront.",
            )
            self.champs_abandonnes.add((modele.name, nom))
            return

        type_champ = TYPES_CHAMPS[constructeur]
        arguments = self._arguments(appel, type_champ)

        # Un champ dont la VALEUR vient du code ne peut pas être dégradé en
        # champ ordinaire. Le garder produirait une colonne toujours vide, que
        # l'écran afficherait sans broncher : le module s'installerait et
        # mentirait. On l'abandonne, et on le dit.
        sources = arguments.pop("_code_valeur", [])
        if sources:
            cles = ", ".join(sorted({c for c, _ in sources}))
            self.rapport.noter(
                COMPORTEMENT, fichier, sources[0][1], f"champ « {nom} » ({cles}=…)",
                "sa valeur vient de code Python ; le garder sans ce code "
                "donnerait un champ toujours vide, affiché comme s'il était juste.",
                "à redécrire dans l'Atelier comme expression calculée.",
            )
            self.champs_abandonnes.add((modele.name, nom))
            return

        # Une valeur par défaut illisible, en revanche, ne fausse rien : le
        # champ existe et se saisit, il démarre seulement vide.
        for cle, position in arguments.pop("_code_defaut", []):
            self.rapport.noter(
                STRUCTURE, fichier, position, f"champ « {nom} » : {cle}=…",
                "la valeur n'est pas écrite en clair ; le champ est conservé sans elle.",
            )
        for cle in arguments.pop("_inconnus", []):
            self.rapport.noter(
                OBSOLETE if cle in ARGUMENTS_RENOMMES else STRUCTURE,
                fichier, noeud.lineno, f"champ « {nom} » : {cle}=…",
                ARGUMENTS_RENOMMES.get(
                    cle, "argument absent du vocabulaire de la spécification."
                ),
            )

        if type_champ == "selection" and not arguments.get("selection"):
            self.rapport.noter(
                COMPORTEMENT, fichier, noeud.lineno, f"champ « {nom} » : sélection illisible",
                "les valeurs ne sont pas écrites en clair (fonction, variable…).",
                "les vues qui le citaient l'oublieront.",
            )
            self.champs_abandonnes.add((modele.name, nom))
            return
        if type_champ in ("many2one", "one2many", "many2many") and not arguments.get("comodel"):
            self.rapport.noter(
                COMPORTEMENT, fichier, noeud.lineno, f"champ « {nom} » : comodèle illisible",
                "le modèle visé n'est pas écrit en clair.",
                "les vues qui le citaient l'oublieront.",
            )
            self.champs_abandonnes.add((modele.name, nom))
            return
        if type_champ == "one2many" and not arguments.get("inverse_name"):
            self.rapport.noter(
                COMPORTEMENT, fichier, noeud.lineno, f"champ « {nom} » : inverse illisible",
                "Odoo refuserait un one2many sans champ inverse.",
                "les vues qui le citaient l'oublieront.",
            )
            self.champs_abandonnes.add((modele.name, nom))
            return

        if any(c.name == nom for c in modele.fields):
            return
        modele.fields.append(Champ(
            name=nom,
            type=type_champ,
            string=arguments.get("string") or nom.replace("_", " ").capitalize(),
            required=bool(arguments.get("required")),
            readonly=bool(arguments.get("readonly")),
            comodel=arguments.get("comodel"),
            inverse_name=arguments.get("inverse_name"),
            selection=arguments.get("selection") or [],
            default=arguments.get("default"),
            help=arguments.get("help"),
        ))

    def _arguments(self, appel: ast.Call, type_champ: str) -> dict:
        """Les arguments d'un champ, positionnels compris."""
        trouves: dict = {"_code_valeur": [], "_code_defaut": [], "_inconnus": []}

        for rang, argument in enumerate(appel.args):
            noms = POSITIONNELS.get(type_champ, ["string"])
            if rang >= len(noms):
                continue
            cle = noms[rang]
            valeur = _litteral(argument)
            if valeur is _CODE:
                trouves["_code_defaut"].append(
                    (cle, getattr(argument, "lineno", appel.lineno))
                )
                continue
            if cle == "selection":
                trouves["selection"] = _selection_lisible(valeur)
            else:
                trouves[cle] = valeur

        for motcle in appel.keywords:
            cle = motcle.arg
            if cle is None:          # **kwargs
                continue
            if cle in ARGUMENTS_MUETS:
                continue
            valeur = _litteral(motcle.value)
            position = getattr(motcle.value, "lineno", appel.lineno)
            if cle in ARGUMENTS_DE_CODE:
                trouves["_code_valeur"].append((cle, position))
                continue
            if cle not in ARGUMENTS_PORTES:
                trouves["_inconnus"].append(cle)
                continue
            if valeur is _CODE:
                trouves["_code_defaut"].append((cle, position))
                continue
            if cle == "selection":
                trouves["selection"] = _selection_lisible(valeur)
            elif cle == "comodel_name":
                trouves["comodel"] = valeur
            else:
                trouves[cle] = valeur
        return trouves

    # -------------------------------------------------------------- méthodes

    def _lire_methode(self, noeud, modele: Modele, fichier: str) -> None:
        """Toute méthode est signalée. Aucune n'est devinée.

        On enrichit le message quand la méthode écrit visiblement un état :
        c'est l'information qui permet de redécrire la transition dans
        l'Atelier, sans qu'on prétende l'avoir portée.
        """
        genre = "méthode"
        for decorateur in noeud.decorator_list:
            attribut = decorateur.func.attr if isinstance(decorateur, ast.Call) and \
                isinstance(decorateur.func, ast.Attribute) else \
                (decorateur.attr if isinstance(decorateur, ast.Attribute) else "")
            if attribut in DECORATEURS_OBSOLETES:
                self.rapport.noter(
                    OBSOLETE, fichier, noeud.lineno, f"« @api.{attribut} » sur {noeud.name}",
                    DECORATEURS_OBSOLETES[attribut],
                )
            genre = {
                "depends": "champ calculé", "constrains": "contrainte",
                "onchange": "onchange", "model_create_multi": "surcharge de création",
            }.get(attribut, genre)

        if noeud.name in METHODES_DISPARUES:
            # Dire « à réécrire » serait un mauvais conseil : réécrite à
            # l'identique, elle ne serait plus appelée par personne.
            self.rapport.noter(
                OBSOLETE, fichier, noeud.lineno, f"surcharge de « {noeud.name} »",
                METHODES_DISPARUES[noeud.name],
            )

        ecrits = self._etats_ecrits(noeud)
        conduite = (
            f"porte « {ecrits[0]} » à {', '.join(repr(v) for v in ecrits[1])} ; "
            "à redécrire comme transition dans l'Atelier."
            if ecrits else
            "à redécrire dans l'Atelier, ou à réécrire à la main après conversion."
        )
        self.rapport.noter(
            COMPORTEMENT, fichier, noeud.lineno, f"{genre} « {noeud.name} »",
            "la spécification ne contient jamais de Python : cette méthode "
            "n'est pas portée.",
            conduite,
        )

    def _etats_ecrits(self, noeud) -> tuple[str, list[str]] | None:
        """« self.state = 'x' » ou « self.write({'state': 'x'}) », rien de plus.

        Volontairement borné : on décrit ce qu'on a vu, on n'en déduit pas un
        circuit.
        """
        champ = None
        valeurs: list[str] = []
        for interne in ast.walk(noeud):
            if isinstance(interne, ast.Assign) and len(interne.targets) == 1:
                cible = interne.targets[0]
                valeur = _litteral(interne.value)
                if isinstance(cible, ast.Attribute) and isinstance(valeur, str):
                    champ = champ or cible.attr
                    if cible.attr == champ:
                        valeurs.append(valeur)
            elif isinstance(interne, ast.Call) and isinstance(interne.func, ast.Attribute) \
                    and interne.func.attr == "write" and interne.args:
                ecrit = _litteral(interne.args[0])
                if isinstance(ecrit, dict):
                    for cle, valeur in ecrit.items():
                        if isinstance(cle, str) and isinstance(valeur, str):
                            champ = champ or cle
                            if cle == champ:
                                valeurs.append(valeur)
        return (champ, valeurs) if champ and valeurs else None

    # ------------------------------------------------------------------- XML

    def _lire_xml(self, chemin: str) -> None:
        fichier = self._relatif(chemin)
        try:
            arbre = ElementTree.parse(chemin)
        except ElementTree.ParseError as erreur:
            self.rapport.noter(
                STRUCTURE, fichier, 0, "fichier XML illisible", str(erreur),
            )
            return
        racine = arbre.getroot()
        if racine.tag == "openerp":
            self.rapport.noter(
                OBSOLETE, fichier, 1, "racine « <openerp> »",
                "la racine s'écrit « <odoo> » depuis la version 10.",
            )

        for element in racine.iter():
            if element.tag == "record":
                self._lire_enregistrement(element, fichier)
            elif element.tag == "menuitem":
                self._lire_menu(element, fichier)
            elif element.tag == "template":
                self.rapport.noter(
                    STRUCTURE, fichier, 0,
                    f"gabarit QWeb « {element.get('id', '?')} »",
                    "la spécification ne décrit pas les gabarits QWeb.",
                )
            elif element.tag == "function":
                self.rapport.noter(
                    COMPORTEMENT, fichier, 0,
                    f"appel « <function model={element.get('model', '?')}> »",
                    "du code appelé au chargement des données ; non porté.",
                )
            elif element.tag == "act_window":
                self.rapport.noter(
                    OBSOLETE, fichier, 0, f"« <act_window id={element.get('id', '?')}> »",
                    "cette forme abrégée a disparu en Odoo 17.",
                    "à redéclarer comme action dans l'Atelier.",
                )

    def _champ_texte(self, enregistrement, nom):
        for champ in enregistrement.findall("field"):
            if champ.get("name") == nom:
                return (champ.text or "").strip() or champ.get("ref") or ""
        return ""

    def _lire_enregistrement(self, enregistrement, fichier: str) -> None:
        modele = enregistrement.get("model") or ""
        identifiant = enregistrement.get("id") or "?"

        if modele == "ir.ui.view":
            self._lire_vue(enregistrement, fichier, identifiant)
        elif modele == "ir.actions.act_window":
            self._lire_action(enregistrement, fichier, identifiant)
        elif modele == "ir.ui.menu":
            self._lire_menu(enregistrement, fichier)
        else:
            genre = COMPORTEMENT if modele in (
                "ir.cron", "ir.actions.server", "base.automation"
            ) else STRUCTURE
            self.rapport.noter(
                genre, fichier, 0, f"enregistrement « {identifiant} » ({modele})",
                "ce type d'enregistrement n'est pas au vocabulaire de la spécification.",
            )

    def _lire_vue(self, enregistrement, fichier: str, identifiant: str) -> None:
        modele = self._champ_texte(enregistrement, "model")
        if not modele:
            return
        for champ in enregistrement.findall("field"):
            if champ.get("name") == "inherit_id":
                self.rapport.noter(
                    STRUCTURE, fichier, 0, f"vue héritée « {identifiant} »",
                    "la spécification décrit des vues entières, pas des greffes "
                    "sur une vue existante.",
                    "à redemander dans l'Atelier une fois l'héritage de vues au "
                    "vocabulaire.",
                )
                return

        arch = None
        for champ in enregistrement.findall("field"):
            if champ.get("name") == "arch":
                arch = champ
        if arch is None or len(arch) == 0:
            return
        racine = arch[0]

        # « list » depuis Odoo 18, « tree » avant : la spécification retient un
        # seul nom, et c'est le dialecte qui rend celui de la version visée.
        # Sans cette normalisation, convertir un module 18 vers 17 produirait
        # une vue « list » qu'Odoo 17 ne connaît pas.
        type_vue = "tree" if racine.tag == "list" else racine.tag

        for element in racine.iter():
            for perime in ("attrs", "states"):
                if element.get(perime):
                    self.rapport.noter(
                        OBSOLETE, fichier, 0,
                        f"vue « {identifiant} » : attribut « {perime} »",
                        "supprimé en Odoo 17 au profit de « invisible », "
                        "« readonly » et « required » directs.",
                    )
                    break
            if element.tag == "button" and element.get("type") == "object":
                self.rapport.noter(
                    COMPORTEMENT, fichier, 0,
                    f"vue « {identifiant} » : bouton « {element.get('name', '?')} »",
                    "le bouton appelle une méthode qui n'est pas portée.",
                    "la transition est à redécrire dans l'Atelier.",
                )

        champs = []
        for element in racine.iter("field"):
            nom = element.get("name")
            if nom and nom not in champs:
                champs.append(nom)

        self.vues.append(Vue(
            model=modele,
            type=type_vue,
            name=self._champ_texte(enregistrement, "name") or identifiant,
            fields=champs,
        ))

    def _lire_action(self, enregistrement, fichier: str, identifiant: str) -> None:
        modele = self._champ_texte(enregistrement, "res_model")
        if not modele:
            return
        if self._champ_texte(enregistrement, "view_type"):
            self.rapport.noter(
                OBSOLETE, fichier, 0, f"action « {identifiant} » : « view_type »",
                "ce champ a disparu en Odoo 12.",
            )
        modes = [
            "tree" if m.strip() == "list" else m.strip()
            for m in (self._champ_texte(enregistrement, "view_mode") or "tree,form").split(",")
            if m.strip()
        ]
        self.actions.append(Action(
            id=re.sub(r"[^a-z0-9_]", "_", identifiant.lower()),
            name=self._champ_texte(enregistrement, "name") or identifiant,
            model=modele,
            view_modes=modes,
            domain=self._champ_texte(enregistrement, "domain") or "[]",
            context=self._champ_texte(enregistrement, "context") or "{}",
        ))

    def _lire_menu(self, element, fichier: str) -> None:
        identifiant = element.get("id")
        if not identifiant:
            return
        self.menus.append(Menu(
            id=re.sub(r"[^a-z0-9_]", "_", identifiant.lower()),
            name=element.get("name") or identifiant,
            parent=element.get("parent"),
            action=element.get("action"),
            sequence=int(element.get("sequence") or 10),
        ))

    # ------------------------------------------------------------ droits CSV

    def _lire_acces(self, chemin: str) -> None:
        fichier = self._relatif(chemin)
        with open(chemin, encoding="utf-8") as f:
            lecteur = csv.DictReader(io.StringIO(f.read()))
            for ligne in lecteur:
                reference = (ligne.get("model_id:id") or ligne.get("model_id/id") or "").strip()
                modele = self._modele_depuis_reference(reference)
                if not modele:
                    self.rapport.noter(
                        STRUCTURE, fichier, 0, f"droit sur « {reference} »",
                        "le modèle visé n'a pas été trouvé parmi ceux du module.",
                    )
                    continue
                droits = "".join(
                    lettre for lettre, colonne in (
                        ("r", "perm_read"), ("w", "perm_write"),
                        ("c", "perm_create"), ("d", "perm_unlink"),
                    )
                    if str(ligne.get(colonne, "0")).strip() in ("1", "True", "true")
                )
                self.acces.append(Acces(
                    model=modele,
                    group=(ligne.get("group_id:id") or "base.group_user").strip()
                    or "base.group_user",
                    perms=droits or "r",
                ))

    def _modele_depuis_reference(self, reference: str) -> str | None:
        """« model_mission_request » → « mission.request », sans deviner.

        On résout contre les modèles réellement trouvés : remplacer bêtement
        les « _ » par des « . » ferait de « mission_request_line » un
        « mission.request.line » plausible et faux dès que le vrai modèle
        s'appelle « mission.request_line ».
        """
        court = reference.split(".")[-1]
        if not court.startswith("model_"):
            return None
        aplati = court[len("model_"):]
        for nom in self.modeles:
            if nom.replace(".", "_") == aplati:
                return nom
        return None

    # ------------------------------------------------------------ consolidation

    def _consolider(self) -> None:
        """Rendre l'ensemble installable, ou dire pourquoi il ne l'est pas.

        Un module d'origine est cohérent chez lui : ses vues citent des champs
        qui existent, ses identifiants sont uniques. La conversion casse les
        deux — elle abandonne des champs, et elle refabrique les identifiants
        depuis le modèle et le type de vue. Sans cette passe, on produit un
        module qui passe la validation statique et qu'Odoo refuse à
        l'installation, c'est-à-dire l'échec le plus coûteux à diagnostiquer.
        """
        self._ecarter_ce_qui_suit_les_modeles_ecartes()
        self._nettoyer_champs_de_vues()
        self._deduire_doublons()
        self._recoller_references_de_menus()
        self._droits_manquants()

    def _droits_manquants(self) -> None:
        """Un modèle sans droits d'accès n'est utilisable que par le super-utilisateur.

        C'est fréquent dans les modules anciens, où les droits vivaient
        ailleurs ou nulle part. Deux conduites étaient possibles : refuser de
        convertir, ou inventer le minimum.

        On invente — et on le dit fort. Refuser laisserait l'utilisateur sans
        recours, puisque le convertisseur ne prend pas de droits en entrée.
        Mais inventer des droits est la seule chose que fait ce fichier qui
        rende le module converti PLUS permissif que l'original : cela ne doit
        jamais passer inaperçu.
        """
        couverts = {a.model for a in self.acces}
        for nom, modele in self.modeles.items():
            if modele.est_extension or nom in couverts:
                continue
            self.acces.append(Acces(model=nom, group="base.group_user", perms="rwcd"))
            self.rapport.noter(
                COMPORTEMENT, "security/ir.model.access.csv", 0,
                f"droits inventés sur « {nom} »",
                "le module d'origine n'en déclarait aucun : le modèle n'y était "
                "utilisable que par le super-utilisateur. Le module converti "
                "l'ouvre en lecture, écriture, création et suppression aux "
                "utilisateurs internes — il est donc PLUS permissif que l'original.",
                "à restreindre avant toute mise en production.",
            )

    def _ecarter_ce_qui_suit_les_modeles_ecartes(self) -> None:
        """Un écran sans son modèle est une erreur d'installation garantie.

        Écarter un assistant sans écarter sa vue produit un module qui décrit
        un formulaire pour un modèle que rien ne déclare. La validation
        statique l'attrape — mais elle le présente comme une dépendance
        manquante, à des lieues de la vraie cause.
        """
        if not self.modeles_ecartes:
            return
        suivis = []
        for vue in self.vues:
            if vue.model in self.modeles_ecartes:
                suivis.append(f"vue {vue.type} de « {vue.model} »")
        for action in self.actions:
            if action.model in self.modeles_ecartes:
                suivis.append(f"action « {action.id} »")
        for droit in self.acces:
            if droit.model in self.modeles_ecartes:
                suivis.append(f"droits sur « {droit.model} »")

        self.vues = [v for v in self.vues if v.model not in self.modeles_ecartes]
        self.actions = [a for a in self.actions if a.model not in self.modeles_ecartes]
        self.acces = [d for d in self.acces if d.model not in self.modeles_ecartes]
        ouvrantes = {a.id for a in self.actions}
        self.menus = [
            m for m in self.menus
            if not m.action or "." in m.action
            or re.sub(r"[^a-z0-9_]", "_", m.action.lower()) in ouvrantes
        ]

        for quoi in suivis:
            self.rapport.noter(
                STRUCTURE, "conversion", 0, quoi,
                "porte sur un modèle écarté ci-dessus ; il part avec lui.",
            )

    def _nettoyer_champs_de_vues(self) -> None:
        """Une vue ne doit jamais citer un champ que le modèle n'a pas.

        Deux causes distinctes, même conséquence. Le champ a pu être abandonné
        à la conversion ; ou il appartient à une sous-vue en ligne — les
        champs d'un one2many affiché dans un formulaire sont ceux du comodèle,
        et on les a ramassés avec les autres en parcourant l'arbre.
        """
        for vue in self.vues:
            modele = self.modeles.get(vue.model)
            if modele is None:
                continue
            # Sur une extension, les champs du module d'origine nous sont
            # inconnus : filtrer les retirerait tous.
            if modele.est_extension:
                continue
            connus = {c.name for c in modele.fields}
            connus.update({"id", "display_name", "create_date", "write_date"})
            retires = [c for c in vue.fields if c not in connus]
            if retires:
                vue.fields = [c for c in vue.fields if c in connus]
                self.rapport.noter(
                    STRUCTURE, "vues", 0,
                    f"vue {vue.type} de « {vue.model} » : {retires} retiré(s)",
                    "ces champs n'existent pas sur le modèle converti — champ "
                    "non porté, ou champ d'une sous-vue en ligne.",
                    "à replacer dans l'Atelier si l'écran en a besoin.",
                )

    def _deduire_doublons(self) -> None:
        """Le générateur nomme les vues d'après le modèle et le type.

        Deux vues « tree » du même modèle produiraient donc deux fois le même
        identifiant XML, et Odoo refuse le module. On garde la première et on
        le dit — plutôt que d'inventer un suffixe qui ferait croire que les
        deux écrans ont survécu.
        """
        vues, vues_vues = [], set()
        for vue in self.vues:
            cle = (vue.model, vue.type)
            if cle in vues_vues:
                self.rapport.noter(
                    STRUCTURE, "vues", 0,
                    f"seconde vue {vue.type} de « {vue.model} » (« {vue.name} »)",
                    "la spécification ne retient qu'une vue par modèle et par type.",
                    "seule la première est conservée.",
                )
                continue
            vues_vues.add(cle)
            vues.append(vue)
        self.vues = vues

        acces, par_cle = [], {}
        for droit in self.acces:
            cle = (droit.model, droit.group)
            if cle in par_cle:
                # Fusionner les droits plutôt que d'en perdre : deux lignes
                # pour le même couple sont presque toujours une addition.
                ancien = par_cle[cle]
                ancien.perms = "".join(
                    lettre for lettre in "rwcd"
                    if lettre in ancien.perms or lettre in droit.perms
                )
                continue
            par_cle[cle] = droit
            acces.append(droit)
        self.acces = acces

        for liste, quoi in ((self.actions, "action"), (self.menus, "menu")):
            vus = set()
            gardes = []
            for element in liste:
                if element.id in vus:
                    self.rapport.noter(
                        STRUCTURE, "données", 0,
                        f"{quoi} « {element.id} » en double",
                        "deux identifiants d'origine se ramènent au même nom.",
                        "seul le premier est conservé.",
                    )
                    continue
                vus.add(element.id)
                gardes.append(element)
            liste[:] = gardes

    def _recoller_references_de_menus(self) -> None:
        """Les identifiants ont été normalisés : les renvois doivent suivre.

        Un menu qui pointe « parent="Menu_Racine" » désigne un identifiant que
        la conversion a écrit « menu_racine ». Laisser le renvoi tel quel
        donnerait une référence introuvable au chargement — et le message
        d'Odoo ne dirait pas que c'est la conversion qui a renommé.
        """
        actions = {a.id for a in self.actions}
        menus = {m.id for m in self.menus}
        for menu in self.menus:
            for attribut, connus in (("parent", menus), ("action", actions)):
                valeur = getattr(menu, attribut)
                if not valeur or "." in valeur:
                    continue          # référence à un autre module : intacte
                normalise = re.sub(r"[^a-z0-9_]", "_", valeur.lower())
                if normalise in connus:
                    setattr(menu, attribut, normalise)
                elif normalise != valeur:
                    setattr(menu, attribut, normalise)


def convertir(racine: str, cible: str) -> tuple[ModuleSpec, RapportConversion]:
    """Lit le module du dossier « racine » et le décrit pour la version « cible »."""
    return Extracteur(racine, cible).convertir()
