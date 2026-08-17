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

LES PROJETS SURVIVENT. Ce qu'on fabrique est enregistré dans un fichier
SQLite (voir persistance/depot.py) : fermer la fenêtre ou changer de poste ne
fait plus tout recommencer. La spécification est gardée, jamais le module
engendré — celui-ci se régénère, et le régénérer garantit qu'il porte les
corrections apportées au générateur depuis.

CHACUN CHEZ SOI. Les projets appartiennent à un compte, et le filtre est dans
le SQL — pas dans le Python, qu'on peut oublier d'appliquer. Sur un poste
personnel sans compte, ils appartiennent au « poste » et rien ne demande de
mot de passe : exiger une phrase secrète pour un outil qui n'écoute que
127.0.0.1 ferait choisir « azerty » à tout le monde. Dès qu'un compte existe,
ou dès que l'écoute est ouverte, la connexion devient obligatoire.

EN LIGNE. « --ouvert » écoute sur toutes les interfaces, et alors :
l'authentification est exigée d'emblée ; la conversion PAR CHEMIN est fermée,
puisque le chemin désignerait un dossier du serveur et non du poste — on
dépose une archive ; et la création du premier compte demande un code
d'installation (ATELIER_INSCRIPTION), sans quoi le premier visiteur venu
deviendrait administrateur. Voir docker-compose.atelier.yml.
"""

from __future__ import annotations

import argparse
import hmac
import io
import json
import os
import sys
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

import datetime  # noqa: E402

from ai.provider import OpenAIProvider, fournisseur_configure  # noqa: E402
from ai.routeur import Etape, RouterProvider  # noqa: E402
# Le paquet s'appelle « persistance » et non « atelier » : ce script porte
# déjà ce nom, et le dossier d'un script passe en tête du chemin d'import.
# « import atelier.depot » retombait donc sur le script lui-même — une panne
# qui ne se voit qu'à l'exécution, jamais à la lecture.
from persistance.comptes import (  # noqa: E402
    DUREE_SESSION_JOURS, CompteInvalide, Comptes,
)
from persistance.depot import Depot, ProjetInaccessible  # noqa: E402
from persistance.notifications import Evenement, Notifications  # noqa: E402
from persistance.reglages import (  # noqa: E402
    FOURNISSEURS, INSCRIPTIONS, Reglages, ReglageInvalide,
    adresse_du_catalogue,
)
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


# Le compte que sert la requête EN COURS, propre à chaque fil d'exécution.
# Le serveur est multi-fils : une variable ordinaire serait écrasée par la
# requête d'un autre utilisateur au milieu de la nôtre.
_courant = threading.local()


@dataclass
class Piece:
    """Ce sur quoi UNE personne travaille en ce moment.

    L'Atelier fabrique deux choses très différentes — un module métier et un
    thème — mais chacun ne fait qu'une chose à la fois. Une seule pièce
    « courante » évite qu'un aperçu de thème ouvre l'archive d'un module.
    """

    spec: ModuleSpec | None = None
    charte: Charte | None = None
    courant: str = ""                 # « module » ou « theme »
    projet: str | None = None         # l'identifiant en cours
    cible_courante: str = "17.0"
    journal: list = field(default_factory=list)
    # Où en est une conception longue, pour qu'une autre requête puisse le
    # lire et l'afficher. Pas dans le fil d'exécution : c'est justement un
    # AUTRE appel qui vient le consulter.
    progres: dict = field(default_factory=dict)


class Atelier:
    """Les services partagés, et une pièce de travail PAR COMPTE.

    LE DÉFAUT QUE CETTE SÉPARATION CORRIGE. Tout vivait dans un seul objet,
    partagé par le processus entier. Tant qu'il n'y avait qu'un poste, cela ne
    se voyait pas. Dès qu'il y a des comptes, deux personnes se marchent
    dessus : la spécification de l'une devient l'aperçu de l'autre, et
    « /module.zip » sert l'archive du dernier arrivé. Le refus « ce projet ne
    vous appartient pas » n'était que le symptôme visible — le plus bénin.

    Ce qui reste PARTAGÉ est ce qui doit l'être : le dépôt, les comptes, les
    réglages, les notifications. Ce qui devient PROPRE À CHACUN est l'état de
    travail.
    """

    def __init__(self):
        self.depot = Depot()
        self.comptes = Comptes(self.depot.chemin)
        self.reglages = Reglages(self.depot.chemin)
        self.notifications = Notifications(self.depot.chemin)
        self._pieces: dict[str, Piece] = {}
        self._verrou = threading.Lock()

    # -------------------------------------------------- la pièce du moment

    @property
    def compte(self) -> str:
        """Le compte servi par CETTE requête. Vide en local sans comptes :
        les projets appartiennent alors au « poste »."""
        return getattr(_courant, "compte", "")

    @compte.setter
    def compte(self, identifiant: str) -> None:
        _courant.compte = identifiant or ""

    def piece(self) -> Piece:
        with self._verrou:
            return self._pieces.setdefault(self.compte, Piece())

    def __getattr__(self, nom):
        # Les attributs de travail sont lus sur la pièce du compte courant.
        # Passer par « __getattr__ » évite de réécrire les cent points d'appel
        # — et surtout d'en oublier un, qui resterait partagé sans que rien ne
        # le montre.
        if nom in Piece.__annotations__:
            return getattr(self.piece(), nom)
        raise AttributeError(nom)

    def __setattr__(self, nom, valeur):
        if nom in Piece.__annotations__:
            setattr(self.piece(), nom, valeur)
        else:
            object.__setattr__(self, nom, valeur)

    @staticmethod
    def maintenant() -> str:
        return datetime.datetime.now().isoformat(timespec="seconds")

    def retenir_projet(self, nom, genre, cible, technique, contenu,
                       origine="", motif="") -> None:
        """Tout passe par ici. Un seul point d'enregistrement, donc rien
        qui puisse être oublié sur l'un des trois chemins."""
        self.projet = self.depot.enregistrer(
            nom=nom, genre=genre, cible=cible, technique=technique,
            contenu=contenu, horodatage=self.maintenant(), origine=origine,
            identifiant=self.projet, motif=motif,
            proprietaire=self.compte,
        )
        self.noter(f"Projet enregistré ({self.projet}).")

    def signaler(self, genre: str, sujet: str, detail: str = "",
                 par: str = "") -> None:
        """Journalise, et prévient qui est branché. Ne lève jamais.

        Un acte d'administration réussi ne doit pas être annulé parce qu'un
        service de notification est en panne.
        """
        try:
            self.notifications.signaler(
                Evenement(genre=genre, sujet=sujet, detail=detail, par=par),
                self.maintenant())
        except Exception:                                     # noqa: BLE001
            pass

    def noter(self, ligne: str) -> None:
        ligne = str(ligne).rstrip()
        self.journal.append(ligne)
        # Chaque ligne du journal est aussi un point d'avancement : c'est le
        # rédacteur lui-même qui les émet — « tentative 2/3 », « refusée par le
        # validateur ». Les recopier ici évite d'inventer une seconde
        # comptabilité, qui mentirait dès qu'on toucherait à la première.
        avance = dict(self.progres)
        if avance.get("actif"):
            avance["etape"] = ligne
            avance["lignes"] = len(self.journal)
            self.progres = avance

    def commencer(self, quoi: str) -> None:
        """Ouvre une opération longue, visible depuis une AUTRE requête."""
        self.journal = []
        self.progres = {"actif": True, "quoi": quoi, "etape": "En cours…",
                        "debut": time.time(), "lignes": 0}

    def terminer(self, motif: str = "") -> None:
        avance = dict(self.progres)
        avance.update({"actif": False, "fin": time.time(), "motif": motif})
        self.progres = avance

    # ------------------------------------------------------------ conception

    def fournisseur(self, journal=None):
        """Le fournisseur à employer, et d'où il vient.

        Ce qui a été posé DEPUIS L'INTERFACE l'emporte sur l'environnement.
        L'ordre inverse serait déroutant : on change le réglage à l'écran, on
        ne voit rien changer, et rien ne dit pourquoi. L'environnement reste
        l'amorçage — celui de l'installeur — et le recours si l'on efface le
        réglage.
        """
        # PLUSIEURS CLÉS : on les essaie dans l'ordre. Un seul fournisseur,
        # c'est une panne unique — quota du jour épuisé, service en
        # maintenance, clé révoquée par un collègue — et l'Atelier ne sait
        # plus rédiger. Le routeur bascule sur le suivant quand l'un est
        # INDISPONIBLE ; il ne bascule jamais parce qu'une spécification est
        # perfectible, ce cas-là appartient au validateur.
        file = self.reglages.fournisseurs()
        if file:
            if journal:
                journal(f"  {len(file)} fournisseur(s) en file : "
                        + ", ".join(f["service"] for f in file))
            return RouterProvider(
                etapes=[Etape(nom=f"{f['service']} ({f['modele']})",
                              fournisseur=OpenAIProvider(
                                  cle_api=f["cle"], modele=f["modele"],
                                  url=f["url"]))
                        for f in file],
                journal=journal or (lambda _: None))

        etat = self.reglages.etat()
        if etat is not None:
            if journal:
                journal(f"  modèle « {etat.modele} » ({etat.fournisseur}), "
                        f"posé depuis l'interface")
            return OpenAIProvider(cle_api=self.reglages.cle(),
                                  modele=etat.modele, url=etat.url)
        return fournisseur_configure(journal)

    def concevoir(self, besoin: str, cible: str) -> dict:
        self.commencer("Conception de la spécification")
        fournisseur = self.fournisseur(self.noter)
        if fournisseur is None:
            raise RuntimeError(
                "Aucun fournisseur de modèle configuré. Ouvrez « Modèle » en "
                "haut de la page pour en poser un — la clé reste sur le "
                "serveur, elle ne redescend jamais dans le navigateur."
            )
        spec = SpecDrafter(fournisseur).draft(besoin, self.noter)
        spec.cible = cible
        return self.retenir(spec)

    # Un ZIP de module tient en quelques centaines de kilooctets. La borne
    # protège la machine d'un envoi qui la remplirait — et elle est
    # VÉRIFIÉE À LA DÉCOMPRESSION, pas seulement sur l'archive : une archive
    # de 2 Mo peut contenir 20 Go de zéros.
    TAILLE_MAX = 40 * 1024 * 1024

    def convertir_archive(self, brut: bytes, cible: str) -> dict:
        """Convertir un module envoyé en archive.

        C'est la seule voie possible en ligne : le champ « chemin » y
        désignerait un dossier du SERVEUR, ce qui serait au mieux inutile et
        au pire un moyen de lire ce qui traîne sur la machine.
        """
        if len(brut) > self.TAILLE_MAX:
            raise ValueError(
                f"Archive trop lourde ({len(brut) // 1024} Ko). "
                f"La limite est de {self.TAILLE_MAX // 1024 // 1024} Mo.")
        dossier = tempfile.mkdtemp(prefix="atelier-envoi-")
        try:
            with zipfile.ZipFile(io.BytesIO(brut)) as archive:
                total = 0
                for membre in archive.infolist():
                    # « ../ » et les chemins absolus s'échapperaient du
                    # dossier temporaire pour écrire n'importe où. Python le
                    # neutralise depuis 3.6, mais on refuse explicitement :
                    # un jour on changera d'outil d'extraction.
                    nom = membre.filename.replace("\\", "/")
                    if nom.startswith("/") or ".." in nom.split("/"):
                        raise ValueError(
                            f"Chemin refusé dans l'archive : « {membre.filename} ».")
                    total += membre.file_size
                    if total > self.TAILLE_MAX:
                        raise ValueError(
                            "Le contenu décompressé dépasse la limite : "
                            "archive refusée.")
                archive.extractall(dossier)

            racine = self._racine_de_module(dossier)
            if racine is None:
                raise ValueError(
                    "Aucun module dans cette archive : il faut un dossier "
                    "contenant « __manifest__.py ».")
            self.noter(f"Archive reçue : {len(brut) // 1024} Ko, "
                       f"module « {os.path.basename(racine)} ».")
            return self.convertir(racine, cible)
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

    @staticmethod
    def _racine_de_module(dossier: str) -> str | None:
        for courant, sous, noms in os.walk(dossier):
            sous[:] = [s for s in sous if s not in ("__MACOSX", "__pycache__")]
            if "__manifest__.py" in noms or "__openerp__.py" in noms:
                return courant
        return None

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
        self.retenir_projet(spec.name, "module", spec.cible, spec.technical_name,
                            _en_dict(spec), motif="spécification")
        return {
            "projet": self.projet,
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

    def ouvrir(self, identifiant: str, cible: str | None = None) -> dict:
        """Reprendre un projet là où on l'avait laissé."""
        projet = self.depot.ouvrir(identifiant, self.compte)
        if projet is None:
            raise FileNotFoundError(f"projet « {identifiant} » introuvable.")
        self.projet = projet.id
        cible = cible or projet.cible
        self.cible_courante = cible
        self.noter(f"Projet « {projet.nom} » rouvert "
                   f"({projet.revisions} révision(s)).")
        if projet.genre == "theme":
            return self.theme(projet.contenu, cible)
        return self.charger(projet.contenu, cible)

    def nouveau(self) -> None:
        """Repartir de zéro sans effacer ce qui est enregistré."""
        self.spec = self.charte = None
        self.courant = ""
        self.projet = None

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
        self.retenir_projet(
            charte.nom, "theme", cible, charte.technical_name,
            {"nom": charte.nom, "technique": charte.technical_name,
             "primaire": charte.primaire, "accent": charte.accent,
             "police": charte.police, "densite": charte.densite,
             "arrondi": charte.arrondi, "auteur": charte.auteur},
            motif="charte")
        fichiers = generer_theme(charte, cible)
        self.noter(f"Thème généré : {len(fichiers)} fichiers pour Odoo {cible}.")
        return {
            "projet": self.projet,
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
        if getattr(self, "_cookie", ""):
            self.send_header("Set-Cookie", self._cookie)
        self.send_header("Content-Length", str(len(corps)))
        # Rien de cet outil n'a vocation à être encadré ou appelé d'ailleurs.
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, code: int, donnee: dict) -> None:
        self._repondre(code, json.dumps(donnee, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

    # ------------------------------------------------------- authentification

    def _jeton(self) -> str:
        """Le jeton de session, lu dans le cookie."""
        brut = self.headers.get("Cookie") or ""
        for morceau in brut.split(";"):
            nom, _, valeur = morceau.strip().partition("=")
            if nom == "atelier":
                return valeur
        return ""

    def _poser_cookie(self, jeton: str, effacer: bool = False) -> None:
        """HttpOnly : le JavaScript de la page ne doit jamais lire ce jeton.

        SameSite=Lax : un formulaire posté depuis un autre site n'emporte pas
        la session — c'est ce qui protège des requêtes forgées sans qu'on ait
        à promener un jeton supplémentaire.

        Secure quand on est derrière HTTPS : sans lui, le navigateur
        renverrait le cookie en clair sur une éventuelle requête HTTP.
        """
        parties = [f"atelier={'' if effacer else jeton}", "Path=/",
                   "HttpOnly", "SameSite=Lax"]
        if effacer:
            parties.append("Max-Age=0")
        else:
            parties.append(f"Max-Age={DUREE_SESSION_JOURS * 86400}")
        if self.headers.get("X-Forwarded-Proto") == "https":
            parties.append("Secure")
        self._cookie = "; ".join(parties)

    def _identifier(self) -> bool:
        """Pose « self.atelier.compte », ou rend False s'il faut se connecter.

        Quand aucun compte n'existe ET qu'on n'écoute que sur la machine,
        l'Atelier reste ouvert : exiger un mot de passe pour un outil
        personnel sur 127.0.0.1 ferait choisir « azerty » à tout le monde.
        Dès qu'un compte existe, ou dès que l'écoute est ouverte, la
        connexion devient obligatoire.
        """
        compte = self.atelier.comptes.session(self._jeton(), Atelier.maintenant())
        if compte:
            self.atelier.compte = compte.id
            self.compte = compte
            return True
        self.compte = None
        if self.server.ouvert or self.atelier.comptes.combien():
            return False
        self.atelier.compte = ""
        return True

    def _corps(self) -> dict:
        # Lire AVANT toute décision : refuser une requête sans vider son corps
        # empoisonne la connexion suivante sur une connexion persistante, et
        # la requête d'après échoue sans rapport avec sa propre validité.
        taille = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(taille) if taille else b"{}"
        try:
            donnee = json.loads(brut or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # UnicodeDecodeError, et pas seulement JSONDecodeError : un corps
            # BINAIRE lève la première, qui n'hérite pas de la seconde. Sans
            # elle, un envoi de fichier arrivé sur une route JSON tuait la
            # connexion — le navigateur ne voyait aucune réponse, seulement un
            # échec de réseau, et rien n'indiquait où chercher.
            return {}
        # Un corps JSON valide mais qui n'est pas un objet — « [] », « 12 » —
        # ferait échouer chaque « .get » plus loin, très loin d'ici.
        return donnee if isinstance(donnee, dict) else {}

    # ------------------------------------------------------------------ GET

    def do_GET(self):                                    # noqa: N802
        chemin = self.path.split("?")[0]
        identifie = self._identifier()
        if chemin == "/sante":
            # La seule route ouverte : elle dit s'il faut se connecter, et
            # rien d'autre. Sans elle, la page ne saurait quoi afficher.
            return self._json(200, {
                "connecte": identifie and self.compte is not None,
                "compte": self.compte.en_dict() if self.compte else None,
                "comptes_existants": bool(self.atelier.comptes.combien()),
                # Tant que le mot de passe est provisoire, la seule chose que
                # le compte puisse faire est d'en changer.
                "provisoire": bool(self.compte and self.compte.provisoire),
                "ouvert": self.server.ouvert,
                # Ne dit PAS le code, seulement qu'il en faut un.
                "code_requis": bool(self.server.ouvert
                                    and not self.atelier.comptes.combien()),
                # De quoi peindre un bouton « Créer un compte ». Le code
                # d'équipe, lui, ne sort jamais d'ici : la page dit qu'il en
                # faut un, elle ne le connaît pas.
                "inscription": self.atelier.reglages.inscription(),
                "fournisseur": self.atelier.fournisseur(None) is not None,
                "modele": (self.atelier.reglages.etat().en_dict()
                           if self.atelier.reglages.etat() else None),
                # La file, sans aucune clé entière.
                "file": self.atelier.reglages.file_visible(),
                "fournisseurs": {c: {"nom": n, "url": u, "modele": m}
                                 for c, (n, u, m) in FOURNISSEURS.items()},
                "cibles": list(CIBLES),
                "courant": self.atelier.courant,
                "polices": {c: d for c, (_, d) in POLICES.items()},
                "densites": {c: d for c, (_, d) in DENSITES.items()},
            })
        if chemin == "/":
            return self._repondre(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if chemin == "/robots.txt":
            # Un outil interne n'a rien à faire dans un index. Et une page de
            # connexion indexée sur un domaine récent attire précisément
            # l'attention des classificateurs d'hameçonnage.
            return self._repondre(200, b"User-agent: *\nDisallow: /\n",
                                  "text/plain; charset=utf-8")
        if chemin == "/.well-known/security.txt":
            # Un signal que les sites d'hameçonnage n'ont jamais : à qui
            # écrire. Servi seulement si une adresse est configurée — en
            # publier une au hasard ne vaudrait rien.
            contact = os.environ.get("ATELIER_CONTACT", "").strip()
            if not contact:
                return self._repondre(404, b"", "text/plain; charset=utf-8")
            corps = (f"Contact: mailto:{contact}\n"
                     "Preferred-Languages: fr, en\n").encode("utf-8")
            return self._repondre(200, corps, "text/plain; charset=utf-8")
        if not identifie:
            return self._json(401, {"erreur": "connexion requise"})
        if self._bloque_par_mot_de_passe_provisoire(chemin):
            return self._json(403, {"erreur": "Changez d'abord votre mot de passe.",
                                    "provisoire": True})
        if chemin == "/notifications":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            return self._json(200, {
                "journal": self.atelier.notifications.journal(),
                "voies": Notifications.voies_configurees()})
        if chemin == "/inscription/reglage":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            # Le code d'équipe est rendu ICI, et seulement ici : un
            # administrateur doit pouvoir le relire pour le transmettre à
            # quelqu'un qui arrive. Ce n'est pas un secret personnel.
            return self._json(200, {
                "mode": self.atelier.reglages.inscription(),
                "code_equipe": self.atelier.reglages.code_inscription(),
                "modes": list(INSCRIPTIONS)})
        if chemin == "/invitations":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            return self._json(200, {
                "invitations": self.atelier.comptes.lister_invitations(
                    Atelier.maintenant()),
                "jours": self.atelier.comptes.DUREE_INVITATION_JOURS})
        if chemin == "/comptes":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {
                    "erreur": "Réservé aux administrateurs."})
            return self._json(200, {
                "comptes": self.atelier.comptes.journal_des_comptes()})
        if chemin == "/progres":
            # Lue en boucle par la page pendant une conception : elle ne
            # touche à rien et ne coûte qu'une lecture mémoire.
            avance = dict(self.atelier.progres)
            if avance.get("debut"):
                avance["secondes"] = round(
                    (avance.get("fin") or time.time()) - avance["debut"])
            return self._json(200, avance)
        if chemin == "/projets":
            return self._json(200, {
                "projets": [p.en_dict()
                            for p in self.atelier.depot.lister(self.atelier.compte)],
                "courant": self.atelier.projet,
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
        chemin = self.path.split("?")[0]
        identifie = self._identifier()

        # AVANT toute lecture du corps : un envoi de fichier est binaire, et
        # « _corps » le consommerait pour tenter d'y lire du JSON. Le corps
        # n'est lu qu'une fois — celui qui le lit le premier le garde.
        if chemin == "/televerser":
            if not identifie:
                return self._json(401, {"erreur": "connexion requise"})
            return self._televerser()

        donnee = self._corps()
        if chemin == "/connexion":
            return self._connecter(donnee)
        if chemin == "/inscription":
            return self._inscrire(donnee)
        if chemin == "/inscription/reglage":
            return self._regler_inscription(donnee)
        if chemin == "/invitation":
            return self._creer_invitation(donnee)
        if chemin == "/invitation/revoquer":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            trouvee = self.atelier.comptes.revoquer_invitation(
                donnee.get("jeton") or "")
            return self._json(200 if trouvee else 404,
                              {"revoquee": trouvee} if trouvee
                              else {"erreur": "Invitation introuvable."})
        if chemin == "/compte/activer":
            return self._activer_compte(donnee)
        if chemin == "/compte/supprimer":
            return self._supprimer_compte(donnee)
        if chemin == "/modele":
            return self._poser_modele(donnee)
        if chemin == "/modele/oublier":
            return self._oublier_modele()
        if chemin == "/modele/ajouter":
            return self._ajouter_fournisseur(donnee)
        if chemin == "/modele/oter":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            ote = self.atelier.reglages.oter_fournisseur(donnee.get("id") or "")
            return self._json(200 if ote else 404, {"ote": ote} if ote
                              else {"erreur": "Fournisseur introuvable."})
        if chemin == "/modele/deplacer":
            if not (self.compte and self.compte.administrateur):
                return self._json(403, {"erreur": "Réservé aux administrateurs."})
            bouge = self.atelier.reglages.deplacer_fournisseur(
                donnee.get("id") or "", bool(donnee.get("haut")))
            return self._json(200, {"deplace": bouge})
        if chemin == "/modele/catalogue":
            return self._catalogue_des_modeles(donnee)
        if chemin == "/modele/essai":
            return self._essayer_modele()
        if chemin == "/motdepasse":
            return self._changer_motdepasse(donnee)
        if chemin == "/deconnexion":
            self.atelier.comptes.fermer_session(self._jeton())
            self.atelier.nouveau()
            self.atelier.compte = ""
            self._poser_cookie("", effacer=True)
            return self._json(200, {"deconnecte": True})
        if not identifie:
            return self._json(401, {"erreur": "connexion requise"})
        if self._bloque_par_mot_de_passe_provisoire(chemin):
            return self._json(403, {"erreur": "Changez d'abord votre mot de passe.",
                                    "provisoire": True})
        cible = donnee.get("cible") or "17.0"
        if cible not in CIBLES:
            return self._json(400, {"erreur": f"cible inconnue « {cible} »"})

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
                if self.server.ouvert:
                    # Le chemin désignerait un dossier du SERVEUR. Sur une
                    # instance partagée, c'est un moyen de lire ce qui s'y
                    # trouve — on ferme la route plutôt que de filtrer des
                    # chemins, exercice qu'on perd toujours.
                    return self._json(403, {
                        "erreur": "Sur une instance en ligne, envoyez une "
                                  "archive : le chemin désignerait le serveur."})
                self.atelier.commencer("Lecture du module")
                resultat = self.atelier.convertir(donnee.get("chemin") or "", cible)
            elif chemin == "/projet/ouvrir":
                # La cible du corps est IGNORÉE : un projet porte la sienne.
                # L'honorer ferait qu'un simple clic sur « Ouvrir » changerait
                # la version visée sans que rien ne le dise — un module conçu
                # pour Odoo 19 reviendrait en 17 parce qu'un sélecteur était
                # resté sur sa valeur par défaut.
                resultat = self.atelier.ouvrir(donnee.get("id") or "")
            elif chemin == "/projet/supprimer":
                efface = self.atelier.depot.supprimer(donnee.get("id") or "",
                                                      self.atelier.compte)
                if self.atelier.projet == donnee.get("id"):
                    self.atelier.nouveau()
                return self._json(200, {"supprime": efface,
                                        "journal": self.atelier.journal})
            elif chemin == "/projet/nouveau":
                self.atelier.nouveau()
                return self._json(200, {"journal": ["Nouveau projet."]})
            elif chemin == "/theme":
                resultat = self.atelier.theme(donnee, cible)
            elif chemin == "/charger":
                resultat = self.atelier.charger(donnee.get("specification") or {}, cible)
            else:
                return self._json(404, {"erreur": "route inconnue"})
        except (RedactionImpossible, ConversionImpossible, SpecInvalide,
                ThemeInvalide, ProjetInaccessible, RuntimeError,
                FileNotFoundError) as erreur:
            # Sans cela, une conception qui échoue laisse la jauge tourner
            # indéfiniment — et l'utilisateur attend un résultat déjà perdu.
            self.atelier.terminer(str(erreur)[:120])
            # La même traduction que pour « Éprouver ». Un refus du
            # fournisseur arrivait ici tel quel — « 401 Unauthorized —
            # Invalid Authentication » — ce qui est exact et n'apprend rien :
            # ni que c'est la clé, ni qu'elle part peut-être au mauvais
            # service. L'utilisateur voyait le message le moins utile
            # précisément à l'endroit où il travaille.
            return self._json(400, {"erreur": self._lisible(erreur),
                                    "journal": self.atelier.journal})
        self.atelier.terminer()
        resultat["journal"] = self.atelier.journal
        return self._json(200, resultat)


    def _televerser(self):
        """Recevoir une archive et la convertir."""
        self.atelier.commencer("Lecture de l'archive")
        taille = int(self.headers.get("Content-Length") or 0)
        if taille > self.atelier.TAILLE_MAX + 8192:
            self.rfile.read(taille)            # vider avant de refuser
            return self._json(413, {"erreur": "Archive trop lourde."})
        brut = self.rfile.read(taille) if taille else b""

        # Un envoi de formulaire enveloppe le fichier dans des frontières.
        # On extrait le contenu plutôt que d'ajouter une bibliothèque : la
        # structure est simple, et une dépendance de plus est une mise à jour
        # de plus à surveiller.
        type_contenu = self.headers.get("Content-Type") or ""
        cible = "17.0"
        if "multipart/form-data" in type_contenu and "boundary=" in type_contenu:
            frontiere = ("--" + type_contenu.split("boundary=")[1].strip()
                         ).encode("utf-8")
            fichier = b""
            for morceau in brut.split(frontiere):
                separateur = morceau.find(b"\r\n\r\n")
                if separateur == -1:
                    continue
                entetes = morceau[:separateur].decode("utf-8", "replace")
                corps = morceau[separateur + 4:].rstrip(b"\r\n-")
                if 'name="cible"' in entetes:
                    valeur = corps.decode("utf-8", "replace").strip()
                    if valeur in CIBLES:
                        cible = valeur
                elif "filename=" in entetes:
                    fichier = corps
            brut = fichier

        if not brut:
            return self._json(400, {"erreur": "Aucun fichier reçu."})
        self.atelier.cible_courante = cible
        try:
            resultat = self.atelier.convertir_archive(brut, cible)
        except (ValueError, zipfile.BadZipFile, ConversionImpossible,
                SpecInvalide) as erreur:
            return self._json(400, {"erreur": str(erreur),
                                    "journal": self.atelier.journal})
        self.atelier.terminer()
        resultat["journal"] = self.atelier.journal
        return self._json(200, resultat)

    # ------------------------------------------------------- comptes

    def _connecter(self, donnee: dict):
        nom = (donnee.get("nom") or "").strip()
        ouverture = self.atelier.comptes.ouvrir_session(
            nom, donnee.get("motdepasse") or "", Atelier.maintenant(),
            self._expiration())
        if ouverture is None:
            # Un seul message pour « nom inconnu » et « mot de passe faux » :
            # les distinguer dirait à un inconnu quels comptes existent.
            return self._json(401, {"erreur": "Nom ou mot de passe incorrect."})
        compte, jeton = ouverture
        self.atelier.compte = compte.id
        self.atelier.nouveau()
        self._poser_cookie(jeton)
        return self._json(200, {"compte": compte.en_dict()})

    def _inscrire(self, donnee: dict):
        """Le PREMIER compte se crée sans être connecté ; les suivants, non.

        Sans cette exception, une instance neuve serait inutilisable : il
        faudrait un compte pour créer le premier compte. Après quoi
        l'inscription se referme — une instance en ligne dont n'importe qui
        peut se créer un accès n'est pas protégée.

        EN LIGNE, CETTE EXCEPTION EST UNE COURSE. Le certificat obtenu,
        l'adresse est joignable : le premier arrivé devient administrateur, et
        rien ne dit que ce sera vous. On exige donc un code d'installation,
        tiré au sort par l'installeur et affiché sur la console du serveur.
        Sans ce code, l'inscription est refusée plutôt qu'ouverte : une
        instance qu'on n'arrive pas à amorcer se répare, une instance prise
        par un inconnu, non.
        """
        premier = self.atelier.comptes.combien() == 0
        if premier and self.server.ouvert:
            motif = self._motif_de_refus_a_l_amorcage(donnee)
            if motif:
                return self._json(403, {"erreur": motif})

        # UNE INVITATION VAUT AUTORISATION. C'est ce qui permet à quelqu'un de
        # créer SON compte avec SON mot de passe : l'administrateur convie,
        # il ne connaît pas le secret. Sans elle, il fallait taper le mot de
        # passe de chacun et le lui transmettre — ce qui ne tient pas à trois
        # personnes, et met l'administrateur en position de pouvoir entrer
        # partout.
        invitation = None
        jeton_invitation = (donnee.get("invitation") or "").strip()
        if not premier and jeton_invitation:
            invitation = self.atelier.comptes.invitation(
                jeton_invitation, Atelier.maintenant())
            if invitation is None:
                return self._json(403, {
                    "erreur": "Cette invitation n'est plus valable : elle a "
                              "déjà servi, ou elle a expiré. Demandez-en une "
                              "autre."})
        elif not premier and not (self.compte and self.compte.administrateur):
            # Pas d'invitation, pas d'administrateur : reste la porte que
            # l'instance ouvre elle-même, si elle en ouvre une.
            mode = self.atelier.reglages.inscription()
            if mode == "libre":
                pass
            elif mode == "code":
                attendu = self.atelier.reglages.code_inscription()
                donne = (donnee.get("code_equipe") or "").strip()
                if not attendu or not hmac.compare_digest(donne, attendu):
                    return self._json(403, {
                        "erreur": "Code d'équipe incorrect. Demandez-le à la "
                                  "personne qui administre cet Atelier."})
            else:
                return self._json(403, {
                    "erreur": "Cette instance n'ouvre pas d'inscription : "
                              "demandez un lien d'invitation."})
        try:
            compte = self.atelier.comptes.creer(
                (donnee.get("nom") or "").strip(),
                donnee.get("motdepasse") or "", Atelier.maintenant(),
                role=("administrateur" if premier
                      else (invitation["role"] if invitation
                            else (donnee.get("role") or "membre"))),
                # PROVISOIRE VEUT DIRE : QUELQU'UN D'AUTRE L'A TAPÉ. C'est le
                # seul cas — un administrateur qui pose le mot de passe d'un
                # tiers. Par invitation, par code d'équipe ou par porte libre,
                # la personne choisit le sien : le marquer provisoire lui
                # imposerait de changer un secret que personne d'autre ne
                # connaît, ce qui n'apprend rien à personne et agace.
                provisoire=(not premier and invitation is None
                            and self.compte is not None),
                # PERSONNE N'EST CONNECTÉ sur la voie libre ou par code :
                # lire « self.compte.nom » y tuait la requête, sans réponse et
                # sans trace — le navigateur ne voyait qu'un échec de réseau.
                cree_par=("" if premier
                          else (invitation["cree_par"] if invitation
                                else (self.compte.nom if self.compte
                                      else "porte ouverte"))))
        except CompteInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        if invitation is not None:
            # Consommée APRÈS la création : si celle-ci échoue — nom déjà pris,
            # mot de passe trop court — l'invitation doit rester utilisable.
            self.atelier.comptes.consommer_invitation(
                jeton_invitation, compte.nom, Atelier.maintenant())
        self.atelier.signaler(
            "compte.cree", compte.nom,
            f"Accès {compte.role} créé"
            + (" par invitation." if invitation else "."),
            par=("installation" if premier
                 else (invitation["cree_par"] if invitation
                       else (self.compte.nom if self.compte
                             else "porte ouverte"))))
        if invitation is not None or (not premier and self.compte is None):
            # On ouvre la session tout de suite : la personne vient de choisir
            # son mot de passe, lui redemander de se connecter dans la foulée
            # n'apprend rien à personne.
            ouverture = self.atelier.comptes.ouvrir_session(
                compte.nom, donnee.get("motdepasse"), Atelier.maintenant(),
                self._expiration())
            if ouverture:
                self.atelier.compte = compte.id
                self._poser_cookie(ouverture[1])
        if premier:
            _, jeton = self.atelier.comptes.ouvrir_session(
                compte.nom, donnee.get("motdepasse"), Atelier.maintenant(),
                self._expiration())
            self.atelier.compte = compte.id
            self._poser_cookie(jeton)
        return self._json(200, {"compte": compte.en_dict(), "premier": premier})

    # Les seules routes ouvertes à un compte encore provisoire. Tout le reste
    # attend : un mot de passe que l'administrateur connaît n'est pas un mot de
    # passe, et travailler avec reviendrait à travailler sous son identité.
    OUVERTES_EN_PROVISOIRE = ("/sante", "/", "/motdepasse", "/deconnexion",
                              "/connexion", "/inscription")

    def _bloque_par_mot_de_passe_provisoire(self, chemin: str) -> bool:
        return bool(self.compte and self.compte.provisoire
                    and chemin not in self.OUVERTES_EN_PROVISOIRE)

    def _regler_inscription(self, donnee: dict):
        """Qui peut créer un compte sur cette instance, et comment."""
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        mode = (donnee.get("mode") or "fermee").strip()
        code = (donnee.get("code_equipe") or "").strip()
        try:
            self.atelier.reglages.poser_inscription(
                mode, code, Atelier.maintenant(), par=self.compte.nom)
        except ReglageInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        self.atelier.signaler("inscription.reglee", mode,
                              f"Inscription réglée sur « {mode} ».",
                              par=self.compte.nom)
        return self._json(200, {"mode": mode, "code_equipe": code})

    def _creer_invitation(self, donnee: dict):
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        expire = (datetime.datetime.now() + datetime.timedelta(
            days=Comptes.DUREE_INVITATION_JOURS)).isoformat(timespec="seconds")
        try:
            jeton = self.atelier.comptes.creer_invitation(
                donnee.get("role") or "membre", donnee.get("note") or "",
                Atelier.maintenant(), expire, par=self.compte.nom)
        except CompteInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        self.atelier.signaler("invitation.creee",
                              donnee.get("note") or "sans nom",
                              f"Invitation {donnee.get('role') or 'membre'} "
                              f"valable {Comptes.DUREE_INVITATION_JOURS} jours.",
                              par=self.compte.nom)
        return self._json(200, {"jeton": jeton, "expire_le": expire})

    def _changer_motdepasse(self, donnee: dict):
        """Chacun change le sien. C'est la seule route ouverte à un compte
        dont le mot de passe est encore provisoire."""
        if not self.compte:
            return self._json(401, {"erreur": "connexion requise"})
        ancien = donnee.get("ancien") or ""
        # On revérifie l'ancien mot de passe : un poste laissé ouvert
        # permettrait sinon à qui passe de s'approprier le compte.
        if self.atelier.comptes.ouvrir_session(
                self.compte.nom, ancien, Atelier.maintenant(),
                self._expiration()) is None:
            return self._json(403, {"erreur": "Mot de passe actuel incorrect."})
        try:
            self.atelier.comptes.changer_motdepasse(
                self.compte.id, donnee.get("nouveau") or "",
                garder_session=self._jeton())
        except CompteInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        self.atelier.signaler("compte.motdepasse", self.compte.nom,
                              "Mot de passe changé ; les autres sessions sont "
                              "fermées.", par=self.compte.nom)
        return self._json(200, {"change": True})

    def _activer_compte(self, donnee: dict):
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        nom = (donnee.get("nom") or "").strip()
        actif = bool(donnee.get("actif"))
        if nom == self.compte.nom and not actif:
            return self._json(400, {
                "erreur": "On ne se désactive pas soi-même."})
        if not actif and self.atelier.comptes.administrateurs_actifs() <= 1:
            compte = self.atelier.comptes.compte(nom)
            if compte and compte.administrateur:
                # Sans administrateur actif, plus personne ne peut créer de
                # compte ni en réactiver un : l'instance se ferme sur
                # elle-même.
                return self._json(400, {
                    "erreur": "C'est le dernier administrateur actif."})
        if not self.atelier.comptes.activer(nom, actif):
            return self._json(404, {"erreur": f"Compte « {nom} » introuvable."})
        self.atelier.signaler(
            "compte.actif" if actif else "compte.desactive", nom,
            "Accès rouvert." if actif
            else "Accès fermé ; les sessions ouvertes sont coupées.",
            par=self.compte.nom)
        return self._json(200, {"nom": nom, "actif": actif})

    def _supprimer_compte(self, donnee: dict):
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        nom = (donnee.get("nom") or "").strip()
        # Se supprimer soi-même laisserait une instance sans administrateur,
        # donc sans moyen d'en créer un : l'inscription est refermée. On
        # refuse plutôt que de laisser quelqu'un se verrouiller dehors.
        if nom == self.compte.nom:
            return self._json(400, {
                "erreur": "On ne supprime pas son propre compte : plus "
                          "personne ne pourrait en créer."})
        if not self.atelier.comptes.supprimer(nom):
            return self._json(404, {"erreur": f"Compte « {nom} » introuvable."})
        self.atelier.signaler("compte.supprime", nom,
                              "Compte supprimé ; ses projets sont conservés.",
                              par=self.compte.nom)
        # Ses projets lui survivent : fermer une porte n'est pas effacer du
        # travail.
        return self._json(200, {"supprime": nom})

    # -------------------------------------------------------------- modèle

    def _administrateur(self) -> bool:
        return bool(self.compte and self.compte.administrateur)

    def _poser_modele(self, donnee: dict):
        """Poser la clé depuis la page. Elle monte, elle ne redescend jamais.

        Réservé aux administrateurs : changer de fournisseur, c'est décider
        où partent les besoins qu'on décrit.
        """
        if not self._administrateur():
            return self._json(403, {
                "erreur": "Seul un administrateur peut changer le modèle."})
        fournisseur = (donnee.get("fournisseur") or "autre").strip()
        connu = FOURNISSEURS.get(fournisseur)
        # Le choix d'un fournisseur connu remplit l'adresse et le modèle, mais
        # ne les impose pas : un service change d'URL ou de nom de modèle plus
        # vite qu'on ne met à jour une liste.
        url = (donnee.get("url") or (connu[1] if connu else "")).strip()
        modele = (donnee.get("modele") or (connu[2] if connu else "")).strip()
        try:
            self.atelier.reglages.poser_modele(
                fournisseur, url, modele, donnee.get("cle") or "",
                Atelier.maintenant(), par=self.compte.nom)
        except ReglageInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        etat = self.atelier.reglages.etat()
        return self._json(200, {"modele": etat.en_dict() if etat else None})

    def _oublier_modele(self):
        if not self._administrateur():
            return self._json(403, {
                "erreur": "Seul un administrateur peut changer le modèle."})
        self.atelier.reglages.oublier_modele()
        # Effacer ne laisse pas l'Atelier muet s'il existe un réglage
        # d'environnement : on retombe sur celui de l'installeur, et on le dit.
        return self._json(200, {
            "modele": None,
            "fournisseur": self.atelier.fournisseur(None) is not None})

    def _ajouter_fournisseur(self, donnee: dict):
        """Un fournisseur de plus dans la file d'essai."""
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        service = (donnee.get("fournisseur") or "autre").strip()
        connu = FOURNISSEURS.get(service)
        url = (donnee.get("url") or (connu[1] if connu else "")).strip()
        modele = (donnee.get("modele") or (connu[2] if connu else "")).strip()
        try:
            identifiant = self.atelier.reglages.ajouter_fournisseur(
                service, url, modele, donnee.get("cle") or "",
                Atelier.maintenant(), par=self.compte.nom)
        except ReglageInvalide as erreur:
            return self._json(400, {"erreur": str(erreur)})
        self.atelier.signaler("modele.ajoute", f"{service} / {modele}",
                              "Fournisseur ajouté à la file d'essai.",
                              par=self.compte.nom)
        return self._json(200, {"id": identifiant,
                                "file": self.atelier.reglages.file_visible()})

    def _catalogue_des_modeles(self, donnee: dict):
        """Demander au fournisseur la liste de SES modèles.

        POURQUOI CETTE ROUTE EXISTE. Une table de noms écrite dans le code
        vieillit — et elle vieillit vite : un modèle gratuit disparaît du
        catalogue en quelques mois, le fournisseur répond « 404 modèle
        inconnu », et l'utilisateur n'a aucun moyen de savoir par quoi le
        remplacer. Deviner un nom de mémoire ne fait que déplacer le problème
        de quelques semaines. Le fournisseur, lui, sait.
        """
        if not (self.compte and self.compte.administrateur):
            return self._json(403, {"erreur": "Réservé aux administrateurs."})
        etat = self.atelier.reglages.etat()
        url = (donnee.get("url") or (etat.url if etat else "")).strip()
        # LA CLÉ PEUT VENIR DU FORMULAIRE, et c'est le bon ordre : on la
        # saisit, on voit ce qu'elle donne accès, on choisit. L'exiger
        # enregistrée d'abord obligeait à connaître un nom de modèle valide
        # AVANT d'avoir prouvé la clé — l'ordre inverse de celui où l'on
        # travaille.
        #
        # Elle monte, elle ne redescend pas : cette route ne rend que des noms
        # de modèles, jamais la clé, et rien n'est enregistré ici.
        cle = (donnee.get("cle") or "").strip() or self.atelier.reglages.cle()
        if not cle:
            cle = os.environ.get("BUILDER_IA_CLE") or os.environ.get(
                "OPENAI_API_KEY", "")
        if not url:
            return self._json(400, {"erreur": "Aucune adresse de fournisseur."})

        requete = urllib.request.Request(adresse_du_catalogue(url))
        if cle:
            requete.add_header("Authorization", f"Bearer {cle}")
        try:
            with urllib.request.urlopen(requete, timeout=15) as reponse:
                brut = json.loads(reponse.read().decode("utf-8"))
        except Exception as erreur:                           # noqa: BLE001
            return self._json(502, {"erreur": self._lisible(erreur)})

        return self._json(200, self._classer(brut))

    @staticmethod
    def _classer(brut: dict) -> dict:
        """Trier les modèles selon ce que le FOURNISSEUR déclare d'eux.

        POURQUOI PAS UNE LISTE DE « meilleurs modèles » ÉCRITE ICI. On vient
        de se brûler deux fois avec des noms figés dans le code : ils
        vieillissent en quelques mois, et une recommandation périmée est pire
        qu'aucune — elle a l'air sûre. Le fournisseur, lui, décrit chaque
        modèle à chaque appel. On lit ce qu'il dit.

        CE QUI COMPTE POUR CET OUTIL, ET RIEN D'AUTRE :

          rendre du JSON STRICT. Toute la chaîne en dépend : le modèle
          n'écrit qu'une spécification, et elle doit être analysable. Un
          service qui déclare « response_format » ou « structured_outputs »
          annonce qu'il sait le faire ;

          être GRATUIT, ou pas. Un modèle payant sur un compte sans crédit
          rend un 402 qui parle d'argent et qu'on met dix minutes à
          comprendre ;

          avoir de la place. Une spécification de module et son motif de
          refus tiennent large, mais pas dans 4 000 jetons.
        """
        modeles = []
        for entree in (brut.get("data") or brut.get("models") or []):
            if not isinstance(entree, dict):
                modeles.append({"id": str(entree), "gratuit": False,
                                "json": False, "contexte": 0})
                continue
            nom = entree.get("id") or ""
            if not nom:
                continue
            parametres = entree.get("supported_parameters") or []
            tarif = entree.get("pricing") or {}
            def zero(valeur):
                try:
                    return float(valeur) == 0
                except (TypeError, ValueError):
                    return False
            modeles.append({
                "id": nom,
                "gratuit": nom.endswith(":free") or (
                    zero(tarif.get("prompt")) and zero(tarif.get("completion"))),
                "json": any(p in parametres for p in
                            ("response_format", "structured_outputs")),
                "contexte": int(entree.get("context_length") or 0),
            })

        def rang(modele):
            # Gratuit ET capable de JSON d'abord : c'est le couple qui fait
            # qu'on peut travailler sans y penser.
            return (0 if (modele["gratuit"] and modele["json"]) else
                    1 if modele["json"] else
                    2 if modele["gratuit"] else 3,
                    -modele["contexte"], modele["id"])

        modeles.sort(key=rang)
        recommande = next((m for m in modeles
                           if m["gratuit"] and m["json"] and m["contexte"] >= 30000),
                          None) or next((m for m in modeles if m["json"]), None)
        return {
            "modeles": [m["id"] for m in modeles],
            "details": {m["id"]: m for m in modeles},
            "gratuits": sum(1 for m in modeles if m["gratuit"]),
            "total": len(modeles),
            "recommande": recommande["id"] if recommande else "",
            "pourquoi": (
                f"gratuit, sait rendre du JSON strict, "
                f"{recommande['contexte'] // 1000} k de contexte"
                if recommande and recommande["gratuit"] and recommande["json"]
                else ("sait rendre du JSON strict" if recommande else "")),
        }

    def _essayer_modele(self):
        """Appeler VRAIMENT le fournisseur, et rapporter ce qu'il répond.

        « Configuré » ne veut pas dire « répond ». Une clé révoquée, un nom de
        modèle disparu, un pare-feu sortant : rien de tout cela ne se voit
        d'un réglage, et tout se voit d'un appel. On en fait donc un, le plus
        petit possible.
        """
        if not self._administrateur():
            return self._json(403, {
                "erreur": "Seul un administrateur peut éprouver le modèle."})
        fournisseur = self.atelier.fournisseur(None)
        if fournisseur is None:
            return self._json(400, {"erreur": "Aucun modèle configuré."})
        journal = []
        fournisseur = self.atelier.fournisseur(journal.append)
        try:
            reponse = fournisseur.completer_json(
                "Réponds uniquement par un objet JSON.",
                'Rends exactement {"pret": true}.')
        except Exception as erreur:                       # noqa: BLE001
            # Large à dessein : un fournisseur inconnu peut lever à peu près
            # n'importe quoi, et le message doit arriver à l'écran plutôt que
            # dans le journal du conteneur.
            return self._json(502, {"erreur": self._lisible(erreur)})
        # Avec plusieurs clés, savoir LAQUELLE a répondu est le renseignement
        # utile : c'est ce qui dit si l'on travaille sur son premier choix ou
        # sur un recours.
        resume = fournisseur.resume() if hasattr(fournisseur, "resume") else {}
        return self._json(200, {
            "repond": True, "recu": str(reponse)[:200],
            "par": resume.get("fournisseur") or "",
            "modele": resume.get("modele") or "",
            "basculements": resume.get("basculements", 0),
            "journal": journal})

    def _lisible(self, erreur: Exception) -> str:
        """Un message qui dit quoi faire, quand on peut le savoir.

        Le message brut d'un fournisseur est exact et inutile : « 401
        Unauthorized » ne dit ni que c'est la clé, ni — et c'est le cas le
        plus fréquent — qu'une clé parfaitement valide part au mauvais
        service. On nomme donc l'adresse réellement appelée : c'est elle qui
        rend la faute évidente.
        """
        texte = str(erreur)
        etat = self.atelier.reglages.etat()
        ou = f" Adresse appelée : {etat.url}" if etat else (
            " L'adresse est celle posée à l'installation du serveur ; si la clé "
            "n'est pas une clé OpenAI, c'est là qu'est la faute.")
        if "401" in texte or "invalid_api_key" in texte or "Unauthorized" in texte:
            # On nomme le préfixe attendu : c'est le contrôle que l'utilisateur
            # peut faire en une seconde, sans rien ouvrir.
            attendus = {
                "openrouter.ai": "une clé OpenRouter commence par « sk-or-v1- »",
                "api.groq.com": "une clé Groq commence par « gsk_ »",
                "api.openai.com": "une clé OpenAI commence par « sk- »",
                "api.deepseek.com": "une clé DeepSeek commence par « sk- »",
                "moonshot": "une clé Moonshot commence par « sk- »",
            }
            indice = next((mot for hote, mot in attendus.items()
                           if etat and hote in etat.url), "")
            return ("Le fournisseur refuse la clé (401). Trois causes, dans "
                    "l'ordre de fréquence : la clé a été recopiée incomplète, "
                    "elle appartient à un AUTRE service, ou elle a été "
                    "révoquée."
                    + (f" Vérifiez le début : {indice}." if indice else "")
                    + ou)
        if "404" in texte and ("model" in texte.lower() or "modèle" in texte):
            return ("Le fournisseur ne connaît pas ce nom de modèle (404). "
                    "Corrigez le nom dans « Modèle » — c'est un mot à changer."
                    + ou)
        if "429" in texte:
            return ("Le fournisseur limite les appels (429). C'est le quota "
                    "d'une offre gratuite : réessayez dans un moment.")
        if "402" in texte or "credits" in texte.lower():
            return ("Le fournisseur demande des crédits pour ce modèle (402). "
                    "Choisissez un modèle GRATUIT dans la liste — ils sont "
                    "marqués et placés en tête — ou créditez le compte chez "
                    "ce fournisseur." + ou)
        if "Name or service not known" in texte or "getaddrinfo" in texte:
            return ("L'adresse du fournisseur est introuvable : vérifiez-la "
                    "dans « Modèle », ou la sortie réseau du serveur." + ou)
        return texte[:400]

    @staticmethod
    def _motif_de_refus_a_l_amorcage(donnee: dict) -> str:
        """Rend le motif du refus, ou une chaîne vide si le code est bon.

        Un MOTIF, et non une réponse déjà envoyée : « _json » ne rend rien, si
        bien qu'un appelant qui écrirait « if refus is not None » ne verrait
        jamais le refus. C'est exactement ce qui s'est produit ici — le 403
        partait vers le navigateur ET le compte se créait derrière. Une
        fonction qui décide ne doit pas, en même temps, répondre.
        """
        attendu = os.environ.get("ATELIER_INSCRIPTION", "").strip()
        if not attendu:
            return ("Cette instance est en ligne et n'a pas de code "
                    "d'installation. Définissez ATELIER_INSCRIPTION sur le "
                    "serveur, puis rechargez cette page.")
        # Temps constant, comme pour un mot de passe : la durée de la
        # comparaison dirait combien de caractères sont déjà justes.
        if not hmac.compare_digest((donnee.get("code") or "").strip(), attendu):
            return "Code d'installation incorrect."
        return ""

    @staticmethod
    def _expiration() -> str:
        return (datetime.datetime.now()
                + datetime.timedelta(days=DUREE_SESSION_JOURS)
                ).isoformat(timespec="seconds")


def principal(argv=None) -> int:
    a = argparse.ArgumentParser(prog="atelier", description=__doc__)
    a.add_argument("--port", type=int, default=8100)
    a.add_argument("--ouvert", action="store_true",
                   help="écouter sur toutes les interfaces (décision explicite)")
    args = a.parse_args(argv)

    adresse = "0.0.0.0" if args.ouvert else "127.0.0.1"
    serveur = ThreadingHTTPServer((adresse, args.port), Poignee)
    serveur.ouvert = args.ouvert

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
