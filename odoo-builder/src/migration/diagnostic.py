"""Parcourir un parc de modules et désigner ce qu'il faut y changer.

Le code n'est jamais exécuté : on le lit, ligne à ligne. Un module téléchargé
du store vient d'ailleurs ; le diagnostiquer ne doit pas être une façon de le
faire tourner.

CE QUE CE DIAGNOSTIC EST : la liste de ce qu'un outil SAIT reconnaître, avec
le fichier et la ligne, pour qu'un humain aille vérifier et corriger.

CE QU'IL N'EST PAS : une garantie. Ce qu'il ne connaît pas, il ne le voit pas.
La seule preuve reste l'installation dans un vrai Odoo de la version visée.
Un diagnostic vide ne veut pas dire « ça marchera » — il veut dire « je n'ai
rien reconnu de ce que je sais reconnaître ». La nuance n'est pas rhétorique :
c'est la différence entre un outil qui aide et un outil qui rassure à tort.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field

from migration.regles import BLOQUANT, MANUEL, ORDRE, SILENCIEUX, regles_pour

# Le préfixe de version d'un manifeste. Le contrôler à part des autres règles :
# ce n'est pas une écriture périmée, c'est une valeur à recalculer.
VERSION = re.compile(r"['\"]version['\"]\s*:\s*['\"]([^'\"]+)['\"]")
IGNORES = {".git", "__pycache__", "node_modules", ".idea"}


@dataclass
class Trouvaille:
    fichier: str
    ligne: int
    texte: str
    regle: object

    @property
    def gravite(self) -> str:
        return self.regle.gravite


@dataclass
class Module:
    nom: str
    chemin: str
    origine: str                       # d'où il vient (dossier ou archive)
    version: str = ""
    licence: str = ""
    trouvailles: list = field(default_factory=list)
    fichiers_js: int = 0
    erreur: str = ""

    def par_gravite(self, gravite: str) -> list:
        return [t for t in self.trouvailles if t.gravite == gravite]

    @property
    def total(self) -> int:
        return len(self.trouvailles)


def _lignes(chemin: str):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _pertinente(ligne: str, extension: str) -> bool:
    """Écarter les commentaires : ils citent souvent ce qu'ils remplacent.

    Un module bien tenu écrit « # remplace l'ancien attrs= » ; le compter
    ferait signaler un travail déjà fait, et le rapport perdrait sa valeur au
    premier faux positif.
    """
    nu = ligne.strip()
    if extension == ".py":
        return not nu.startswith("#")
    if extension == ".xml":
        return not nu.startswith("<!--")
    if extension == ".js":
        return not (nu.startswith("//") or nu.startswith("*") or nu.startswith("/*"))
    return True


def examiner(racine: str, nom: str, origine: str, cible: str) -> Module:
    """Un module, une version visée, la liste de ce qui doit changer."""
    module = Module(nom=nom, chemin=racine, origine=origine)
    regles = regles_pour(cible)
    majeure = int(str(cible).split(".")[0])

    manifeste = None
    for candidat in ("__manifest__.py", "__openerp__.py"):
        chemin = os.path.join(racine, candidat)
        if os.path.isfile(chemin):
            manifeste = chemin
            if candidat == "__openerp__.py":
                module.trouvailles.append(Trouvaille(
                    candidat, 0, candidat,
                    next(r for r in regles if r.cle == "manifeste_openerp")))
            break
    if manifeste is None:
        module.erreur = "aucun manifeste"
        return module

    contenu = "\n".join(_lignes(manifeste))
    correspondance = VERSION.search(contenu)
    module.version = correspondance.group(1) if correspondance else ""
    licence = re.search(r"['\"]license['\"]\s*:\s*['\"]([^'\"]+)['\"]", contenu)
    module.licence = licence.group(1) if licence else ""

    for dossier, sous, noms in os.walk(racine):
        sous[:] = [s for s in sous if s not in IGNORES]
        for fichier in sorted(noms):
            extension = os.path.splitext(fichier)[1]
            if extension not in (".py", ".xml", ".js"):
                continue
            complet = os.path.join(dossier, fichier)
            relatif = os.path.relpath(complet, racine)
            if extension == ".js":
                module.fichiers_js += 1
            applicables = [r for r in regles if extension in r.fichiers]
            if not applicables:
                continue
            for numero, ligne in enumerate(_lignes(complet), 1):
                if not _pertinente(ligne, extension):
                    continue
                for regle in applicables:
                    if regle.motif.search(ligne):
                        module.trouvailles.append(
                            Trouvaille(relatif, numero, ligne.strip()[:160], regle))

    module.trouvailles.extend(_version_du_manifeste(module, majeure, cible))
    return module


def _version_du_manifeste(module: Module, majeure: int, cible: str) -> list:
    """La série du manifeste doit être celle d'Odoo. Sinon rien ne démarre.

    Ce n'est pas une écriture périmée : c'est la première chose qui tombe, et
    elle ne tombe pas à l'installation du module mais à l'INITIALISATION de la
    base — Odoo lit tous les manifestes du chemin d'addons avant de créer quoi
    que ce soit. Un seul module d'une autre série suffit à empêcher Odoo 18 de
    démarrer.
    """
    if not module.version:
        return []
    morceaux = module.version.split(".")
    serie = ".".join(morceaux[:2]) if len(morceaux) >= 2 else module.version
    if serie == cible:
        return []

    class _Ad:
        gravite = BLOQUANT
        depuis = majeure
        quoi = f"version du manifeste « {module.version} »"
        faire = (f"écrire « {cible}.{'.'.join(morceaux[2:]) or '1.0.0'} » — "
                 f"la série d'Odoo d'abord, votre version fonctionnelle ensuite")
        source = ("Odoo refuse une version dont la série n'est pas la sienne, et "
                  "le refus arrive à l'initialisation de la base, pas à "
                  "l'installation du module.")
        cle = "version_manifeste"
    return [Trouvaille("__manifest__.py", 0, f"'version': '{module.version}'", _Ad())]


def parcourir(racine: str, cible: str, temporaire: str) -> list:
    """Tous les modules sous « racine » : dossiers déballés et archives ZIP.

    Les archives sont déballées dans un dossier temporaire, jamais à côté de
    leur source : un dossier de téléchargements n'a pas à se peupler de
    dossiers que personne n'a demandés.
    """
    modules = []
    for dossier, sous, noms in os.walk(racine):
        sous[:] = [s for s in sous if s not in IGNORES]
        if "__manifest__.py" in noms or "__openerp__.py" in noms:
            modules.append(examiner(dossier, os.path.basename(dossier),
                                    os.path.relpath(dossier, racine), cible))
            sous[:] = []
            continue
        for nom in sorted(noms):
            if not nom.lower().endswith(".zip"):
                continue
            archive = os.path.join(dossier, nom)
            destination = os.path.join(temporaire, os.path.relpath(archive, racine))
            try:
                os.makedirs(destination, exist_ok=True)
                with zipfile.ZipFile(archive) as z:
                    z.extractall(destination)
            except (zipfile.BadZipFile, OSError, RuntimeError) as erreur:
                perdu = Module(nom=nom, chemin=archive,
                               origine=os.path.relpath(archive, racine))
                perdu.erreur = f"archive illisible : {erreur}"
                modules.append(perdu)
                continue
            for sd, ss, sn in os.walk(destination):
                ss[:] = [s for s in ss if s not in IGNORES]
                if "__manifest__.py" in sn or "__openerp__.py" in sn:
                    modules.append(examiner(
                        sd, os.path.basename(sd),
                        f"{os.path.relpath(archive, racine)} → {os.path.basename(sd)}",
                        cible))
                    ss[:] = []
    return sorted(modules, key=lambda m: (-len(m.par_gravite(BLOQUANT)), m.nom))


def compter(modules: list) -> dict:
    return {
        gravite: sum(len(m.par_gravite(gravite)) for m in modules)
        for gravite in (BLOQUANT, SILENCIEUX, MANUEL)
    }
