"""Le fournisseur de modèle, choisi depuis l'interface plutôt qu'en SSH.

POURQUOI CE FICHIER EXISTE. Jusqu'ici, changer de fournisseur demandait une
session sur le serveur et une relance de l'installeur. C'est contraire à ce
qu'on attend d'un outil en ligne, et contraire à la règle qu'on s'est donnée :
l'utilisateur tranche, l'outil exécute — il ne renvoie pas vers une
manipulation.

CE QUE ÇA NE CHANGE PAS, ET C'EST L'ESSENTIEL. La clé reste du côté du
serveur. Elle entre par la page, elle n'en ressort jamais : « etat() » rend
le fournisseur, le modèle et les QUATRE DERNIERS caractères — de quoi
reconnaître laquelle est en place, jamais de quoi s'en servir. Aucune route
ne rend la clé entière, et le JavaScript de la page ne la voit qu'au moment
où c'est l'utilisateur qui la tape.

CE QUE ÇA NE PRÉTEND PAS ÊTRE. La clé est stockée en clair dans le fichier
SQLite, comme elle l'était en clair dans « .env ». La chiffrer avec une clé
posée à côté, sur la même machine, ne protégerait de rien — il faut bien
déchiffrer pour appeler le fournisseur. Ce qui protège, c'est que le fichier
n'est lisible que par le service, que le volume n'est pas publié, et que la
clé ne traverse jamais le réseau en clair. Dire « chiffré au repos » ici
serait une décoration.

EN CLAIR SUR LE RÉSEAU, JAMAIS. Une adresse en « http:// » vers une machine
publique enverrait la clé en clair : elle est refusée. « http:// » vers la
boucle locale ou un réseau privé reste permis — c'est le cas d'un modèle
qui tourne sur la machine même, et là rien ne sort.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sqlite3
from dataclasses import dataclass
from urllib.parse import urlparse

SCHEMA = """
CREATE TABLE IF NOT EXISTS reglage (
    cle       TEXT PRIMARY KEY,
    valeur    TEXT NOT NULL,
    ecrit_le  TEXT NOT NULL,
    ecrit_par TEXT NOT NULL DEFAULT ''
);

-- PLUSIEURS FOURNISSEURS, ESSAYÉS DANS L'ORDRE. Un seul, c'est une panne
-- unique : quota du jour épuisé, service en maintenance, clé révoquée par un
-- collègue — et l'Atelier ne sait plus rédiger. Le rang décide de l'ordre
-- d'essai ; on bascule au suivant quand l'un est INDISPONIBLE, jamais parce
-- qu'une spécification est perfectible (ce cas-là appartient au validateur).
CREATE TABLE IF NOT EXISTS fournisseur (
    id          TEXT PRIMARY KEY,
    rang        INTEGER NOT NULL DEFAULT 0,
    service     TEXT NOT NULL,           -- « openrouter », « groq »…
    url         TEXT NOT NULL,
    modele      TEXT NOT NULL,
    cle         TEXT NOT NULL,
    ecrit_le    TEXT NOT NULL,
    ecrit_par   TEXT NOT NULL DEFAULT ''
);
"""

# Les fournisseurs connus, pour éviter d'avoir à retenir une URL. « autre »
# laisse tout saisir : le protocole d'OpenAI est parlé par beaucoup de monde,
# et figer une liste fermée nous ferait courir après chaque nouveau venu.
#
# CES NOMS DE MODÈLES VIEILLISSENT, ET VITE. Ce sont des points de départ, pas
# une vérité : le champ reste modifiable, et le bouton « Éprouver » appelle
# vraiment le service — c'est lui qui tranche, pas cette table.
#
# LE GRATUIT EXISTE, AVEC SES LIMITES. Les offres marquées « gratuit » le sont
# à quota : quelques appels par minute, souvent quelques centaines par jour.
# Pour rédiger une spécification de temps en temps, cela suffit largement.
FOURNISSEURS = {
    "openrouter": (
        "OpenRouter — modèles gratuits (DeepSeek, Gemma…)",
        "https://openrouter.ai/api/v1/chat/completions",
        "deepseek/deepseek-chat-v3-0324:free"),
    "groq": (
        "Groq — gratuit, très rapide",
        "https://api.groq.com/openai/v1/chat/completions",
        "llama-3.3-70b-versatile"),
    "gemini": (
        "Google Gemini — palier gratuit",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "gemini-2.0-flash"),
    "deepseek": (
        "DeepSeek — payant, peu cher",
        "https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
    "openai": ("OpenAI", "https://api.openai.com/v1/chat/completions", "gpt-4o"),
    "kimi": ("Moonshot / Kimi", "https://api.moonshot.ai/v1/chat/completions",
             "kimi-k2-turbo-preview"),
    "local": ("Sur cette machine (Ollama…)",
              "http://127.0.0.1:11434/v1/chat/completions", "qwen2.5-coder"),
    "autre": ("Autre (compatible OpenAI)", "", ""),
}


class ReglageInvalide(Exception):
    """Le réglage proposé ne peut pas être retenu."""


@dataclass(frozen=True)
class Modele:
    """Ce qu'on peut dire du fournisseur SANS livrer la clé."""

    fournisseur: str
    url: str
    modele: str
    fin_de_cle: str          # les quatre derniers caractères, jamais plus
    source: str              # « interface » ou « environnement »

    def en_dict(self) -> dict:
        return {
            "fournisseur": self.fournisseur,
            "url": self.url,
            "modele": self.modele,
            "fin_de_cle": self.fin_de_cle,
            "source": self.source,
        }


def verifier_url(url: str) -> str:
    """Rend l'URL nettoyée, ou lève. Refuse ce qui enverrait la clé en clair."""
    url = (url or "").strip()
    if not url:
        raise ReglageInvalide("L'adresse du fournisseur est vide.")
    morceaux = urlparse(url)
    if morceaux.scheme not in ("http", "https"):
        raise ReglageInvalide("L'adresse doit commencer par http:// ou https://.")
    if not morceaux.hostname:
        raise ReglageInvalide("L'adresse n'a pas d'hôte.")
    if morceaux.scheme == "http" and not _chez_soi(morceaux.hostname):
        raise ReglageInvalide(
            "En http://, la clé voyagerait en clair. Utilisez https://, ou une "
            "adresse locale si le modèle tourne sur cette machine.")
    return url


def adresse_du_catalogue(url_de_completion: str) -> str:
    """De « …/v1/chat/completions » à « …/v1/models ».

    Tous les services parlant le protocole d'OpenAI exposent la liste de leurs
    modèles à cet endroit. La déduire de l'adresse déjà configurée évite d'en
    demander une seconde à l'utilisateur — et une adresse qu'on ne saisit pas
    est une adresse qu'on ne se trompe pas d'écrire.
    """
    url = (url_de_completion or "").strip().rstrip("/")
    for suffixe in ("/chat/completions", "/completions", "/messages"):
        if url.endswith(suffixe):
            return url[: -len(suffixe)] + "/models"
    return url + "/models"


def _chez_soi(hote: str) -> bool:
    """Vrai si l'hôte ne sort pas de la machine ou du réseau privé."""
    if hote in ("localhost", "host.docker.internal"):
        return True
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        return False
    return adresse.is_loopback or adresse.is_private


# Comment on entre dans cette instance. Trois postures, et elles répondent à
# trois situations réelles — pas à trois goûts.
#
#   « fermee » : rien à l'écran, on n'entre que par un lien d'invitation. Le
#   plus sûr, mais l'administrateur est dans la boucle à chaque personne.
#
#   « code »   : un bouton « Créer un compte » demande un CODE D'ÉQUIPE, donné
#   une fois à tout le monde. C'est le bon compromis pour une équipe : chacun
#   s'inscrit seul, mais un passant qui trouve l'adresse ne peut rien.
#
#   « libre »  : n'importe qui peut se créer un compte. Sur une adresse
#   publique, cela revient à confier un outil qui fabrique du code au premier
#   venu — l'Atelier le dit, et ne l'active jamais de lui-même.
INSCRIPTIONS = ("fermee", "code", "libre")


class Reglages:
    """Les réglages durables, dans le même fichier que projets et comptes."""

    CLES = ("ia_fournisseur", "ia_url", "ia_modele", "ia_cle")

    def __init__(self, chemin: str):
        self.chemin = chemin
        os.makedirs(os.path.dirname(self.chemin) or ".", exist_ok=True)
        with self._lien() as lien:
            lien.executescript(SCHEMA)

    def _lien(self) -> sqlite3.Connection:
        lien = sqlite3.connect(self.chemin)
        lien.row_factory = sqlite3.Row
        return lien

    def _lire(self, cle: str) -> str:
        with self._lien() as lien:
            ligne = lien.execute(
                "SELECT valeur FROM reglage WHERE cle = ?", (cle,)).fetchone()
        return ligne["valeur"] if ligne else ""

    # ------------------------------------------------------------ le modèle

    def poser_modele(self, fournisseur: str, url: str, modele: str, cle: str,
                     horodatage: str, par: str = "") -> None:
        if fournisseur not in FOURNISSEURS:
            raise ReglageInvalide(f"Fournisseur inconnu « {fournisseur} ».")
        url = verifier_url(url)
        modele = (modele or "").strip()
        if not modele:
            raise ReglageInvalide("Le nom du modèle est vide.")
        cle = (cle or "").strip()
        # Une clé collée depuis un courriel emporte souvent un retour à la
        # ligne ou une espace : elle produirait alors un 401 incompréhensible.
        if re.search(r"\s", cle):
            raise ReglageInvalide("La clé contient une espace ou un retour à "
                                  "la ligne : recopiez-la sans.")
        if len(cle) < 8:
            raise ReglageInvalide("Cette clé est trop courte pour en être une.")
        with self._lien() as lien:
            for nom, valeur in (("ia_fournisseur", fournisseur), ("ia_url", url),
                                ("ia_modele", modele), ("ia_cle", cle)):
                lien.execute(
                    "INSERT INTO reglage (cle, valeur, ecrit_le, ecrit_par) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(cle) DO UPDATE SET "
                    "valeur = excluded.valeur, ecrit_le = excluded.ecrit_le, "
                    "ecrit_par = excluded.ecrit_par",
                    (nom, valeur, horodatage, par))

    def oublier_modele(self) -> None:
        with self._lien() as lien:
            lien.execute(
                "DELETE FROM reglage WHERE cle IN "
                "('ia_fournisseur', 'ia_url', 'ia_modele', 'ia_cle')")

    # ------------------------------------------------------ plusieurs clés

    def ajouter_fournisseur(self, service: str, url: str, modele: str,
                            cle: str, horodatage: str, par: str = "") -> str:
        """Un fournisseur de plus dans la file. Rend son identifiant."""
        if service not in FOURNISSEURS:
            raise ReglageInvalide(f"Fournisseur inconnu « {service} ».")
        url = verifier_url(url)
        modele = (modele or "").strip()
        if not modele:
            raise ReglageInvalide("Le nom du modèle est vide.")
        cle = (cle or "").strip()
        if re.search(r"\s", cle):
            raise ReglageInvalide("La clé contient une espace : recopiez-la sans.")
        if len(cle) < 8:
            raise ReglageInvalide("Cette clé est trop courte pour en être une.")
        identifiant = f"{service}-{abs(hash((service, modele, cle))) % 10**8:08d}"
        with self._lien() as lien:
            rang = lien.execute(
                "SELECT COALESCE(MAX(rang), -1) + 1 AS suivant FROM fournisseur"
            ).fetchone()["suivant"]
            lien.execute(
                "INSERT INTO fournisseur (id, rang, service, url, modele, cle, "
                "ecrit_le, ecrit_par) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET url = excluded.url, "
                "modele = excluded.modele, cle = excluded.cle, "
                "ecrit_le = excluded.ecrit_le",
                (identifiant, rang, service, url, modele, cle, horodatage, par))
        return identifiant

    def fournisseurs(self) -> list[dict]:
        """La file, dans l'ordre d'essai. LA CLÉ ENTIÈRE Y EST : réservé à la
        construction du routeur, jamais à une route."""
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT * FROM fournisseur ORDER BY rang, ecrit_le").fetchall()
        return [dict(l) for l in lignes]

    def file_visible(self) -> list[dict]:
        """La même file, montrable : quatre derniers caractères de la clé."""
        return [{"id": f["id"], "service": f["service"], "modele": f["modele"],
                 "url": f["url"], "fin_de_cle": f["cle"][-4:], "rang": f["rang"]}
                for f in self.fournisseurs()]

    def oter_fournisseur(self, identifiant: str) -> bool:
        with self._lien() as lien:
            return lien.execute("DELETE FROM fournisseur WHERE id = ?",
                                (identifiant,)).rowcount > 0

    def deplacer_fournisseur(self, identifiant: str, vers_le_haut: bool) -> bool:
        """L'ordre est une décision : le premier essayé est celui qu'on
        préfère — le plus fiable, ou le moins cher, c'est à l'utilisateur."""
        file = self.fournisseurs()
        positions = [f["id"] for f in file]
        if identifiant not in positions:
            return False
        i = positions.index(identifiant)
        j = i - 1 if vers_le_haut else i + 1
        if j < 0 or j >= len(positions):
            return False
        positions[i], positions[j] = positions[j], positions[i]
        with self._lien() as lien:
            for rang, cle_id in enumerate(positions):
                lien.execute("UPDATE fournisseur SET rang = ? WHERE id = ?",
                             (rang, cle_id))
        return True

    # -------------------------------------------------------- inscriptions

    def poser_inscription(self, mode: str, code: str, horodatage: str,
                          par: str = "") -> None:
        if mode not in INSCRIPTIONS:
            raise ReglageInvalide(f"Mode d'inscription inconnu « {mode} ».")
        code = (code or "").strip()
        if mode == "code":
            # Court, il se devine ; c'est le seul rempart entre l'adresse
            # publique et la création d'un compte.
            if len(code) < 8:
                raise ReglageInvalide(
                    "Le code d'équipe doit faire au moins 8 caractères.")
            if re.search(r"\s", code):
                raise ReglageInvalide("Le code d'équipe ne doit pas contenir "
                                      "d'espace : il se recopie mal.")
        with self._lien() as lien:
            for nom, valeur in (("inscription_mode", mode),
                                ("inscription_code", code)):
                lien.execute(
                    "INSERT INTO reglage (cle, valeur, ecrit_le, ecrit_par) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(cle) DO UPDATE SET "
                    "valeur = excluded.valeur, ecrit_le = excluded.ecrit_le, "
                    "ecrit_par = excluded.ecrit_par",
                    (nom, valeur, horodatage, par))

    def inscription(self) -> str:
        """« fermee » par défaut : une instance neuve n'ouvre rien d'elle-même."""
        return self._lire("inscription_mode") or "fermee"

    def code_inscription(self) -> str:
        """Le code d'équipe entier. Réservé à la vérification et à
        l'administrateur qui doit le transmettre."""
        return self._lire("inscription_code")

    def cle(self) -> str:
        """La clé entière. RÉSERVÉ à l'appel du fournisseur, jamais à une route."""
        return self._lire("ia_cle")

    def etat(self) -> Modele | None:
        """Ce qu'on peut montrer : jamais la clé, seulement de quoi la reconnaître.

        Rend None si rien n'est posé par l'interface ; l'appelant se rabat
        alors sur l'environnement.
        """
        cle = self._lire("ia_cle")
        if not cle:
            return None
        return Modele(
            fournisseur=self._lire("ia_fournisseur") or "autre",
            url=self._lire("ia_url"),
            modele=self._lire("ia_modele"),
            fin_de_cle=cle[-4:],
            source="interface",
        )
