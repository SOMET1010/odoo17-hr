"""Client JSON-RPC minimal vers Odoo.

Le service ne dispose pas du socket Docker : il ne peut pas lancer
« docker compose run odoo -i module ». Il écrit le module dans le volume
d'addons, puis demande à Odoo lui-même de mettre à jour sa liste et
d'installer — par les mêmes appels que fait l'interface web.

Conséquence assumée : le journal remonté vient d'Odoo (message d'erreur
JSON-RPC et sa trace), pas de la sortie standard d'une commande.
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request


class ErreurOdoo(Exception):
    """Odoo a répondu une erreur, ou n'a pas répondu du tout."""


class ClientOdoo:
    def __init__(
        self,
        url: str,
        base: str,
        login: str,
        motdepasse: str,
        delai: int = 600,
    ):
        self.url = url.rstrip("/")
        self.base = base
        self.login = login
        self.motdepasse = motdepasse
        self.delai = delai
        self._cookies = http.cookiejar.CookieJar()
        self._ouvreur = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )

    # ------------------------------------------------------------- transport

    def _poster(self, chemin: str, params: dict, delai: int | None = None) -> object:
        charge = json.dumps(
            {"jsonrpc": "2.0", "method": "call", "params": params}
        ).encode("utf-8")
        requete = urllib.request.Request(
            f"{self.url}{chemin}",
            data=charge,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._ouvreur.open(requete, timeout=delai or self.delai) as reponse:
                donnee = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.URLError as erreur:
            raise ErreurOdoo(f"Odoo injoignable sur {self.url} : {erreur}")
        except json.JSONDecodeError:
            raise ErreurOdoo("Réponse d'Odoo illisible (JSON attendu).")

        if "error" in donnee:
            erreur = donnee["error"]
            details = erreur.get("data") or {}
            message = details.get("message") or erreur.get("message") or "erreur Odoo"
            trace = details.get("debug") or ""
            raise ErreurOdoo(f"{message}\n{trace}".strip())
        return donnee.get("result")

    # ---------------------------------------------------------------- appels

    def authentifier(self) -> int:
        resultat = self._poster(
            "/web/session/authenticate",
            {"db": self.base, "login": self.login, "password": self.motdepasse},
            delai=60,
        )
        if not isinstance(resultat, dict) or not resultat.get("uid"):
            raise ErreurOdoo(
                f"Authentification refusée sur la base « {self.base} »."
            )
        return int(resultat["uid"])

    def appeler(
        self,
        modele: str,
        methode: str,
        args: list,
        kwargs: dict | None = None,
        delai: int | None = None,
    ) -> object:
        return self._poster(
            "/web/dataset/call_kw",
            {
                "model": modele,
                "method": methode,
                "args": args,
                "kwargs": kwargs or {},
            },
            delai=delai,
        )

    # ------------------------------------------------------------- opérations

    def etat_module(self, nom: str) -> str | None:
        """État du module dans ir.module.module, ou None s'il est inconnu."""
        trouves = self.appeler(
            "ir.module.module",
            "search_read",
            [[["name", "=", nom]], ["id", "state"]],
            {"limit": 1},
            delai=60,
        )
        if not trouves:
            return None
        return trouves[0]["state"]

    def _identifiant(self, nom: str) -> int:
        trouves = self.appeler(
            "ir.module.module",
            "search_read",
            [[["name", "=", nom]], ["id"]],
            {"limit": 1},
            delai=60,
        )
        if not trouves:
            raise ErreurOdoo(
                f"Odoo ne voit pas le module « {nom} » après mise à jour de la "
                "liste : le dossier d'addons est-il bien dans addons_path ?"
            )
        return int(trouves[0]["id"])

    def installer(self, nom: str, journal) -> str:
        """Met à jour la liste puis installe (ou met à jour) le module.

        `journal` est un appelable qui reçoit chaque ligne à tracer.
        Renvoie l'état final lu dans ir.module.module.
        """
        self.authentifier()
        journal(f"Authentifié sur la base « {self.base} ».")

        self.appeler("ir.module.module", "update_list", [], delai=180)
        journal("Liste des modules mise à jour.")

        etat = self.etat_module(nom)
        if etat is None:
            raise ErreurOdoo(
                f"Odoo ne voit pas le module « {nom} » après mise à jour de la "
                "liste : le dossier d'addons est-il bien dans addons_path ?"
            )
        identifiant = self._identifiant(nom)

        if etat == "installed":
            journal("Module déjà installé : mise à jour demandée.")
            self.appeler(
                "ir.module.module", "button_immediate_upgrade", [[identifiant]]
            )
        else:
            journal(f"Installation demandée (état de départ : {etat}).")
            self.appeler(
                "ir.module.module", "button_immediate_install", [[identifiant]]
            )

        # L'installation recharge le registre : la session peut avoir été
        # invalidée, on se ré-authentifie avant de relire l'état.
        self.authentifier()
        final = self.etat_module(nom)
        journal(f"État final rapporté par Odoo : {final}.")
        if final != "installed":
            raise ErreurOdoo(
                f"Le module « {nom} » n'est pas installé (état : {final})."
            )
        return final
