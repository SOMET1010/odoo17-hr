"""Installation guidée : une commande au lieu de dix.

L'utilisateur du Builder n'est pas administrateur système. Lui demander
d'exporter des variables, de recopier un fichier d'exemple et de composer un
secret à la main revient à lui déléguer un travail qui est celui de l'outil.

Ce module pose les questions, écrit ce qu'il faut où il faut, et vérifie que
ça marche. Il ne demande jamais de recopier une commande.

Deux règles tenues ici, les mêmes qu'ailleurs :
  - la clé n'est jamais écrite dans le dépôt, ni dans `routeur.json` ;
  - elle n'est jamais affichée, ni passée en argument de commande.
"""

from __future__ import annotations

import json
import os
import secrets
import stat

# Ce qu'on sait proposer, avec le nom de variable retenu pour chacun.
FOURNISSEURS = {
    "kimi": {
        "libelle": "Kimi / Moonshot",
        "protocole": "openai",
        "url": "https://api.moonshot.ai/v1/chat/completions",
        "cle_env": "KIMI_API_KEY",
        "modele_suggere": "kimi-k3",
    },
    "openai": {
        "libelle": "OpenAI",
        "protocole": "openai",
        "url": "https://api.openai.com/v1/chat/completions",
        "cle_env": "OPENAI_API_KEY",
        "modele_suggere": "gpt-5.6",
    },
    "anthropic": {
        "libelle": "Anthropic",
        "protocole": "anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "cle_env": "ANTHROPIC_API_KEY",
        "modele_suggere": "claude-sonnet-5",
    },
}


class InstallationImpossible(Exception):
    """L'installation ne peut pas aboutir sans intervention."""


def dossier_configuration() -> str:
    """Hors du dépôt, dans l'espace de configuration de l'utilisateur."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "atelier-odoo")


def chemin_secrets() -> str:
    return os.path.join(dossier_configuration(), "env")


def _hors_du_depot(chemin: str, depot: str) -> bool:
    return os.path.commonpath([os.path.abspath(chemin), os.path.abspath(depot)]) != (
        os.path.abspath(depot)
    )


def ecrire_secrets(valeurs: dict[str, str], depot: str) -> str:
    """Écrit les secrets, en refusant tout emplacement situé dans le dépôt."""
    chemin = chemin_secrets()
    if not _hors_du_depot(chemin, depot):
        raise InstallationImpossible(
            f"refus d'écrire des secrets dans le dépôt ({chemin})."
        )
    os.makedirs(os.path.dirname(chemin), exist_ok=True)

    lignes = [
        "# Secrets de l'Atelier Odoo — ne pas partager, ne pas versionner.\n",
        "# Fichier lisible par vous seul.\n",
    ]
    lignes += [f'export {nom}="{valeur}"\n' for nom, valeur in valeurs.items()]

    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as f:
        f.writelines(lignes)
    os.chmod(chemin, stat.S_IRUSR | stat.S_IWUSR)
    return chemin


def declarer_fournisseur(url: str, modele: str, chemin: str | None = None) -> str:
    """Inscrit le point d'entrée et le modèle dans le fichier de secrets.

    Ni l'un ni l'autre n'est un secret — mais ils vivent auprès de la clé,
    parce qu'ils n'ont de sens qu'avec elle : une clé Moonshot envoyée à OpenAI
    est refusée, et c'est exactement le mur rencontré en production.

    Les déclarations existantes sont remplacées, jamais empilées : deux
    `export BUILDER_IA_URL` dans le même fichier laisseraient la dernière
    gagner en silence, ce qui rend un diagnostic incompréhensible.
    """
    chemin = chemin or chemin_secrets()
    os.makedirs(os.path.dirname(chemin), exist_ok=True)

    conservees = []
    if os.path.isfile(chemin):
        with open(chemin, encoding="utf-8") as f:
            conservees = [
                ligne for ligne in f
                if not ligne.lstrip().startswith(
                    ("export BUILDER_IA_URL=", "export BUILDER_IA_MODELE=")
                )
            ]
        if conservees and not conservees[-1].endswith("\n"):
            conservees[-1] += "\n"

    conservees.append(f'export BUILDER_IA_URL="{url}"\n')
    conservees.append(f'export BUILDER_IA_MODELE="{modele}"\n')

    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as f:
        f.writelines(conservees)
    os.chmod(chemin, stat.S_IRUSR | stat.S_IWUSR)
    return chemin


def ecrire_routeur(choisis: list[tuple[str, str]], chemin: str) -> str:
    """Écrit routeur.json — qui ne contient jamais de clé, seulement des noms."""
    fournisseurs = []
    for cle, modele in choisis:
        modele_defaut = FOURNISSEURS[cle]
        fournisseurs.append({
            "nom": cle,
            "protocole": modele_defaut["protocole"],
            "url": modele_defaut["url"],
            "modele": modele or modele_defaut["modele_suggere"],
            "cle_env": modele_defaut["cle_env"],
        })
    donnee = {
        "_commentaire": "Écrit par « atelier-odoo setup ». Ne contient aucune clé : "
                        "seulement le nom de la variable d'environnement qui la porte.",
        "fournisseurs": fournisseurs,
    }
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(donnee, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return chemin


def secret_installateur() -> str:
    """Un secret pour le service d'installation : l'outil le compose lui-même.

    Il n'y a aucune raison de demander à l'utilisateur d'inventer une chaîne
    aléatoire, ni de lui faire exécuter une commande pour en obtenir une.
    """
    return secrets.token_urlsafe(32)
