"""Contrôles déterministes avant toute installation.

Chaque contrôle ici évite un aller-retour avec le bac à sable. Ils viennent
pour la plupart d'échecs réellement observés — pas d'une lecture de la
documentation.

Le contrôle du domaine, en particulier, encode le défaut qui a empêché
diligence_simple de s'installer : en Odoo 17, un domaine qui référence un champ
absent de la vue fait échouer le chargement de la vue, donc l'installation du
module. Il s'était manifesté deux fois — sur le formulaire, puis sur la liste.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from spec.module_spec import ModuleSpec

CLES_MANIFESTE = ("name", "version", "depends", "data", "license")
# Repère les champs cités dans un domaine : [('company_id', '=', ...)]
CHAMPS_DU_DOMAINE = re.compile(r"[('\"]([a-z][a-z0-9_]*)['\"]\s*,\s*['\"]?(?:=|!=|in|not in|like|ilike|<|>)")


@dataclass
class Anomalie:
    fichier: str
    message: str

    def __str__(self) -> str:
        return f"{self.fichier} : {self.message}"


@dataclass
class Rapport:
    anomalies: list[Anomalie]

    @property
    def ok(self) -> bool:
        return not self.anomalies

    def texte(self) -> str:
        if self.ok:
            return "Validation statique : PASS"
        lignes = [f"Validation statique : {len(self.anomalies)} anomalie(s)"]
        lignes += [f"  - {a}" for a in self.anomalies]
        return "\n".join(lignes)


class OdooStaticValidator:
    def check(self, fichiers: dict[str, str], spec: ModuleSpec) -> Rapport:
        anomalies: list[Anomalie] = []
        racine = spec.technical_name

        anomalies += self._structure(fichiers, racine)
        anomalies += self._python(fichiers)
        anomalies += self._xml(fichiers)
        manifeste = self._manifeste(fichiers, racine, anomalies)
        if manifeste:
            anomalies += self._donnees_declarees(fichiers, racine, manifeste)
        anomalies += self._droits(fichiers, spec, racine)
        anomalies += self._vues(fichiers, spec)

        return Rapport(anomalies)

    # ------------------------------------------------------------- structure

    def _structure(self, fichiers: dict[str, str], racine: str) -> list[Anomalie]:
        anomalies = []
        for attendu in (f"{racine}/__manifest__.py", f"{racine}/__init__.py"):
            if attendu not in fichiers:
                anomalies.append(Anomalie(attendu, "fichier obligatoire absent"))
        hors_racine = [c for c in fichiers if not c.startswith(f"{racine}/")]
        for chemin in hors_racine:
            anomalies.append(Anomalie(chemin, f"hors du dossier « {racine} »"))
        return anomalies

    # ---------------------------------------------------------------- python

    def _python(self, fichiers: dict[str, str]) -> list[Anomalie]:
        anomalies = []
        for chemin, contenu in fichiers.items():
            if not chemin.endswith(".py") or chemin.endswith("__manifest__.py"):
                continue
            try:
                ast.parse(contenu)
            except SyntaxError as erreur:
                anomalies.append(
                    Anomalie(chemin, f"Python invalide ligne {erreur.lineno} : {erreur.msg}")
                )
        return anomalies

    # ------------------------------------------------------------------- xml

    def _xml(self, fichiers: dict[str, str]) -> list[Anomalie]:
        anomalies = []
        for chemin, contenu in fichiers.items():
            if not chemin.endswith(".xml"):
                continue
            try:
                racine = ElementTree.fromstring(contenu)
            except ElementTree.ParseError as erreur:
                anomalies.append(Anomalie(chemin, f"XML invalide : {erreur}"))
                continue
            if racine.tag != "odoo":
                anomalies.append(
                    Anomalie(chemin, f"racine « {racine.tag} » au lieu de « odoo »")
                )
        return anomalies

    # ------------------------------------------------------------- manifeste

    def _manifeste(self, fichiers: dict[str, str], racine: str, anomalies: list) -> dict | None:
        chemin = f"{racine}/__manifest__.py"
        contenu = fichiers.get(chemin)
        if contenu is None:
            return None
        # Odoo lit le manifeste comme un littéral : il ne doit pas s'exécuter.
        sans_commentaires = "\n".join(
            l for l in contenu.splitlines() if not l.strip().startswith("#")
        )
        try:
            declare = ast.literal_eval(sans_commentaires)
        except (ValueError, SyntaxError) as erreur:
            anomalies.append(Anomalie(chemin, f"n'est pas un littéral Python : {erreur}"))
            return None
        if not isinstance(declare, dict):
            anomalies.append(Anomalie(chemin, "ne déclare pas un dictionnaire"))
            return None
        for cle in CLES_MANIFESTE:
            if not declare.get(cle):
                anomalies.append(Anomalie(chemin, f"clé « {cle} » absente ou vide"))
        return declare

    def _donnees_declarees(self, fichiers, racine, manifeste) -> list[Anomalie]:
        anomalies = []
        for relatif in manifeste.get("data", []):
            complet = f"{racine}/{relatif}"
            if complet not in fichiers:
                anomalies.append(
                    Anomalie(
                        f"{racine}/__manifest__.py",
                        f"« {relatif} » est déclaré dans data mais absent du module",
                    )
                )
        declares = set(manifeste.get("data", []))
        for chemin in fichiers:
            relatif = chemin[len(racine) + 1:]
            if relatif.endswith((".xml", ".csv")) and relatif not in declares:
                anomalies.append(
                    Anomalie(chemin, "présent mais jamais déclaré dans data : jamais chargé")
                )
        return anomalies

    # ---------------------------------------------------------------- droits

    def _droits(self, fichiers, spec: ModuleSpec, racine: str) -> list[Anomalie]:
        """Un modèle sans droit d'accès est inutilisable, même installé."""
        anomalies = []
        csv = fichiers.get(f"{racine}/security/ir.model.access.csv", "")
        for modele in spec.modeles_nouveaux:
            marqueur = f"model_{modele.name.replace('.', '_')}"
            if marqueur not in csv:
                anomalies.append(
                    Anomalie(
                        f"{racine}/security/ir.model.access.csv",
                        f"aucun droit d'accès pour « {modele.name} » : "
                        "le modèle sera inaccessible",
                    )
                )
        return anomalies

    # ------------------------------------------------------------------ vues

    def _vues(self, fichiers, spec: ModuleSpec) -> list[Anomalie]:
        anomalies = []
        # `tous_les_champs` inclut le champ d'état dérivé du cycle de vie : il
        # n'est pas saisi dans « fields » mais existe bel et bien sur le modèle.
        champs_par_modele = {
            m.name: {c.name for c in m.tous_les_champs} for m in spec.modeles_nouveaux
        }

        for chemin, contenu in fichiers.items():
            if not chemin.endswith(".xml"):
                continue
            try:
                racine_xml = ElementTree.fromstring(contenu)
            except ElementTree.ParseError:
                continue  # déjà signalé

            for record in racine_xml.iter("record"):
                if record.get("model") != "ir.ui.view":
                    continue
                modele = self._valeur(record, "model")
                arch = record.find("./field[@name='arch']")
                if arch is None:
                    continue

                # `arch.iter` renvoie aussi le noeud <field name="arch"> qui
                # porte l'architecture : il n'est pas un champ de la vue.
                champs_vue = [f for f in arch.iter("field") if f is not arch]
                presents = {f.get("name") for f in champs_vue if f.get("name")}

                # Invariant clé : un domaine ne peut citer qu'un champ présent.
                for champ in champs_vue:
                    domaine = champ.get("domain")
                    if not domaine:
                        continue
                    for cite in set(CHAMPS_DU_DOMAINE.findall(domaine)):
                        if cite not in presents:
                            anomalies.append(
                                Anomalie(
                                    chemin,
                                    f"le domaine de « {champ.get('name')} » référence "
                                    f"« {cite} », absent de la vue : Odoo 17 refusera "
                                    "de charger cette vue",
                                )
                            )

                # Sur un modèle que le module crée, tout champ doit exister.
                if modele in champs_par_modele:
                    connus = champs_par_modele[modele]
                    for nom in sorted(presents - connus):
                        anomalies.append(
                            Anomalie(
                                chemin,
                                f"la vue de « {modele} » utilise « {nom} », "
                                "qui n'est pas déclaré par le modèle",
                            )
                        )
        return anomalies

    @staticmethod
    def _valeur(record, nom: str) -> str | None:
        noeud = record.find(f"./field[@name='{nom}']")
        return noeud.text if noeud is not None else None
