#!/usr/bin/env python3
"""Une spécification — ou un module existant —, une version d'Odoo, la preuve.

    python3 cli/verifier_cible.py specs/mission.json --cible 18.0
    python3 cli/verifier_cible.py ../ansut_rh        --cible 19.0

Donner un DOSSIER au lieu d'un fichier convertit le module qui s'y trouve :
il est lu, décrit sous forme de spécification, puis rendu par le générateur.
Le reste du banc ne change pas d'une ligne — c'est le but. Convertir n'est
pas une seconde façon de fabriquer un module ; c'est décrire l'existant, puis
passer par le chemin déjà éprouvé.

Le générateur sait viser 17, 18 et 19. Savoir viser n'est pas atteindre : les
règles du dialecte restent des hypothèses tant qu'un vrai Odoo ne les a pas
acceptées. Cette commande demande la réponse à l'Odoo de la version visée.

Elle enchaîne, dans cet ordre :

  1. génération et validation statique ;
  2. installation réelle dans le bac à sable de cette version ;
  3. MISE À JOUR du module déjà installé — l'étape qui compte pour une
     migration : réinstaller à neuf ne prouve pas qu'un module existant peut
     passer d'une version à l'autre. La mise à jour rejoue les vues et les
     changements de schéma, là où une installation neuve part d'une base
     vierge et ne rencontre jamais l'ancien état ;
  4. appel fonctionnel réel : créer, calculer, franchir une transition.

Le banc d'essai est celui de l'acceptation, importé et non recopié : deux
implémentations divergeraient, et l'une se corrigerait sans l'autre.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))
sys.path.insert(0, os.path.join(RACINE, "cli"))

import acceptation  # noqa: E402  — banc d'essai partagé, jamais recopié
from converter.extraction import convertir  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import OdooInstallClient  # noqa: E402
from installer.odoo_runtime import ErreurRuntime, OdooRuntime  # noqa: E402
from spec.module_spec import ModuleSpec  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, GRAS, FIN = "\033[32m", "\033[31m", "\033[1m", "\033[0m"


def _eprouver_sans_cycle(runtime, spec, modele) -> None:
    """Créer, puis relire. Le minimum qui distingue « installé » de « existe ».

    Un module peut s'installer sans que ses tables soient utilisables — une
    colonne mal typée, une relation vers un modèle absent. Créer un
    enregistrement puis le relire est ce qui sépare « Odoo a accepté le
    module » de « le modèle fonctionne ».
    """
    valeurs = acceptation._valeurs_obligatoires(runtime, spec, modele)
    identifiant = runtime.creer(modele.name, valeurs)
    acceptation.controle(
        bool(identifiant), f"Création d'un {modele.name} (id={identifiant})."
    )
    champs = [c.name for c in modele.tous_les_champs][:8]
    relu = runtime.lire(modele.name, identifiant, champs)
    acceptation.controle(
        bool(relu) and all(c in relu for c in champs),
        f"Relecture de {len(champs)} champ(s) sur {modele.name}.",
    )


def principal(argv=None) -> int:
    analyseur = argparse.ArgumentParser(prog="verifier-cible", description=__doc__)
    analyseur.add_argument(
        "spec",
        help="spécification JSON, ou DOSSIER d'un module existant à convertir",
    )
    analyseur.add_argument("--cible", required=True, help="version d'Odoo visée")
    analyseur.add_argument(
        "--service",
        default=os.environ.get("INSTALLATEUR_URL", "http://localhost:8090"),
    )
    args = analyseur.parse_args(argv)

    # Le banc d'essai tient son propre compte des contrôles ; on repart de zéro.
    acceptation.resultats.clear()

    # Un dossier, c'est un module existant : on le convertit. Le reste du banc
    # est rigoureusement le même — c'est bien le but. Convertir n'est pas une
    # autre façon de fabriquer un module : c'est décrire l'existant, puis
    # passer par le générateur déjà éprouvé.
    if os.path.isdir(args.spec):
        spec, bilan = convertir(args.spec, args.cible)
        print(f"{GRAS}=== Odoo {args.cible} — conversion de « {spec.technical_name} » ==={FIN}")
        print(bilan.texte())
        print()
        perdus = len(bilan.comportements_perdus)
        acceptation.controle(
            True,
            f"Conversion : {sum(bilan.repris.values())} élément(s) repris, "
            f"{perdus} comportement(s) non porté(s).",
        )
    else:
        with open(args.spec, encoding="utf-8") as f:
            donnee = json.load(f)
        donnee["cible"] = args.cible
        spec = ModuleSpec.depuis_dict(donnee)
        print(f"{GRAS}=== Odoo {args.cible} — « {spec.technical_name} » ==={FIN}")

    # --- 1. Génération et validation
    fichiers = OdooModuleGenerator().generate(spec)
    rapport = OdooStaticValidator().check(fichiers, spec)
    if not acceptation.controle(rapport.ok, f"Validation statique ({len(fichiers)} fichiers)."):
        print(rapport.texte())
        return 1

    cle = os.environ.get("INSTALLATEUR_CLE_API", "")
    client = OdooInstallClient(args.service, cle)

    # --- 2. Installation
    premier = client.installer(fichiers)
    if not acceptation.controle(premier.ok, f"Installation : {premier.etat}."):
        print(premier.texte())
        return 1

    # --- 3. Mise à jour du module déjà installé
    # Le service d'installation bascule seul sur « button_immediate_upgrade »
    # quand le module est déjà là : redéposer la même archive suffit.
    second = client.installer(fichiers)
    if not acceptation.controle(second.ok, f"Mise à jour : {second.etat}."):
        print(second.texte())
        return 1

    # --- 4. Le comportement, en base
    #
    # Un module converti n'a PAS de cycle de vie : le convertisseur n'en
    # infère jamais. Éprouver un circuit qu'on sait absent n'aurait aucun
    # sens ; on éprouve alors ce que la conversion prétend avoir porté — que
    # le modèle existe vraiment en base et accepte un enregistrement.
    modele = acceptation._modele_avec_cycle(spec)
    epreuve_de_cycle = modele is not None
    if modele is None:
        modele = next(
            (m for m in spec.models if not m.est_extension and m.fields), None
        )
    if modele is None:
        acceptation.controle(False, "Aucun modèle concret à éprouver.")
        return 1

    login, motdepasse = acceptation.identifiants_odoo()
    runtime = OdooRuntime(
        os.environ.get("ODOO_URL", "http://localhost:8069"),
        os.environ.get("ODOO_BASE", "ansut"),
        login,
        motdepasse,
    )
    try:
        runtime.authentifier()
        if epreuve_de_cycle:
            acceptation._eprouver(runtime, spec, modele)
        else:
            _eprouver_sans_cycle(runtime, spec, modele)
    except ErreurRuntime as erreur:
        acceptation.controle(False, f"Exécution : {erreur}")

    echecs = [m for ok, m in acceptation.resultats if not ok]
    print()
    if echecs:
        print(f"{ROUGE}Odoo {args.cible} : {len(echecs)} contrôle(s) en échec.{FIN}")
        for message in echecs:
            print(f"  - {message}")
        return 1
    print(f"{VERT}Odoo {args.cible} : généré, installé, mis à jour, exécuté.{FIN}")
    print(f"  {len(acceptation.resultats)} contrôles passent.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
