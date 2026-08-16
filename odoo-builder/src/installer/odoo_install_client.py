"""Client du service d'installation de .docker/service-installation.

Le Builder ne parle pas à Odoo ni à Docker : il dépose une archive sur le
service, qui tient les barrières de sécurité et pilote l'installation. Le
Builder n'a donc jamais besoin du socket Docker, lui non plus.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass


class ErreurInstallation(Exception):
    """Le service d'installation est injoignable ou refuse l'archive."""


@dataclass
class Resultat:
    etat: str                  # success | failed
    module: str
    journal: list[str]
    erreur: str | None = None

    @property
    def ok(self) -> bool:
        return self.etat == "success"

    def texte(self) -> str:
        lignes = [f"Installation : {'SUCCESS' if self.ok else 'FAILED'}"]
        lignes += [f"  {l}" for l in self.journal]
        if self.erreur:
            lignes.append(f"  Erreur : {self.erreur}")
        return "\n".join(lignes)


def empaqueter(fichiers: dict[str, str]) -> bytes:
    """Construit l'archive ZIP attendue par le service d'installation."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for chemin, contenu in sorted(fichiers.items()):
            archive.writestr(chemin, contenu)
    return tampon.getvalue()


class OdooInstallClient:
    def __init__(self, url: str, cle_api: str, delai_total: int = 600):
        self.url = url.rstrip("/")
        self.cle_api = cle_api
        self.delai_total = delai_total

    def _requete(self, chemin: str, corps: bytes | None = None, type_contenu: str | None = None):
        requete = urllib.request.Request(
            f"{self.url}{chemin}",
            data=corps,
            method="POST" if corps is not None else "GET",
        )
        requete.add_header("X-Cle-Api", self.cle_api)
        if type_contenu:
            requete.add_header("Content-Type", type_contenu)
        try:
            with urllib.request.urlopen(requete, timeout=60) as reponse:
                return json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as erreur:
            try:
                charge = json.loads(erreur.read().decode("utf-8"))
            except Exception:
                charge = {"erreur": erreur.reason}
            raise ErreurInstallation(
                f"{erreur.code} — {charge.get('erreur', 'refus du service')}"
            )
        except urllib.error.URLError as erreur:
            raise ErreurInstallation(
                f"service d'installation injoignable sur {self.url} : {erreur.reason}"
            )

    def sante(self) -> bool:
        try:
            return self._requete("/sante").get("etat") == "ok"
        except ErreurInstallation:
            return False

    def installer(self, fichiers: dict[str, str], pause: float = 2.0) -> Resultat:
        depot = self._requete("/modules", empaqueter(fichiers), "application/zip")
        identifiant = depot["id"]
        module = depot.get("module", "?")

        echeance = time.time() + self.delai_total
        while time.time() < echeance:
            etat = self._requete(f"/modules/{identifiant}")
            if etat["etat"] in ("success", "failed"):
                return Resultat(
                    etat=etat["etat"],
                    module=module,
                    journal=etat.get("journal", []),
                    erreur=etat.get("erreur"),
                )
            time.sleep(pause)

        raise ErreurInstallation(
            f"l'installation de « {module} » n'a pas abouti en {self.delai_total} s"
        )
