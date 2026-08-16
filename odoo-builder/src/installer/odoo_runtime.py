"""Contrôles d'exécution contre l'Odoo du bac à sable.

Le Builder sait fabriquer et installer. Ce module sert à répondre à la seule
question qui compte ensuite : **est-ce que le comportement décrit fonctionne
vraiment ?** Créer un enregistrement, lire un champ calculé, déclencher une
transition, relire l'état.

C'est Odoo qui répond, jamais la sortie d'une commande.
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request


class ErreurRuntime(Exception):
    """Odoo n'a pas répondu, ou a refusé l'appel."""


class OdooRuntime:
    def __init__(self, url: str, base: str, login: str, motdepasse: str, delai: int = 120):
        self.url = url.rstrip("/")
        self.base = base
        self.login = login
        self.motdepasse = motdepasse
        self.delai = delai
        self._ouvreur = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _poster(self, chemin: str, params: dict):
        charge = json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}).encode("utf-8")
        requete = urllib.request.Request(
            f"{self.url}{chemin}", data=charge,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._ouvreur.open(requete, timeout=self.delai) as reponse:
                donnee = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.URLError as erreur:
            raise ErreurRuntime(f"Odoo injoignable sur {self.url} : {erreur}")
        if "error" in donnee:
            details = donnee["error"].get("data") or {}
            raise ErreurRuntime(details.get("message") or donnee["error"].get("message", "erreur"))
        return donnee.get("result")

    def authentifier(self) -> int:
        resultat = self._poster(
            "/web/session/authenticate",
            {"db": self.base, "login": self.login, "password": self.motdepasse},
        )
        if not isinstance(resultat, dict) or not resultat.get("uid"):
            raise ErreurRuntime(f"authentification refusée sur « {self.base} »")
        return int(resultat["uid"])

    def appeler(self, modele: str, methode: str, args: list, kwargs: dict | None = None):
        return self._poster(
            "/web/dataset/call_kw",
            {"model": modele, "method": methode, "args": args, "kwargs": kwargs or {}},
        )

    # --------------------------------------------------------------- raccourcis

    def creer(self, modele: str, valeurs: dict) -> int:
        return int(self.appeler(modele, "create", [valeurs]))

    def lire(self, modele: str, identifiant: int, champs: list[str]) -> dict:
        enregistrements = self.appeler(modele, "read", [[identifiant], champs])
        if not enregistrements:
            raise ErreurRuntime(f"{modele} #{identifiant} introuvable")
        return enregistrements[0]

    def executer(self, modele: str, methode: str, identifiant: int):
        return self.appeler(modele, methode, [[identifiant]])
