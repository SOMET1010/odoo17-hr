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

from ai.detection import accepte, detecter, modeles_disponibles  # noqa: E402
from ai.diagnostic import Constat, VARIABLE, verifier_etapes  # noqa: E402
from ai.installation import (  # noqa: E402
    FOURNISSEURS, InstallationImpossible, chemin_secrets, ecrire_routeur,
    ecrire_secrets, secret_installateur,
)
from ai.provider import (  # noqa: E402
    fournisseur_configure, fournisseur_depuis_environnement,
)
from ai.routeur import (  # noqa: E402
    ConfigurationInvalide, Etape, RouterProvider, _construire,
    chemin_configuration, charger_configuration,
)
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import (  # noqa: E402
    ErreurInstallation, OdooInstallClient, empaqueter,
)
from repair.repair_loop import RepairLoop  # noqa: E402
from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402
from spec.module_spec import ModuleSpec, SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, JAUNE, GRAS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def journal(message: str) -> None:
    print(message, flush=True)


def _charger_spec(args) -> ModuleSpec:
    """Depuis un fichier, ou depuis un besoin en français via le modèle."""
    if args.besoin:
        fournisseur = fournisseur_configure(journal)
        if fournisseur is None:
            raise SpecInvalide(
                "Aucun fournisseur de modèle configuré (BUILDER_IA_CLE ou "
                "OPENAI_API_KEY) : impossible de traduire un besoin en "
                "spécification. Fournir un fichier de spécification, ou "
                "définir la clé dans l'environnement."
            )
        redacteur = SpecDrafter(fournisseur, tentatives_max=args.tentatives)
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

    fournisseur = fournisseur_configure(journal)
    if fournisseur is None and not args.sans_installation:
        journal("(aucun fournisseur de modèle : réparation automatique désactivée)")

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


def commande_setup(args) -> int:
    """Installation guidée : pose les questions, écrit les fichiers, vérifie."""
    import getpass  # noqa: PLC0415

    depot = RACINE
    print(f"{GRAS}Installation de l'Atelier Odoo{FIN}")
    print("Trois questions, puis je m'occupe du reste.\n")

    # --- 1. Quel fournisseur.
    print(f"{GRAS}1. Quel service d'IA rédigera les spécifications ?{FIN}")
    cles = list(FOURNISSEURS)
    for rang, cle in enumerate(cles, 1):
        print(f"   {rang}. {FOURNISSEURS[cle]['libelle']}")
    choix = input(f"   Votre choix [1-{len(cles)}] : ").strip() or "1"
    try:
        fournisseur = cles[int(choix) - 1]
    except (ValueError, IndexError):
        print(f"{ROUGE}Choix invalide.{FIN}")
        return 2
    details = FOURNISSEURS[fournisseur]

    # --- 2. La clé, jamais affichée.
    print(f"\n{GRAS}2. Votre clé d'API {details['libelle']}{FIN}")
    print("   Elle ne s'affichera pas pendant la saisie, et n'entrera")
    print("   ni dans le dépôt ni dans l'historique du terminal.")
    cle_api = getpass.getpass("   Clé : ").strip()
    if not cle_api:
        print(f"{ROUGE}Aucune clé saisie.{FIN}")
        return 2

    # --- 3. Le modèle.
    suggere = details["modele_suggere"]
    print(f"\n{GRAS}3. Quel modèle ?{FIN}")
    print(f"   Entrée pour « {suggere} », ou saisissez le nom exact.")
    modele = input("   Modèle : ").strip() or suggere

    # --- Écriture.
    print(f"\n{GRAS}Écriture{FIN}")
    installateur_secret = secret_installateur()
    try:
        fichier_secrets = ecrire_secrets(
            {details["cle_env"]: cle_api, "INSTALLATEUR_CLE_API": installateur_secret},
            depot,
        )
    except InstallationImpossible as erreur:
        print(f"{ROUGE}{erreur}{FIN}")
        return 2
    print(f"  secrets   → {fichier_secrets} (lisible par vous seul)")

    fichier_routeur = ecrire_routeur(
        [(fournisseur, modele)], os.path.join(depot, "routeur.json")
    )
    print(f"  routeur   → {fichier_routeur} (sans aucune clé)")
    print(f"  secret du service d'installation : composé automatiquement")

    # --- Vérification immédiate, dans le même processus.
    print(f"\n{GRAS}Vérification{FIN}")
    os.environ[details["cle_env"]] = cle_api
    os.environ["INSTALLATEUR_CLE_API"] = installateur_secret
    code = commande_providers(args)

    print()
    if code == 0:
        print(f"{VERT}Installation terminée.{FIN}")
        print("  À chaque nouvelle session, une seule ligne à jouer :")
        print(f"    source {fichier_secrets}")
    else:
        print(f"{ROUGE}La configuration est écrite mais le service ne répond pas.{FIN}")
        print("  Le diagnostic ci-dessus dit sur quoi porte le problème.")
    return code


def commande_detecter(args) -> int:
    """Cherche à quel fournisseur appartient la clé configurée.

    Une clé refusée par OpenAI peut être parfaitement valide ailleurs. Plutôt
    que de deviner d'après sa forme — « sk-… » ne désigne personne —, on la
    présente à chaque fournisseur connu.
    """
    cle = os.environ.get("BUILDER_IA_CLE") or os.environ.get("OPENAI_API_KEY", "")
    if not cle:
        print(f"{ROUGE}Aucune clé dans l'environnement "
              f"(BUILDER_IA_CLE ou OPENAI_API_KEY).{FIN}")
        return 2

    print(f"{GRAS}Recherche du fournisseur de la clé {cle[:6]}…{cle[-4:]}{FIN}\n")
    constats = detecter(cle, journal)

    print()
    retenus = []
    for constat in constats:
        details = FOURNISSEURS[constat.nom]
        if accepte(constat):
            retenus.append(constat)
            etat = f"{VERT}ACCEPTÉE{FIN}"
        else:
            etat = f"{ROUGE}refusée{FIN}"
        print(f"  {etat}  {details['libelle']} — {constat.cause}")

    print()
    if not retenus:
        print(f"{ROUGE}Aucun fournisseur connu ne reconnaît cette clé.{FIN}")
        print("  Elle est probablement révoquée, ou vient d'un service absent")
        print("  de la table. Dans ce second cas, déclarer directement :")
        print("    export BUILDER_IA_URL=\"…/v1/chat/completions\"")
        print("    export BUILDER_IA_MODELE=\"…\"")
        return 1

    gagnant = retenus[0]
    details = FOURNISSEURS[gagnant.nom]
    print(f"{VERT}Cette clé appartient à {details['libelle']}.{FIN}")

    if gagnant.ok:
        print(f"  Le modèle « {details['modele_suggere']} » répond : rien à changer "
              f"que le point d'entrée.")
        modeles = []
    else:
        print(f"  La clé passe, mais « {details['modele_suggere']} » est refusé "
              f"({gagnant.cause}).")
        modeles = modeles_disponibles(details["url"], cle, details["protocole"])
        if modeles:
            print(f"  Modèles déclarés par le service : {', '.join(modeles[:12])}"
                  + (" …" if len(modeles) > 12 else ""))
        else:
            print("  Le service ne publie pas la liste de ses modèles ; le nom")
            print("  exact est à prendre dans sa documentation.")

    fichier = chemin_secrets()
    modele = modeles[0] if modeles else details["modele_suggere"]
    print(f"\n{GRAS}À ajouter à {fichier} :{FIN}")
    print(f"    export BUILDER_IA_URL=\"{details['url']}\"")
    print(f"    export BUILDER_IA_MODELE=\"{modele}\"")
    print("\n  En une commande :")
    print(f"    printf '%s\\n' 'export BUILDER_IA_URL=\"{details['url']}\"' "
          f"'export BUILDER_IA_MODELE=\"{modele}\"' >> {fichier}")
    return 0


def commande_providers(args) -> int:
    """Diagnostique chaque fournisseur, sans rien générer.

    Le diagnostic doit examiner ce qui sert réellement. `fournisseur_configure`
    se rabat sur l'environnement quand aucun routeur n'est écrit ; exiger ici
    un `routeur.json` reviendrait à déclarer absente une configuration qui
    fonctionne — ce que faisait cette commande, et qui bloquait toute machine
    installée par `deployer/installer.sh`.
    """
    if getattr(args, "action", "check") == "detect":
        return commande_detecter(args)

    chemin = chemin_configuration()
    constats: list[Constat] = []
    etapes = []

    if os.path.isfile(chemin):
        try:
            donnee = charger_configuration(chemin)
        except ConfigurationInvalide as erreur:
            print(f"{ROUGE}{erreur}{FIN}")
            print(f"  Corriger {chemin}, ou le supprimer pour repartir de "
                  "l'environnement.")
            return 2
        print(f"{GRAS}Routeur : {chemin}{FIN}\n")
        for entree in donnee.get("fournisseurs", []):
            nom = entree.get("nom", "sans-nom")
            try:
                etapes.append(_construire(entree))
            except ConfigurationInvalide as erreur:
                # Non configuré n'est pas en échec : c'est le cas normal d'une
                # machine qui n'a pas toutes les clés.
                constats.append(Constat(nom, False, VARIABLE, str(erreur)))
    else:
        fournisseur = fournisseur_depuis_environnement()
        if fournisseur is None:
            print(f"{ROUGE}Aucun fournisseur configuré.{FIN}")
            print(f"  Ni routeur dans {chemin},")
            print("  ni BUILDER_IA_CLE ou OPENAI_API_KEY dans l'environnement.")
            print("  Pour en déclarer un : atelier-odoo setup")
            return 2
        print(f"{GRAS}Fournisseur unique, décrit par l'environnement{FIN}")
        print("  Pas de routeur : aucun secours si ce fournisseur tombe.")
        print(f"  Pour en enchaîner plusieurs, écrire {chemin}.\n")
        etapes.append(Etape("environnement", fournisseur))

    constats = verifier_etapes(etapes, journal) + constats

    print()
    utilisables = [c for c in constats if c.ok]
    for constat in constats:
        if constat.ok:
            marque = f"{VERT}OK{FIN}   "
        elif constat.transitoire:
            marque = f"{JAUNE}PANNE{FIN}"
        elif constat.cause == VARIABLE:
            marque = f"{JAUNE}ABSENT{FIN}"
        else:
            marque = f"{ROUGE}ÉCHEC{FIN}"
        print(f"  {marque} {constat.ligne()}")

    print()
    if utilisables:
        print(f"{VERT}{len(utilisables)} fournisseur(s) opérationnel(s) : "
              f"{', '.join(c.nom for c in utilisables)}.{FIN}")
        return 0
    print(f"{ROUGE}Aucun fournisseur opérationnel.{FIN}")
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

    fournisseurs = sous.add_parser(
        "providers", help="diagnostique les fournisseurs du routeur"
    )
    fournisseurs.add_argument(
        "action", nargs="?", default="check", choices=["check", "detect"],
        help="check : vérifie variable, point d'entrée, authentification, modèle ; "
             "detect : cherche à quel fournisseur appartient la clé configurée",
    )
    fournisseurs.set_defaults(fonction=commande_providers)

    setup = sous.add_parser(
        "setup", help="installation guidée : clé, routeur, vérification"
    )
    setup.set_defaults(fonction=commande_setup, action="check")

    args = analyseur.parse_args(argv)
    try:
        return args.fonction(args)
    except ErreurInstallation as erreur:
        print(f"{ROUGE}Installation impossible : {erreur}{FIN}")
        return 1


if __name__ == "__main__":
    raise SystemExit(principal())
