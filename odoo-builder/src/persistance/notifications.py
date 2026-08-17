"""Prévenir, quand quelque chose mérite de l'être.

CE QUE CE FICHIER FAIT, ET SURTOUT CE QU'IL NE FAIT PAS. Il décrit un
ÉVÉNEMENT et le remet à qui veut l'entendre. Il ne sait rien du destinataire :
ni son protocole, ni son format, ni son adresse. C'est ce qui permet de
brancher ANSUT Hub le jour où l'on connaît son contrat, sans rouvrir une ligne
de la gestion des comptes.

TROIS DESTINATAIRES, PAR ORDRE DE CE QU'ILS COÛTENT.

  Le JOURNAL. Toujours. Il ne demande rien, ne peut pas tomber, et suffit à
  répondre à « qui a créé ce compte, et quand ». Une notification qui part
  ailleurs sans laisser de trace ici est une notification qu'on ne pourra pas
  vérifier.

  Un WEBHOOK — ANSUT Hub, ou n'importe quel service qui accepte du JSON en
  POST. C'est la voie prévue pour le Hub : une adresse, un jeton, et le
  contrat ci-dessous.

  Le COURRIEL, par « smtplib ». Bibliothèque standard : pas de dépendance à
  installer, pas de service tiers dans la boucle, et rien de plus à mettre à
  jour le jour d'une alerte.

CE QU'UN ÉVÉNEMENT NE CONTIENT JAMAIS : un mot de passe, une clé, un jeton de
session. Ces objets ne sortent pas du serveur, et une notification est
précisément ce qui sort — souvent vers un service qui l'archive, l'indexe, et
le montre à plus de monde qu'on ne croit.

L'ENVOI NE DOIT JAMAIS FAIRE ÉCHOUER L'ACTE. Créer un compte réussit même si
le Hub est en panne : l'inverse ferait dépendre l'administration de l'Atelier
de la disponibilité d'un service qui n'a rien à voir. L'échec d'envoi est
JOURNALISÉ, jamais silencieux, jamais bloquant.
"""

from __future__ import annotations

import json
import os
import smtplib
import sqlite3
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage

# Les clés qu'un événement ne portera jamais, quoi qu'on lui passe. Une liste
# blanche serait plus sûre encore, mais elle interdirait d'enrichir un
# événement sans revenir ici ; ce filtre-ci attrape ce qui compte.
INTERDITS = ("motdepasse", "mot_de_passe", "cle", "cle_api", "jeton", "token",
             "password", "secret", "empreinte")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notification (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    genre    TEXT NOT NULL,
    sujet    TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT '',
    par      TEXT NOT NULL DEFAULT '',
    ecrit_le TEXT NOT NULL,
    remis    TEXT NOT NULL DEFAULT ''      -- « », « ok » ou le motif de l'échec
);

CREATE INDEX IF NOT EXISTS notification_date ON notification(ecrit_le);
"""


@dataclass
class Evenement:
    genre: str                       # « compte.cree », « compte.desactive »…
    sujet: str                       # ce que ça concerne : un nom de compte
    detail: str = ""
    par: str = ""                    # qui l'a provoqué
    donnees: dict = field(default_factory=dict)

    def en_dict(self) -> dict:
        """La charge remise au destinataire, expurgée."""
        propres = {c: v for c, v in self.donnees.items()
                   if not any(interdit in c.lower() for interdit in INTERDITS)}
        return {"genre": self.genre, "sujet": self.sujet,
                "detail": self.detail, "par": self.par, "donnees": propres}


class Notifications:
    """Le journal, et les voies de sortie configurées."""

    def __init__(self, chemin: str):
        self.chemin = chemin
        os.makedirs(os.path.dirname(self.chemin) or ".", exist_ok=True)
        with self._lien() as lien:
            lien.executescript(SCHEMA)

    def _lien(self) -> sqlite3.Connection:
        lien = sqlite3.connect(self.chemin)
        lien.row_factory = sqlite3.Row
        return lien

    # ------------------------------------------------------------ émission

    def signaler(self, evenement: Evenement, horodatage: str) -> int:
        """Journalise TOUJOURS, puis tente les voies configurées.

        Rend l'identifiant de la trace. L'ordre compte : on écrit avant
        d'envoyer, pour qu'une panne d'envoi laisse quand même une trace de ce
        qui s'est passé.
        """
        with self._lien() as lien:
            curseur = lien.execute(
                "INSERT INTO notification (genre, sujet, detail, par, ecrit_le) "
                "VALUES (?, ?, ?, ?, ?)",
                (evenement.genre, evenement.sujet, evenement.detail,
                 evenement.par, horodatage))
            identifiant = curseur.lastrowid

        motifs = []
        for envoyer in (self._vers_webhook, self._vers_courriel):
            try:
                envoyer(evenement)
            except Exception as erreur:                       # noqa: BLE001
                # Large à dessein : un service distant peut échouer de mille
                # façons, et AUCUNE ne doit empêcher la création d'un compte.
                motifs.append(f"{envoyer.__name__[6:]} : {erreur}")

        etat = "; ".join(motifs) if motifs else "ok"
        with self._lien() as lien:
            lien.execute("UPDATE notification SET remis = ? WHERE id = ?",
                         (etat[:400], identifiant))
        return identifiant

    def journal(self, combien: int = 50) -> list[dict]:
        with self._lien() as lien:
            lignes = lien.execute(
                "SELECT genre, sujet, detail, par, ecrit_le, remis "
                "FROM notification ORDER BY id DESC LIMIT ?",
                (combien,)).fetchall()
        return [dict(l) for l in lignes]

    # -------------------------------------------------------------- sorties

    @staticmethod
    def _vers_webhook(evenement: Evenement) -> None:
        """POST JSON vers un service — ANSUT Hub, ou tout autre.

        LE CONTRAT, tant qu'on n'a pas celui du Hub :

            POST <NOTIF_WEBHOOK_URL>
            Content-Type: application/json
            Authorization: Bearer <NOTIF_WEBHOOK_JETON>   (si le jeton est posé)

            {"genre": "compte.cree", "sujet": "dev1",
             "detail": "...", "par": "pierre", "donnees": {...}}

        Le jour où le Hub attend autre chose — un autre en-tête, un autre
        enveloppement — c'est ICI que ça se change, et nulle part ailleurs.
        """
        url = os.environ.get("NOTIF_WEBHOOK_URL", "").strip()
        if not url:
            return
        if not url.startswith("https://") and "localhost" not in url \
                and not url.startswith("http://127."):
            # Un événement porte des noms de comptes : en clair sur un réseau,
            # ça se lit.
            raise ValueError(
                "NOTIF_WEBHOOK_URL doit être en https:// (ou local).")
        charge = json.dumps(evenement.en_dict(), ensure_ascii=False)
        requete = urllib.request.Request(
            url, data=charge.encode("utf-8"), method="POST")
        requete.add_header("Content-Type", "application/json; charset=utf-8")
        jeton = os.environ.get("NOTIF_WEBHOOK_JETON", "").strip()
        if jeton:
            requete.add_header("Authorization", f"Bearer {jeton}")
        # Court : une notification qui bloque dix secondes bloque la page de
        # celui qui vient de cliquer.
        with urllib.request.urlopen(requete, timeout=5) as reponse:
            if reponse.status >= 300:
                raise ValueError(f"réponse {reponse.status}")

    @staticmethod
    def _vers_courriel(evenement: Evenement) -> None:
        """Courriel par « smtplib » — bibliothèque standard, aucune dépendance.

            NOTIF_SMTP_HOTE, NOTIF_SMTP_PORT, NOTIF_SMTP_UTILISATEUR,
            NOTIF_SMTP_MOTDEPASSE, NOTIF_COURRIEL_DE, NOTIF_COURRIEL_A
        """
        hote = os.environ.get("NOTIF_SMTP_HOTE", "").strip()
        destinataires = os.environ.get("NOTIF_COURRIEL_A", "").strip()
        if not hote or not destinataires:
            return
        message = EmailMessage()
        message["Subject"] = f"[Atelier] {evenement.genre} — {evenement.sujet}"
        message["From"] = os.environ.get("NOTIF_COURRIEL_DE", "atelier@localhost")
        message["To"] = destinataires
        message.set_content(
            f"{evenement.detail or evenement.genre}\n\n"
            f"Concerne : {evenement.sujet}\n"
            f"À l'initiative de : {evenement.par or 'inconnu'}\n")

        port = int(os.environ.get("NOTIF_SMTP_PORT", "587"))
        utilisateur = os.environ.get("NOTIF_SMTP_UTILISATEUR", "")
        motdepasse = os.environ.get("NOTIF_SMTP_MOTDEPASSE", "")
        with smtplib.SMTP(hote, port, timeout=8) as serveur:
            if port != 25:
                # STARTTLS avec vérification du certificat : sans contexte
                # explicite, certaines versions de Python ne vérifient rien, et
                # un identifiant SMTP passe alors en clair sans que rien ne le
                # dise.
                serveur.starttls(context=ssl.create_default_context())
            if utilisateur:
                serveur.login(utilisateur, motdepasse)
            serveur.send_message(message)

    # ------------------------------------------------------------- diagnostic

    @staticmethod
    def voies_configurees() -> dict:
        """Ce qui est branché, sans jamais dire avec quel secret."""
        return {
            "webhook": bool(os.environ.get("NOTIF_WEBHOOK_URL", "").strip()),
            "courriel": bool(os.environ.get("NOTIF_SMTP_HOTE", "").strip()
                             and os.environ.get("NOTIF_COURRIEL_A", "").strip()),
        }
