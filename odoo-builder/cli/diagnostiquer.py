#!/usr/bin/env python3
"""Ce qu'il faut changer pour faire passer vos modules à une autre version.

    python3 cli/diagnostiquer.py "C:\\Users\\HP\\Downloads\\odoo apps" --cible 17.0
    python3 cli/diagnostiquer.py /chemin/vers/vos/modules --cible 19.0 --rapport bilan.html

Pour un module QU'ON POSSÈDE et qu'on veut garder, c'est le bon outil : il
désigne, il ne régénère pas. Vous gardez vos méthodes, vos assistants, votre
JavaScript ; l'outil vous dit où poser les mains.

Le convertisseur (cli/convertir.py) fait l'inverse — il reconstruit depuis une
spécification et laisse tomber ce qu'elle ne sait pas dire. C'est justifié
pour repartir de zéro, pas pour migrer un module qui marche.

Le code est LU, jamais exécuté.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from generator.dialecte import CIBLES  # noqa: E402
from migration.diagnostic import compter, parcourir  # noqa: E402
from migration.rapport_html import ecrire  # noqa: E402
from migration.regles import BLOQUANT, MANUEL, SILENCIEUX  # noqa: E402

VERT, ROUGE, JAUNE, GRAS, FIN = (
    "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m")
COULEUR = {BLOQUANT: ROUGE, SILENCIEUX: JAUNE, MANUEL: ""}


def principal(argv=None) -> int:
    a = argparse.ArgumentParser(prog="diagnostiquer", description=__doc__)
    a.add_argument("racine", help="dossier contenant vos modules (ZIP acceptés)")
    a.add_argument("--cible", default="17.0", choices=CIBLES)
    a.add_argument("--rapport", default="diagnostic-migration.html",
                   help="fichier HTML à écrire")
    a.add_argument("--detail", action="store_true",
                   help="lister chaque ligne à l'écran")
    args = a.parse_args(argv)

    if not os.path.isdir(args.racine):
        print(f"{ROUGE}Dossier introuvable : {args.racine}{FIN}")
        return 2

    temporaire = tempfile.mkdtemp(prefix="atelier-diag-")
    try:
        modules = parcourir(args.racine, args.cible, temporaire)
        if not modules:
            print(f"{ROUGE}Aucun module sous « {args.racine} ».{FIN}")
            return 2

        print(f"\n{GRAS}=== {len(modules)} module(s) → Odoo {args.cible}{FIN}\n")
        entete = (f"  {'module':<34}{'version':>10}  {'bloq.':>6}{'silenc.':>8}"
                  f"{'manuel':>7}  licence")
        print(entete)
        print("  " + "-" * (len(entete) - 2))
        for m in modules:
            if m.erreur:
                print(f"  {m.nom[:34]:<34}{ROUGE}{m.erreur}{FIN}")
                continue
            b, s, n = (len(m.par_gravite(g)) for g in (BLOQUANT, SILENCIEUX, MANUEL))
            marque = f"{ROUGE}{b:>6}{FIN}" if b else f"{VERT}{b:>6}{FIN}"
            print(f"  {m.nom[:34]:<34}{m.version:>10}  {marque}"
                  f"{JAUNE if s else ''}{s:>8}{FIN}{n:>7}  {m.licence or '—'}")
            if args.detail:
                for t in sorted(m.trouvailles, key=lambda x: (x.fichier, x.ligne)):
                    print(f"      {COULEUR[t.gravite]}{t.gravite:<11}{FIN}"
                          f"{t.fichier}:{t.ligne}  {t.regle.quoi}")
                    print(f"      {'':<11}→ {t.regle.faire}")

        totaux = compter(modules)
        print(f"\n  {ROUGE}{totaux[BLOQUANT]} bloquant(s){FIN} — Odoo refuse le "
              f"module ou refuse de démarrer.")
        print(f"  {JAUNE}{totaux[SILENCIEUX]} silencieux{FIN} — Odoo accepte, et "
              f"le comportement disparaît sans message. C'est le plus coûteux.")
        print(f"  {totaux[MANUEL]} manuel(s) — hors de portée d'un outil.")

        chemin = os.path.abspath(args.rapport)
        ecrire(modules, args.cible, args.racine, chemin)
        print(f"\n  Rapport détaillé : {chemin}\n")
        return 0
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(principal())
