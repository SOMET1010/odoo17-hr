"""Relire le besoin AVANT de fabriquer, et dire ce qu'on ne saura pas faire.

POURQUOI CETTE ÉTAPE EXISTE. Un cahier des charges de thème a été décrit dans
la voie des modules métier. L'Atelier a produit sept modèles, treize vues, une
validation statique passée — et pas une ligne de style. Le module s'installait
et ne changeait rien. Personne ne pouvait le savoir avant de l'installer.

La faute n'est pas dans le générateur : il a fait exactement ce qu'on lui a
demandé. Elle est dans l'enchaînement — besoin, puis code, sans que rien ne
soit soumis à celui qui sait, c'est-à-dire l'utilisateur.

CE QUE LA RELECTURE REND, ET DANS CET ORDRE :

  ce qui a été COMPRIS, en une phrase qu'on peut contredire ;
  les MODÈLES et leurs champs, parce que c'est là qu'un contresens se voit ;
  les ÉCRANS et le CIRCUIT de validation ;
  ce qui restera DEHORS — et c'est le point capital ;
  les QUESTIONS, quand le besoin ne tranche pas.

LE HORS-PÉRIMÈTRE N'EST PAS DEMANDÉ AU MODÈLE. Il est calculé ici, à partir de
ce que la spécification sait dire — nous le savons exactement, c'est notre
vocabulaire. Demander à un modèle « qu'est-ce que tu ne sauras pas faire »
revient à lui demander de connaître nos limites : il répondra
vraisemblablement, c'est-à-dire au hasard. Une limite annoncée au hasard est
pire que pas de limite du tout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# Ce que la spécification NE SAIT PAS dire aujourd'hui, et le mot qui le
# trahit dans un besoin. Cette table est le miroir de « ce qui reste » dans
# ETAT.md : quand un chantier est livré, on retire sa ligne d'ici — et le
# contrôle « les deux listes se répondent » empêche de l'oublier.
HORS_PERIMETRE = {
    "apparence": (
        ("thème", "theme", "charte graphique", "mode sombre", "dark mode",
         "sidebar", "barre latérale", "couleurs de l'interface", "police",
         "écran de connexion", "logo"),
        "Changer l'ASPECT d'Odoo — couleurs, barre latérale, écran de "
        "connexion. Cette voie fabrique des modèles et des écrans, pas du "
        "style : le module s'installerait sans rien changer à l'affichage. "
        "Utilisez « Ou fabriquez un thème », plus bas dans la page."),
    "portail": (
        ("portail", "portal", "extranet", "espace client", "site web",
         "website", "front-office"),
        "Publier sur le PORTAIL web d'Odoo. Les écrans produits sont ceux du "
        "back-office ; un accès portail demande des vues et un contrôleur que "
        "la spécification ne sait pas encore décrire."),
    "assistant": (
        ("assistant", "wizard", "pop-up", "popup", "boîte de dialogue",
         "fenêtre de saisie"),
        "Les ASSISTANTS (fenêtres de saisie temporaires). Une action de "
        "validation directe est produite à la place."),
    "rapport": (
        ("pdf", "rapport imprimable", "impression", "attestation",
         "bordereau", "qweb", "état imprimé"),
        "Les RAPPORTS PDF. Les données seront là, l'édition imprimable non."),
    "planification": (
        ("cron", "tâche planifiée", "automatiquement chaque", "relance "
         "automatique", "toutes les nuits", "périodique"),
        "Les TÂCHES PLANIFIÉES. Ce qui doit se déclencher tout seul devra "
        "être lancé à la main."),
    "discussion": (
        ("chatter", "fil de discussion", "mail.thread", "suivi des "
         "activités", "notification par courriel"),
        "Le FIL DE DISCUSSION et les activités (mail.thread). Les champs et "
        "le circuit existeront, la conversation attachée non."),
    "analyse": (
        ("tableau croisé", "pivot", "graphique", "gantt", "calendrier",
         "tableau de bord"),
        "Les écrans d'ANALYSE — pivot, graphe, gantt, calendrier. Les listes "
        "et formulaires sont produits, pas ceux-là."),
    "données": (
        ("données de départ", "données initiales", "pré-remplir", "catalogue "
         "livré", "paramétrage livré"),
        "Les DONNÉES INITIALES livrées avec le module. Les écrans de saisie "
        "existeront, les enregistrements de départ non."),
}

CONSIGNE = """Tu relis un besoin métier pour un module Odoo. Tu ne produis PAS
de code ni de spécification technique : tu rends une RELECTURE, en français,
qu'un non-informaticien puisse contredire.

Rends un objet JSON avec exactement ces clés :

  "comprend"  : une phrase disant ce que le module servira à faire.
  "modeles"   : liste d'objets {"nom": "...", "role": "...",
                "champs": ["libellé lisible", ...]}. Les noms et libellés en
                français, tels qu'un utilisateur les dirait.
  "ecrans"    : liste de phrases décrivant les écrans (liste, formulaire).
  "circuit"   : liste des étapes de validation, dans l'ordre, ou [] s'il n'y
                en a pas.
  "questions" : liste des points que le besoin ne tranche pas et sur lesquels
                tu as dû choisir. Sois honnête : si tout est clair, rends [].

N'invente pas de fonctionnalité qui n'est pas demandée. Ne rends rien d'autre
que cet objet JSON."""


@dataclass
class Lecture:
    """Ce que l'Atelier a compris, soumis avant toute fabrication."""

    comprend: str = ""
    modeles: list = field(default_factory=list)
    ecrans: list = field(default_factory=list)
    circuit: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    hors_perimetre: list = field(default_factory=list)

    def en_dict(self) -> dict:
        return {
            "comprend": self.comprend, "modeles": self.modeles,
            "ecrans": self.ecrans, "circuit": self.circuit,
            "questions": self.questions, "hors_perimetre": self.hors_perimetre,
        }

    @property
    def vide(self) -> bool:
        return not (self.comprend or self.modeles)


def hors_perimetre(besoin: str) -> list[dict]:
    """Ce que ce besoin demande et que la spécification ne sait pas dire.

    Calculé, jamais demandé au modèle : nos limites sont un fait de notre
    code, pas une opinion. Un seul mot suffit ici — contrairement à
    l'avertissement d'apparence, on ne bloque rien et on ne crie pas : on
    informe avant de fabriquer, moment où l'information est encore utile.
    """
    minuscule = (besoin or "").lower()
    trouves = []
    for sujet, (mots, explication) in HORS_PERIMETRE.items():
        vus = [mot for mot in mots if mot in minuscule]
        if vus:
            trouves.append({"sujet": sujet, "declencheurs": vus[:3],
                            "explication": explication})
    return trouves


def lire(fournisseur, besoin: str, journal=None) -> Lecture:
    """Demander la relecture au modèle, et y ajouter nos propres limites."""
    if journal:
        journal("Relecture du besoin…")
    brut = fournisseur.completer_json(CONSIGNE, besoin)
    if not isinstance(brut, dict):
        brut = {}

    def liste(cle):
        valeur = brut.get(cle)
        return valeur if isinstance(valeur, list) else []

    lecture = Lecture(
        comprend=str(brut.get("comprend") or "").strip(),
        modeles=[m for m in liste("modeles") if isinstance(m, dict)],
        ecrans=[str(e) for e in liste("ecrans")],
        circuit=[str(e) for e in liste("circuit")],
        questions=[str(q) for q in liste("questions")],
        hors_perimetre=hors_perimetre(besoin),
    )
    if journal:
        journal(f"  {len(lecture.modeles)} modèle(s) compris, "
                f"{len(lecture.questions)} question(s), "
                f"{len(lecture.hors_perimetre)} point(s) hors périmètre.")
    return lecture


def rappel_pour_la_redaction(lecture: Lecture) -> str:
    """Ce qu'on repasse au rédacteur : la relecture VALIDÉE par l'utilisateur.

    Sans cela, la relecture serait un affichage sans effet — on demanderait
    son avis à quelqu'un pour ensuite l'ignorer. C'est le texte relu et
    éventuellement corrigé qui fait foi, pas le besoin d'origine.
    """
    if lecture.vide:
        return ""
    morceaux = ["Relecture validée par l'utilisateur, à respecter :",
                lecture.comprend]
    for modele in lecture.modeles:
        champs = ", ".join(str(c) for c in (modele.get("champs") or []))
        morceaux.append(f"- {modele.get('nom', '?')} : {champs}")
    if lecture.circuit:
        morceaux.append("Circuit : " + " → ".join(lecture.circuit))
    return "\n".join(morceaux)


def en_json(lecture: Lecture) -> str:
    return json.dumps(lecture.en_dict(), ensure_ascii=False, indent=2)
