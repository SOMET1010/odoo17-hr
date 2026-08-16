#!/usr/bin/env python3
"""Convertir un module Odoo existant vers une autre version.

    python3 cli/convertir.py /chemin/vers/mon_module --cible 19.0
    python3 cli/convertir.py /chemin/vers/mon_module --cible 19.0 --ecrire ./sortie

Le module est lu — jamais exécuté —, décrit sous forme de spécification, puis
rendu par le même générateur qui produit les modules neufs. Il n'y a donc pas
de « code de conversion » quelque part : convertir, c'est décrire puis
régénérer, avec le générateur déjà éprouvé sur 17, 18 et 19.

LE RAPPORT EST LA SORTIE PRINCIPALE. La spécification ne sait pas tout dire :
elle ne contient jamais de Python, donc aucune méthode n'est portée. Ce que la
conversion laisse derrière elle est nommé, fichier et ligne à l'appui. Un
module converti sans lire ce rapport est un module dont on ignore ce qu'il ne
fait plus.

Le code de sortie ne vaut pas jugement de qualité : 0 signifie « la
spécification obtenue est valide et se génère », pas « rien n'a été perdu ».
Utiliser --exiger-complet pour que toute perte de comportement soit un échec.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from converter.extraction import ConversionImpossible, convertir  # noqa: E402
from generator.dialecte import CIBLES  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from spec.module_spec import SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, JAUNE, GRAS, FIN = (
    "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
)


def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(prog="convertir", description=__doc__)
    analyseur.add_argument("module", help="dossier du module à convertir")
    analyseur.add_argument("--cible", required=True, choices=CIBLES,
                           help="version d'Odoo visée")
    analyseur.add_argument("--ecrire", metavar="DOSSIER",
                           help="écrire le module converti dans ce dossier")
    analyseur.add_argument("--specification", metavar="FICHIER",
                           help="écrire la spécification obtenue (JSON)")
    analyseur.add_argument("--exiger-complet", action="store_true",
                           help="échouer si un comportement n'a pas été porté")
    args = analyseur.parse_args(argv)

    try:
        spec, rapport = convertir(args.module, args.cible)
    except ConversionImpossible as erreur:
        print(f"{ROUGE}Conversion impossible{FIN} : {erreur}")
        return 2

    print(f"{GRAS}=== {rapport.module} → Odoo {args.cible}{FIN}")
    print()
    print(rapport.texte())
    print()

    # La spécification obtenue doit tenir debout d'elle-même. Si elle ne
    # valide pas, c'est le convertisseur qui a produit quelque chose
    # d'incohérent, et il faut le voir ici — pas à l'installation.
    try:
        spec.valider()
    except SpecInvalide as erreur:
        print(f"{ROUGE}La spécification obtenue est invalide{FIN} : {erreur}")
        print("  C'est un défaut du convertisseur, pas du module d'origine.")
        return 1

    fichiers = OdooModuleGenerator().generate(spec)
    controle = OdooStaticValidator().check(fichiers, spec)
    if not controle.ok:
        print(f"{ROUGE}Le module converti ne passe pas la validation statique.{FIN}")
        print(controle.texte())
        return 1
    print(f"{VERT}Module converti : {len(fichiers)} fichiers, validation statique passée.{FIN}")

    if args.specification:
        with open(args.specification, "w", encoding="utf-8") as f:
            json.dump(_en_dict(spec), f, ensure_ascii=False, indent=2)
        print(f"  spécification écrite : {args.specification}")

    if args.ecrire:
        for chemin, contenu in sorted(fichiers.items()):
            complet = os.path.join(args.ecrire, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as f:
                f.write(contenu)
        print(f"  module écrit : {os.path.join(args.ecrire, spec.technical_name)}")

    perdus = rapport.comportements_perdus
    if perdus:
        print()
        print(f"{JAUNE}Rappel : {len(perdus)} élément(s) de comportement ne sont "
              f"pas dans le module converti.{FIN}")
        if args.exiger_complet:
            return 1
    return 0


def _en_dict(spec) -> dict:
    """Sérialisation de la spécification, empruntée à la boucle de réparation.

    Importée et non recopiée : deux sérialiseurs divergeraient, et l'un se
    corrigerait sans l'autre.
    """
    from repair.repair_loop import _en_dict as serialiser
    return serialiser(spec)


if __name__ == "__main__":
    sys.exit(principal())
