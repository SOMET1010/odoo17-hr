# -*- coding: utf-8 -*-
{
    'name': 'Thème Backend',
    'summary': "Habillage global du backend : couleurs de marque, typographie, arrondis, ombres et densité",
    'description': """
Thème global du backend Odoo
============================
Applique l'identité visuelle de l'entreprise à l'ensemble du backend :
couleurs de marque, police, coins arrondis, ombres douces et densité
des tableaux. Aucune logique métier n'est modifiée — le module est
purement cosmétique et désinstallable sans risque.

Personnalisation : éditez les variables en tête de
``static/src/scss/primary_variables.scss`` (couleurs) et
``static/src/scss/bootstrap_overrides.scss`` (typo, arrondis, densité).
""",
    'version': '17.0.1.0.0',
    'category': 'Themes/Backend',
    'author': 'Interne',
    'license': 'LGPL-3',
    'depends': ['web'],
    # Depuis Odoo 15, les assets se déclarent ici (plus de fichier XML d'assets).
    'assets': {
        # 1) Variables de marque Odoo — 'prepend' pour passer avant les
        #    définitions d'Odoo (qui utilisent !default).
        'web._assets_primary_variables': [
            ('prepend', 'theme_backend/static/src/scss/primary_variables.scss'),
        ],
        # 2) Variables Bootstrap (arrondis, ombres, densité, typo) — chargées
        #    avant la compilation de Bootstrap par le backend.
        'web._assets_backend_helpers': [
            ('prepend', 'theme_backend/static/src/scss/bootstrap_overrides.scss'),
        ],
        # 3) Règles CSS finales (retouches ciblées, @font-face) — chargées
        #    après tout le style standard, donc prioritaires.
        'web.assets_backend': [
            'theme_backend/static/src/scss/theme.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
