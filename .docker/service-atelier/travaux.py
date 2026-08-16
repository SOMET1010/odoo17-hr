"""Suivi des fabrications demandées par l'interface.

Fabriquer un module prend des dizaines de secondes : générer, valider,
empaqueter, déposer, puis attendre qu'Odoo l'installe. Une requête HTTP qui
attendrait tout cela expirerait chez le premier proxy venu. On rend donc un
identifiant tout de suite, et l'interface interroge l'état.

Une fabrication à la fois, comme pour l'installation : deux modules installés
en même temps se battraient pour le registre d'Odoo.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

EN_ATTENTE = "queued"
EN_COURS = "building"
SUCCES = "success"
ECHEC = "failed"


@dataclass
class Travail:
    identifiant: str
    charge: dict
    module: str | None = None
    etat: str = EN_ATTENTE
    journal: list[str] = field(default_factory=list)
    erreur: str | None = None
    cree_le: float = field(default_factory=time.time)
    fini_le: float | None = None

    def tracer(self, ligne: str) -> None:
        self.journal.append(str(ligne))

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
    """Les fabrications connues, et le fil unique qui les exécute."""

    def __init__(self):
        self._travaux: dict[str, Travail] = {}
        self._verrou = threading.Lock()
        self._file: queue.Queue = queue.Queue()
        self._fil = threading.Thread(target=self._boucler, daemon=True)
        self._fil.start()

    def ouvrir(self, travail: Travail) -> None:
        with self._verrou:
            self._travaux[travail.identifiant] = travail

    def lire(self, identifiant: str) -> Travail | None:
        with self._verrou:
            return self._travaux.get(identifiant)

    def lancer(self, identifiant: str, action) -> None:
        self._file.put((identifiant, action))

    def _boucler(self) -> None:
        while True:
            identifiant, action = self._file.get()
            travail = self.lire(identifiant)
            if travail is None:
                continue
            travail.etat = EN_COURS
            try:
                action(travail)
                travail.etat = SUCCES
            except Exception as erreur:  # noqa: BLE001 - la cause est rendue au client
                # Le message part vers l'interface : il doit nommer la cause,
                # sans porter ni chemin interne ni secret. Les exceptions du
                # Builder sont écrites pour être lues par un humain.
                travail.etat = ECHEC
                travail.erreur = str(erreur)
                travail.tracer(f"échec : {erreur}")
            finally:
                travail.fini_le = time.time()
