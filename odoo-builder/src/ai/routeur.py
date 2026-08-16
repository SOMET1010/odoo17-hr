"""Routeur de fournisseurs : ne pas dépendre d'un seul modèle.

Le routeur est lui-même un `AIProvider`. Le reste du Builder ne sait pas qu'il
existe — c'est ce que l'abstraction devait permettre, et c'est ce qui rend le
remplacement d'un fournisseur sans conséquence sur le générateur, le
validateur ou la boucle de réparation.

Ce qu'il fait, et surtout ce qu'il ne fait pas
----------------------------------------------
Il bascule sur le fournisseur suivant quand le précédent est **indisponible** :
réseau coupé, 5xx, quota dépassé, délai écoulé, réponse illisible.

Il ne bascule PAS quand un fournisseur répond correctement mais que la
spécification produite est refusée par le validateur. Ce cas-là appartient au
`SpecDrafter`, qui renvoie le motif du refus au même modèle pour qu'il
corrige. Confondre les deux brûlerait toute la liste des fournisseurs sur une
spécification simplement perfectible.

La configuration ne contient jamais de clé : elle nomme la variable
d'environnement qui la porte. Le fichier reste donc versionnable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ai.provider import (
    AIProvider, AnthropicProvider, ErreurFournisseur, OpenAIProvider,
)

PROTOCOLES = ("openai", "anthropic")


class ConfigurationInvalide(Exception):
    """La description du routeur n'est pas exploitable."""


@dataclass
class Etape:
    nom: str
    fournisseur: AIProvider


@dataclass
class RouterProvider(AIProvider):
    """Essaie les fournisseurs dans l'ordre, rend la première réponse obtenue."""

    etapes: list[Etape]
    journal: object = print
    # Trace de ce qui s'est passé : quel fournisseur, quel modèle, à quel
    # appel. Sans elle, une acceptation verte n'est pas reproductible et deux
    # fournisseurs ne sont pas comparables. Elle ne contient aucun secret.
    dernier_utilise: str | None = None
    dernier_modele: str | None = None
    incidents: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.etapes:
            raise ConfigurationInvalide("le routeur n'a aucun fournisseur.")

    @property
    def noms(self) -> list[str]:
        return [e.nom for e in self.etapes]

    def completer_json(self, consigne: str, contexte: str) -> dict:
        echecs: list[str] = []
        rang = len(self.trace) + 1
        for etape in self.etapes:
            modele = self._modele(etape)
            try:
                reponse = etape.fournisseur.completer_json(consigne, contexte)
            except ErreurFournisseur as erreur:
                message = f"{etape.nom} : {erreur}"
                echecs.append(message)
                self.incidents.append(message)
                self.trace.append({
                    "appel": rang, "fournisseur": etape.nom, "modele": modele,
                    "ok": False, "motif": str(erreur)[:200],
                })
                self._tracer(f"  fournisseur « {etape.nom} » indisponible — {erreur}")
                continue
            self.dernier_utilise = etape.nom
            self.dernier_modele = modele
            self.trace.append({
                "appel": rang, "fournisseur": etape.nom, "modele": modele, "ok": True,
            })
            self._tracer(f"  réponse obtenue de « {etape.nom} » ({modele})")
            return reponse

        raise ErreurFournisseur(
            "aucun fournisseur n'a répondu :\n  - " + "\n  - ".join(echecs)
        )

    @staticmethod
    def _modele(etape: Etape) -> str:
        return getattr(etape.fournisseur, "modele", "?")

    def resume(self) -> dict:
        """Ce qu'il faut consigner pour rendre une recette reproductible."""
        return {
            "fournisseur": self.dernier_utilise,
            "modele": self.dernier_modele,
            "appels": len({e["appel"] for e in self.trace}),
            "basculements": sum(1 for e in self.trace if not e["ok"]),
            "trace": list(self.trace),
        }

    def _tracer(self, message: str) -> None:
        if callable(self.journal):
            self.journal(message)


def _construire(entree: dict) -> Etape:
    nom = entree.get("nom") or entree.get("modele") or "sans-nom"
    protocole = entree.get("protocole", "openai")
    if protocole not in PROTOCOLES:
        raise ConfigurationInvalide(
            f"« {nom} » : protocole « {protocole} » inconnu. Admis : {', '.join(PROTOCOLES)}."
        )

    variable = entree.get("cle_env")
    if not variable:
        raise ConfigurationInvalide(
            f"« {nom} » : « cle_env » manquant. La configuration nomme la variable "
            "d'environnement qui porte la clé ; elle ne contient jamais la clé."
        )
    if any(mot in entree for mot in ("cle", "cle_api", "api_key", "key", "token")):
        raise ConfigurationInvalide(
            f"« {nom} » : une clé figure dans la configuration. Elle doit rester "
            "dans l'environnement — utiliser « cle_env »."
        )

    cle = os.environ.get(variable, "")
    if not cle:
        raise ConfigurationInvalide(f"« {nom} » : {variable} n'est pas définie.")

    modele = entree.get("modele")
    if not modele:
        raise ConfigurationInvalide(f"« {nom} » : « modele » manquant.")

    if protocole == "openai":
        fournisseur: AIProvider = OpenAIProvider(
            cle_api=cle, modele=modele,
            url=entree.get("url", "https://api.openai.com/v1/chat/completions"),
        )
    else:
        fournisseur = AnthropicProvider(
            cle_api=cle, modele=modele,
            url=entree.get("url", "https://api.anthropic.com/v1/messages"),
        )
    return Etape(nom=nom, fournisseur=fournisseur)


def routeur_depuis_config(
    donnee: dict, journal=print, tolerant: bool = True
) -> RouterProvider:
    """Construit le routeur ; ignore les fournisseurs non configurés.

    `tolerant` permet de décrire plusieurs fournisseurs et de n'en avoir qu'un
    seul de configuré sur une machine donnée : les autres sont sautés, avec une
    trace, plutôt que de faire échouer le démarrage.
    """
    entrees = donnee.get("fournisseurs")
    if not isinstance(entrees, list) or not entrees:
        raise ConfigurationInvalide("la configuration ne liste aucun fournisseur.")

    etapes: list[Etape] = []
    for entree in entrees:
        try:
            etapes.append(_construire(entree))
        except ConfigurationInvalide as erreur:
            if not tolerant:
                raise
            if callable(journal):
                journal(f"  fournisseur ignoré — {erreur}")

    if not etapes:
        raise ConfigurationInvalide(
            "aucun fournisseur utilisable : les variables d'environnement "
            "nommées par la configuration ne sont pas définies."
        )
    return RouterProvider(etapes=etapes, journal=journal)


def chemin_configuration() -> str:
    """Le fichier de routeur en vigueur : celui désigné, sinon celui du Builder."""
    return os.environ.get("BUILDER_IA_ROUTEUR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "routeur.json",
    )


def charger_configuration(chemin: str) -> dict:
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigurationInvalide(f"configuration introuvable : {chemin}")
    except json.JSONDecodeError as erreur:
        raise ConfigurationInvalide(f"JSON invalide dans {chemin} : {erreur}")


def routeur_depuis_fichier(chemin: str, journal=print) -> RouterProvider:
    return routeur_depuis_config(charger_configuration(chemin), journal)
