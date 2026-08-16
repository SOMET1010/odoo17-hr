#!/usr/bin/env python3
"""atelier-odoo — fabrique un module Odoo depuis une spécification.

    atelier-odoo build specs/diligence_simple.json
    atelier-odoo build spec.json --sortie /tmp/module --sans-installation

La commande enchaîne : spécification → génération → validation statique →
archive → installation réelle → statut et journaux. En cas d'échec, et si un
fournisseur de modèle est configuré, elle tente jusqu'à trois réparations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from ai.provider import OpenAIProvider  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import (  # noqa: E402
    ErreurInstallation, OdooInstallClient, empaqueter,
)
from repair.repair_loop import RepairLoop  # noqa: E402
from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402
from spec.module_spec import ModuleSpec, SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, GRAS, FIN = "\033[32m", "\033[31m", "\033[1m", "\033[0m"


def journal(message: str) -> None:
    print(message, flush=True)


def _charger_spec(args) -> ModuleSpec:
    """Depuis un fichier, ou depuis un besoin en français via le modèle."""
    if args.besoin:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SpecInvalide(
                "OPENAI_API_KEY n'est pas définie : impossible de traduire un "
                "besoin en spécification. Fournir un fichier de spécification, "
                "ou définir la clé."
            )
        redacteur = SpecDrafter(OpenAIProvider(), tentatives_max=args.tentatives)
        spec = redacteur.draft(args.besoin, journal)
        if args.ecrire_spec:
            with open(args.ecrire_spec, "w", encoding="utf-8") as f:
                f.write(redacteur.tentatives[-1])
            journal(f"Spécification écrite dans {args.ecrire_spec}")
        return spec

    with open(args.spec, encoding="utf-8") as f:
        return ModuleSpec.depuis_dict(json.load(f))


def commande_build(args) -> int:
    if not args.spec and not args.besoin:
        print(f"{ROUGE}Fournir un fichier de spécification, ou --besoin.{FIN}")
        return 2
    try:
        spec = _charger_spec(args)
    except FileNotFoundError:
        print(f"{ROUGE}Spécification introuvable : {args.spec}{FIN}")
        return 2
    except json.JSONDecodeError as erreur:
        print(f"{ROUGE}JSON invalide dans {args.spec} : {erreur}{FIN}")
        return 2
    except SpecInvalide as erreur:
        print(f"{ROUGE}Spécification refusée : {erreur}{FIN}")
        return 2
    except RedactionImpossible as erreur:
        print(f"{ROUGE}Rédaction impossible : {erreur}{FIN}")
        return 2

    print(f"{GRAS}Module {spec.technical_name} — {spec.name}{FIN}")

    installateur = None
    if not args.sans_installation:
        cle = os.environ.get("INSTALLATEUR_CLE_API", "")
        if not cle:
            print(
                f"{ROUGE}INSTALLATEUR_CLE_API n'est pas définie.{FIN} "
                "Utiliser --sans-installation pour s'arrêter à la validation."
            )
            return 2
        installateur = OdooInstallClient(args.service, cle)
        if not installateur.sante():
            print(f"{ROUGE}Service d'installation injoignable sur {args.service}.{FIN}")
            print("  Démarrer la pile : docker compose --profile installateur up -d")
            return 2

    fournisseur = OpenAIProvider() if os.environ.get("OPENAI_API_KEY") else None
    if fournisseur is None and not args.sans_installation:
        journal("(aucun OPENAI_API_KEY : réparation automatique désactivée)")

    boucle = RepairLoop(
        OdooModuleGenerator(),
        OdooStaticValidator(),
        installateur,
        fournisseur,
        tentatives_max=args.tentatives,
    )
    issue = boucle.executer(spec, journal)

    if args.sortie:
        os.makedirs(args.sortie, exist_ok=True)
        for chemin, contenu in issue.fichiers.items():
            complet = os.path.join(args.sortie, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as f:
                f.write(contenu)
        archive = os.path.join(args.sortie, f"{spec.technical_name}.zip")
        with open(archive, "wb") as f:
            f.write(empaqueter(issue.fichiers))
        journal(f"Module écrit dans {args.sortie} ({archive})")

    print()
    if issue.reussi:
        if installateur is None:
            # Sans bac à sable, on n'a prouvé que la validation statique :
            # annoncer « is running » serait un mensonge.
            print(
                f"{VERT}Module {spec.technical_name} généré et validé.{FIN} "
                "Installation non jouée (--sans-installation)."
            )
        else:
            print(f"{VERT}Module {spec.technical_name} is running.{FIN}")
        return 0

    print(f"{ROUGE}Échec.{FIN}")
    print(issue.texte())
    return 1


def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(prog="atelier-odoo", description=__doc__)
    sous = analyseur.add_subparsers(dest="commande", required=True)

    build = sous.add_parser("build", help="fabrique et installe un module")
    build.add_argument("spec", nargs="?", help="fichier de spécification JSON")
    build.add_argument(
        "--besoin",
        help="besoin en français ; le modèle en rédige la spécification "
             "(nécessite OPENAI_API_KEY)",
    )
    build.add_argument(
        "--ecrire-spec", dest="ecrire_spec",
        help="enregistre la spécification rédigée par le modèle",
    )
    build.add_argument("--sortie", help="dossier où écrire le module généré")
    build.add_argument(
        "--service", default=os.environ.get("INSTALLATEUR_URL", "http://localhost:8090"),
        help="URL du service d'installation",
    )
    build.add_argument(
        "--sans-installation", action="store_true",
        help="s'arrêter après la validation statique",
    )
    build.add_argument("--tentatives", type=int, default=3, help="réparations maximales")
    build.set_defaults(fonction=commande_build)

    args = analyseur.parse_args(argv)
    try:
        return args.fonction(args)
    except ErreurInstallation as erreur:
        print(f"{ROUGE}Installation impossible : {erreur}{FIN}")
        return 1


if __name__ == "__main__":
    raise SystemExit(principal())
