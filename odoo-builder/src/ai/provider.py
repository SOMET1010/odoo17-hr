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
    """Le fournisseur est indisponible ou rend une réponse inexploitable.

    Porte le code HTTP et le corps de la réponse quand ils existent : c'est ce
    qui permet au diagnostic de distinguer un mauvais nom de modèle d'une clé
    invalide ou d'un point d'entrée erroné — trois causes qui, sans cela, se
    ressemblent toutes.
    """

    def __init__(self, message: str, code: int | None = None, corps: str = ""):
        super().__init__(message)
        self.code = code
        self.corps = corps


def _apercu(valeur, limite: int = 300) -> str:
    """Ce que le service a réellement rendu, tronqué et sur une seule ligne.

    Sans cet aperçu, « Expecting value: line 1 column 1 » ne distingue pas une
    réponse vide, une réponse enrobée de ```json, une page HTML d'un portail
    d'authentification, ni un message d'erreur en clair. Ce sont quatre causes
    différentes et quatre corrections différentes.
    """
    if valeur is None:
        return "(rien)"
    texte = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    if not texte.strip():
        return "(réponse vide)"
    texte = " ".join(texte.split())
    return texte[:limite] + ("…" if len(texte) > limite else "")


def _corps_erreur(erreur) -> str:
    """Le corps d'une réponse en erreur, tronqué. Les API y nomment la cause."""
    try:
        brut = erreur.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        charge = json.loads(brut)
        detail = charge.get("error")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)[:400]
        return str(detail or charge)[:400]
    except json.JSONDecodeError:
        return brut[:400]


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
            corps = _corps_erreur(erreur)
            raise ErreurFournisseur(
                f"{erreur.code} {erreur.reason}" + (f" — {corps}" if corps else ""),
                code=erreur.code, corps=corps,
            )
        except urllib.error.URLError as erreur:
            raise ErreurFournisseur(f"point d'entrée injoignable : {erreur.reason}")

        try:
            choix = donnee["choices"][0]
            texte = choix["message"]["content"]
        except (KeyError, IndexError) as erreur:
            raise ErreurFournisseur(
                f"réponse inexploitable : {erreur} — reçu : {_apercu(donnee)}"
            )

        # « response_format: json_object » n'est pas honoré partout : certains
        # services rendent le JSON enrobé de ```json … ``` ou précédé d'une
        # phrase. Le chemin Anthropic passait déjà par extraire_json ; celui-ci
        # supposait la consigne respectée, et échouait sur « Expecting value:
        # line 1 column 1 » — message qui ne dit rien de ce qui a été reçu.
        try:
            return extraire_json(texte or "")
        except ErreurFournisseur as erreur:
            raison = choix.get("finish_reason")
            détail = f" (finish_reason : {raison})" if raison else ""
            raise ErreurFournisseur(
                f"{erreur}{détail} — reçu : {_apercu(texte)}"
            )


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
            corps = _corps_erreur(erreur)
            raise ErreurFournisseur(
                f"{erreur.code} {erreur.reason}" + (f" — {corps}" if corps else ""),
                code=erreur.code, corps=corps,
            )
        except urllib.error.URLError as erreur:
            raise ErreurFournisseur(f"point d'entrée injoignable : {erreur.reason}")

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
    from ai.routeur import (  # noqa: PLC0415
        ConfigurationInvalide, chemin_configuration, routeur_depuis_fichier,
    )

    chemin = chemin_configuration()
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

    def __init__(self, reponses: list[dict], modele: str = "scripte"):
        self.reponses = list(reponses)
        self.modele = modele
        self.appels: list[tuple[str, str]] = []

    def completer_json(self, consigne: str, contexte: str) -> dict:
        self.appels.append((consigne, contexte))
        if not self.reponses:
            raise ErreurFournisseur("aucune réponse scriptée restante")
        return self.reponses.pop(0)
