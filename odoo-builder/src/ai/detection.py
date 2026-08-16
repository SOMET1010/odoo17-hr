"""Trouve à quel fournisseur appartient une clé, en la lui présentant.

Une clé refusée par OpenAI n'est pas forcément mauvaise : elle peut être
excellente et appartenir à quelqu'un d'autre. Les clés se ressemblent toutes —
`sk-…` chez OpenAI comme chez Moonshot, DeepSeek ou Groq — et leur préfixe ne
dit rien de fiable. Deviner à partir de la forme reviendrait à recommencer
l'erreur : on demande.

Le critère n'est pas « ça marche » mais « ce n'est pas un refus
d'authentification ». Un modèle inconnu prouve que la clé a été acceptée : le
serveur n'aurait pas examiné le nom du modèle sinon. C'est ce qui permet de
reconnaître le bon fournisseur même quand le nom de modèle par défaut est
périmé — cas courant, les modèles changeant plus vite que les tables.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ai.diagnostic import AUTH, Constat, verifier
from ai.installation import FOURNISSEURS
from ai.provider import AnthropicProvider, OpenAIProvider


def fournisseur_pour(details: dict, cle: str, modele: str | None = None):
    """Construit le client d'un fournisseur de la table, avec cette clé."""
    nom_modele = modele or details["modele_suggere"]
    if details["protocole"] == "anthropic":
        return AnthropicProvider(cle_api=cle, modele=nom_modele, url=details["url"])
    return OpenAIProvider(cle_api=cle, modele=nom_modele, url=details["url"])


def detecter(cle: str, journal=lambda _: None, table: dict | None = None):
    """Présente la clé à chaque fournisseur ; rend un constat par fournisseur.

    L'ordre de la table est conservé : la sortie se lit comme la liste des
    fournisseurs essayés, dans l'ordre où ils l'ont été.
    """
    constats = []
    for nom, details in (table if table is not None else FOURNISSEURS).items():
        journal(f"  {details['libelle']}…")
        constats.append(verifier(nom, fournisseur_pour(details, cle)))
    return constats


def accepte(constat: Constat) -> bool:
    """La clé a-t-elle passé l'authentification chez ce fournisseur ?

    Tout sauf un refus d'authentification vaut acceptation : un modèle inconnu,
    un quota épuisé ou une panne supposent tous une clé reconnue.
    """
    return constat.ok or constat.cause != AUTH


def modeles_disponibles(url: str, cle: str, protocole: str = "openai",
                        delai: int = 30) -> list[str]:
    """Les modèles que ce fournisseur déclare, au mieux de ce qu'il veut dire.

    Sert quand la clé est acceptée mais le nom de modèle refusé : plutôt que
    d'en proposer un au hasard, on demande la liste. Toute erreur rend une
    liste vide — c'est un confort de diagnostic, jamais un invariant.
    """
    base = url.split("/chat/completions")[0].split("/messages")[0]
    requete = urllib.request.Request(f"{base}/models", method="GET")
    if protocole == "anthropic":
        requete.add_header("x-api-key", cle)
        requete.add_header("anthropic-version", "2023-06-01")
    else:
        requete.add_header("Authorization", f"Bearer {cle}")

    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            donnee = json.loads(reponse.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []

    entrees = donnee.get("data") if isinstance(donnee, dict) else None
    if not isinstance(entrees, list):
        return []
    return [e["id"] for e in entrees if isinstance(e, dict) and e.get("id")]
