"""Ce qui change d'une version d'Odoo à l'autre, et rien d'autre.

Le modèle de spécification décrit un besoin : des objets, des champs, des
listes, des états. Rien là-dedans n'appartient à une version d'Odoo. Ce qui
change entre 17, 18 et 19, ce sont les mots employés pour l'écrire — et c'est
tout ce que ce module connaît.

La séparation est délibérée. Sans elle, chaque nouvelle version obligerait à
relire le générateur entier pour y traquer les endroits sensibles ; ici, elle
se traite en ajoutant une entrée. Et surtout, une même spécification produit
plusieurs modules sans que la logique métier soit dupliquée — dupliquée, elle
divergerait, et l'un des deux se corrigerait sans l'autre.

CE QUE CE MODULE N'EST PAS : une théorie des différences entre versions
d'Odoo. Chaque entrée ici doit être **vérifiée par l'installation réelle**
dans l'image correspondante. Ce qui n'est pas éprouvé par la recette
multi-versions n'a rien à faire ici — une différence supposée est pire qu'une
différence ignorée, parce qu'elle produit du code qui a l'air juste.
"""

from __future__ import annotations

from dataclasses import dataclass

# Les versions que le Builder sait viser. En ajouter une suppose d'ajouter
# l'image correspondante à la recette : sans preuve d'installation, une cible
# ne vaut rien.
CIBLES = ("17.0", "18.0", "19.0")


class CibleInconnue(Exception):
    """Version demandée hors de celles que la recette éprouve."""


@dataclass(frozen=True)
class Dialecte:
    """Les mots d'une version donnée."""

    cible: str

    def __post_init__(self):
        if self.cible not in CIBLES:
            raise CibleInconnue(
                f"cible « {self.cible} » inconnue ; attendu l'une de "
                f"{', '.join(CIBLES)}."
            )

    @property
    def majeure(self) -> int:
        return int(self.cible.split(".")[0])

    # ------------------------------------------------------------------ vues

    @property
    def balise_liste(self) -> str:
        """« tree » jusqu'en 17, « list » à partir de 18.

        ÉPROUVÉ à deux titres, et il faut distinguer les deux.

        La recette multi-versions établit que « list » PASSE en 18 et 19, et
        « tree » en 17 : générés, installés, mis à jour, exécutés. Elle ne dit
        rien de plus — elle n'a jamais soumis « tree » à un Odoo 18.

        Ce que « tree » y deviendrait vient des sources. Le type d'une vue est
        le nom de sa balise racine :

            values['type'] = etree.fromstring(...arch...).tag
            (odoo/addons/base/models/ir_ui_view.py, 18.0 l. 506)

        et la sélection de « ir.ui.view.type » ne comporte plus « tree » à
        partir de 18 — seulement « list » (même fichier, l. 153). Une vue
        « tree » y prend donc un type hors sélection : elle est refusée à
        l'écriture, c'est-à-dire au chargement du module.
        """
        return "tree" if self.majeure < 18 else "list"

    def mode_vue(self, mode: str) -> str:
        """Le nom d'un mode dans « view_mode » d'une action.

        Il suit la balise : une action en « tree » sur une version qui ne
        connaît que « list » ouvre une vue introuvable.
        """
        return self.balise_liste if mode == "tree" else mode

    # -------------------------------------------------------------- manifeste

    def version_manifeste(self, version_fonctionnelle: str) -> str:
        """« 1.0.0 » pour la cible 18.0 donne « 18.0.1.0.0 ».

        Odoo attend que la version d'un module commence par celle d'Odoo. Ce
        n'est pas décoratif : c'est ce qui lui permet de savoir qu'un module
        installé en 17.0 doit être mis à jour au passage en 18.0.

        ÉPROUVÉ. Cette règle n'est plus une supposition : la recette
        multi-versions a fait tomber Odoo 18 dessus. Un module du dépôt
        déclarant « 17.0.1.0.0 » sur le chemin d'addons d'un Odoo 18 donne

            ValueError: Module ansut_rh: invalid manifest
              ← Invalid version '17.0.1.0.0'. Modules should have a version
                in format `x.y`, `x.y.z`, `18.0.x.y` ou `18.0.x.y.z`.

        et l'échec n'est PAS l'installation du module : c'est l'initialisation
        de la base. Odoo lit tous les manifestes du chemin d'addons avant de
        créer quoi que ce soit ; un seul module d'une autre série l'empêche de
        démarrer. C'est la première chose que rencontrera le convertisseur de
        versions, et elle n'a rien de graduel.
        """
        return f"{self.cible}.{version_fonctionnelle}"
