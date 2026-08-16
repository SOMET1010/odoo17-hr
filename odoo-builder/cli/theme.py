#!/usr/bin/env python3
"""Fabriquer un thème backend Odoo — et le VOIR avant de l'installer.

    python3 cli/theme.py --nom "Thème ANSUT" --technique ansut_backend_theme \
        --primaire "#2256A3" --accent "#F08224" --sortie ./theme

Produit, pour chaque version visée, un module installable ET une page
d'aperçu. Pour un module métier l'aperçu montre une structure ; pour un thème
il EST le produit — un thème n'est rien d'autre que ce qu'on voit. Livrer une
archive sans rien à regarder revient à faire choisir une peinture sur son nom
de référence.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from theme.apercu import rendre  # noqa: E402
from theme.generateur import (  # noqa: E402
    CIBLES, DENSITES, POLICES, Charte, ThemeInvalide, contraste, generer,
    texte_lisible,
)

VERT, ROUGE, JAUNE, GRAS, FIN = (
    "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m")


def principal(argv=None) -> int:
    a = argparse.ArgumentParser(prog="theme", description=__doc__)
    a.add_argument("--nom", required=True)
    a.add_argument("--technique", required=True, help="nom technique du module")
    a.add_argument("--primaire", required=True, help="couleur principale, #RRGGBB")
    a.add_argument("--accent", required=True, help="couleur secondaire, #RRGGBB")
    a.add_argument("--police", default="systeme", choices=sorted(POLICES))
    a.add_argument("--densite", default="normale", choices=sorted(DENSITES))
    a.add_argument("--arrondi", default="4px")
    a.add_argument("--auteur", default="")
    a.add_argument("--licence", default="LGPL-3")
    a.add_argument("--cibles", nargs="+", default=list(CIBLES), choices=list(CIBLES))
    a.add_argument("--sortie", default="./theme")
    args = a.parse_args(argv)

    charte = Charte(
        nom=args.nom, technical_name=args.technique, primaire=args.primaire,
        accent=args.accent, police=args.police, densite=args.densite,
        arrondi=args.arrondi, auteur=args.auteur, licence=args.licence,
    )
    try:
        charte.valider()
    except ThemeInvalide as erreur:
        print(f"{ROUGE}Charte invalide{FIN} : {erreur}")
        return 2

    print(f"\n{GRAS}=== {charte.nom}{FIN}\n")
    print("  Lisibilité — le seuil du WCAG est 4,5:1")
    for nom, couleur in (("primaire", charte.primaire), ("accent", charte.accent)):
        texte = texte_lisible(couleur)
        rapport = contraste(couleur, texte)
        etat = f"{VERT}OK{FIN}" if rapport >= 4.5 else f"{ROUGE}INSUFFISANT{FIN}"
        lisible = "blanc" if texte == "#FFFFFF" else "noir"
        print(f"    {nom:<9} {couleur}  texte {lisible:<6} {rapport:>5.2f}:1  {etat}")
    for avertissement in charte.avertissements:
        print(f"  {JAUNE}ATTENTION{FIN} {avertissement}")

    os.makedirs(args.sortie, exist_ok=True)
    print()
    for cible in args.cibles:
        fichiers = generer(charte, cible)
        archive = os.path.join(args.sortie, f"{charte.technical_name}-{cible}.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for chemin, contenu in sorted(fichiers.items()):
                z.writestr(chemin, contenu)
        apercu = os.path.join(args.sortie, f"apercu-{cible}.html")
        with open(apercu, "w", encoding="utf-8") as f:
            f.write(rendre(charte, cible))
        print(f"  Odoo {cible}  module {os.path.basename(archive)}"
              f"  ·  aperçu {os.path.basename(apercu)}")

    premier = os.path.abspath(os.path.join(args.sortie,
                                           f"apercu-{args.cibles[0]}.html"))
    print(f"\n  {GRAS}Ouvrez l'aperçu avant d'installer :{FIN}\n  {premier}\n")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
