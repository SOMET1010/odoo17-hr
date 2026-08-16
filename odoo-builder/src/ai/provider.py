"""Abstraction du fournisseur de modèle.

Le reste du Builder ne connaît que `AIProvider`. Remplacer OpenAI par un autre
fournisseur ne doit toucher aucun autre fichier — c'est la raison d'être de
cette interface, et la raison pour laquelle le générateur, le validateur et
l'installateur n'importent rien d'ici.

Le modèle rend toujours du JSON conforme à une intention précise : une
spécification, ou un correctif de spécification. Il n'écrit jamais de fichier
Odoo, et n'est jamais en charge d'un invariant.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod


class ErreurFournisseur(Exception):
    """Le fournisseur est indisponible ou rend une réponse inexploitable."""


class AIProvider(ABC):
    """Contrat minimal : une instruction, un contexte, un objet JSON en retour."""

    @abstractmethod
    def completer_json(self, consigne: str, contexte: str) -> dict:
        """Renvoie l'objet JSON produit par le modèle.

        `consigne` décrit la tâche et le format attendu ; `contexte` porte la
        matière (spécification, extraits de fichiers, erreur d'installation).
        """


class OpenAIProvider(AIProvider):
    """Implémentation OpenAI, isolée derrière l'interface.

    Pas de SDK : un appel HTTP suffit et évite une dépendance de plus dans un
    outil dont tout le reste tient dans la bibliothèque standard.
    """

    def __init__(
        self,
        cle_api: str | None = None,
        modele: str = "gpt-4o",
        url: str = "https://api.openai.com/v1/chat/completions",
        delai: int = 120,
    ):
        self.cle_api = cle_api or os.environ.get("OPENAI_API_KEY", "")
        self.modele = modele
        self.url = url
        self.delai = delai

    def completer_json(self, consigne: str, contexte: str) -> dict:
        if not self.cle_api:
            raise ErreurFournisseur(
                "OPENAI_API_KEY n'est pas définie : aucun fournisseur de modèle "
                "disponible."
            )
        charge = json.dumps({
            "model": self.modele,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": consigne},
                {"role": "user", "content": contexte},
            ],
        }).encode("utf-8")

        requete = urllib.request.Request(self.url, data=charge, method="POST")
        requete.add_header("Content-Type", "application/json")
        requete.add_header("Authorization", f"Bearer {self.cle_api}")

        try:
            with urllib.request.urlopen(requete, timeout=self.delai) as reponse:
                donnee = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as erreur:
            raise ErreurFournisseur(f"OpenAI a répondu {erreur.code} : {erreur.reason}")
        except urllib.error.URLError as erreur:
            raise ErreurFournisseur(f"OpenAI injoignable : {erreur.reason}")

        try:
            texte = donnee["choices"][0]["message"]["content"]
            return json.loads(texte)
        except (KeyError, IndexError, json.JSONDecodeError) as erreur:
            raise ErreurFournisseur(f"réponse inexploitable : {erreur}")


class AnthropicProvider(AIProvider):
    """Implémentation du protocole Anthropic.

    Deuxième protocole, pour que le Builder ne dépende pas non plus d'un
    format de requête unique. Anthropic n'a pas de « response_format » : on
    demande le JSON dans la consigne, et on extrait l'objet de la réponse.
    """

    def __init__(
        self,
        cle_api: str,
        modele: str = "claude-sonnet-5",
        url: str = "https://api.anthropic.com/v1/messages",
        version: str = "2023-06-01",
        delai: int = 120,
        jetons_max: int = 8192,
    ):
        self.cle_api = cle_api
        self.modele = modele
        self.url = url
        self.version = version
        self.delai = delai
        self.jetons_max = jetons_max

    def completer_json(self, consigne: str, contexte: str) -> dict:
        if not self.cle_api:
            raise ErreurFournisseur("clé absente pour le protocole Anthropic")
        charge = json.dumps({
            "model": self.modele,
            "max_tokens": self.jetons_max,
            "system": consigne + "\n\nRends uniquement l'objet JSON, sans texte autour.",
            "messages": [{"role": "user", "content": contexte}],
        }).encode("utf-8")

        requete = urllib.request.Request(self.url, data=charge, method="POST")
        requete.add_header("Content-Type", "application/json")
        requete.add_header("x-api-key", self.cle_api)
        requete.add_header("anthropic-version", self.version)

        try:
            with urllib.request.urlopen(requete, timeout=self.delai) as reponse:
                donnee = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as erreur:
            raise ErreurFournisseur(f"Anthropic a répondu {erreur.code} : {erreur.reason}")
        except urllib.error.URLError as erreur:
            raise ErreurFournisseur(f"Anthropic injoignable : {erreur.reason}")

        try:
            texte = "".join(
                bloc.get("text", "") for bloc in donnee["content"]
                if bloc.get("type") == "text"
            )
        except (KeyError, TypeError) as erreur:
            raise ErreurFournisseur(f"réponse inexploitable : {erreur}")
        return extraire_json(texte)


def extraire_json(texte: str) -> dict:
    """Isole l'objet JSON d'une réponse qui peut l'avoir enrobé.

    Les modèles encadrent volontiers leur JSON de ```json … ``` ou d'une
    phrase d'introduction, même quand on l'interdit. Plutôt que de refuser
    une réponse par ailleurs correcte, on va chercher l'objet.
    """
    nettoye = texte.strip()
    if nettoye.startswith("```"):
        nettoye = nettoye.split("\n", 1)[-1]
        if nettoye.rstrip().endswith("```"):
            nettoye = nettoye.rstrip()[: -3]
    nettoye = nettoye.strip()

    try:
        return json.loads(nettoye)
    except json.JSONDecodeError:
        pass

    debut, fin = nettoye.find("{"), nettoye.rfind("}")
    if debut == -1 or fin <= debut:
        raise ErreurFournisseur("aucun objet JSON dans la réponse du modèle")
    try:
        return json.loads(nettoye[debut : fin + 1])
    except json.JSONDecodeError as erreur:
        raise ErreurFournisseur(f"JSON illisible dans la réponse : {erreur}")


def fournisseur_configure(journal=None) -> AIProvider | None:
    """Le fournisseur à utiliser : routeur si configuré, sinon simple.

    Un fichier `routeur.json` à la racine du Builder — ou désigné par
    BUILDER_IA_ROUTEUR — prend le pas sur la configuration à fournisseur
    unique. Il n'est pas obligatoire : sans lui, rien ne change.
    """
    from ai.routeur import ConfigurationInvalide, routeur_depuis_fichier  # noqa: PLC0415

    chemin = os.environ.get("BUILDER_IA_ROUTEUR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "routeur.json",
    )
    if os.path.isfile(chemin):
        try:
            return routeur_depuis_fichier(chemin, journal or (lambda _: None))
        except ConfigurationInvalide as erreur:
            if journal:
                journal(f"  routeur inutilisable ({erreur}) — repli sur l'environnement")
    return fournisseur_depuis_environnement()


def fournisseur_depuis_environnement() -> AIProvider | None:
    """Construit le fournisseur décrit par l'environnement, ou None.

    Le protocole est celui d'OpenAI ; l'hôte, le modèle et la clé viennent de
    l'environnement. N'importe quel service exposant une API compatible OpenAI
    convient — Moonshot/Kimi, un service local, un proxy d'entreprise — sans
    toucher une ligne du Builder. C'est ce que l'abstraction devait permettre.

        BUILDER_IA_URL     point d'entrée « chat completions » du fournisseur
        BUILDER_IA_MODELE  nom du modèle chez ce fournisseur
        BUILDER_IA_CLE     clé ; à défaut OPENAI_API_KEY

    Aucune de ces valeurs n'est acceptée en argument de commande : une clé
    passée ainsi fuirait dans l'historique du shell et la liste des processus.
    """
    cle = os.environ.get("BUILDER_IA_CLE") or os.environ.get("OPENAI_API_KEY", "")
    if not cle:
        return None
    return OpenAIProvider(
        cle_api=cle,
        modele=os.environ.get("BUILDER_IA_MODELE", "gpt-4o"),
        url=os.environ.get(
            "BUILDER_IA_URL", "https://api.openai.com/v1/chat/completions"
        ),
    )


class ScriptedProvider(AIProvider):
    """Fournisseur déterministe, pour les recettes et le mode hors ligne.

    Il rend les réponses qu'on lui a données, dans l'ordre. Il permet
    d'éprouver toute la chaîne — y compris la boucle de réparation — sans clé
    d'API et sans réseau.
    """

    def __init__(self, reponses: list[dict]):
        self.reponses = list(reponses)
        self.appels: list[tuple[str, str]] = []

    def completer_json(self, consigne: str, contexte: str) -> dict:
        self.appels.append((consigne, contexte))
        if not self.reponses:
            raise ErreurFournisseur("aucune réponse scriptée restante")
        return self.reponses.pop(0)
