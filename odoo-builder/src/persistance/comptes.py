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
    vu_le      TEXT NOT NULL DEFAULT '',
    -- Un mot de passe posé par l'administrateur est PROVISOIRE : il le
    -- connaît. Tant que ce drapeau est levé, la seule chose que le compte
    -- puisse faire est d'en changer.
    provisoire INTEGER NOT NULL DEFAULT 0,
    -- Désactiver plutôt que supprimer : on ferme la porte sans effacer la
    -- trace de qui a fait quoi, et on peut rouvrir.
    actif      INTEGER NOT NULL DEFAULT 1,
    cree_par   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session (
    jeton     TEXT PRIMARY KEY,
    compte    TEXT NOT NULL REFERENCES compte(id) ON DELETE CASCADE,
    ouverte_le TEXT NOT NULL,
    expire_le  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS session_compte ON session(compte);

-- Une invitation permet à quelqu'un de créer SON compte, avec SON mot de
-- passe. C'est ce qui distingue une instance close d'une instance fermée :
-- personne n'entre sans y avoir été convié, et pourtant l'administrateur ne
-- connaît le secret de personne.
CREATE TABLE IF NOT EXISTS invitation (
    jeton      TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'membre',
    note       TEXT NOT NULL DEFAULT '',      -- « pour Awa », pour s'y retrouver
    cree_par   TEXT NOT NULL DEFAULT '',
    cree_le    TEXT NOT NULL,
    expire_le  TEXT NOT NULL,
    utilise_le TEXT NOT NULL DEFAULT '',
    utilise_par TEXT NOT NULL DEFAULT ''
);
"""


class CompteInvalide(Exception):
    """Le compte demandé ne peut pas être créé ou utilisé."""


@dataclass(frozen=True)
class Compte:
    id: str
    nom: str
    role: str
    provisoire: bool = False
    actif: bool = True

    @property
    def administrateur(self) -> bool:
        return self.role == "administrateur"

    def en_dict(self) -> dict:
        return {"id": self.id, "nom": self.nom, "role": self.role,
                "provisoire": self.provisoire}


def _depuis_ligne(ligne) -> Compte:
    """Une ligne de base devient un compte. Un seul endroit qui sache le faire."""
    return Compte(ligne["id"], ligne["nom"], ligne["role"],
                  provisoire=bool(ligne["provisoire"]),
                  actif=bool(ligne["actif"]))


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

    # Les colonnes ajoutées après coup. Une base créée par une version
    # antérieure ne les a pas ; « ALTER TABLE » au démarrage évite d'avoir à
    # refaire le fichier — donc de perdre les comptes déjà créés.
    AJOUTS = (
        ("provisoire", "INTEGER NOT NULL DEFAULT 0"),
        ("actif", "INTEGER NOT NULL DEFAULT 1"),
        ("cree_par", "TEXT NOT NULL DEFAULT ''"),
    )

    def __init__(self, chemin: str):
        self.chemin = chemin
        os.makedirs(os.path.dirname(self.chemin) or ".", exist_ok=True)
        with self._lien() as lien:
            lien.executescript(SCHEMA)
            existantes = {c["name"] for c in
                          lien.execute("PRAGMA table_info(compte)").fetchall()}
            for nom, definition in self.AJOUTS:
                if nom not in existantes:
                    lien.execute(f"ALTER TABLE compte ADD COLUMN {nom} {definition}")

    def _lien(self) -> sqlite3.Connection:
        lien = sqlite3.connect(self.chemin)
        lien.row_factory = sqlite3.Row
        lien.execute("PRAGMA foreign_keys = ON")
        return lien

    # -------------------------------------------------------------- comptes

    def creer(self, nom: str, motdepasse: str, horodatage: str,
              role: str = "membre", provisoire: bool = False,
              cree_par: str = "") -> Compte:
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
                    "INSERT INTO compte (id, nom, empreinte, role, cree_le, "
                    "provisoire, cree_par) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (identifiant, nom, empreinte(motdepasse), role, horodatage,
                     1 if provisoire else 0, cree_par),
                )
        except sqlite3.IntegrityError:
            raise CompteInvalide(f"Le nom « {nom} » est déjà pris.")
        return Compte(identifiant, nom, role, provisoire=provisoire)

    def compte(self, nom: str) -> Compte | None:
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT id, nom, role, provisoire, actif FROM compte "
                "WHERE nom = ?", (nom,)).fetchone()
        return _depuis_ligne(ligne) if ligne else None

    def activer(self, nom: str, actif: bool) -> bool:
        """Fermer une porte sans effacer la trace de qui a fait quoi.

        Désactiver ferme aussi les sessions ouvertes : sans cela, la personne
        continue de travailler jusqu'à l'expiration de son jeton — trente
        jours — et « accès retiré » ne veut rien dire.
        """
        with self._lien() as lien:
            curseur = lien.execute(
                "UPDATE compte SET actif = ? WHERE nom = ?",
                (1 if actif else 0, nom))
            if not actif:
                lien.execute(
                    "DELETE FROM session WHERE compte IN "
                    "(SELECT id FROM compte WHERE nom = ?)", (nom,))
            return curseur.rowcount > 0

    def fermer_les_sessions(self, nom: str) -> int:
        with self._lien() as lien:
            curseur = lien.execute(
                "DELETE FROM session WHERE compte IN "
                "(SELECT id FROM compte WHERE nom = ?)", (nom,))
            return curseur.rowcount

    def administrateurs_actifs(self) -> int:
        with self._lien() as lien:
            return lien.execute(
                "SELECT COUNT(*) AS n FROM compte WHERE actif = 1 "
                "AND role = 'administrateur'").fetchone()["n"]

    def lister(self) -> list[Compte]:
        """Qui a accès, pour que l'administrateur puisse le savoir.

        Sans cette liste, on ouvre des accès sans jamais pouvoir en faire
        l'inventaire — et on découvre un compte oublié le jour où quelqu'un
        s'en sert.
        """
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT id, nom, role, provisoire, actif FROM compte "
                "ORDER BY cree_le").fetchall()
        return [_depuis_ligne(l) for l in lignes]

    def journal_des_comptes(self) -> list[dict]:
        """La même liste, avec les dates — pour l'écran, pas pour la logique."""
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT c.nom, c.role, c.cree_le, c.vu_le, c.provisoire, "
                "c.actif, c.cree_par, "
                "(SELECT COUNT(*) FROM session s WHERE s.compte = c.id) "
                "AS sessions "
                "FROM compte c ORDER BY c.cree_le").fetchall()
        return [dict(l) for l in lignes]

    def supprimer(self, nom: str) -> bool:
        """Retirer un accès. Les projets du compte, eux, restent.

        Les effacer avec lui ferait disparaître du travail au moment précis
        où l'on veut seulement fermer une porte.
        """
        with self._lien() as lien:
            curseur = lien.execute("DELETE FROM compte WHERE nom = ?", (nom,))
            return curseur.rowcount > 0

    # ---------------------------------------------------------- invitations

    DUREE_INVITATION_JOURS = 7

    def creer_invitation(self, role: str, note: str, horodatage: str,
                         expire_le: str, par: str = "") -> str:
        """Rend le jeton. À USAGE UNIQUE et daté.

        Sans expiration, un lien oublié dans une conversation ouvre encore un
        compte des mois plus tard. Sans usage unique, il en ouvre autant qu'on
        veut — et un lien se transfère.
        """
        if role not in ("membre", "administrateur"):
            raise CompteInvalide(f"rôle inconnu « {role} ».")
        jeton = secrets.token_urlsafe(24)
        with self._lien() as lien:
            lien.execute(
                "INSERT INTO invitation (jeton, role, note, cree_par, cree_le, "
                "expire_le) VALUES (?, ?, ?, ?, ?, ?)",
                (jeton, role, note.strip()[:80], par, horodatage, expire_le))
        return jeton

    def invitation(self, jeton: str, maintenant: str) -> dict | None:
        """L'invitation si elle est utilisable, None sinon. Ne consomme rien."""
        if not jeton:
            return None
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT * FROM invitation WHERE jeton = ?", (jeton,)).fetchone()
        if ligne is None or ligne["utilise_le"] or ligne["expire_le"] <= maintenant:
            return None
        return dict(ligne)

    def consommer_invitation(self, jeton: str, par: str, maintenant: str) -> bool:
        """Marque l'invitation comme utilisée. Rend False si elle ne l'est plus.

        La condition est DANS le UPDATE : deux personnes qui cliquent le même
        lien en même temps ne peuvent pas créer deux comptes, parce que c'est
        SQLite qui arbitre, pas une vérification faite juste avant.
        """
        with self._lien() as lien:
            curseur = lien.execute(
                "UPDATE invitation SET utilise_le = ?, utilise_par = ? "
                "WHERE jeton = ? AND utilise_le = '' AND expire_le > ?",
                (maintenant, par, jeton, maintenant))
            return curseur.rowcount > 0

    def lister_invitations(self, maintenant: str) -> list[dict]:
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT role, note, cree_par, cree_le, expire_le, utilise_le, "
                "utilise_par, jeton FROM invitation ORDER BY cree_le DESC "
                "LIMIT 50").fetchall()
        dehors = []
        for ligne in lignes:
            invitation = dict(ligne)
            invitation["etat"] = (
                "utilisée" if invitation["utilise_le"]
                else ("périmée" if invitation["expire_le"] <= maintenant
                      else "en attente"))
            # Le jeton n'est rendu QUE tant qu'il sert : réafficher un lien
            # consommé invite à le renvoyer, et il ne marchera pas.
            if invitation["etat"] != "en attente":
                invitation["jeton"] = ""
            dehors.append(invitation)
        return dehors

    def revoquer_invitation(self, jeton: str) -> bool:
        with self._lien() as lien:
            curseur = lien.execute("DELETE FROM invitation WHERE jeton = ?",
                                   (jeton,))
            return curseur.rowcount > 0

    def combien(self) -> int:
        with self._lien() as lien:
            return lien.execute("SELECT COUNT(*) AS n FROM compte").fetchone()["n"]

    def changer_motdepasse(self, identifiant: str, motdepasse: str,
                           garder_session: str = "") -> None:
        """Change le mot de passe ET ferme les sessions ouvertes ailleurs.

        Laisser vivre les sessions après un changement de mot de passe vide
        celui-ci de son sens : on change justement parce qu'on soupçonne que
        quelqu'un d'autre est entré.
        """
        if len(motdepasse or "") < 12:
            raise CompteInvalide("Le mot de passe doit faire au moins 12 caractères.")
        with self._lien() as lien:
            # « provisoire » retombe : c'est l'acte même de choisir son mot de
            # passe qui rend le compte utilisable.
            lien.execute(
                "UPDATE compte SET empreinte = ?, provisoire = 0 WHERE id = ?",
                (empreinte(motdepasse), identifiant))
            # Toutes les sessions SAUF celle qui vient de changer le mot de
            # passe : la fermer aussi déconnecterait la personne au moment
            # précis où elle vient de faire ce qu'on lui demandait.
            lien.execute("DELETE FROM session WHERE compte = ? AND jeton != ?",
                         (identifiant, garder_session))

    def reinitialiser(self, nom: str, motdepasse: str) -> bool:
        """Repose un mot de passe PROVISOIRE, coupe les sessions, réactive.

        Réservé à la maintenance, depuis la machine elle-même : y avoir accès,
        c'est déjà pouvoir lire et modifier ce fichier. Cette fonction ne donne
        donc aucun pouvoir nouveau — elle évite d'écrire du SQL de mémoire un
        jour de panique, moment où l'on se trompe et où l'on efface ce qu'on
        voulait sauver.

        Provisoire à dessein : ce mot de passe s'affiche sur une console et
        traverse un canal quelconque. Il ne doit servir qu'à entrer une fois.
        """
        with self._lien() as lien:
            curseur = lien.execute(
                "UPDATE compte SET empreinte = ?, provisoire = 1, actif = 1 "
                "WHERE nom = ?", (empreinte(motdepasse), nom))
            if curseur.rowcount:
                lien.execute(
                    "DELETE FROM session WHERE compte IN "
                    "(SELECT id FROM compte WHERE nom = ?)", (nom,))
            return curseur.rowcount > 0

    # ------------------------------------------------------------- sessions

    def ouvrir_session(self, nom: str, motdepasse: str, horodatage: str,
                       expire_le: str) -> tuple[Compte, str] | None:
        """Rend (compte, jeton) si le mot de passe est bon, None sinon.

        Un seul « None » pour « nom inconnu » et « mot de passe faux » : les
        distinguer dirait à un inconnu quels noms existent.
        """
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT id, nom, role, empreinte, provisoire, actif "
                "FROM compte WHERE nom = ?", (nom,)).fetchone()
        if ligne is None:
            # Même travail que pour un compte réel : sans cela, la RAPIDITÉ de
            # la réponse révèle qu'un nom n'existe pas.
            empreinte(motdepasse or "", tours=TOURS)
            return None
        if not verifier(motdepasse or "", ligne["empreinte"]):
            return None
        if not ligne["actif"]:
            # Même réponse qu'un mot de passe faux : dire « compte désactivé »
            # confirmerait à un inconnu que ce nom existe.
            return None

        jeton = secrets.token_urlsafe(32)
        with self._lien() as lien:
            lien.execute(
                "INSERT INTO session (jeton, compte, ouverte_le, expire_le) "
                "VALUES (?, ?, ?, ?)", (jeton, ligne["id"], horodatage, expire_le))
            lien.execute("UPDATE compte SET vu_le = ? WHERE id = ?",
                         (horodatage, ligne["id"]))
        return _depuis_ligne(ligne), jeton

    def session(self, jeton: str, maintenant: str) -> Compte | None:
        if not jeton:
            return None
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT c.id, c.nom, c.role, c.provisoire, c.actif, "
                "s.expire_le FROM session s "
                "JOIN compte c ON c.id = s.compte WHERE s.jeton = ?", (jeton,)
            ).fetchone()
            if ligne is None:
                return None
            if ligne["expire_le"] <= maintenant:
                # Une session périmée s'efface au passage : sinon la table
                # grossit indéfiniment de jetons qui ne servent plus.
                lien.execute("DELETE FROM session WHERE jeton = ?", (jeton,))
                return None
        if not ligne["actif"]:
            return None
        return _depuis_ligne(ligne)

    def fermer_session(self, jeton: str) -> None:
        with self._lien() as lien:
            lien.execute("DELETE FROM session WHERE jeton = ?", (jeton,))

    def purger(self, maintenant: str) -> int:
        with self._lien() as lien:
            curseur = lien.execute(
                "DELETE FROM session WHERE expire_le <= ?", (maintenant,))
            return curseur.rowcount
