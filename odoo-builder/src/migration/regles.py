"""Ce qu'il faut changer pour passer un module d'une version d'Odoo à l'autre.

Ce fichier ne convertit rien. Il ne régénère rien. Il DÉSIGNE — fichier, ligne,
ancienne écriture, nouvelle écriture, et depuis quelle version.

C'est le bon outil pour un module qu'on POSSÈDE et qu'on veut garder. Le
convertisseur, lui, régénère depuis une spécification et laisse tomber tout ce
qu'elle ne sait pas dire : sur un parc réel, cela représentait 232
comportements. Reconstruire est justifié quand on repart de zéro ; c'est
absurde quand le code existe, qu'il marche, et qu'il vous appartient.

TROIS GRAVITÉS, ET LA DEUXIÈME EST LA PLUS DANGEREUSE.

    BLOQUANT   — Odoo refuse le module, ou refuse de démarrer. Ça se voit.
    SILENCIEUX — Odoo accepte le module et le comportement disparaît. Rien ne
                 le signale à l'utilisateur ; on l'apprend en production, le
                 jour où la règle aurait dû jouer. C'est ce qu'il faut
                 traquer en premier.
    MANUEL     — hors de portée d'un outil : il faut un développeur. Le dire
                 vaut mieux que de laisser croire que la liste est complète.

PROVENANCE. Chaque règle porte sa source : le journal officiel de l'ORM
(dépôt odoo/documentation), la différence entre deux branches de la
documentation, ou le code d'Odoo lui-même. Une règle qu'on ne sait pas
justifier n'a rien à faire ici — elle produirait une correction qui a l'air
juste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BLOQUANT = "bloquant"
SILENCIEUX = "silencieux"
MANUEL = "manuel"

ORDRE = {BLOQUANT: 0, SILENCIEUX: 1, MANUEL: 2}


@dataclass(frozen=True)
class Regle:
    cle: str
    motif: re.Pattern
    fichiers: tuple           # extensions concernées
    depuis: int               # version STABLE d'Odoo qui impose le changement
    gravite: str
    quoi: str                 # ce qu'on a trouvé
    faire: str                # ce qu'il faut écrire à la place
    source: str


def _r(motif: str) -> re.Pattern:
    return re.compile(motif)


# Les versions « Odoo Online » (17.2, 18.2…) n'existent pas à l'installation :
# leurs changements arrivent dans la version stable SUIVANTE. « aggregator »,
# renommé en 17.2 d'après le journal, est absent de la 17.0 et présent en 18.0 :
# la règle porte donc 18. Se fier au numéro du journal ferait corriger un
# module pour une version qui n'a pas encore le remplacement.
REGLES = (
    # ------------------------------------------------------------- manifeste
    Regle("manifeste_openerp", _r(r"^\s*$"), (".openerp",), 10, BLOQUANT,
          "manifeste nommé « __openerp__.py »",
          "renommer le fichier en « __manifest__.py »",
          "nom abandonné en Odoo 10 ; les versions récentes ne le lisent plus."),

    # -------------------------------------------------------------- Python
    Regle("import_openerp", _r(r"^\s*(from|import)\s+openerp\b"), (".py",), 10,
          BLOQUANT, "import du paquet « openerp »",
          "remplacer « openerp » par « odoo »",
          "le paquet a été renommé en Odoo 10."),
    Regle("osv", _r(r"\bosv\.(osv|Model|osv_memory)\b|\bfrom\s+odoo\.osv\b"),
          (".py",), 10, BLOQUANT, "classe bâtie sur l'ancienne couche « osv »",
          "hériter de « models.Model » (ou « models.TransientModel »)",
          "la couche osv a disparu en Odoo 10 ; « odoo.osv » est déprécié en 19."),
    Regle("api_multi", _r(r"^\s*@api\.(multi|one)\b"), (".py",), 13, BLOQUANT,
          "décorateur « @api.multi » ou « @api.one »",
          "supprimer la ligne — une méthode reçoit un ensemble d'enregistrements "
          "par défaut ; « @api.one » demande en plus de boucler sur « self »",
          "décorateurs supprimés en Odoo 13."),
    Regle("api_cr", _r(r"^\s*@api\.(cr|cr_uid|cr_uid_ids|cr_uid_id|model_cr)\b"),
          (".py",), 13, BLOQUANT, "décorateur de l'ancienne signature « cr, uid »",
          "supprimer la ligne et adapter la signature à « self »",
          "signatures d'avant Odoo 8, décorateurs supprimés en 13."),
    Regle("colonnes", _r(r"^\s*_columns\s*=|^\s*_defaults\s*="), (".py",), 8,
          BLOQUANT, "champs déclarés en « _columns » / « _defaults »",
          "déclarer les champs par « nom = fields.Type(...) » et les valeurs par "
          "défaut par « default= » sur le champ",
          "écriture d'avant Odoo 8, plus lue du tout."),
    Regle("sql_constraints", _r(r"^\s*_sql_constraints\s*="), (".py",), 19,
          SILENCIEUX, "contraintes SQL en « _sql_constraints »",
          "réécrire en « models.Constraint », déclaré comme un champ",
          "Odoo 19 ne l'applique PLUS : il journalise un avertissement et la "
          "contrainte disparaît sans erreur (odoo/orm/model_classes.py, 19.0). "
          "Le module s'installe et la protection n'existe plus."),
    Regle("constraints", _r(r"^\s*_constraints\s*="), (".py",), 8, SILENCIEUX,
          "contraintes en « _constraints »",
          "réécrire en méthodes décorées « @api.constrains »",
          "attribut ignoré depuis Odoo 8 ; Odoo 19 le signale au journal."),
    Regle("name_get", _r(r"^\s*def\s+name_get\s*\("), (".py",), 18, SILENCIEUX,
          "surcharge de « name_get »",
          "réécrire en « _compute_display_name » sur le champ « display_name »",
          "« def name_get » présent en 17.0, ABSENT en 18.0 : la surcharge n'est "
          "plus appelée, et l'affichage revient silencieusement au défaut."),
    Regle("fields_view_get", _r(r"\bfields_view_get\s*\("), (".py",), 13,
          SILENCIEUX, "appel ou surcharge de « fields_view_get »",
          "utiliser « get_view »",
          "remplacé en Odoo 13 ; une surcharge n'est plus appelée."),
    Regle("read_group", _r(r"^\s*def\s+read_group\s*\(|\.read_group\s*\("),
          (".py",), 19, SILENCIEUX, "usage de « read_group »",
          "utiliser « _read_group » en interne, ou « formatted_read_group » "
          "pour une sortie déjà mise en forme",
          "déprécié en Odoo 18.2 ; « formatted_read_group » apparaît en 19.0."),
    Regle("group_operator", _r(r"\bgroup_operator\s*="), (".py",), 18, SILENCIEUX,
          "argument de champ « group_operator »",
          "renommer en « aggregator »",
          "renommé en Odoo 17.2 d'après le journal officiel de l'ORM ; absent "
          "du code de la 17.0, présent en 18.0. L'argument inconnu est ignoré, "
          "et l'agrégation de colonne cesse sans message."),
    Regle("track_visibility", _r(r"\btrack_visibility\s*="), (".py",), 12,
          SILENCIEUX, "argument de champ « track_visibility »",
          "remplacer par « tracking=True »",
          "renommé en Odoo 12 ; l'ancien nom est ignoré, le suivi disparaît."),
    Regle("oldname", _r(r"\boldname\s*="), (".py",), 13, SILENCIEUX,
          "argument de champ « oldname »",
          "supprimer, et gérer le renommage par un script de migration",
          "supprimé en Odoo 13."),
    Regle("select", _r(r"\bselect\s*=\s*(True|1)\b"), (".py",), 9, SILENCIEUX,
          "argument de champ « select »",
          "remplacer par « index=True »",
          "renommé en Odoo 9 ; l'ancien nom est ignoré, l'index n'est pas créé."),
    Regle("digits_compute", _r(r"\bdigits_compute\s*="), (".py",), 9, SILENCIEUX,
          "argument de champ « digits_compute »",
          "remplacer par « digits= »",
          "supprimé en Odoo 9."),

    # ----------------------------------------------------------------- XML
    Regle("racine_openerp", _r(r"<openerp\b"), (".xml",), 10, BLOQUANT,
          "racine XML « <openerp> »",
          "remplacer par « <odoo> » et retirer le « <data> » intérieur "
          "quand il ne porte pas « noupdate »",
          "racine renommée en Odoo 10."),
    Regle("attrs", _r(r"\battrs\s*="), (".xml",), 17, BLOQUANT,
          "attribut de vue « attrs »",
          "écrire « invisible », « readonly » ou « required » directement sur "
          "l'élément, avec l'expression Python en valeur",
          "supprimé en Odoo 17 ; la vue est refusée au chargement."),
    Regle("states_vue", _r(r"<(field|button|page|group)[^>]*\bstates\s*="), (".xml",),
          17, BLOQUANT, "attribut de vue « states »",
          "écrire « invisible=\"state not in ['a','b']\" »",
          "supprimé en Odoo 17."),
    Regle("balise_tree", _r(r"<tree\b|</tree>"), (".xml",), 18, BLOQUANT,
          "vue liste écrite « <tree> »",
          "renommer la balise en « <list> »",
          "« ir.ui.view.type » n'offre plus « tree » à partir de 18.0 : le type "
          "de la vue est le nom de sa balise racine, et une valeur hors "
          "sélection est refusée à l'écriture."),
    Regle("mode_tree", _r(r"<field\s+name=[\"']view_mode[\"']\s*>[^<]*\btree\b"),
          (".xml",), 18, BLOQUANT, "mode de vue « tree » dans une action",
          "remplacer « tree » par « list » dans « view_mode »",
          "suit le renommage de la balise ; l'action ouvrirait une vue "
          "introuvable."),
    Regle("view_type", _r(r"<field\s+name=[\"']view_type[\"']"), (".xml",), 12,
          BLOQUANT, "champ « view_type » sur une action",
          "supprimer la ligne",
          "champ supprimé en Odoo 12."),
    Regle("act_window", _r(r"<act_window\b"), (".xml",), 17, BLOQUANT,
          "forme abrégée « <act_window> »",
          "déclarer un « <record model=\"ir.actions.act_window\"> »",
          "forme abrégée supprimée en Odoo 17."),
    Regle("kanban_box", _r(r"t-name\s*=\s*[\"']kanban-box[\"']"), (".xml",), 18,
          SILENCIEUX, "gabarit kanban « kanban-box »",
          "définir un gabarit « card »",
          "Odoo 18 journalise « 'kanban-box' is deprecated, define a 'card' "
          "template instead » (odoo/addons/base/models/ir_ui_view.py)."),

    # ------------------------------------------------------------ JavaScript
    Regle("odoo_define", _r(r"odoo\.define\s*\("), (".js",), 16, MANUEL,
          "module JavaScript déclaré par « odoo.define »",
          "réécrire en module ES avec « /** @odoo-module **/ »",
          "Odoo est passé aux modules ES à partir de la 16 ; le cadriciel "
          "d'interface a changé (OWL). Aucun outil ne peut faire cette "
          "traduction à votre place."),
    Regle("widget_legacy", _r(r"\brequire\s*\(\s*['\"]web\.(Widget|AbstractAction|"
                              r"FormController|ListRenderer)"), (".js",), 16, MANUEL,
          "composant d'interface de l'ancien cadriciel",
          "réécrire en composant OWL",
          "l'ancien cadriciel a été retiré ; la réécriture est un travail de "
          "développeur, pas une substitution."),
)


def regles_pour(cible: str) -> tuple:
    """Les règles qui s'appliquent à la version visée.

    Une règle dont la version est postérieure à la cible ne s'applique pas :
    corriger « _sql_constraints » n'a aucun sens si l'on vise la 17, où il
    fonctionne parfaitement.
    """
    majeure = int(str(cible).split(".")[0])
    return tuple(r for r in REGLES if r.depuis <= majeure)
