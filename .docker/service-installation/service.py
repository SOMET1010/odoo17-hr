"""Service privé d'installation de modules Odoo.

Périmètre volontairement étroit : recevoir une archive authentifiée, la
vérifier, l'écrire dans un volume d'addons dédié — séparé des sources Git —
puis demander à Odoo de l'installer et rendre l'état de l'opération.

Pas d'iframe, pas de multi-utilisateur, pas de place de marché. Et surtout
pas de socket Docker : le service ne sait qu'écrire un volume et parler
HTTP à Odoo.

API
    GET  /sante              état du service (sans authentification)
    POST /modules            dépôt d'une archive ZIP (Content-Type: application/zip)
    GET  /modules/<id>       état d'une demande

Authentification : en-tête « X-Cle-Api », comparée à la variable
d'environnement CLE_API.
"""

from __future__ import annotations

import hmac
import json
import os
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import validation
from client_odoo import ClientOdoo
from travaux import Ouvrier, Registre, Travail


def _entier(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, defaut))
    except ValueError:
        return defaut


CLE_API = os.environ.get("CLE_API", "")
ODOO_URL = os.environ.get("ODOO_URL", "http://odoo:8069")
ODOO_BASE = os.environ.get("ODOO_BASE", "ansut")
ODOO_LOGIN = os.environ.get("ODOO_LOGIN", "admin")
ODOO_MOTDEPASSE = os.environ.get("ODOO_MOTDEPASSE", "admin")
DOSSIER_ADDONS = os.environ.get("DOSSIER_ADDONS", "/mnt/addons-installes")
DOSSIER_SOURCES = os.environ.get("DOSSIER_SOURCES", "/mnt/extra-addons")
PORT = _entier("PORT", 8090)

LIMITES = validation.Limites(
    taille_archive=_entier("TAILLE_MAX_MO", 20) * 1024 * 1024,
    taille_decompressee=_entier("TAILLE_DECOMPRESSEE_MAX_MO", 100) * 1024 * 1024,
    nombre_fichiers=_entier("NOMBRE_FICHIERS_MAX", 2000),
)

registre = Registre()


def _installer(travail: Travail) -> None:
    client = ClientOdoo(ODOO_URL, ODOO_BASE, ODOO_LOGIN, ODOO_MOTDEPASSE)
    client.installer(travail.module, travail.tracer)


def _extraire(chemin_zip: str, destination: str) -> str:
    return validation.extraire(
        chemin_zip,
        destination,
        LIMITES,
        validation.modules_des_sources(DOSSIER_SOURCES),
    )


ouvrier = Ouvrier(registre, _installer, DOSSIER_ADDONS)


# Au-delà, on ne vide plus le corps d'une requête qu'on refuse : on ferme.
VIDANGE_MAX = 32 * 1024 * 1024


class Poignee(BaseHTTPRequestHandler):
    server_version = "installateur-odoo"
    # HTTP/1.1 pour pouvoir répondre à « Expect: 100-continue » : c'est ce qui
    # permet de refuser une archive hors gabarit avant qu'elle ne transite.
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- utilitaires

    def _repondre(self, code: int, charge: dict) -> None:
        corps = json.dumps(charge, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _longueur(self) -> int | None:
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None

    def _vider_corps(self, longueur: int) -> None:
        """Absorbe le corps d'une requête refusée, pour pouvoir répondre.

        Sans cela, fermer la connexion pendant que le client écrit encore lui
        renvoie une erreur réseau au lieu du message d'erreur : il ne saurait
        pas *pourquoi* son envoi a été rejeté.
        """
        if longueur > VIDANGE_MAX:
            self.close_connection = True
            return
        restant = longueur
        while restant > 0:
            morceau = self.rfile.read(min(64 * 1024, restant))
            if not morceau:
                break
            restant -= len(morceau)

    def handle_expect_100(self) -> bool:
        """Refuse avant transfert ce qui est déjà hors gabarit ou non autorisé."""
        if self.path == "/modules" and self.command == "POST":
            fournie = self.headers.get("X-Cle-Api", "")
            if not CLE_API or not hmac.compare_digest(fournie, CLE_API):
                self._repondre(401, {"erreur": "Clé d'API absente ou invalide."})
                self.close_connection = True
                return False
            longueur = self._longueur()
            if longueur is not None and longueur > LIMITES.taille_archive:
                self._repondre(
                    413,
                    {
                        "erreur": f"Archive trop volumineuse : {longueur} octets, "
                        f"maximum {LIMITES.taille_archive}."
                    },
                )
                self.close_connection = True
                return False
        return super().handle_expect_100()

    def _autorise(self) -> bool:
        fournie = self.headers.get("X-Cle-Api", "")
        # compare_digest évite de laisser fuiter la clé par le temps de réponse.
        if not CLE_API or not hmac.compare_digest(fournie, CLE_API):
            self._repondre(401, {"erreur": "Clé d'API absente ou invalide."})
            return False
        return True

    def log_message(self, format, *args):  # noqa: A002 - signature imposée
        print(f"{self.address_string()} {format % args}", flush=True)

    # ---------------------------------------------------------------- routage

    def do_GET(self):  # noqa: N802 - signature imposée
        if self.path == "/sante":
            self._repondre(200, {"etat": "ok", "odoo": ODOO_URL, "base": ODOO_BASE})
            return
        if self.path.startswith("/modules/"):
            if not self._autorise():
                return
            identifiant = self.path[len("/modules/") :]
            travail = registre.lire(identifiant)
            if travail is None:
                self._repondre(404, {"erreur": "Demande inconnue."})
                return
            self._repondre(200, travail.en_json())
            return
        self._repondre(404, {"erreur": "Route inconnue."})

    def do_POST(self):  # noqa: N802 - signature imposée
        longueur = self._longueur()
        if longueur is None:
            self._repondre(400, {"erreur": "En-tête Content-Length invalide."})
            return

        if self.path != "/modules":
            self._vider_corps(longueur)
            self._repondre(404, {"erreur": "Route inconnue."})
            return

        # Chaque refus vide d'abord le corps : le client doit recevoir la
        # raison du rejet, pas une connexion coupée.
        fournie = self.headers.get("X-Cle-Api", "")
        if not CLE_API or not hmac.compare_digest(fournie, CLE_API):
            self._vider_corps(longueur)
            self._repondre(401, {"erreur": "Clé d'API absente ou invalide."})
            return

        if longueur <= 0:
            self._repondre(400, {"erreur": "Corps de requête vide."})
            return
        if longueur > LIMITES.taille_archive:
            self._vider_corps(longueur)
            self._repondre(
                413,
                {
                    "erreur": f"Archive trop volumineuse : {longueur} octets, "
                    f"maximum {LIMITES.taille_archive}."
                },
            )
            return

        descripteur, chemin_zip = tempfile.mkstemp(suffix=".zip")
        garder = False
        try:
            with os.fdopen(descripteur, "wb") as sortie:
                restant = longueur
                while restant > 0:
                    morceau = self.rfile.read(min(64 * 1024, restant))
                    if not morceau:
                        break
                    sortie.write(morceau)
                    restant -= len(morceau)
            if restant > 0:
                self._repondre(400, {"erreur": "Corps de requête incomplet."})
                return

            try:
                module = validation.inspecter(
                    chemin_zip,
                    LIMITES,
                    validation.modules_des_sources(DOSSIER_SOURCES),
                )
            except validation.Refus as refus:
                self._repondre(refus.code, {"erreur": str(refus)})
                return

            travail = Travail(identifiant=uuid.uuid4().hex, module=module)
            ouvrier.deposer(travail, chemin_zip, _extraire)
            garder = True  # l'ouvrier se charge de supprimer l'archive
            self._repondre(202, travail.en_json())
        finally:
            if not garder:
                try:
                    os.unlink(chemin_zip)
                except OSError:
                    pass


def principal() -> None:
    if not CLE_API:
        raise SystemExit(
            "CLE_API n'est pas définie : le service refuse de démarrer sans "
            "clé d'API."
        )
    os.makedirs(DOSSIER_ADDONS, exist_ok=True)
    serveur = ThreadingHTTPServer(("0.0.0.0", PORT), Poignee)
    print(
        f"Service d'installation à l'écoute sur le port {PORT} — "
        f"Odoo : {ODOO_URL}, base : {ODOO_BASE}, addons : {DOSSIER_ADDONS}",
        flush=True,
    )
    ouvrier.demarrer()
    serveur.serve_forever()


if __name__ == "__main__":
    principal()
