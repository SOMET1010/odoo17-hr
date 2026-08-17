#!/usr/bin/env python3
"""Reprendre la main sur un compte dont le mot de passe est perdu.

    python3 cli/reprendre_la_main.py            # liste les comptes
    python3 cli/reprendre_la_main.py psomet     # repose un mot de passe

POURQUOI CET OUTIL A LE DROIT D'EXISTER. Il ne s'exécute que sur la machine
qui porte le dépôt. Or, y avoir accès, c'est déjà pouvoir lire et modifier ce
fichier à la main : cette commande ne donne aucun pouvoir nouveau. Elle évite
seulement d'écrire du SQL de mémoire un jour de panique — moment où l'on se
trompe, et où l'on efface ce qu'on voulait sauver.

CE QU'IL FAIT, ET POURQUOI DANS CET ORDRE.

  Il tire un mot de passe au sort plutôt que de vous en demander un. Un mot de
  passe tapé dans une commande reste dans l'historique du shell et dans la
  liste des processus, où le premier venu sur la machine le relit.

  Il le pose comme PROVISOIRE. Ce mot de passe s'affiche sur une console et
  traverse un canal quelconque avant d'arriver à vous : il ne doit servir qu'à
  entrer une fois. L'Atelier exigera d'en choisir un autre, que vous seul
  connaîtrez.

  Il coupe toutes les sessions du compte. Si quelqu'un d'autre était entré
  avec l'ancien mot de passe, il est dehors.

  Il RÉACTIVE le compte s'il était désactivé — car le cas le plus probable où
  l'on se retrouve dehors est justement celui-là.
"""

from __future__ import annotations

import os
import secrets
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from persistance.comptes import Comptes  # noqa: E402
from persistance.depot import Depot  # noqa: E402

MOTS = ("atelier", "module", "chantier", "registre", "bordereau", "greffe",
        "version", "facture", "dossier", "mission", "cahier", "epreuve")


def phrase() -> str:
    """Quatre mots tirés de « secrets », lisibles à voix haute au téléphone."""
    tirage = [secrets.choice(MOTS) for _ in range(4)]
    return "-".join(tirage) + "-" + str(secrets.randbelow(100))


def principal(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    depot = Depot()
    comptes = Comptes(depot.chemin)
    print(f"Dépôt : {depot.chemin}\n")

    inventaire = comptes.journal_des_comptes()
    if not inventaire:
        print("Aucun compte dans ce dépôt. Vérifiez ATELIER_DEPOT :")
        print("dans le conteneur, il vaut /var/lib/atelier/atelier.sqlite3.")
        return 1

    if not argv:
        print("Comptes existants :\n")
        for compte in inventaire:
            etats = [compte["role"]]
            if not compte["actif"]:
                etats.append("désactivé")
            if compte["provisoire"]:
                etats.append("mot de passe provisoire")
            print(f"  {compte['nom']:<20} {' · '.join(etats)}")
        print("\nRelancez avec le nom du compte à reprendre.")
        return 0

    nom = argv[0]
    nouveau = phrase()
    if not comptes.reinitialiser(nom, nouveau):
        print(f"Aucun compte « {nom} ». Relancez sans argument pour la liste.")
        return 1

    print(f"Mot de passe PROVISOIRE de « {nom} » :\n")
    print(f"    {nouveau}\n")
    print("Toutes ses sessions sont fermées, et le compte est réactivé s'il")
    print("ne l'était plus. À la première connexion, l'Atelier exigera d'en")
    print("choisir un autre — celui-ci a traversé une console, il ne vaut que")
    print("pour entrer une fois.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
