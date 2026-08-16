"""Comportement métier d'un module : ce que la structure seule ne dit pas.

Un module Odoo n'est pas un schéma de tables. Il est fait de champs calculés,
de contraintes, d'états et de transitions. C'est précisément ce que la première
version de la spécification ne savait pas décrire — d'où la reconstruction.

Le principe qui tient l'ensemble : **la spécification ne contient jamais de
Python**. Elle contient des expressions d'un langage contrôlé (voir
`expression.py`), que le générateur traduit selon des règles fixes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from spec.expression import Expression, ExpressionInvalide

NOM = re.compile(r"^[a-z][a-z0-9_]*$")


class ComportementInvalide(Exception):
    """Le comportement décrit n'est pas réalisable."""


@dataclass
class Calcul:
    """Champ calculé : une expression, ses dépendances, son stockage.

    `depends` est déclaré par l'auteur de la spécification, mais vérifié : une
    dépendance manquante produit un champ qui ne se recalcule pas, et c'est
    l'un des bugs les plus difficiles à voir en Odoo.
    """

    expression: str
    depends: list[str] = field(default_factory=list)
    store: bool = True

    def compiler(self, variable: str = "enreg") -> Expression:
        try:
            return Expression(self.expression, variable)
        except ExpressionInvalide as erreur:
            raise ComportementInvalide(str(erreur))

    def valider(self, contexte: str) -> None:
        expression = self.compiler()
        lus = expression.chemins()
        declares = set(self.depends)

        manquants = lus - declares
        if manquants:
            raise ComportementInvalide(
                f"{contexte} : l'expression lit {sorted(manquants)} sans le "
                "déclarer dans « depends ». Le champ ne se recalculerait pas."
            )
        superflus = declares - lus
        if superflus:
            raise ComportementInvalide(
                f"{contexte} : « depends » cite {sorted(superflus)}, que "
                "l'expression ne lit pas."
            )


@dataclass
class Contrainte:
    """Règle qui doit rester vraie. Exprimée en positif, comme en Odoo."""

    name: str
    condition: str            # doit être VRAIE pour que l'enregistrement soit valide
    message: str
    depends: list[str] = field(default_factory=list)

    def compiler(self, variable: str = "enreg") -> Expression:
        try:
            return Expression(self.condition, variable)
        except ExpressionInvalide as erreur:
            raise ComportementInvalide(str(erreur))

    def valider(self, contexte: str) -> None:
        if not NOM.match(self.name):
            raise ComportementInvalide(f"{contexte} : nom de contrainte invalide « {self.name} ».")
        if not self.message:
            raise ComportementInvalide(
                f"{contexte} : la contrainte « {self.name} » n'a pas de message. "
                "Une contrainte muette est inexploitable pour l'utilisateur."
            )
        expression = self.compiler()
        declares = set(self.depends)
        lus = expression.racines()
        manquants = lus - declares
        if manquants:
            raise ComportementInvalide(
                f"{contexte} : la contrainte « {self.name} » lit {sorted(manquants)} "
                "sans le déclarer dans « depends »."
            )


@dataclass
class Etat:
    """Un état du cycle de vie, tel qu'il apparaît dans la barre de statut."""

    value: str
    label: str
    is_initial: bool = False
    is_final: bool = False

    def valider(self, contexte: str) -> None:
        if not NOM.match(self.value):
            raise ComportementInvalide(f"{contexte} : état invalide « {self.value} ».")
        if not self.label:
            raise ComportementInvalide(f"{contexte} : l'état « {self.value} » n'a pas de libellé.")


@dataclass
class Transition:
    """Passage d'un état à un autre, avec ses conditions d'exercice.

    Le générateur en tire une méthode, ses contrôles, et le bouton qui la
    déclenche — le tout selon des règles fixes, jamais du code fourni.
    """

    name: str
    label: str
    from_states: list[str]
    to_state: str
    allowed_groups: list[str] = field(default_factory=list)
    validations: list[dict] = field(default_factory=list)  # {condition, message}

    def valider(self, contexte: str, etats: set[str]) -> None:
        if not NOM.match(self.name):
            raise ComportementInvalide(f"{contexte} : transition invalide « {self.name} ».")
        if not self.from_states:
            raise ComportementInvalide(
                f"{contexte} : la transition « {self.name} » ne dit pas d'où elle part."
            )
        inconnus = (set(self.from_states) | {self.to_state}) - etats
        if inconnus:
            raise ComportementInvalide(
                f"{contexte} : la transition « {self.name} » référence des états "
                f"inconnus : {sorted(inconnus)}."
            )
        for validation in self.validations:
            if "condition" not in validation or "message" not in validation:
                raise ComportementInvalide(
                    f"{contexte} : chaque validation de « {self.name} » doit "
                    "porter une condition et un message."
                )
            try:
                Expression(validation["condition"])
            except ExpressionInvalide as erreur:
                raise ComportementInvalide(f"{contexte} / {self.name} : {erreur}")


@dataclass
class CycleDeVie:
    """États et transitions d'un modèle. Génère le champ d'état lui-même."""

    field_name: str = "state"
    states: list[Etat] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)

    @property
    def etat_initial(self) -> Etat | None:
        for etat in self.states:
            if etat.is_initial:
                return etat
        return self.states[0] if self.states else None

    def valider(self, contexte: str) -> None:
        if not self.states:
            return
        if not NOM.match(self.field_name):
            raise ComportementInvalide(
                f"{contexte} : nom de champ d'état invalide « {self.field_name} »."
            )
        valeurs = set()
        for etat in self.states:
            etat.valider(contexte)
            if etat.value in valeurs:
                raise ComportementInvalide(f"{contexte} : état « {etat.value} » en double.")
            valeurs.add(etat.value)

        initiaux = [e for e in self.states if e.is_initial]
        if len(initiaux) > 1:
            raise ComportementInvalide(
                f"{contexte} : plusieurs états initiaux ({[e.value for e in initiaux]})."
            )

        noms = set()
        for transition in self.transitions:
            transition.valider(contexte, valeurs)
            if transition.name in noms:
                raise ComportementInvalide(
                    f"{contexte} : transition « {transition.name} » en double."
                )
            noms.add(transition.name)

        # Un état non final que rien n'atteint ni ne quitte est un cul-de-sac :
        # signe d'un cycle de vie mal décrit plutôt que d'une intention. Le
        # contrôle vaut aussi sans aucune transition — plusieurs états qu'on ne
        # peut jamais quitter, c'est un cycle de vie qui ne vit pas.
        if len(self.states) > 1:
            atteints = {t.to_state for t in self.transitions}
            quittes = {e for t in self.transitions for e in t.from_states}
            initial = self.etat_initial
            for etat in self.states:
                if etat.value == (initial.value if initial else None):
                    continue
                if etat.value not in atteints:
                    raise ComportementInvalide(
                        f"{contexte} : l'état « {etat.value} » n'est atteint par "
                        "aucune transition."
                    )
                if not etat.is_final and etat.value not in quittes:
                    raise ComportementInvalide(
                        f"{contexte} : l'état « {etat.value} » n'est final et "
                        "pourtant aucune transition n'en sort."
                    )
