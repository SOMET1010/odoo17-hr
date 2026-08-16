# Modules d'exemple

## `suivi_dossier` — un module écrit à la mode d'Odoo 12

Il n'est pas là pour être installé tel quel : il est là pour être **converti**.

    python3 cli/convertir.py exemples/suivi_dossier --cible 19.0

Il rassemble volontairement les tournures qu'on rencontre dans un module
ancien, et que le convertisseur doit savoir traiter ou signaler :

| Tournure | Ce que la conversion en fait |
|---|---|
| manifeste `__openerp__.py` | signalée, et le converti porte `__manifest__.py` |
| racine XML `<openerp><data>` | signalée |
| `from openerp import …` | signalée |
| `@api.multi` | signalée |
| `attrs="{…}"` dans une vue | signalée (supprimé en Odoo 17) |
| `view_type` sur une action | signalée (disparu en Odoo 12) |
| `fields.Char('Référence')` | le premier argument est le libellé, pas un comodèle |
| `fields.Many2one('res.partner', 'Client')` | comodèle **et** libellé, chacun à sa place |
| `<tree>` | rendu `<list>` si la cible est 18 ou 19 |
| version `12.0.1.3.0` | devient `19.0.1.3.0` — la version fonctionnelle survit |
| champ `compute=` | **abandonné**, jamais dégradé en champ vide |
| `default=lambda …` | le champ est gardé, le défaut est signalé |
| `_sql_constraints` | signalée comme perte de comportement |
| méthodes | signalées une par une, avec l'état qu'elles écrivent |
| champ de vue inexistant | retiré, et signalé |
| aucun fichier de droits | droits inventés, **et annoncés en toutes lettres** |
| `group_operator=` | signalé : renommé `aggregator` en Odoo 17.2 |
| surcharge de `name_get` | signalée : dépréciée en 16.4, lire `display_name` |

Odoo ne le voit pas comme un module : depuis la version 10, un dossier n'est un
module que s'il contient `__manifest__.py`. Il peut donc vivre dans le dépôt
sans être chargé par l'instance qui le monte.

Les tests et la recette multi-versions lisent ce dossier — pas une copie.
Deux copies divergeraient, et l'une se corrigerait sans l'autre.

## Ce que la version d'arrivée apporte

    python3 cli/convertir.py exemples/suivi_dossier --cible 19.0 --comparer-versions

L'autre moitié d'une migration. Porter fidèlement un contournement écrit pour
la v12 revient à réimplanter en v19 ce que la v19 sait faire — on obtient un
module qui marche et qui coûte cher.

Deux règles, sans lesquelles la liste serait un prospectus :

1. un apport n'est cité que si le module **contient** le motif qu'il remplace,
   fichier et ligne à l'appui ;
2. un apport n'est cité que s'il existe **dans la version visée** — c'est ce
   qui fait qu'une conversion vers 17 et une vers 19 ne disent pas la même
   chose, et donc ce qui répond à « qu'est-ce que la 19 m'apporte de plus ».

Les apports sont séparés en deux : **acquis** (la régénération vous les donne
sans rien écrire — `<list>`, attributs de vue directs) et **à saisir** (ils
portent sur du code que le convertisseur ne reprend pas ; il faut réécrire —
`models.Constraint`, `aggregator`, `_compute_display_name`).

Rien n'est appliqué. Réécrire à la place de l'auteur supposerait de comprendre
son intention, et le convertisseur ne comprend rien : il lit.

## D'où vient ce que le convertisseur sait des versions

Deux sources, et jamais la mémoire.

1. **La documentation officielle**, lue à sa source — le dépôt
   `odoo/documentation`, branche par branche. Elle ne porte pas de directives
   de version : il n'existe donc pas de liste toute faite des ruptures. Ce qui
   en tient lieu, c'est le journal de l'ORM
   (`content/developer/reference/backend/orm/changelog.rst`) et **la différence
   entre les branches** — comparer `17.0`, `18.0` et `19.0` du même fichier
   donne l'inventaire que le journal ne donne pas.

2. **Le code d'Odoo**, sur la branche concernée, pour vérifier. La
   documentation dit ce qui est prévu ; le code dit ce qui arrive. Quand les
   deux se contredisent, c'est le code qui a raison — mais c'est la
   documentation qui dit où regarder.

Exemple des deux à l'œuvre : la disparition de `_sql_constraints` de la
documentation d'Odoo 19 a mené à `odoo/orm/model_classes.py`, où l'on voit
qu'Odoo se contente d'un avertissement au journal. Le module s'installe, la
ligne défile, et la contrainte n'existe plus. Ni la documentation seule ni le
code seul ne l'auraient dit aussi nettement.
