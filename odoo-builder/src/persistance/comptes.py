"""Qui utilise l'Atelier, et comment on le prouve.

Sans comptes, l'Atelier ne peut pas sortir de « 127.0.0.1 » : il lit des
dossiers de la machine et fabrique du code. En ligne et sans authentification,
c'est une console offerte à qui trouve l'adresse.

CE FICHIER NE FAIT QUE DE LA BIBLIOTHÈQUE STANDARD. Pas de dépendance à
installer, donc rien à mettre à jour en urgence le jour d'une alerte dans une
bibliothèque tierce — et l'Atelier continue de démarrer sur un poste sans
réseau.

LES CHOIX, ET LEURS RAISONS :

  PBKDF2-HMAC-SHA256, 600 000 tours. Un mot de passe n'est jamais stocké,
  seulement son empreinte salée. Le nombre de tours suit la recommandation de
  l'OWASP pour cette famille ; il est ENREGISTRÉ AVEC L'EMPREINTE, de sorte
  qu'on puisse l'augmenter demain sans invalider les comptes existants.

  Comparaison à temps constant. « == » sur des empreintes laisse fuir, par la
  durée, combien d'octets coïncident. « compare_digest » ne le fait pas.

  Sessions EN BASE, pas des jetons signés autoportants. Un jeton signé ne se
  révoque pas : changer un mot de passe laisserait vivre les sessions
  ouvertes ailleurs. Ici, on les efface.

  Jetons tirés de « secrets », jamais de « random ». Le second est prévisible
  par construction — c'est son objet — et sert aux simulations, pas aux
  secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass

TOURS = 600_000
ALGORITHME = "pbkdf2-sha256"
NOM = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
DUREE_SESSION_JOURS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS compte (
    id         TEXT PRIMARY KEY,
    nom        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    empreinte  TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'membre',   -- « membre » ou « administrateur »
    cree_le    TEXT NOT NULL,
    vu_le      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session (
    jeton     TEXT PRIMARY KEY,
    compte    TEXT NOT NULL REFERENCES compte(id) ON DELETE CASCADE,
    ouverte_le TEXT NOT NULL,
    expire_le  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS session_compte ON session(compte);
"""


class CompteInvalide(Exception):
    """Le compte demandé ne peut pas être créé ou utilisé."""


@dataclass(frozen=True)
class Compte:
    id: str
    nom: str
    role: str

    @property
    def administrateur(self) -> bool:
        return self.role == "administrateur"

    def en_dict(self) -> dict:
        return {"id": self.id, "nom": self.nom, "role": self.role}


def empreinte(motdepasse: str, sel: bytes | None = None, tours: int = TOURS) -> str:
    """« algorithme$tours$sel$empreinte », tout ce qu'il faut pour revérifier.

    Le paramétrage voyage AVEC l'empreinte. Le figer dans le code
    interdirait de l'augmenter sans invalider tous les comptes — et c'est
    précisément ce qu'on veut pouvoir faire quand le matériel progresse.
    """
    sel = sel or secrets.token_bytes(16)
    brut = hashlib.pbkdf2_hmac("sha256", motdepasse.encode("utf-8"), sel, tours)
    return f"{ALGORITHME}${tours}${sel.hex()}${brut.hex()}"


def verifier(motdepasse: str, stockee: str) -> bool:
    try:
        algorithme, tours, sel, attendue = stockee.split("$")
        if algorithme != ALGORITHME:
            return False
        calculee = hashlib.pbkdf2_hmac(
            "sha256", motdepasse.encode("utf-8"), bytes.fromhex(sel), int(tours)
        ).hex()
    except (ValueError, TypeError):
        return False
    # Temps constant : sinon la durée de comparaison trahit le nombre
    # d'octets déjà justes, et une empreinte se reconstitue octet par octet.
    return hmac.compare_digest(calculee, attendue)


class Comptes:
    """Les comptes et les sessions, dans le même fichier que les projets."""

    def __init__(self, chemin: str):
        self.chemin = chemin
        os.makedirs(os.path.dirname(self.chemin) or ".", exist_ok=True)
        with self._lien() as lien:
            lien.executescript(SCHEMA)

    def _lien(self) -> sqlite3.Connection:
        lien = sqlite3.connect(self.chemin)
        lien.row_factory = sqlite3.Row
        lien.execute("PRAGMA foreign_keys = ON")
        return lien

    # -------------------------------------------------------------- comptes

    def creer(self, nom: str, motdepasse: str, horodatage: str,
              role: str = "membre") -> Compte:
        if not NOM.match(nom or ""):
            raise CompteInvalide(
                "Le nom d'utilisateur doit faire 3 à 32 caractères, en lettres, "
                "chiffres, point, tiret ou tiret bas."
            )
        # Douze caractères, pas huit. Un Atelier en ligne fabrique du code et
        # garde des spécifications : ce n'est pas un forum.
        if len(motdepasse or "") < 12:
            raise CompteInvalide(
                "Le mot de passe doit faire au moins 12 caractères. Une phrase "
                "dont vous vous souvenez vaut mieux qu'un mot compliqué."
            )
        if role not in ("membre", "administrateur"):
            raise CompteInvalide(f"rôle inconnu « {role} ».")

        identifiant = secrets.token_hex(8)
        try:
            with self._lien() as lien:
                lien.execute(
                    "INSERT INTO compte (id, nom, empreinte, role, cree_le) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (identifiant, nom, empreinte(motdepasse), role, horodatage),
                )
        except sqlite3.IntegrityError:
            raise CompteInvalide(f"Le nom « {nom} » est déjà pris.")
        return Compte(identifiant, nom, role)

    def compte(self, nom: str) -> Compte | None:
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT id, nom, role FROM compte WHERE nom = ?", (nom,)
            ).fetchone()
        return Compte(ligne["id"], ligne["nom"], ligne["role"]) if ligne else None

    def combien(self) -> int:
        with self._lien() as lien:
            return lien.execute("SELECT COUNT(*) AS n FROM compte").fetchone()["n"]

    def changer_motdepasse(self, identifiant: str, motdepasse: str) -> None:
        """Change le mot de passe ET ferme les sessions ouvertes ailleurs.

        Laisser vivre les sessions après un changement de mot de passe vide
        celui-ci de son sens : on change justement parce qu'on soupçonne que
        quelqu'un d'autre est entré.
        """
        if len(motdepasse or "") < 12:
            raise CompteInvalide("Le mot de passe doit faire au moins 12 caractères.")
        with self._lien() as lien:
            lien.execute("UPDATE compte SET empreinte = ? WHERE id = ?",
                         (empreinte(motdepasse), identifiant))
            lien.execute("DELETE FROM session WHERE compte = ?", (identifiant,))

    # ------------------------------------------------------------- sessions

    def ouvrir_session(self, nom: str, motdepasse: str, horodatage: str,
                       expire_le: str) -> tuple[Compte, str] | None:
        """Rend (compte, jeton) si le mot de passe est bon, None sinon.

        Un seul « None » pour « nom inconnu » et « mot de passe faux » : les
        distinguer dirait à un inconnu quels noms existent.
        """
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT id, nom, role, empreinte FROM compte WHERE nom = ?", (nom,)
            ).fetchone()
        if ligne is None:
            # Même travail que pour un compte réel : sans cela, la RAPIDITÉ de
            # la réponse révèle qu'un nom n'existe pas.
            empreinte(motdepasse or "", tours=TOURS)
            return None
        if not verifier(motdepasse or "", ligne["empreinte"]):
            return None

        jeton = secrets.token_urlsafe(32)
        with self._lien() as lien:
            lien.execute(
                "INSERT INTO session (jeton, compte, ouverte_le, expire_le) "
                "VALUES (?, ?, ?, ?)", (jeton, ligne["id"], horodatage, expire_le))
            lien.execute("UPDATE compte SET vu_le = ? WHERE id = ?",
                         (horodatage, ligne["id"]))
        return Compte(ligne["id"], ligne["nom"], ligne["role"]), jeton

    def session(self, jeton: str, maintenant: str) -> Compte | None:
        if not jeton:
            return None
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT c.id, c.nom, c.role, s.expire_le FROM session s "
                "JOIN compte c ON c.id = s.compte WHERE s.jeton = ?", (jeton,)
            ).fetchone()
            if ligne is None:
                return None
            if ligne["expire_le"] <= maintenant:
                # Une session périmée s'efface au passage : sinon la table
                # grossit indéfiniment de jetons qui ne servent plus.
                lien.execute("DELETE FROM session WHERE jeton = ?", (jeton,))
                return None
        return Compte(ligne["id"], ligne["nom"], ligne["role"])

    def fermer_session(self, jeton: str) -> None:
        with self._lien() as lien:
            lien.execute("DELETE FROM session WHERE jeton = ?", (jeton,))

    def purger(self, maintenant: str) -> int:
        with self._lien() as lien:
            curseur = lien.execute(
                "DELETE FROM session WHERE expire_le <= ?", (maintenant,))
            return curseur.rowcount
