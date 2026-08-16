#!/usr/bin/env python3
"""Passer un parc de modules au convertisseur, et en tirer une vue d'ensemble.

    python3 cli/convertir_lot.py /chemin/vers/les/addons --cible 19.0
    python3 cli/convertir_lot.py /chemin/vers/les/addons --cible 19.0 --detail

Un module à la fois, on lit un rapport. Dix modules à la fois, on a besoin de
savoir PAR OÙ COMMENCER — et ce n'est pas la même question.

La synthèse classe donc les modules par ce qu'ils coûteront, pas par leur nom.
Le coût d'une migration ne se mesure pas au nombre de lignes : il se mesure au
nombre de comportements que la spécification ne sait pas dire, parce que ce
sont eux qu'il faudra redécrire ou réécrire à la main.

CE QUE CET OUTIL NE FAIT PAS : trier à votre place. Il donne des nombres
comparables entre modules, tous obtenus de la même façon. La décision de
commencer par le plus simple ou par le plus urgent n'est pas technique.

Les archives ZIP sont acceptées et déballées dans un dossier temporaire —
jamais à côté de leur source. Un dépôt de livraison ne doit pas se retrouver
peuplé de dossiers déballés que personne n'a demandés.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from converter.extraction import ConversionImpossible, convertir  # noqa: E402
from converter.rapport import COMPORTEMENT, OBSOLETE, STRUCTURE  # noqa: E402
from generator.dialecte import CIBLES  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from spec.module_spec import SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, JAUNE, GRAS, FIN = (
    "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
)


def modules(racine: str, temporaire: str) -> list[tuple[str, str]]:
    """Tous les modules sous « racine » : dossiers et archives.

    Rend des couples (étiquette lisible, chemin du module). L'étiquette garde
    la place d'origine — dans un parc rangé en produit/version/module, savoir
    de quelle version vient un module est la moitié de l'information.
    """
    trouves: list[tuple[str, str]] = []

    for dossier, sous, noms in os.walk(racine):
        sous[:] = [s for s in sous if s not in (".git", "__pycache__", "node_modules")]
        if "__manifest__.py" in noms or "__openerp__.py" in noms:
            trouves.append((os.path.relpath(dossier, racine), dossier))
            sous[:] = []          # un module n'en contient pas un autre
            continue
        for nom in sorted(noms):
            if not nom.endswith(".zip"):
                continue
            archive = os.path.join(dossier, nom)
            cible = os.path.join(temporaire, os.path.relpath(archive, racine))
            try:
                os.makedirs(cible, exist_ok=True)
                with zipfile.ZipFile(archive) as z:
                    z.extractall(cible)
            except (zipfile.BadZipFile, OSError):
                trouves.append((os.path.relpath(archive, racine), ""))
                continue
            for sous_dossier, _, sous_noms in os.walk(cible):
                if "__manifest__.py" in sous_noms or "__openerp__.py" in sous_noms:
                    etiquette = os.path.relpath(archive, racine)
                    trouves.append((f"{etiquette} → {os.path.basename(sous_dossier)}",
                                    sous_dossier))
                    break
    return sorted(trouves)


def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(prog="convertir-lot", description=__doc__)
    analyseur.add_argument("racine", help="dossier contenant les modules")
    analyseur.add_argument("--cible", required=True, choices=CIBLES)
    analyseur.add_argument("--detail", action="store_true",
                           help="afficher le rapport complet de chaque module")
    args = analyseur.parse_args(argv)

    temporaire = tempfile.mkdtemp(prefix="atelier-lot-")
    try:
        return _passer(args, temporaire)
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)


def _passer(args, temporaire: str) -> int:
    trouves = modules(args.racine, temporaire)
    if not trouves:
        print(f"{ROUGE}Aucun module sous « {args.racine} ».{FIN}")
        return 2

    print(f"{GRAS}=== {len(trouves)} module(s) → Odoo {args.cible}{FIN}")
    bilans = []
    for etiquette, chemin in trouves:
        bilans.append((etiquette, _un_module(etiquette, chemin, args)))

    _synthese(bilans, args.cible)
    return 0


def _un_module(etiquette: str, chemin: str, args) -> dict:
    if not chemin:
        return {"erreur": "archive illisible"}
    try:
        spec, rapport = convertir(chemin, args.cible)
    except ConversionImpossible as erreur:
        return {"erreur": str(erreur)}

    resultat = {
        "origine": rapport.version_origine or "—",
        "licence": spec.license,
        "repris": sum(rapport.repris.values()),
        "modeles": len(spec.models),
        "comportement": len(rapport.comportements_perdus),
        "structure": len([m for m in rapport.manques if m.genre == STRUCTURE]),
        "obsolete": len([m for m in rapport.manques if m.genre == OBSOLETE]),
        "apports": len(rapport.apports),
        "rapport": rapport,
    }

    # Le module converti tient-il debout ? C'est ce qui sépare « on sait le
    # lire » de « on sait le produire », et seul le second a de la valeur.
    try:
        spec.valider()
        fichiers = OdooModuleGenerator().generate(spec)
        controle = OdooStaticValidator().check(fichiers, spec)
        resultat["genere"] = len(fichiers) if controle.ok else 0
        resultat["blocage"] = "" if controle.ok else controle.texte().splitlines()[1].strip()
    except SpecInvalide as erreur:
        resultat["genere"] = 0
        resultat["blocage"] = str(erreur)

    if args.detail:
        print()
        print(f"{GRAS}--- {etiquette}{FIN}")
        print(rapport.texte())
    return resultat


def _synthese(bilans, cible: str) -> None:
    print()
    print(f"{GRAS}=== Synthèse{FIN}")
    print()
    entete = (f"  {'module':<42} {'version':>10} {'licence':<10} "
              f"{'repris':>6} {'compo.':>6} {'struct.':>7} {'périmé':>6} "
              f"{'apports':>7}  converti")
    print(entete)
    print("  " + "-" * (len(entete) - 2))

    for etiquette, bilan in bilans:
        court = etiquette if len(etiquette) <= 42 else "…" + etiquette[-41:]
        if "erreur" in bilan:
            print(f"  {court:<42} {ROUGE}{bilan['erreur']}{FIN}")
            continue
        etat = (f"{VERT}oui ({bilan['genere']} fich.){FIN}" if bilan["genere"]
                else f"{ROUGE}NON{FIN}")
        print(f"  {court:<42} {bilan['origine']:>10} {bilan['licence']:<10} "
              f"{bilan['repris']:>6} {bilan['comportement']:>6} "
              f"{bilan['structure']:>7} {bilan['obsolete']:>6} "
              f"{bilan['apports']:>7}  {etat}")
        if bilan.get("blocage"):
            print(f"  {'':<42} {ROUGE}↳ {bilan['blocage']}{FIN}")

    valides = [b for _, b in bilans if "erreur" not in b]
    if not valides:
        return

    print()
    print(f"  Total : {sum(b['repris'] for b in valides)} éléments repris, "
          f"{sum(b['comportement'] for b in valides)} comportements à redécrire, "
          f"{sum(b['obsolete'] for b in valides)} tournures périmées.")

    print()
    print(f"{GRAS}=== Par où commencer{FIN}")
    print("  Le coût d'une migration se mesure au nombre de comportements que")
    print("  la spécification ne sait pas dire — pas au nombre de lignes.")
    print()
    classes = sorted(
        ((e, b) for e, b in bilans if "erreur" not in b),
        key=lambda couple: (couple[1]["comportement"], -couple[1]["repris"]),
    )
    for etiquette, bilan in classes:
        court = etiquette if len(etiquette) <= 46 else "…" + etiquette[-45:]
        print(f"  {bilan['comportement']:>3} à redécrire   {court}")

    # Les tournures périmées ne coûtent rien à convertir — le générateur ne les
    # reproduit pas — mais elles disent l'âge réel du code, qui n'est pas
    # toujours celui qu'annonce le manifeste.
    vieux = [(e, b) for e, b in classes if b["obsolete"] >= 3]
    if vieux:
        print()
        print(f"{JAUNE}  Modules dont le code est plus ancien que leur numéro de version :{FIN}")
        for etiquette, bilan in vieux:
            print(f"    {bilan['obsolete']:>3} tournures périmées   {etiquette}")


if __name__ == "__main__":
    sys.exit(principal())
