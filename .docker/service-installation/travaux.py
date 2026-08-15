"""Suivi des demandes d'installation.

Une seule installation à la fois : les demandes sont sérialisées dans une
file et traitées par un unique fil d'exécution. Deux installations
simultanées se battraient pour le registre d'Odoo.

Les quatre états exposés par l'API sont ceux arbitrés au moment de définir
le périmètre : queued, installing, success, failed.
"""

from __future__ import annotations

import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field

EN_ATTENTE = "queued"
EN_COURS = "installing"
SUCCES = "success"
ECHEC = "failed"


@dataclass
class Travail:
    identifiant: str
    module: str
    etat: str = EN_ATTENTE
    journal: list[str] = field(default_factory=list)
    erreur: str | None = None
    cree_le: float = field(default_factory=time.time)
    fini_le: float | None = None

    def tracer(self, ligne: str) -> None:
        self.journal.append(ligne)

    def en_json(self) -> dict:
        return {
            "id": self.identifiant,
            "module": self.module,
            "etat": self.etat,
            "journal": list(self.journal),
            "erreur": self.erreur,
            "cree_le": self.cree_le,
            "fini_le": self.fini_le,
        }


class Registre:
    """Mémoire des travaux, bornée pour ne pas grossir indéfiniment."""

    def __init__(self, maximum: int = 200):
        self._verrou = threading.Lock()
        self._travaux: dict[str, Travail] = {}
        self._maximum = maximum

    def ajouter(self, travail: Travail) -> None:
        with self._verrou:
            self._travaux[travail.identifiant] = travail
            self._elaguer()

    def lire(self, identifiant: str) -> Travail | None:
        with self._verrou:
            return self._travaux.get(identifiant)

    def _elaguer(self) -> None:
        """Oublie les travaux terminés les plus anciens au-delà du plafond."""
        if len(self._travaux) <= self._maximum:
            return
        termines = sorted(
            (t for t in self._travaux.values() if t.etat in (SUCCES, ECHEC)),
            key=lambda t: t.fini_le or t.cree_le,
        )
        for travail in termines:
            if len(self._travaux) <= self._maximum:
                break
            del self._travaux[travail.identifiant]


class Ouvrier:
    """Fil d'exécution unique qui déballe puis installe, demande après demande."""

    def __init__(self, registre: Registre, installer, dossier_addons: str):
        self.registre = registre
        # `installer(travail, dossier_module)` : injecté pour rester testable
        # sans Odoo.
        self.installer = installer
        self.dossier_addons = dossier_addons
        self.file: queue.Queue = queue.Queue()
        self._fil = threading.Thread(target=self._boucler, daemon=True)

    def demarrer(self) -> None:
        self._fil.start()

    def deposer(self, travail: Travail, chemin_zip: str, extraire) -> None:
        self.registre.ajouter(travail)
        self.file.put((travail, chemin_zip, extraire))

    def _boucler(self) -> None:
        while True:
            travail, chemin_zip, extraire = self.file.get()
            try:
                self._traiter(travail, chemin_zip, extraire)
            except Exception as erreur:  # le fil ne doit jamais mourir
                travail.etat = ECHEC
                travail.erreur = str(erreur)
                travail.tracer(f"Échec : {erreur}")
                travail.fini_le = time.time()
            finally:
                try:
                    os.unlink(chemin_zip)
                except OSError:
                    pass
                self.file.task_done()

    def _traiter(self, travail: Travail, chemin_zip: str, extraire) -> None:
        travail.etat = EN_COURS
        travail.tracer(f"Déballage du module « {travail.module} ».")

        # On déballe à côté, puis on bascule d'un coup : une extraction
        # interrompue ne doit pas laisser un module à moitié écrit dans
        # l'addons_path d'Odoo.
        transit = os.path.join(self.dossier_addons, f".transit-{travail.identifiant}")
        shutil.rmtree(transit, ignore_errors=True)
        try:
            extraire(chemin_zip, transit)
            destination = os.path.join(self.dossier_addons, travail.module)
            shutil.rmtree(destination, ignore_errors=True)
            os.replace(os.path.join(transit, travail.module), destination)
            travail.tracer(f"Module écrit dans {destination}.")
        finally:
            shutil.rmtree(transit, ignore_errors=True)

        self.installer(travail)
        travail.etat = SUCCES
        travail.fini_le = time.time()
        travail.tracer("Installation terminée.")
