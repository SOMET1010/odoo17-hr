"""Ce que la version d'arrivée fait nativement là où le module le fait à la main.

C'est l'autre moitié d'une migration, et la plus souvent manquée. Un module de
v12 est plein de contournements écrits pour une plateforme qui ne savait pas
encore faire. Le porter fidèlement en v19 revient à réimplanter, à grands
frais, ce que la v19 offre. On obtient un module qui marche et qui coûte cher.

CE FICHIER N'APPLIQUE RIEN. Il signale. Réécrire à la place de l'auteur
supposerait de comprendre son intention, et le convertisseur ne comprend rien —
il lit. Prétendre le contraire serait exactement la faute qu'on s'interdit
ailleurs : produire du code qui a l'air juste.

DEUX RÈGLES, sans lesquelles cette liste serait un prospectus.

1. Un apport n'est cité que si le module CONTIENT le motif qu'il remplace,
   fichier et ligne à l'appui. Pas de « saviez-vous que ».
2. Un apport n'est cité que s'il existe DANS LA VERSION VISÉE. C'est ce qui
   fait qu'une conversion vers 17 et une conversion vers 19 ne disent pas la
   même chose — et donc ce qui répond à « qu'est-ce que la 19 m'apporte de
   plus que la 18 ».

PROVENANCE. Chaque entrée porte la vérification qui l'établit : un comptage
dans le code de la branche concernée, pas un souvenir. Une entrée qu'on ne
sait pas vérifier n'a rien à faire ici — la balise « <chatter/> » a ainsi été
retirée, la documentation d'Odoo 18 décrivant toujours « div.oe_chatter ».
"""

from __future__ import annotations

from dataclasses import dataclass

# Un apport est ACQUIS quand le module converti en bénéficie sans que personne
# n'écrive rien : la régénération ne reproduit pas la vieille tournure. Il est
# À SAISIR quand il porte sur du code que le convertisseur ne reprend pas —
# on ne l'obtient qu'en réécrivant.
ACQUIS = "acquis"
A_SAISIR = "à saisir"


@dataclass(frozen=True)
class Regle:
    marqueur: str          # ce qu'on a repéré dans le module d'origine
    depuis: int            # première version STABLE d'Odoo qui l'offre
    ancien: str            # ce que le module fait aujourd'hui
    nouveau: str           # ce que la plateforme offre
    genre: str             # ACQUIS ou A_SAISIR
    verification: str      # comment on sait que c'est vrai


# Les versions « Odoo Online » (17.2, 18.1, 18.4…) ne sont pas des versions
# qu'on installe : leurs apports arrivent dans la version stable SUIVANTE.
# « aggregator », renommé en 17.2 d'après le journal officiel, est absent du
# code de la 17.0 stable et présent en 18.0 — d'où « depuis 18 ». Se fier au
# numéro du journal ferait promettre à un utilisateur de la 17 une capacité
# qu'il n'a pas.
CATALOGUE = (
    Regle(
        "sql_constraints", 19,
        "contraintes SQL déclarées dans « _sql_constraints »",
        "« models.Constraint », « models.Index » et « models.UniqueIndex », "
        "déclarés comme des champs, avec un message d'erreur personnalisable "
        "— et une contrainte enfin visible dans le modèle",
        A_SAISIR,
        "odoo/orm/table_objects.py (19.0) définit Constraint, Index et "
        "UniqueIndex ; absent des branches 17.0 et 18.0.",
    ),
    Regle(
        "attrs", 17,
        "visibilité pilotée par « attrs » ou « states » dans les vues",
        "« invisible », « readonly » et « required » écrits directement sur "
        "l'élément, en expression Python lisible",
        ACQUIS,
        "les vues engendrées n'emploient que la forme directe ; « attrs » a "
        "été supprimé en 17.0.",
    ),
    Regle(
        "name_get", 17,
        "libellé d'enregistrement calculé par « name_get »",
        "« _compute_display_name », qui fait de l'affichage un champ comme un "
        "autre — donc consultable, triable et traduisible",
        A_SAISIR,
        "« def _compute_display_name » présent dès 17.0 ; « def name_get » "
        "présent en 17.0, ABSENT en 18.0 et 19.0 : le remplacement n'est plus "
        "facultatif à partir de 18.",
    ),
    Regle(
        "group_operator", 18,
        "agrégation de colonne déclarée par « group_operator »",
        "« aggregator », même service sous son nom actuel",
        A_SAISIR,
        "« aggregator » absent du fields.py de 17.0, présent en 18.0 et 19.0.",
    ),
    Regle(
        "controle_acces", 18,
        "droits vérifiés par « check_access_rights » puis « check_access_rule »",
        "« check_access », « has_access » et « _filtered_access », qui "
        "réunissent droits et règles en un seul appel — un oubli de moitié "
        "devient impossible",
        A_SAISIR,
        "« def check_access » et « def has_access » absents en 17.0, présents "
        "en 18.0 et 19.0.",
    ),
    Regle(
        "read_group", 19,
        "regroupements construits avec « read_group »",
        "« formatted_read_group », dont la sortie est déjà mise en forme pour "
        "l'affichage",
        A_SAISIR,
        "« def formatted_read_group » absent en 18.0, présent en 19.0.",
    ),
    Regle(
        "api_multi", 17,
        "méthodes marquées « @api.multi » ou « @api.one »",
        "rien à écrire : une méthode reçoit un ensemble d'enregistrements par "
        "défaut",
        ACQUIS,
        "décorateurs disparus en 13 ; le générateur n'en produit aucun.",
    ),
    Regle(
        "balise_tree", 18,
        "vues liste écrites « <tree> »",
        "« <list> », le nom actuel de la balise",
        ACQUIS,
        "« ir.ui.view.type » n'offre plus « tree » à partir de 18.0 ; le "
        "dialecte rend la balise de la version visée.",
    ),
    Regle(
        "colonnes_anciennes", 17,
        "champs déclarés dans « _columns » et défauts dans « _defaults »",
        "déclaration directe par « fields.X(...) », avec les types et les "
        "contrôles que l'ORM connaît",
        ACQUIS,
        "formes d'avant Odoo 8 ; le générateur ne produit que la forme "
        "actuelle.",
    ),
    Regle(
        "fields_view_get", 17,
        "vues manipulées par « fields_view_get »",
        "« get_view », à la signature stabilisée",
        A_SAISIR,
        "« fields_view_get » supprimé en 13.",
    ),
    Regle(
        "osv", 17,
        "modèles bâtis sur l'ancienne couche « osv »",
        "« models.Model », seule base depuis Odoo 10",
        ACQUIS,
        "la couche osv a disparu en 10 ; « odoo.osv » est déprécié en 19.0 "
        "d'après le journal officiel de l'ORM.",
    ),
)

PAR_MARQUEUR = {regle.marqueur: regle for regle in CATALOGUE}


@dataclass(frozen=True)
class Apport:
    regle: Regle
    fichier: str
    ligne: int

    def texte(self) -> str:
        ou = f"{self.fichier}:{self.ligne}" if self.ligne else self.fichier
        return (
            f"  {ou} — {self.regle.ancien}\n"
            f"      → {self.regle.nouveau}\n"
            f"      (Odoo {self.regle.depuis}.0)"
        )


def calculer(observations, cible: str) -> list[Apport]:
    """Les apports d'une version donnée, pour ce module-là.

    « observations » est la liste des (marqueur, fichier, ligne) relevés à la
    lecture. Un même marqueur peut apparaître plusieurs fois ; on ne garde que
    la première occurrence, sinon un module qui écrit « attrs » quarante fois
    produirait quarante lignes disant la même chose.
    """
    majeure = int(str(cible).split(".")[0])
    apports, vus = [], set()
    for marqueur, fichier, ligne in observations:
        regle = PAR_MARQUEUR.get(marqueur)
        if regle is None or marqueur in vus or regle.depuis > majeure:
            continue
        vus.add(marqueur)
        apports.append(Apport(regle, fichier, ligne))
    return sorted(apports, key=lambda a: (a.regle.genre, -a.regle.depuis))


def par_version(observations) -> dict[str, list[Apport]]:
    """Le même module vu par chaque version : c'est la comparaison utile.

    Répond à « qu'est-ce que la 19 m'apporte de plus que la 18 » sans qu'on
    ait à raisonner : la différence entre deux listes est la réponse.
    """
    from generator.dialecte import CIBLES
    return {cible: calculer(observations, cible) for cible in CIBLES}
