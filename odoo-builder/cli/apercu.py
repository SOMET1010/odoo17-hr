#!/usr/bin/env python3
"""Voir les écrans d'un module avant de le fabriquer.

    python3 cli/apercu.py specs/mission.json        --sortie apercu.html
    python3 cli/apercu.py /chemin/vers/mon_module   --sortie apercu.html --cible 19.0

Un dossier est converti d'abord ; un fichier JSON est lu tel quel. Dans les
deux cas, l'aperçu vient de la spécification — celle-là même que le générateur
transformera en module. C'est ce qui garantit que l'écran validé est l'écran
livré.
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
from preview.page import rendre  # noqa: E402
from spec.module_spec import ModuleSpec  # noqa: E402


def principal(argv=None) -> int:
    a = argparse.ArgumentParser(prog="apercu", description=__doc__)
    a.add_argument("source", help="spécification JSON, ou dossier d'un module")
    a.add_argument("--cible", default="17.0", choices=CIBLES)
    a.add_argument("--sortie", required=True, help="fichier HTML à écrire")
    a.add_argument("--titre", help="titre de la page")
    args = a.parse_args(argv)

    if os.path.isdir(args.source):
        try:
            spec, _ = convertir(args.source, args.cible)
        except ConversionImpossible as erreur:
            print(f"Conversion impossible : {erreur}")
            return 2
    else:
        with open(args.source, encoding="utf-8") as f:
            donnee = json.load(f)
        donnee["cible"] = args.cible
        spec = ModuleSpec.depuis_dict(donnee)

    with open(args.sortie, "w", encoding="utf-8") as f:
        f.write(rendre(spec, args.titre))
    print(f"Aperçu écrit : {args.sortie}  ({len(spec.models)} objet(s), "
          f"{len(spec.views)} vue(s))")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
