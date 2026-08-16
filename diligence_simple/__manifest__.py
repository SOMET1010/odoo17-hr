# -*- coding: utf-8 -*-
{
    'name': "Diligences",
    'version': '17.0.1.0.0',
    'category': 'Services/Project',
    'sequence': 25,
    'summary': "Gestion de tâches simplifiée : une interface épurée au-dessus du module Projet",
    'description': """
Diligences — gestion de tâches simplifiée
=========================================
Cette application offre une interface volontairement épurée pour gérer les
diligences (tâches) au quotidien, sans la complexité du module Projet complet :

* Page « Aujourd'hui » : ce qui nécessite votre attention (retards, échéances du jour)
* Kanban simple à 4 colonnes : À faire / En cours / En validation / Terminé
* Priorités visuelles (Haute / Moyenne / Normale)
* Fiche réduite à l'essentiel : titre, responsable, échéance, description, sous-tâches
* Progression calculée automatiquement à partir des sous-tâches
* Calendrier des échéances et rapports simples

Les données restent les tâches standard d'Odoo (project.task) : rien n'est
dupliqué, le chatter et les activités sont conservés, et le module Projet
classique reste utilisable en parallèle.
    """,
    'depends': ['project'],
    'data': [
        'views/project_task_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'diligence_simple/static/src/scss/diligence.scss',
        ],
    },
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}
