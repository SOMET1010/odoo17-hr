"""Boucle de réparation : générer, installer, corriger, recommencer.

Deux règles tiennent cette boucle :

1. **Le modèle ne voit pas tout le projet.** On lui donne la spécification,
   l'erreur, et les seuls fichiers que l'erreur désigne. Redonner l'ensemble à
   chaque tour coûte cher et produit des réécritures massives là où un champ
   manquait.

2. **Le modèle ne corrige que la spécification.** Il ne touche jamais aux
   fichiers générés : sa correction repasse par le générateur et le validateur,
   donc par les mêmes invariants. Une réparation ne peut pas contourner les
   contrôles.

La boucle s'arrête au bout de `tentatives_max` et rend le diagnostic plutôt que
de tourner indéfiniment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ai.provider import AIProvider, ErreurFournisseur
from generator.odoo_module_generator import OdooModuleGenerator
from installer.odoo_install_client import OdooInstallClient, Resultat
from spec.module_spec import ModuleSpec, SpecInvalide
from validator.odoo_static_validator import OdooStaticValidator

CONSIGNE_REPARATION = """Tu corriges la spécification JSON d'un module Odoo 17 qui a échoué.

Rends UNIQUEMENT un objet JSON, la spécification complète corrigée, au même
format que celle fournie. N'ajoute aucun commentaire.

Règles :
- corrige la cause de l'erreur, pas autre chose ;
- ne renomme pas le module ;
- si un domaine référence un champ, ce champ doit figurer dans la vue, au
  besoin via « invisible_fields » ;
- tout modèle créé par le module doit avoir une entrée dans « access »."""

# Repère les fichiers cités par une erreur Odoo, pour ne joindre que ceux-là.
FICHIERS_CITES = re.compile(r"([\w./-]+\.(?:py|xml|csv))")


@dataclass
class Tentative:
    numero: int
    validation_ok: bool
    installation: Resultat | None
    anomalies: list[str] = field(default_factory=list)
    reparation_demandee: bool = False


@dataclass
class Issue:
    reussi: bool
    spec: ModuleSpec
    fichiers: dict[str, str]
    tentatives: list[Tentative]
    diagnostic: str = ""

    def texte(self) -> str:
        lignes = []
        for t in self.tentatives:
            lignes.append(f"— Tentative {t.numero}")
            lignes.append(
                f"   Validation statique : {'PASS' if t.validation_ok else 'ÉCHEC'}"
            )
            for anomalie in t.anomalies:
                lignes.append(f"     · {anomalie}")
            if t.installation:
                lignes.append(
                    f"   Installation : {'SUCCESS' if t.installation.ok else 'FAILED'}"
                )
                if t.installation.erreur:
                    lignes.append(f"     · {t.installation.erreur}")
        if self.diagnostic:
            lignes.append("")
            lignes.append(self.diagnostic)
        return "\n".join(lignes)


class RepairLoop:
    def __init__(
        self,
        generateur: OdooModuleGenerator,
        validateur: OdooStaticValidator,
        installateur: OdooInstallClient | None,
        fournisseur: AIProvider | None = None,
        tentatives_max: int = 3,
    ):
        self.generateur = generateur
        self.validateur = validateur
        self.installateur = installateur
        self.fournisseur = fournisseur
        self.tentatives_max = tentatives_max

    def executer(self, spec: ModuleSpec, journal=lambda _: None) -> Issue:
        tentatives: list[Tentative] = []
        courante = spec

        for numero in range(1, self.tentatives_max + 1):
            journal(f"Génération du module (tentative {numero}/{self.tentatives_max})…")
            fichiers = self.generateur.generate(courante)

            rapport = self.validateur.check(fichiers, courante)
            tentative = Tentative(
                numero=numero,
                validation_ok=rapport.ok,
                installation=None,
                anomalies=[str(a) for a in rapport.anomalies],
            )
            tentatives.append(tentative)
            journal(rapport.texte())

            resultat = None
            if rapport.ok:
                if self.installateur is None:
                    # Sans bac à sable, on s'arrête à la validation statique.
                    return Issue(True, courante, fichiers, tentatives,
                                 "Bac à sable non configuré : validation statique seule.")
                journal("Installation sur Odoo 17…")
                resultat = self.installateur.installer(fichiers)
                tentative.installation = resultat
                journal(resultat.texte())
                if resultat.ok:
                    return Issue(True, courante, fichiers, tentatives)

            if numero == self.tentatives_max:
                break

            probleme = self._probleme(rapport, resultat)
            if self.fournisseur is None:
                return Issue(
                    False, courante, fichiers, tentatives,
                    "Aucun fournisseur de modèle : réparation automatique "
                    f"impossible. Cause retenue : {probleme}",
                )

            journal("Demande de correction au modèle…")
            tentative.reparation_demandee = True
            try:
                courante = self._reparer(courante, fichiers, probleme)
            except (ErreurFournisseur, SpecInvalide) as erreur:
                return Issue(
                    False, courante, fichiers, tentatives,
                    f"La réparation a échoué : {erreur}",
                )

        derniere = tentatives[-1]
        return Issue(
            False, courante, self.generateur.generate(courante), tentatives,
            f"Abandon après {self.tentatives_max} tentatives. "
            f"Dernière cause : {self._probleme_texte(derniere)}",
        )

    # ------------------------------------------------------------- réparation

    def _probleme(self, rapport, resultat: Resultat | None) -> str:
        if not rapport.ok:
            return "Validation statique :\n" + "\n".join(
                f"- {a}" for a in rapport.anomalies
            )
        if resultat is not None:
            details = "\n".join(resultat.journal[-10:])
            return f"Installation refusée par Odoo :\n{resultat.erreur}\n{details}"
        return "cause inconnue"

    def _probleme_texte(self, tentative: Tentative) -> str:
        if not tentative.validation_ok:
            return "; ".join(tentative.anomalies[:3])
        if tentative.installation and tentative.installation.erreur:
            return tentative.installation.erreur
        return "inconnue"

    def _reparer(self, spec: ModuleSpec, fichiers: dict[str, str], probleme: str) -> ModuleSpec:
        """Ne joint que les fichiers que l'erreur désigne."""
        cites = set()
        for nom in FICHIERS_CITES.findall(probleme):
            for chemin in fichiers:
                if chemin.endswith(nom) or nom.endswith(chemin):
                    cites.add(chemin)

        extraits = "\n\n".join(
            f"--- {chemin} ---\n{fichiers[chemin]}" for chemin in sorted(cites)
        )
        contexte = (
            f"SPÉCIFICATION ACTUELLE :\n{json.dumps(_en_dict(spec), ensure_ascii=False, indent=2)}"
            f"\n\nPROBLÈME :\n{probleme}"
            + (f"\n\nFICHIERS CONCERNÉS :\n{extraits}" if extraits else "")
        )
        return ModuleSpec.depuis_dict(self.fournisseur.completer_json(CONSIGNE_REPARATION, contexte))


def _en_dict(spec: ModuleSpec) -> dict:
    """Sérialise la spécification dans le format que le modèle doit rendre."""
    return {
        "technical_name": spec.technical_name,
        "name": spec.name,
        "summary": spec.summary,
        "description": spec.description,
        "category": spec.category,
        "version": spec.version,
        "license": spec.license,
        "depends": spec.depends,
        "application": spec.application,
        "models": [
            {
                "name": m.name,
                "description": m.description,
                **({"inherit": m.inherit} if m.inherit else {}),
                **({"rec_name": m.rec_name} if m.rec_name else {}),
                "fields": [
                    {
                        k: v for k, v in {
                            "name": c.name, "type": c.type, "string": c.string,
                            "required": c.required, "readonly": c.readonly,
                            "comodel": c.comodel, "inverse_name": c.inverse_name,
                            "selection": c.selection, "default": c.default,
                            "help": c.help,
                        }.items()
                        if v not in (None, False, [], "")
                    }
                    for c in m.fields
                ],
            }
            for m in spec.models
        ],
        "views": [
            {
                "model": v.model, "type": v.type, "name": v.name,
                "fields": v.fields, "invisible_fields": v.invisible_fields,
            }
            for v in spec.views
        ],
        "actions": [
            {
                "id": a.id, "name": a.name, "model": a.model,
                "view_modes": a.view_modes, "domain": a.domain, "context": a.context,
            }
            for a in spec.actions
        ],
        "menus": [
            {k: v for k, v in {
                "id": m.id, "name": m.name, "parent": m.parent,
                "action": m.action, "sequence": m.sequence,
            }.items() if v is not None}
            for m in spec.menus
        ],
        "access": [
            {"model": a.model, "group": a.group, "perms": a.perms} for a in spec.access
        ],
    }
