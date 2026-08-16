"""La mémoire de l'Atelier : des projets qui survivent à la fermeture d'un onglet.

Jusqu'ici la pièce en cours vivait en mémoire du processus. On fermait la
fenêtre, le travail était perdu. C'était tenable pour un outil d'un seul poste
qu'on lance et qu'on arrête ; ça ne l'est plus dès qu'on y revient d'une autre
machine, ou simplement le lendemain.

POURQUOI MAINTENANT, ET PAS PLUS TARD. Ajouter la persistance après coup
oblige à reprendre chaque chemin de code — concevoir, convertir, thème — pour
y glisser un enregistrement, et à retrouver ce qui aurait dû être sauvé et ne
l'a pas été. La poser d'abord ne coûte presque rien : les chemins passent tous
par le même point.

CE QUE CE DÉPÔT GARDE : la SPÉCIFICATION, jamais le module engendré. Le module
se régénère à la demande, et le regénérer depuis la spécification garantit
qu'il porte les corrections apportées au générateur depuis. Stocker les
fichiers produits reviendrait à figer un livrable au générateur du jour, puis
à livrer plus tard du code qu'on ne sait plus reproduire.

SQLite, et rien d'autre. Pas de serveur de base à installer, un seul fichier
qu'on copie pour sauvegarder, et la bibliothèque standard de Python suffit —
l'Atelier doit continuer de démarrer sur un poste sans réseau.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS projet (
    id           TEXT PRIMARY KEY,
    nom          TEXT NOT NULL,
    genre        TEXT NOT NULL,          -- « module » ou « theme »
    cible        TEXT NOT NULL,
    technique    TEXT NOT NULL,
    contenu      TEXT NOT NULL,          -- spécification ou charte, en JSON
    proprietaire TEXT NOT NULL DEFAULT '',  -- le compte, vide = poste local
    origine      TEXT NOT NULL DEFAULT '',
    cree_le      TEXT NOT NULL,
    modifie_le   TEXT NOT NULL
);

-- Chaque enregistrement laisse une trace. Sans historique, corriger une
-- spécification écrase l'état précédent : on perd la version qui marchait au
-- moment précis où l'on cherche ce qu'on a changé.
CREATE TABLE IF NOT EXISTS revision (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    projet    TEXT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
    contenu   TEXT NOT NULL,
    motif     TEXT NOT NULL DEFAULT '',
    ecrit_le  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS revision_projet ON revision(projet);
"""


@dataclass
class Projet:
    id: str
    nom: str
    genre: str
    cible: str
    technique: str
    contenu: dict
    origine: str
    cree_le: str
    modifie_le: str
    proprietaire: str = ""
    revisions: int = 0

    def en_dict(self) -> dict:
        return {
            "id": self.id, "nom": self.nom, "genre": self.genre,
            "cible": self.cible, "technique": self.technique,
            "origine": self.origine, "cree_le": self.cree_le,
            "modifie_le": self.modifie_le, "revisions": self.revisions,
        }


class ProjetInaccessible(Exception):
    """Le projet visé n'existe pas, ou n'appartient pas à ce compte."""


class Depot:
    """Les projets de l'Atelier, dans un fichier."""

    def __init__(self, chemin: str | None = None):
        self.chemin = chemin or os.environ.get(
            "ATELIER_DEPOT",
            os.path.join(os.path.expanduser("~"), ".atelier", "projets.sqlite"),
        )
        os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
        with self._lien() as lien:
            lien.executescript(SCHEMA)
            # Les dépôts créés avant les comptes n'ont pas la colonne. La
            # poser après coup vaut mieux qu'exiger d'effacer ses projets
            # pour installer une mise à jour.
            colonnes = {c["name"] for c in lien.execute("PRAGMA table_info(projet)")}
            if "proprietaire" not in colonnes:
                lien.execute("ALTER TABLE projet ADD COLUMN proprietaire "
                             "TEXT NOT NULL DEFAULT ''")

    def _lien(self) -> sqlite3.Connection:
        lien = sqlite3.connect(self.chemin)
        lien.row_factory = sqlite3.Row
        # Les clés étrangères ne sont PAS actives par défaut en SQLite :
        # sans cette ligne, supprimer un projet laisserait ses révisions
        # orphelines, et le fichier grossirait sans qu'on sache pourquoi.
        lien.execute("PRAGMA foreign_keys = ON")
        return lien

    # ------------------------------------------------------------ écriture

    def enregistrer(self, nom: str, genre: str, cible: str, technique: str,
                    contenu: dict, horodatage: str, origine: str = "",
                    identifiant: str | None = None, motif: str = "",
                    proprietaire: str = "") -> str:
        """Créer un projet, ou en déposer une nouvelle révision.

        L'horodatage est FOURNI, jamais lu de l'horloge ici : une fonction qui
        va chercher l'heure elle-même ne se teste pas deux fois de la même
        façon, et c'est le genre de dépendance cachée qui rend un test
        intermittent.
        """
        contenu_json = json.dumps(contenu, ensure_ascii=False)
        with self._lien() as lien:
            if identifiant:
                # Le propriétaire fait partie de la CLÉ de recherche : sans
                # lui, connaître un identifiant suffirait à écraser le projet
                # d'un autre. Un identifiant se devine mal, mais « mal » n'est
                # pas « pas ».
                existant = lien.execute(
                    "SELECT id FROM projet WHERE id = ? AND proprietaire = ?",
                    (identifiant, proprietaire),
                ).fetchone()
            else:
                existant = None
            if identifiant and not existant:
                # L'identifiant est fourni mais ne désigne aucun projet de ce
                # compte. Insérer produirait une violation d'unicité — donc
                # une erreur 500 illisible — et en fabriquer un nouveau
                # masquerait la tentative. On refuse en le disant.
                deja = lien.execute("SELECT 1 FROM projet WHERE id = ?",
                                    (identifiant,)).fetchone()
                if deja:
                    raise ProjetInaccessible(
                        f"Le projet « {identifiant} » ne vous appartient pas.")
            if existant:
                lien.execute(
                    "UPDATE projet SET nom = ?, genre = ?, cible = ?, "
                    "technique = ?, contenu = ?, modifie_le = ? WHERE id = ?",
                    (nom, genre, cible, technique, contenu_json, horodatage,
                     identifiant),
                )
            else:
                identifiant = identifiant or uuid.uuid4().hex[:12]
                lien.execute(
                    "INSERT INTO projet (id, nom, genre, cible, technique, "
                    "contenu, origine, cree_le, modifie_le, proprietaire) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (identifiant, nom, genre, cible, technique, contenu_json,
                     origine, horodatage, horodatage, proprietaire),
                )
            lien.execute(
                "INSERT INTO revision (projet, contenu, motif, ecrit_le) "
                "VALUES (?, ?, ?, ?)",
                (identifiant, contenu_json, motif, horodatage),
            )
        return identifiant

    def supprimer(self, identifiant: str, proprietaire: str = "") -> bool:
        with self._lien() as lien:
            curseur = lien.execute(
                "DELETE FROM projet WHERE id = ? AND proprietaire = ?",
                (identifiant, proprietaire))
            return curseur.rowcount > 0

    # ------------------------------------------------------------- lecture

    def lister(self, proprietaire: str = "", limite: int = 50) -> list:
        """Les projets DE CE COMPTE, du plus récemment touché au plus ancien.

        Le filtre est appliqué en base, pas après coup : filtrer en Python
        une liste déjà chargée finit toujours par oublier un chemin.
        """
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM revision r WHERE r.projet = p.id)"
                " AS revisions FROM projet p WHERE p.proprietaire = ?"
                " ORDER BY p.modifie_le DESC LIMIT ?",
                (proprietaire, limite),
            ).fetchall()
        return [self._depuis_ligne(l) for l in lignes]

    def ouvrir(self, identifiant: str, proprietaire: str = "") -> Projet | None:
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM revision r WHERE r.projet = p.id)"
                " AS revisions FROM projet p WHERE p.id = ? AND p.proprietaire = ?",
                (identifiant, proprietaire),
            ).fetchone()
        return self._depuis_ligne(ligne) if ligne else None

    def historique(self, identifiant: str, proprietaire: str = "",
                   limite: int = 20) -> list:
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT r.id, r.motif, r.ecrit_le FROM revision r "
                "JOIN projet p ON p.id = r.projet "
                "WHERE r.projet = ? AND p.proprietaire = ? "
                "ORDER BY r.id DESC LIMIT ?", (identifiant, proprietaire, limite),
            ).fetchall()
        return [dict(l) for l in lignes]

    def revision(self, identifiant: str, numero: int,
                 proprietaire: str = "") -> dict | None:
        """Le contenu d'une révision précise — pour revenir en arrière.

        Le projet est vérifié en plus du numéro : sans cela, connaître un
        numéro de révision suffirait à lire le contenu d'un autre projet.
        """
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT r.contenu FROM revision r JOIN projet p ON p.id = r.projet "
                "WHERE r.id = ? AND r.projet = ? AND p.proprietaire = ?",
                (numero, identifiant, proprietaire),
            ).fetchone()
        return json.loads(ligne["contenu"]) if ligne else None

    @staticmethod
    def _depuis_ligne(ligne) -> Projet:
        return Projet(
            id=ligne["id"], nom=ligne["nom"], genre=ligne["genre"],
            cible=ligne["cible"], technique=ligne["technique"],
            contenu=json.loads(ligne["contenu"]), origine=ligne["origine"],
            cree_le=ligne["cree_le"], modifie_le=ligne["modifie_le"],
            revisions=ligne["revisions"] if "revisions" in ligne.keys() else 0,
        )
