"""API de l'Atelier : la surface que l'interface appelle.

Le Builder était une ligne de commande. Une interface web ne peut pas appeler
une ligne de commande : il fallait une surface HTTP. Ce service en est une, et
délibérément une peau fine — il n'implémente rien lui-même, il enchaîne
exactement les mêmes objets que `cli/atelier_odoo.py`. Toute logique qui
n'existerait qu'ici finirait par diverger de celle qu'éprouvent les 141 tests.

API
    GET  /sante                état du service (sans authentification)
    POST /specifications       {"besoin": "…"} → la ModuleSpec rédigée
    POST /modules              {"spec": {…}}  → fabrication et installation
    GET  /modules/<id>         état d'une fabrication

Authentification : en-tête « X-Cle-Api », comparée à ATELIER_CLE_API.

Ce que ce service ne fait PAS, et ne doit pas faire :
  - exposer la clé du fournisseur de modèle. Elle vit dans son environnement,
    jamais dans une réponse, jamais dans un journal ;
  - accepter du Python, du XML ou une archive. Il ne reçoit qu'un besoin en
    français ou une spécification, et c'est le générateur déterministe qui
    écrit les fichiers ;
  - installer sans valider. La validation statique est un passage obligé, et
    un refus est une réponse, pas un contournement.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.environ.get("BUILDER_SRC", "/opt/odoo-builder/src"))

from ai.provider import fournisseur_configure  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import (  # noqa: E402
    ErreurInstallation, OdooInstallClient,
)
# La sérialisation d'une ModuleSpec n'existe qu'à un seul endroit, celui que
# couvre le test d'aller-retour. En réécrire une ici la ferait diverger en
# silence — c'est déjà arrivé, et une réparation avait effacé le comportement.
from repair.repair_loop import _en_dict  # noqa: E402
from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402
from spec.module_spec import ModuleSpec, SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

from travaux import Registre, Travail  # noqa: E402


def _entier(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, defaut))
    except ValueError:
        return defaut


CLE_API = os.environ.get("ATELIER_CLE_API", "")
INSTALLATEUR_URL = os.environ.get("INSTALLATEUR_URL", "http://installateur:8090")
INSTALLATEUR_CLE = os.environ.get("INSTALLATEUR_CLE_API", "")
PORT = _entier("PORT", 8091)
TENTATIVES = _entier("TENTATIVES_MAX", 3)
BESOIN_MAX = _entier("BESOIN_MAX_CARACTERES", 8000)
CORPS_MAX = _entier("CORPS_MAX_OCTETS", 1024 * 1024)

# Origines autorisées à appeler depuis un navigateur. Jamais « * » : le service
# exige une clé, et « * » avec authentification laisserait n'importe quelle page
# visitée par l'utilisateur parler à son Atelier.
ORIGINES = [o.strip() for o in os.environ.get("ORIGINES_AUTORISEES", "").split(",") if o.strip()]

registre = Registre()


def _fabriquer(travail: Travail) -> None:
    """Spécification → fichiers → validation → archive → installation réelle."""
    spec = ModuleSpec.depuis_dict(travail.charge)
    travail.module = spec.technical_name
    travail.tracer(f"spécification acceptée : {spec.technical_name}")

    fichiers = OdooModuleGenerator().generate(spec)
    travail.tracer(f"{len(fichiers)} fichier(s) générés, en mémoire")

    rapport = OdooStaticValidator().check(fichiers, spec)
    if not rapport.ok:
        # Un refus est une réponse. Rien n'est écrit, rien n'est envoyé.
        raise SpecInvalide(rapport.texte())
    travail.tracer("validation statique : passée")

    client = OdooInstallClient(INSTALLATEUR_URL, INSTALLATEUR_CLE)
    resultat = client.installer(fichiers)
    for ligne in getattr(resultat, "journal", []) or []:
        travail.tracer(ligne)
    if getattr(resultat, "etat", None) != "success":
        raise ErreurInstallation(getattr(resultat, "erreur", None) or "installation refusée")
    travail.tracer("installation : success")


class Poignee(BaseHTTPRequestHandler):
    server_version = "atelier-api"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- utilitaires

    def _origine_autorisee(self) -> str | None:
        origine = self.headers.get("Origin")
        return origine if origine and origine in ORIGINES else None

    def _repondre(self, code: int, charge: dict) -> None:
        corps = json.dumps(charge, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        # « Vary » sans condition : la réponse dépend de l'origine même quand
        # elle est refusée, et un cache qui l'ignorerait servirait la réponse
        # d'une origine à une autre.
        self.send_header("Vary", "Origin")
        origine = self._origine_autorisee()
        if origine:
            self.send_header("Access-Control-Allow-Origin", origine)
            self.send_header("Access-Control-Allow-Credentials", "false")
        self.end_headers()
        self.wfile.write(corps)

    def _lire_json(self) -> dict | None:
        try:
            longueur = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._repondre(400, {"erreur": "En-tête Content-Length invalide."})
            return None
        if longueur <= 0:
            self._repondre(400, {"erreur": "Corps vide."})
            return None
        if longueur > CORPS_MAX:
            self._repondre(413, {"erreur": f"Corps trop volumineux : {longueur} octets."})
            return None
        try:
            return json.loads(self.rfile.read(longueur).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erreur:
            self._repondre(400, {"erreur": f"JSON illisible : {erreur}"})
            return None

    def _autorise(self) -> bool:
        fournie = self.headers.get("X-Cle-Api", "")
        if not CLE_API or not hmac.compare_digest(fournie, CLE_API):
            self._repondre(401, {"erreur": "Clé d'API absente ou invalide."})
            return False
        return True

    def log_message(self, format, *args):  # noqa: A002 - signature imposée
        print(f"{self.address_string()} {format % args}", flush=True)

    # ---------------------------------------------------------------- routage

    def do_OPTIONS(self):  # noqa: N802 - signature imposée
        origine = self._origine_autorisee()
        self.send_response(204 if origine else 403)
        self.send_header("Vary", "Origin")
        if origine:
            self.send_header("Access-Control-Allow-Origin", origine)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cle-Api")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802 - signature imposée
        if self.path == "/sante":
            self._repondre(200, {
                "etat": "ok",
                "fournisseur_configure": fournisseur_configure() is not None,
                "installateur": INSTALLATEUR_URL,
            })
            return
        if self.path.startswith("/modules/"):
            if not self._autorise():
                return
            travail = registre.lire(self.path[len("/modules/"):])
            if travail is None:
                self._repondre(404, {"erreur": "Fabrication inconnue."})
                return
            self._repondre(200, travail.en_json())
            return
        self._repondre(404, {"erreur": "Route inconnue."})

    def do_POST(self):  # noqa: N802 - signature imposée
        if self.path == "/specifications":
            self._specifications()
        elif self.path == "/modules":
            self._modules()
        else:
            self._repondre(404, {"erreur": "Route inconnue."})

    # ------------------------------------------------------------- traitements

    def _specifications(self) -> None:
        if not self._autorise():
            return
        charge = self._lire_json()
        if charge is None:
            return
        besoin = (charge.get("besoin") or "").strip()
        if not besoin:
            self._repondre(400, {"erreur": "Champ « besoin » absent ou vide."})
            return
        if len(besoin) > BESOIN_MAX:
            self._repondre(413, {"erreur": f"Besoin trop long : {len(besoin)} caractères."})
            return

        fournisseur = fournisseur_configure()
        if fournisseur is None:
            self._repondre(503, {"erreur": "Aucun fournisseur de modèle configuré."})
            return

        redacteur = SpecDrafter(fournisseur, tentatives_max=TENTATIVES)
        try:
            spec = redacteur.draft(besoin)
        except RedactionImpossible as erreur:
            # Le modèle n'a pas produit de spécification valide dans le budget.
            # C'est un refus intelligible, pas une panne du service.
            self._repondre(422, {
                "erreur": str(erreur),
                "tentatives": len(getattr(redacteur, "tentatives", [])),
            })
            return

        self._repondre(200, {
            "spec": _en_dict(spec),
            "fournisseur": getattr(fournisseur, "dernier_utilise", None) or "unique",
            "modele": getattr(fournisseur, "dernier_modele", None)
            or getattr(fournisseur, "modele", None),
            "corrections": max(0, len(getattr(redacteur, "tentatives", [])) - 1),
        })

    def _modules(self) -> None:
        if not self._autorise():
            return
        charge = self._lire_json()
        if charge is None:
            return
        spec = charge.get("spec")
        if not isinstance(spec, dict):
            self._repondre(400, {"erreur": "Champ « spec » absent ou mal formé."})
            return
        # Refuser tout de suite ce qui ne tient pas debout : inutile d'ouvrir
        # une fabrication pour la voir échouer à la première ligne.
        try:
            ModuleSpec.depuis_dict(spec)
        except SpecInvalide as erreur:
            self._repondre(422, {"erreur": str(erreur)})
            return

        identifiant = uuid.uuid4().hex
        registre.ouvrir(Travail(identifiant=identifiant, charge=spec))
        registre.lancer(identifiant, _fabriquer)
        self._repondre(202, {"id": identifiant, "etat": "queued"})


def principal() -> None:
    if not CLE_API:
        raise SystemExit("ATELIER_CLE_API n'est pas définie : le service refuse de démarrer.")
    print(
        f"API de l'Atelier sur le port {PORT} — installateur : {INSTALLATEUR_URL}, "
        f"origines autorisées : {ORIGINES or 'aucune'}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Poignee).serve_forever()


if __name__ == "__main__":
    principal()
