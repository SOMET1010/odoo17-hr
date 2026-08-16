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

Odoo ne le voit pas comme un module : depuis la version 10, un dossier n'est un
module que s'il contient `__manifest__.py`. Il peut donc vivre dans le dépôt
sans être chargé par l'instance qui le monte.

Les tests et la recette multi-versions lisent ce dossier — pas une copie.
Deux copies divergeraient, et l'une se corrigerait sans l'autre.
