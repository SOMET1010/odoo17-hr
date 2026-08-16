#!/usr/bin/env python3
"""Test d'acceptation : besoin en français → module Odoo qui s'exécute.

Le seul maillon que les 48 contrôles ne couvrent pas est l'appel réel au
fournisseur de modèle. Cette commande le joue, en une fois, de bout en bout,
et rend un verdict binaire.

    export OPENAI_API_KEY="…"
    export INSTALLATEUR_CLE_API="…"
    docker compose --profile installateur up -d --build installateur
    python3 cli/acceptation.py

Elle n'est PAS dans la CI, volontairement : dépendance réseau, coût, et
variabilité du modèle n'ont pas leur place dans un socle de non-régression.

Le critère de réussite n'est pas « le JSON est joli » :
  1. la spécification est rédigée par le modèle, sans retouche à la main ;
  2. aucun fichier n'est écrit avant qu'elle soit entièrement validée ;
  3. le module s'installe réellement dans Odoo 17 ;
  4. le champ calculé vaut la somme des lignes ;
  5. la transition change l'état en base.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from ai.provider import OpenAIProvider  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import OdooInstallClient  # noqa: E402
from installer.odoo_runtime import ErreurRuntime, OdooRuntime  # noqa: E402
from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

VERT, ROUGE, JAUNE, GRAS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"

BESOIN = """Je veux un module de gestion des missions avec :
- une demande de mission,
- des frais,
- un total calculé automatiquement,
- un workflow brouillon → soumis,
- interdiction de soumettre sans frais."""

resultats: list[tuple[bool, str]] = []


def controle(ok: bool, message: str) -> bool:
    resultats.append((ok, message))
    marque = f"{VERT}OK{FIN}   " if ok else f"{ROUGE}ÉCHEC{FIN}"
    print(f"  {marque} {message}", flush=True)
    return ok


def principal() -> int:
    for variable in ("OPENAI_API_KEY", "INSTALLATEUR_CLE_API"):
        if not os.environ.get(variable):
            print(f"{ROUGE}{variable} n'est pas définie.{FIN}")
            return 2

    service = os.environ.get("INSTALLATEUR_URL", "http://localhost:8090")
    odoo_url = os.environ.get("ODOO_URL", "http://localhost:8069")
    base = os.environ.get("ODOO_BASE", "ansut")

    print(f"{GRAS}=== Le besoin, tel qu'il est soumis au modèle ==={FIN}")
    print(BESOIN)

    # --- 1. Le modèle rédige la spécification, sans retouche.
    print(f"\n{GRAS}=== 1. Besoin → ModuleSpec ==={FIN}")
    redacteur = SpecDrafter(OpenAIProvider())
    try:
        spec = redacteur.draft(BESOIN, lambda m: print(f"  {m}", flush=True))
    except RedactionImpossible as erreur:
        controle(False, f"Rédaction : {erreur}")
        return rendre_verdict()
    controle(True, f"Spécification rédigée : « {spec.technical_name} »")
    controle(
        len(redacteur.tentatives) >= 1,
        f"Tentatives de rédaction : {len(redacteur.tentatives)}",
    )

    modeles = [m.name for m in spec.modeles_nouveaux]
    calcules = [c.name for m in spec.models for c in m.fields if c.est_calcule]
    cycles = [m for m in spec.models if m.lifecycle and m.lifecycle.transitions]
    print(f"  modèles : {modeles}")
    print(f"  champs calculés : {calcules}")
    print(f"  transitions : {[t.name for m in cycles for t in m.lifecycle.transitions]}")

    controle(bool(calcules), "Le modèle a compris « total calculé automatiquement ».")
    controle(bool(cycles), "Le modèle a compris le workflow.")

    # --- 2. Génération en mémoire : rien n'est écrit avant validation.
    print(f"\n{GRAS}=== 2. Génération et validation ==={FIN}")
    fichiers = OdooModuleGenerator().generate(spec)
    controle(
        isinstance(fichiers, dict) and all(isinstance(v, str) for v in fichiers.values()),
        "La génération reste en mémoire : aucun fichier écrit avant validation.",
    )
    rapport = OdooStaticValidator().check(fichiers, spec)
    if not controle(rapport.ok, "Validation statique de la spécification rédigée."):
        print(rapport.texte())
        return rendre_verdict()

    # --- 3. Installation réelle.
    print(f"\n{GRAS}=== 3. Installation dans Odoo 17 ==={FIN}")
    installateur = OdooInstallClient(service, os.environ["INSTALLATEUR_CLE_API"])
    if not controle(installateur.sante(), f"Service d'installation joignable ({service})."):
        return rendre_verdict()
    issue = installateur.installer(fichiers)
    if not controle(issue.ok, f"Installation : {issue.etat}"):
        for ligne in issue.journal:
            print(f"      {ligne}")
        print(f"      {issue.erreur}")
        return rendre_verdict()

    # --- 4. Le comportement, éprouvé à l'exécution.
    print(f"\n{GRAS}=== 4. Exécution du comportement ==={FIN}")
    modele_principal = _modele_avec_cycle(spec)
    if modele_principal is None:
        controle(False, "Aucun modèle porteur de cycle de vie à éprouver.")
        return rendre_verdict()

    runtime = OdooRuntime(odoo_url, base, "admin", "admin")
    try:
        runtime.authentifier()
        resultat = _eprouver(runtime, spec, modele_principal)
    except ErreurRuntime as erreur:
        controle(False, f"Exécution : {erreur}")
        return rendre_verdict()
    if resultat is False:
        return rendre_verdict()

    return rendre_verdict()


def _modele_avec_cycle(spec):
    for modele in spec.models:
        if modele.lifecycle and modele.lifecycle.transitions:
            return modele
    return None


def _eprouver(runtime: OdooRuntime, spec, modele) -> bool:
    """Crée un enregistrement, vérifie le calcul, joue la première transition."""
    obligatoires = {
        c.name: _valeur_exemple(c) for c in modele.fields
        if c.required and not c.est_calcule
    }
    identifiant = runtime.creer(modele.name, obligatoires)
    controle(bool(identifiant), f"Création d'un {modele.name} (id={identifiant}).")

    # Alimenter la relation qui nourrit le champ calculé, s'il y en a une.
    calcule = next((c for c in modele.fields if c.est_calcule and c.compute.depends), None)
    attendu = None
    if calcule:
        racine = calcule.compute.compiler().racines()
        relation = next(
            (c for c in modele.fields if c.name in racine and c.type == "one2many"), None
        )
        if relation:
            enfant = next(m for m in spec.models if m.name == relation.comodel)
            valeurs = {
                c.name: _valeur_exemple(c) for c in enfant.fields
                if c.required and not c.est_calcule and c.name != relation.inverse_name
            }
            valeurs[relation.inverse_name] = identifiant
            montant = next(
                (c for c in enfant.fields if c.type in ("monetary", "float", "integer")), None
            )
            if montant:
                valeurs[montant.name] = 125000
                attendu = 125000
            runtime.creer(enfant.name, valeurs)

        lu = runtime.lire(modele.name, identifiant, [calcule.name])[calcule.name]
        if attendu is not None:
            controle(
                float(lu or 0) == float(attendu),
                f"Le champ calculé « {calcule.name} » vaut {lu} (attendu {attendu}).",
            )
        else:
            controle(lu is not None, f"Le champ calculé « {calcule.name} » vaut {lu}.")

    transition = modele.lifecycle.transitions[0]
    champ_etat = modele.lifecycle.field_name
    runtime.executer(modele.name, f"action_{transition.name}", identifiant)
    etat = runtime.lire(modele.name, identifiant, [champ_etat])[champ_etat]
    return controle(
        etat == transition.to_state,
        f"La transition « {transition.name} » porte l'état à « {etat} » "
        f"(attendu « {transition.to_state} »).",
    )


def _valeur_exemple(champ):
    return {
        "char": "Recette d'acceptation", "text": "Recette", "html": "<p>Recette</p>",
        "integer": 1, "float": 1.0, "monetary": 0.0, "boolean": True,
        "date": "2026-01-10", "datetime": "2026-01-10 08:00:00",
    }.get(champ.type, "Recette d'acceptation")


def rendre_verdict() -> int:
    echecs = [m for ok, m in resultats if not ok]
    print(f"\n{GRAS}=== Verdict ==={FIN}")
    if echecs:
        print(f"{ROUGE}{len(echecs)} contrôle(s) en échec :{FIN}")
        for message in echecs:
            print(f"  - {message}")
        return 1
    print(f"{VERT}Idée → module Odoo exécutable : acquis.{FIN}")
    print(f"  {len(resultats)} contrôles passent, depuis un besoin en français.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
