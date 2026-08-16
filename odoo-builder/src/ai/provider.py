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
