"""Du besoin exprimé en français à une ModuleSpec valide.

C'est le seul endroit du Builder où un modèle intervient dans la fabrication,
et sa laisse est courte : **il ne produit qu'une ModuleSpec**. Jamais de
Python, jamais de XML, jamais d'archive. Sa sortie traverse ensuite le même
pipeline déterministe que n'importe quelle spécification écrite à la main.

Conséquence : une mauvaise réponse du modèle ne peut pas injecter de code dans
Odoo. Au pire elle décrit un module qui ne passe pas la validation — et on lui
renvoie l'erreur.

La boucle de rédaction est bornée. Au-delà, on rend la dernière erreur plutôt
que d'insister.
"""

from __future__ import annotations

import json

from ai.provider import AIProvider, ErreurFournisseur
from spec.module_spec import ModuleSpec, SpecInvalide

CONTRAT = """Tu traduis un besoin métier en spécification de module Odoo 17.

Tu rends UNIQUEMENT un objet JSON conforme au schéma ci-dessous. Tu n'écris
jamais de Python, jamais de XML, jamais de code : uniquement cette structure.

{
  "technical_name": "nom_technique",     // minuscules, chiffres, soulignés
  "name": "Nom affiché",
  "summary": "une phrase",
  "category": "Human Resources",
  "depends": ["base"],                    // modules Odoo dont celui-ci dépend
  "application": true,
  "models": [
    {
      "name": "mon.modele",               // pointé, minuscules
      "description": "Objet métier",
      "rec_name": "name",                 // champ servant de libellé
      "inherit": "project.task",           // UNIQUEMENT pour étendre un modèle
                                           // existant ; alors name == inherit
      "fields": [
        { "name": "amount", "type": "monetary", "string": "Montant",
          "required": true },
        { "name": "line_ids", "type": "one2many", "string": "Lignes",
          "comodel": "autre.modele", "inverse_name": "parent_id" },
        { "name": "total", "type": "monetary", "string": "Total",
          "readonly": true,
          "compute": { "expression": "sum(line_ids.amount)",
                       "depends": ["line_ids.amount"], "store": true } }
      ],
      "constraints": [
        { "name": "regle", "condition": "date_fin >= date_debut",
          "message": "Message montré à l'utilisateur.",
          "depends": ["date_debut", "date_fin"] }
      ],
      "lifecycle": {
        "field_name": "state",
        "states": [
          { "value": "draft", "label": "Brouillon", "is_initial": true },
          { "value": "done",  "label": "Terminé",  "is_final": true }
        ],
        "transitions": [
          { "name": "valider", "label": "Valider",
            "from_states": ["draft"], "to_state": "done",
            "allowed_groups": ["base.group_system"],
            "validations": [ { "condition": "total > 0",
                               "message": "Total nul." } ] }
        ]
      }
    }
  ],
  "views":   [ { "model": "mon.modele", "type": "tree", "name": "Liste",
                 "fields": ["name", "amount"], "invisible_fields": [] } ],
  "actions": [ { "id": "action_x", "name": "Titre", "model": "mon.modele",
                 "view_modes": ["tree", "form"], "domain": "[]" } ],
  "menus":   [ { "id": "menu_racine", "name": "Racine", "sequence": 10 },
               { "id": "menu_x", "name": "Entrée", "parent": "menu_racine",
                 "action": "action_x" } ],
  "access":  [ { "model": "mon.modele", "group": "base.group_user",
                 "perms": "rwcd" } ]
}

TYPES DE CHAMPS : char, text, html, integer, float, monetary, boolean, date,
datetime, selection, many2one, one2many, many2many, binary, image.
Un champ selection déclare "selection": [["cle", "Libellé"], ...].

LANGAGE DES EXPRESSIONS — c'est le seul « code » admis, et il est restreint :
  agrégats     sum(rel.champ), count(rel), min/max/avg(rel.champ)
  scalaires    abs, len, round, bool, int, float, str
  opérateurs   + - * / % ** // et comparaisons == != < <= > >= in
  logique      and, or, not
Rien d'autre. Pas d'appel de méthode, pas de compréhension, pas d'import.

RÈGLES QUI FONT REFUSER UNE SPÉCIFICATION :
- un champ monétaire impose un champ "currency_id" many2one vers res.currency
  sur le même modèle ;
- "depends" doit citer EXACTEMENT les champs que l'expression lit, ni plus ni
  moins ;
- un champ calculé ne peut pas être "required" ;
- tout modèle créé par le module doit avoir une entrée dans "access" ;
- une vue ne peut porter que sur un modèle déclaré dans "models" ;
- un menu ne peut viser qu'une action déclarée dans "actions" ;
- chaque état non initial doit être atteint par une transition, et tout état
  non final doit pouvoir être quitté ;
- si un domaine de vue référence un champ, ce champ doit figurer dans la vue,
  au besoin via "invisible_fields".

Choisis des noms techniques parlants et des libellés en français."""

CORRECTION = """La spécification que tu viens de rendre a été refusée.

Corrige-la et rends de nouveau UNIQUEMENT l'objet JSON complet, au même
format. Ne corrige que ce que l'erreur signale."""


class RedactionImpossible(Exception):
    """Le modèle n'a pas produit de spécification valide dans le budget donné."""


class SpecDrafter:
    def __init__(self, fournisseur: AIProvider, tentatives_max: int = 3):
        self.fournisseur = fournisseur
        self.tentatives_max = tentatives_max
        self.tentatives: list[str] = []

    def draft(self, besoin: str, journal=lambda _: None) -> ModuleSpec:
        contexte = f"BESOIN :\n{besoin}"
        derniere_erreur = ""

        for numero in range(1, self.tentatives_max + 1):
            journal(f"Rédaction de la spécification ({numero}/{self.tentatives_max})…")
            consigne = CONTRAT if numero == 1 else f"{CONTRAT}\n\n{CORRECTION}"
            try:
                brut = self.fournisseur.completer_json(consigne, contexte)
            except ErreurFournisseur as erreur:
                raise RedactionImpossible(f"fournisseur indisponible : {erreur}")

            self.tentatives.append(json.dumps(brut, ensure_ascii=False))

            try:
                spec = ModuleSpec.depuis_dict(brut)
            except SpecInvalide as erreur:
                # La spécification refusée et son motif repartent au modèle :
                # c'est le validateur déterministe qui corrige le tir, pas une
                # consigne plus insistante.
                derniere_erreur = str(erreur)
                journal(f"  refusée : {derniere_erreur}")
                contexte = (
                    f"BESOIN :\n{besoin}\n\n"
                    f"SPÉCIFICATION REFUSÉE :\n{json.dumps(brut, ensure_ascii=False, indent=2)}"
                    f"\n\nMOTIF DU REFUS :\n{derniere_erreur}"
                )
                continue

            journal(f"  spécification valide : {spec.technical_name}")
            return spec

        raise RedactionImpossible(
            f"aucune spécification valide après {self.tentatives_max} tentatives. "
            f"Dernier motif : {derniere_erreur}"
        )
