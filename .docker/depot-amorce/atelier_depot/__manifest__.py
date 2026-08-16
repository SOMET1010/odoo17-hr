# -*- coding: utf-8 -*-
#
# Ce module ne fait rien, et c'est sa raison d'être.
#
# Odoo 19 filtre « addons_path » au démarrage et ÉCARTE tout dossier qui ne
# contient encore aucun module (odoo/tools/config.py, _is_addons_path). Or le
# dossier où l'Atelier dépose ses modules est vide sur une instance neuve :
# sans ce marqueur, Odoo 19 le retire de son chemin d'addons au démarrage, et
# le premier module déposé reste invisible pour toujours — « update_list »
# répond 200 sans rien trouver, ce qui est le pire des symptômes.
#
# Odoo 17 et 18 ne vérifiaient que l'existence du dossier, et seulement pour
# l'option de ligne de commande : le problème n'y apparaît pas.
#
# La version est écrite « 1.0 » sans préfixe : Odoo la préfixe alors avec sa
# propre série, quelle qu'elle soit. Une version préfixée en dur ferait de ce
# marqueur un module d'une seule version d'Odoo — exactement ce qu'il ne doit
# pas être.
{
    'name': "Dépôt de modules de l'Atelier",
    'version': '1.0',
    'summary': "Marqueur : ce dossier reçoit les modules déposés par l'Atelier.",
    'description': """
Ce dossier est le point de dépôt du service d'installation. Il ne contient
aucun module tant que rien n'a été fabriqué — et un dossier vide disparaît du
chemin d'addons d'Odoo 19. Ce marqueur le garde visible.

Il n'est pas installable : il n'a rien à installer.
""",
    'author': "Atelier",
    'license': 'LGPL-3',
    'category': 'Hidden',
    'depends': [],
    'installable': False,
}
