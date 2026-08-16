"""Fabriquer un thème backend Odoo qui survit aux montées de version.

Un thème Odoo fait deux choses très différentes, et c'est leur mélange qui
rend les thèmes « la chose la plus terrible d'Odoo » :

  1. il RÈGLE DES VARIABLES — couleurs, polices, densité. Cela survit aux
     montées de version ;
  2. il RÉÉCRIT DES GABARITS ET DU JAVASCRIPT — barre, menu, listes. Cela
     casse à chaque version, parce qu'Odoo réécrit son interface.

Ce générateur ne fait que le premier, et c'est un choix, pas une limite.

CE QUI LE JUSTIFIE, vérifié dans les sources d'Odoo : la surface de variables
de « addons/web/static/src/scss/primary_variables.scss » est IDENTIQUE entre
17.0 et 18.0 — mêmes « $o-brand-primary », « $o-gray-100..900 »,
« $o-font-size-base », « $o-webclient-color-scheme ». Un thème qui s'en tient
là se réinstalle d'une version à l'autre sans une ligne à changer. Les thèmes
qui cassent sont ceux qui touchent aux gabarits.

CE QUE CE GÉNÉRATEUR NE FAIT PAS, et qu'il ne faut pas lui demander :
déplacer le menu, réécrire les listes, ajouter une palette de commandes.
La palette Ctrl+K et le lanceur d'applications sont d'ailleurs NATIFS depuis
Odoo 17 — les réimplanter serait payer pour ce qu'on a déjà.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, field

CIBLES = ("17.0", "18.0", "19.0")
HEXA = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Les polices proposées sont celles qu'un système fournit déjà. Embarquer une
# police dans un thème ajoute des mégaoctets à chaque chargement de page, et
# c'est l'une des raisons pour lesquelles les thèmes du commerce sont lourds :
# celui d'Allure porte 52 fichiers TTF.
POLICES = {
    "systeme": ('system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
                "Celle du système — la plus rapide, aucune ressource à charger"),
    "odoo": ('"Odoo Unicode Support Noto Sans", sans-serif', "Celle d'Odoo"),
    "lisible": ('"Segoe UI", Tahoma, Verdana, sans-serif',
                "Large et posée, pour les écrans très remplis"),
}

DENSITES = {
    "compacte": (0.8125, "Beaucoup de lignes à l'écran"),
    "normale": (0.875, "Le réglage d'Odoo"),
    "confortable": (0.9375, "Plus d'air, moins de lignes"),
}


class ThemeInvalide(Exception):
    """La charte décrite n'est pas réalisable."""


def _rvb(hexa: str) -> tuple:
    hexa = hexa.lstrip("#")
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(hexa: str) -> float:
    """Luminance relative, formule du WCAG.

    Sert à choisir un texte lisible SUR une couleur. Deviner « blanc sur tout »
    donne un orange illisible ; c'est l'erreur la plus fréquente des chartes
    reprises telles quelles.
    """
    canaux = []
    for valeur in _rvb(hexa):
        c = valeur / 255
        canaux.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    rouge, vert, bleu = canaux
    return 0.2126 * rouge + 0.7152 * vert + 0.0722 * bleu


def contraste(premier: str, second: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs (1 à 21)."""
    a, b = _luminance(premier), _luminance(second)
    clair, sombre = max(a, b), min(a, b)
    return (clair + 0.05) / (sombre + 0.05)


def texte_lisible(fond: str) -> str:
    """Noir ou blanc, celui qui contraste le mieux sur ce fond."""
    return "#FFFFFF" if contraste(fond, "#FFFFFF") >= contraste(fond, "#111111") \
        else "#111111"


def _teinter(hexa: str, facteur: float) -> str:
    """Éclaircir (facteur > 0) ou assombrir (facteur < 0) une couleur.

    On passe par la luminosité TSL plutôt que par un mélange en RVB : mélanger
    du blanc à un bleu le délave vers le gris, alors qu'augmenter la luminosité
    garde la teinte. Sur une charte institutionnelle, la teinte est justement
    ce qu'on n'a pas le droit de perdre.
    """
    rouge, vert, bleu = (v / 255 for v in _rvb(hexa))
    teinte, luminosite, saturation = colorsys.rgb_to_hls(rouge, vert, bleu)
    luminosite = min(1.0, max(0.0, luminosite + facteur))
    rouge, vert, bleu = colorsys.hls_to_rgb(teinte, luminosite, saturation)
    return "#%02X%02X%02X" % tuple(round(c * 255) for c in (rouge, vert, bleu))


@dataclass
class Charte:
    """La charte graphique, telle qu'un communicant la donne."""

    nom: str
    technical_name: str
    primaire: str                       # la couleur de l'institution
    accent: str                         # la couleur secondaire
    police: str = "systeme"
    densite: str = "normale"
    arrondi: str = "4px"
    sombre: bool = True                 # produire aussi la variante sombre
    auteur: str = ""
    licence: str = "LGPL-3"
    version: str = "1.0.0"
    avertissements: list = field(default_factory=list)

    def valider(self) -> None:
        for nom, valeur in (("primaire", self.primaire), ("accent", self.accent)):
            if not HEXA.match(valeur):
                raise ThemeInvalide(
                    f"couleur {nom} « {valeur} » : attendu un code hexadécimal "
                    "à six chiffres, par exemple #2256A3."
                )
        if self.police not in POLICES:
            raise ThemeInvalide(f"police inconnue « {self.police} ».")
        if self.densite not in DENSITES:
            raise ThemeInvalide(f"densité inconnue « {self.densite} ».")
        if not re.match(r"^[a-z][a-z0-9_]{2,63}$", self.technical_name):
            raise ThemeInvalide(f"nom technique invalide « {self.technical_name} ».")

        # Le contraste se contrôle, il ne se suppose pas. Une charte est faite
        # pour du papier ; un fond de barre latérale n'est pas un logo.
        self.avertissements = []
        for nom, couleur in (("primaire", self.primaire), ("accent", self.accent)):
            rapport = contraste(couleur, texte_lisible(couleur))
            if rapport < 4.5:
                self.avertissements.append(
                    f"La couleur {nom} {couleur} n'atteint que {rapport:.1f}:1 "
                    f"avec le meilleur texte possible — le seuil de lisibilité "
                    f"du WCAG est 4,5:1. Elle conviendra pour un aplat ou une "
                    f"bordure, pas pour un fond portant du texte."
                )


def jetons(charte: Charte, sombre: bool = False) -> dict:
    """Les couleurs dérivées de la charte, claires ou sombres.

    Tout descend des deux couleurs données. Demander douze couleurs à un
    communicant serait le meilleur moyen d'obtenir douze couleurs qui ne vont
    pas ensemble.
    """
    if sombre:
        return {
            "primaire": _teinter(charte.primaire, 0.18),
            "accent": _teinter(charte.accent, 0.06),
            "fond": "#12161C",
            "surface": "#1A2029",
            "bordure": "#2A323D",
            "texte": "#E7ECF2",
            "texte-doux": "#98A5B3",
            "barre": _teinter(charte.primaire, -0.22),
            "texte-barre": "#FFFFFF",
        }
    return {
        "primaire": charte.primaire,
        "accent": charte.accent,
        "fond": "#F4F6F8",
        "surface": "#FFFFFF",
        "bordure": "#DDE2E9",
        "texte": "#151C24",
        "texte-doux": "#5F6B78",
        "barre": charte.primaire,
        "texte-barre": texte_lisible(charte.primaire),
    }


def scss(charte: Charte, cible: str) -> str:
    """Les variables d'Odoo, et rien d'autre.

    Aucune règle CSS visant une classe d'Odoo : ce sont elles qui cassent d'une
    version à l'autre, parce que les classes changent. Les variables, non.
    """
    clair, obscur = jetons(charte), jetons(charte, sombre=True)
    famille, _ = POLICES[charte.police]
    taille, _ = DENSITES[charte.densite]

    lignes = [
        f"// Thème « {charte.nom} » — Odoo {cible}",
        "//",
        "// Ce fichier ne contient QUE des variables d'Odoo. Aucune règle ne vise",
        "// une classe du client web : les classes changent d'une version à",
        "// l'autre, les variables non. C'est ce qui permet à ce thème de passer",
        "// de 17 à 18 sans être réécrit.",
        "",
        "// --- Identité",
        f"$o-brand-primary: {clair['primaire']};",
        f"$o-brand-secondary: {clair['accent']};",
        f"$o-community-color: {clair['primaire']};",
        f"$o-enterprise-color: {clair['primaire']};",
        f"$o-enterprise-primary-color: {clair['primaire']};",
        "",
        "// --- Typographie et densité",
        f"$o-font-size-base: {taille}rem;",
        f"$o-root-font-size: 14px;",
        f"$o-theme-font-family: {famille};",
        "",
        "// --- Jetons du thème, consommables par vos propres règles",
        ":root {",
    ]
    for cle, valeur in clair.items():
        lignes.append(f"  --theme-{cle}: {valeur};")
    lignes.append(f"  --theme-radius: {charte.arrondi};")
    lignes.append(f"  --theme-font: #{{inspect($o-theme-font-family)}};")
    lignes.append("}")

    if charte.sombre:
        lignes += [
            "",
            "// --- Variante sombre.",
            "// Odoo 17 a introduit « $o-webclient-color-scheme » : on s'aligne",
            "// dessus plutôt que d'inventer un second mécanisme, sans quoi le",
            "// thème et Odoo se contrediraient sur ce qu'est le mode sombre.",
            '[data-color-scheme="dark"], .o_dark_mode {',
        ]
        for cle, valeur in obscur.items():
            lignes.append(f"  --theme-{cle}: {valeur};")
        lignes.append("}")
    return "\n".join(lignes) + "\n"


def css(charte: Charte) -> str:
    """Le minimum d'habillage, écrit en jetons — jamais en couleurs figées."""
    return """/* Habillage minimal. Chaque valeur vient d'un jeton : changer la
   charte ne demande donc jamais de revenir ici. */

.o_main_navbar {
  background-color: var(--theme-barre) !important;
  color: var(--theme-texte-barre) !important;
}
.o_main_navbar .o_menu_brand,
.o_main_navbar > a { color: var(--theme-texte-barre) !important; }

.btn-primary {
  background-color: var(--theme-primaire);
  border-color: var(--theme-primaire);
}
.btn-primary:hover, .btn-primary:focus {
  background-color: var(--theme-accent);
  border-color: var(--theme-accent);
}

.o_form_view .o_form_sheet,
.o_list_view, .o_kanban_record {
  border-radius: var(--theme-radius);
}

.o_searchview_facet .o_searchview_facet_label { background-color: var(--theme-accent); }
.o_statusbar_status .o_arrow_button.btn-primary { background-color: var(--theme-primaire); }
"""


def manifeste(charte: Charte, cible: str) -> str:
    """Le manifeste, avec les bundles d'assets — pas la clé « qweb ».

    « qweb » a disparu en Odoo 15 au profit des bundles déclarés dans
    « assets ». C'est l'une des raisons pour lesquelles un thème v14 ne
    s'installe pas tel quel : sa déclaration d'assets n'est plus lue.
    """
    racine = charte.technical_name
    return f"""# -*- coding: utf-8 -*-
{{
    'name': {charte.nom!r},
    'version': {f'{cible}.{charte.version}'!r},
    'category': 'Themes/Backend',
    'summary': "Thème backend — identité visuelle par variables",
    'description': \"\"\"
Thème backend piloté par les variables d'Odoo.

Il ne réécrit aucun gabarit et ne remplace aucun composant : il définit les
variables que le client web consomme déjà. C'est ce qui lui permet de passer
d'une version d'Odoo à la suivante sans réécriture.

Ce qu'il NE fait pas, volontairement : déplacer le menu, réécrire les listes,
ajouter une palette de commandes. La palette Ctrl+K et le lanceur
d'applications sont natifs depuis Odoo 17.
\"\"\",
    'author': {charte.auteur or 'Atelier'!r},
    'license': {charte.licence!r},
    'depends': ['web'],
    'data': [],
    'assets': {{
        'web._assets_primary_variables': [
            ('prepend', '{racine}/static/src/scss/variables.scss'),
        ],
        'web.assets_backend': [
            '{racine}/static/src/css/theme.css',
        ],
    }},
    'installable': True,
    'application': False,
    'auto_install': False,
}}
"""


def generer(charte: Charte, cible: str) -> dict:
    """Le thème complet, prêt à être installé, pour la version visée."""
    charte.valider()
    if cible not in CIBLES:
        raise ThemeInvalide(f"cible « {cible} » inconnue.")
    racine = charte.technical_name
    return {
        f"{racine}/__init__.py": "",
        f"{racine}/__manifest__.py": manifeste(charte, cible),
        f"{racine}/static/src/scss/variables.scss": scss(charte, cible),
        f"{racine}/static/src/css/theme.css": css(charte),
        f"{racine}/README.md": _readme(charte, cible),
    }


def _readme(charte: Charte, cible: str) -> str:
    liste = "\n".join(f"- {a}" for a in charte.avertissements)
    vigilance = ("## Points de vigilance\n\n" + liste) if liste else ""
    return f"""# {charte.nom}

Thème backend pour Odoo {cible}, piloté par les variables d'Odoo.

## Couleurs

| Rôle | Code |
|---|---|
| Primaire | `{charte.primaire}` |
| Accent | `{charte.accent}` |
| Texte sur primaire | `{texte_lisible(charte.primaire)}` |

## Installation

Déposer le dossier dans vos addons, puis :

    Applications → Mettre à jour la liste → « {charte.nom} » → Installer

## Ce que ce thème fait, et ne fait pas

Il définit les variables que le client web d'Odoo consomme déjà —
`$o-brand-primary`, `$o-font-size-base`, et les jetons `--theme-*`.

Il ne réécrit aucun gabarit et ne remplace aucun composant. C'est délibéré :
ce sont les gabarits qui changent d'une version d'Odoo à l'autre, et les
thèmes qui les réécrivent cassent à chaque montée de version.

Conséquence : ce thème ne déplace pas le menu et ne réorganise pas les vues.
Pour cela il faut du JavaScript, donc un développeur, et un entretien à
chaque version.

La palette de commandes (Ctrl+K) et le lanceur d'applications sont **natifs**
depuis Odoo 17 : ce thème ne les réimplante pas.

{vigilance}
"""
