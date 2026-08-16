#!/usr/bin/env python3
"""L'Atelier : décrire un besoin, voir l'écran, télécharger le module.

    python3 cli/atelier.py
    → http://127.0.0.1:8100

La chaîne entière en une page : idée → conception → fabrication → aperçu →
livraison. Le seul maillon manquant est l'exécution réelle dans Odoo, qui
demande un Odoo — la forge s'en charge à chaque envoi, et un serveur le fera
le jour d'une démonstration.

TROIS INVARIANTS, ET ILS NE SE NÉGOCIENT PAS.

1. LA CLÉ RESTE ICI. Le navigateur ne la reçoit jamais, ne la lit jamais, ne
   la devine jamais : il envoie un besoin en français et reçoit une
   spécification. « /sante » dit s'il existe un fournisseur, jamais lequel ni
   avec quelle clé.

2. LE MODÈLE N'ÉCRIT QUE DE LA SPÉCIFICATION. Il ne produit ni Python, ni
   XML, ni archive, et n'a aucun accès au dépôt ni à Odoo. Ce que le
   navigateur affiche et ce que l'archive contient sortent du générateur
   déterministe, pas du modèle.

3. TOUT REPASSE PAR LE MÊME VALIDATEUR. Une spécification refusée retourne au
   modèle avec le motif du refus — jamais avec une consigne plus insistante.
   C'est le validateur qui corrige le tir, et il est le même pour une
   spécification rédigée, convertie ou chargée d'un fichier.

L'ÉCOUTE EST LOCALE PAR DÉFAUT. Cet outil fabrique du code et lit des dossiers
de la machine : l'ouvrir sur un réseau demande une décision explicite, pas un
oubli de configuration.

OUTIL À UN SEUL POSTE. La spécification en cours vit en mémoire du processus.
C'est assumé — deux personnes qui travailleraient sur la même instance se
marcheraient dessus, et un vrai service multi-utilisateur est un autre objet
(voir .docker/service-atelier).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from ai.provider import fournisseur_configure  # noqa: E402
from converter.extraction import ConversionImpossible, convertir  # noqa: E402
from generator.dialecte import CIBLES  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from preview.page import rendre  # noqa: E402
from repair.repair_loop import _en_dict  # noqa: E402
from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402
from spec.module_spec import ModuleSpec, SpecInvalide  # noqa: E402
from theme.apercu import rendre as rendre_theme  # noqa: E402
from theme.generateur import (  # noqa: E402
    DENSITES, POLICES, Charte, ThemeInvalide, contraste, generer as generer_theme,
    texte_lisible,
)
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402
from interface_web import PAGE  # noqa: E402


class Atelier:
    """L'état de la session : une spécification à la fois."""

    def __init__(self):
        self.spec: ModuleSpec | None = None
        # L'Atelier fabrique deux choses très différentes — un module métier
        # et un thème — mais l'utilisateur ne fait qu'une chose à la fois.
        # Une seule pièce « courante » évite qu'un aperçu de thème ouvre
        # l'archive d'un module, ce qui serait la pire des confusions.
        self.charte: Charte | None = None
        self.courant: str = ""            # « module » ou « theme »
        self.journal: list[str] = []

    def noter(self, ligne: str) -> None:
        self.journal.append(str(ligne).rstrip())

    # ------------------------------------------------------------ conception

    def concevoir(self, besoin: str, cible: str) -> dict:
        fournisseur = fournisseur_configure(self.noter)
        if fournisseur is None:
            raise RuntimeError(
                "Aucun fournisseur de modèle configuré. Définir BUILDER_IA_CLE "
                "ou OPENAI_API_KEY dans l'environnement de CETTE commande — "
                "jamais dans le navigateur."
            )
        spec = SpecDrafter(fournisseur).draft(besoin, self.noter)
        spec.cible = cible
        return self.retenir(spec)

    def convertir(self, chemin: str, cible: str) -> dict:
        spec, bilan = convertir(chemin, cible)
        for manque in bilan.comportements_perdus:
            self.noter(f"non porté : {manque.quoi}")
        resultat = self.retenir(spec)
        resultat["conversion"] = {
            "repris": sum(bilan.repris.values()),
            "perdus": len(bilan.comportements_perdus),
            "texte": bilan.texte(),
        }
        return resultat

    def charger(self, donnee: dict, cible: str) -> dict:
        donnee = dict(donnee)
        donnee["cible"] = cible
        return self.retenir(ModuleSpec.depuis_dict(donnee))

    cible_courante: str = "17.0"

    def retenir(self, spec: ModuleSpec) -> dict:
        """Valider avant de retenir : on ne montre pas ce qu'on ne livrerait pas."""
        spec.valider()
        fichiers = OdooModuleGenerator().generate(spec)
        rapport = OdooStaticValidator().check(fichiers, spec)
        self.noter(
            f"Validation statique : {'passée' if rapport.ok else 'refusée'} "
            f"({len(fichiers)} fichiers)."
        )
        if not rapport.ok:
            self.noter(rapport.texte())
        self.spec, self.courant = spec, "module"
        self.charte = None
        return {
            "genre": "module",
            "nom": spec.name,
            "technique": spec.technical_name,
            "cible": spec.cible,
            "version": spec.version,
            "modeles": [
                {"nom": m.name, "libelle": m.description or m.name,
                 "champs": len(m.tous_les_champs),
                 "cycle": bool(m.lifecycle and m.lifecycle.transitions)}
                for m in spec.models
            ],
            "vues": len(spec.views), "menus": len(spec.menus),
            "fichiers": len(fichiers),
            "valide": rapport.ok,
            "anomalies": [str(a) for a in rapport.anomalies],
            "specification": _en_dict(spec),
        }

    # -------------------------------------------------------------- livrables

    def theme(self, donnee: dict, cible: str) -> dict:
        """Une charte graphique, ses contrastes mesurés, son module.

        Le contraste se contrôle plutôt qu'il ne se suppose : une charte est
        conçue pour du papier, et c'est à l'écran que se décide si une couleur
        peut porter du texte.
        """
        charte = Charte(
            nom=donnee.get("nom") or "Thème",
            technical_name=donnee.get("technique") or "mon_theme_backend",
            primaire=(donnee.get("primaire") or "#714B67").upper(),
            accent=(donnee.get("accent") or "#017E84").upper(),
            police=donnee.get("police") or "systeme",
            densite=donnee.get("densite") or "normale",
            arrondi=donnee.get("arrondi") or "4px",
            auteur=donnee.get("auteur") or "",
        )
        charte.valider()
        mesures = []
        for nom, couleur in (("primaire", charte.primaire), ("accent", charte.accent)):
            texte = texte_lisible(couleur)
            rapport = contraste(couleur, texte)
            mesures.append({"role": nom, "couleur": couleur, "texte": texte,
                            "rapport": round(rapport, 2), "ok": rapport >= 4.5})
            self.noter(f"{nom} {couleur} : texte "
                       f"{'blanc' if texte == '#FFFFFF' else 'noir'}, "
                       f"{rapport:.2f}:1 {'OK' if rapport >= 4.5 else 'INSUFFISANT'}")
        for avertissement in charte.avertissements:
            self.noter(avertissement)

        self.charte, self.courant = charte, "theme"
        self.spec = None
        fichiers = generer_theme(charte, cible)
        self.noter(f"Thème généré : {len(fichiers)} fichiers pour Odoo {cible}.")
        return {
            "nom": charte.nom, "technique": charte.technical_name,
            "cible": cible, "version": charte.version,
            "genre": "theme", "fichiers": len(fichiers),
            "mesures": mesures, "avertissements": charte.avertissements,
            "valide": all(m["ok"] for m in mesures),
        }

    def apercu(self) -> bytes:
        if self.courant == "theme":
            return rendre_theme(self.charte, self.cible_courante).encode("utf-8")
        return rendre(self.spec).encode("utf-8")

    def archive(self) -> bytes:
        if self.courant == "theme":
            fichiers = generer_theme(self.charte, self.cible_courante)
            return self._zipper(fichiers)
        fichiers = OdooModuleGenerator().generate(self.spec)
        return self._zipper(fichiers)

    @staticmethod
    def _zipper(fichiers: dict) -> bytes:
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
            for chemin, contenu in sorted(fichiers.items()):
                z.writestr(chemin, contenu)
        return tampon.getvalue()

    @property
    def nom_livrable(self) -> str:
        if self.courant == "theme":
            return self.charte.technical_name
        return self.spec.technical_name


class Poignee(BaseHTTPRequestHandler):
    atelier = Atelier()
    server_version = "Atelier"

    def log_message(self, format, *args):        # noqa: A002
        pass                                      # le journal utile est ailleurs

    # ----------------------------------------------------------------- outils

    def _repondre(self, code: int, corps: bytes, type_mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        # Rien de cet outil n'a vocation à être encadré ou appelé d'ailleurs.
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, code: int, donnee: dict) -> None:
        self._repondre(code, json.dumps(donnee, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

    def _corps(self) -> dict:
        # Lire AVANT toute décision : refuser une requête sans vider son corps
        # empoisonne la connexion suivante sur une connexion persistante, et
        # la requête d'après échoue sans rapport avec sa propre validité.
        taille = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(taille) if taille else b"{}"
        try:
            return json.loads(brut or b"{}")
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------ GET

    def do_GET(self):                                    # noqa: N802
        chemin = self.path.split("?")[0]
        if chemin == "/":
            return self._repondre(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if chemin == "/sante":
            return self._json(200, {
                "fournisseur": fournisseur_configure(None) is not None,
                "cibles": list(CIBLES),
                "courant": self.atelier.courant,
                "polices": {c: d for c, (_, d) in POLICES.items()},
                "densites": {c: d for c, (_, d) in DENSITES.items()},
            })
        if chemin == "/apercu.html":
            if not self.atelier.courant:
                return self._repondre(404, b"Aucune specification en cours.",
                                      "text/plain; charset=utf-8")
            return self._repondre(200, self.atelier.apercu(), "text/html; charset=utf-8")
        if chemin == "/module.zip":
            if not self.atelier.courant:
                return self._json(404, {"erreur": "Aucune spécification en cours."})
            corps = self.atelier.archive()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{self.atelier.nom_livrable}.zip"')
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            return self.wfile.write(corps)
        return self._json(404, {"erreur": "route inconnue"})

    # ----------------------------------------------------------------- POST

    def do_POST(self):                                   # noqa: N802
        donnee = self._corps()
        chemin = self.path.split("?")[0]
        cible = donnee.get("cible") or "17.0"
        if cible not in CIBLES:
            return self._json(400, {"erreur": f"cible inconnue « {cible} »"})

        self.atelier.journal = []
        self.atelier.cible_courante = cible
        try:
            if chemin == "/concevoir":
                besoin = (donnee.get("besoin") or "").strip()
                if len(besoin) < 15:
                    return self._json(400, {
                        "erreur": "Décrivez le besoin en quelques phrases : "
                                  "qui fait quoi, avec quelles informations, et "
                                  "quelles étapes de validation."})
                resultat = self.atelier.concevoir(besoin, cible)
            elif chemin == "/convertir":
                resultat = self.atelier.convertir(donnee.get("chemin") or "", cible)
            elif chemin == "/theme":
                resultat = self.atelier.theme(donnee, cible)
            elif chemin == "/charger":
                resultat = self.atelier.charger(donnee.get("specification") or {}, cible)
            else:
                return self._json(404, {"erreur": "route inconnue"})
        except (RedactionImpossible, ConversionImpossible, SpecInvalide,
                ThemeInvalide, RuntimeError, FileNotFoundError) as erreur:
            return self._json(400, {"erreur": str(erreur),
                                    "journal": self.atelier.journal})
        resultat["journal"] = self.atelier.journal
        return self._json(200, resultat)


def principal(argv=None) -> int:
    a = argparse.ArgumentParser(prog="atelier", description=__doc__)
    a.add_argument("--port", type=int, default=8100)
    a.add_argument("--ouvert", action="store_true",
                   help="écouter sur toutes les interfaces (décision explicite)")
    args = a.parse_args(argv)

    adresse = "0.0.0.0" if args.ouvert else "127.0.0.1"
    serveur = ThreadingHTTPServer((adresse, args.port), Poignee)

    fournisseur = fournisseur_configure(None)
    print(f"\n  Atelier          http://127.0.0.1:{args.port}")
    etat = ("configuré" if fournisseur
            else "ABSENT — définir BUILDER_IA_CLE ou OPENAI_API_KEY")
    print(f"  Modèle           {etat}")
    if args.ouvert:
        print("\n  ATTENTION : à l'écoute sur toutes les interfaces. Cet outil lit\n"
              "  des dossiers de cette machine et fabrique du code. Ne l'exposez\n"
              "  qu'à un réseau de confiance.")
    print("\n  Ctrl-C pour arrêter.\n")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("  Arrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
