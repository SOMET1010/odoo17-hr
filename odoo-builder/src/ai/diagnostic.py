"""Diagnostic du routeur : où exactement ça coince.

Sans ce contrôle, un nom de modèle erroné, une clé invalide et un point
d'entrée mal recopié produisent tous « le Builder ne marche pas ». Ce module
sépare ces causes, pour qu'une erreur de configuration ne soit jamais prise
pour un défaut du Builder.

La sonde est délibérément le **chemin réel** : le même appel `completer_json`
que le rédacteur, avec une consigne minuscule. Un diagnostic qui emprunterait
un autre chemin ne prouverait pas grand-chose.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.provider import AIProvider, ErreurFournisseur
from ai.routeur import Etape

# Consigne minimale : coûte quelques jetons et exerce tout de même le point
# d'entrée, l'authentification, le nom du modèle et le format de réponse.
CONSIGNE = 'Rends exactement cet objet JSON, sans rien ajouter : {"ok": true}'
CONTEXTE = "ping"

# Ce que le diagnostic sait conclure.
VARIABLE = "variable d'environnement"
ENDPOINT = "point d'entrée"
AUTH = "authentification"
MODELE = "nom du modèle"
QUOTA = "quota"
INDISPONIBLE = "fournisseur indisponible"
PROTOCOLE = "protocole"
OK = "opérationnel"


@dataclass
class Constat:
    nom: str
    ok: bool
    cause: str
    detail: str = ""
    # Vrai quand la configuration est bonne mais le service momentanément
    # indisponible : rien à corriger côté fichier.
    transitoire: bool = False

    def ligne(self) -> str:
        if self.ok:
            return f"{self.nom} : {self.cause}"
        # Une clé absente n'est pas un défaut : c'est le cas normal d'une
        # machine qui ne dispose pas de tous les fournisseurs.
        if self.cause == VARIABLE:
            marque = "non configuré"
        elif self.transitoire:
            marque = "indisponible, configuration correcte"
        else:
            marque = "à corriger"
        detail = f" — {self.detail}" if self.detail else ""
        return f"{self.nom} : {self.cause} ({marque}){detail}"


def _classer(erreur: ErreurFournisseur) -> tuple[str, bool]:
    """Du symptôme à la cause, et dit si elle est transitoire."""
    code, corps = erreur.code, (erreur.corps or "").lower()

    if code is None:
        return ENDPOINT, False
    if code in (401, 403):
        return AUTH, False
    if code == 429:
        return QUOTA, True
    if code >= 500:
        return INDISPONIBLE, True
    if code in (400, 404, 422):
        # Le corps nomme presque toujours la cause ; c'est plus fiable que le
        # code seul, qui vaut 404 aussi bien pour une URL que pour un modèle.
        if "model" in corps or "modèle" in corps:
            return MODELE, False
        if code == 404:
            return ENDPOINT, False
        return PROTOCOLE, False
    return PROTOCOLE, False


def verifier(nom: str, fournisseur: AIProvider) -> Constat:
    try:
        reponse = fournisseur.completer_json(CONSIGNE, CONTEXTE)
    except ErreurFournisseur as erreur:
        cause, transitoire = _classer(erreur)
        return Constat(nom, False, cause, str(erreur), transitoire)

    if not isinstance(reponse, dict):
        return Constat(nom, False, PROTOCOLE, "la réponse n'est pas un objet JSON")
    return Constat(nom, True, OK, f"réponse JSON reçue ({len(reponse)} clé(s))")


def verifier_etapes(etapes: list[Etape], journal=lambda _: None) -> list[Constat]:
    constats = []
    for etape in etapes:
        journal(f"  {etape.nom}…")
        constats.append(verifier(etape.nom, etape.fournisseur))
    return constats
