"""Décrire un thème en français, plutôt que choisir des couleurs une à une.

POURQUOI. La case « thème » demandait des codes hexadécimaux, une police et
une densité. C'est du vocabulaire de développeur, et cela suppose qu'on ait la
charte sous les yeux, convertie. Or la demande arrive presque toujours en
français — « les couleurs de l'institution, du bleu foncé et un orange, dense,
avec une variante sombre » — ou dans un document de charte graphique.

La règle du projet ne change pas d'un iota : LE MODÈLE N'ÉCRIT PAS DE CODE. Il
ne rend ici que des VALEURS — six caractères hexadécimaux, un nom de police
choisi dans une liste fermée, une densité. Tout ce qui est produit ensuite —
variables SCSS, bundle d'assets, manifeste — sort du générateur déterministe,
comme avant.

ET SURTOUT : le contraste reste MESURÉ, jamais accordé sur parole. Un modèle
qui propose un jaune pâle sur blanc n'a aucune idée de ce que cela donne à
l'écran ; « generateur.py » le calcule et le refuse. La relecture montre donc
les couleurs proposées AVANT de fabriquer quoi que ce soit.
"""

from __future__ import annotations

import re

from theme.generateur import DENSITES, POLICES, Charte, contraste

HEXA = re.compile(r"^#[0-9A-Fa-f]{6}$")

CONSIGNE = """Tu traduis une demande de charte graphique en valeurs exactes,
pour un thème d'interface Odoo. Tu ne rends que des valeurs, jamais de code.

Rends un objet JSON avec exactement ces clés :

  "nom"       : le nom lisible du thème, en français.
  "technique" : un identifiant en minuscules, sans accent, mots séparés par
                des tirets bas ; commence par une lettre. Exemple :
                theme_ansut_bleu.
  "primaire"  : la couleur principale de l'institution, en hexadécimal à six
                chiffres, par exemple #1F4E79.
  "accent"    : la couleur secondaire, même format.
  "police"    : un seul mot parmi %(polices)s.
  "densite"   : un seul mot parmi %(densites)s.
  "sombre"    : true si une variante sombre est souhaitée, false sinon.
  "raison"    : une phrase expliquant le choix des deux couleurs.

Si la demande cite des couleurs par leur nom, traduis-les fidèlement. Si elle
n'en cite aucune, choisis un couple sobre et LISIBLE : le texte blanc devra
rester lisible sur la couleur primaire. Ne rends rien d'autre que cet objet."""


def consigne() -> str:
    return CONSIGNE % {"polices": ", ".join(POLICES),
                       "densites": ", ".join(DENSITES)}


def _couleur(valeur, defaut: str) -> str:
    valeur = str(valeur or "").strip()
    if not valeur.startswith("#"):
        valeur = "#" + valeur
    return valeur if HEXA.match(valeur) else defaut


def decrire(fournisseur, besoin: str, journal=None) -> dict:
    """Rend les valeurs de la charte, prêtes à remplir le formulaire.

    Ne fabrique rien : c'est l'utilisateur qui regarde, corrige, et lance.
    """
    if journal:
        journal("Lecture de la charte…")
    brut = fournisseur.completer_json(consigne(), besoin)
    if not isinstance(brut, dict):
        brut = {}

    technique = re.sub(r"[^a-z0-9_]", "_", str(brut.get("technique") or "").lower())
    technique = re.sub(r"_+", "_", technique).strip("_") or "mon_theme"
    if not technique[0].isalpha():
        technique = "theme_" + technique

    charte = {
        "nom": str(brut.get("nom") or "Thème").strip()[:80],
        "technique": technique[:60],
        # Des défauts SOBRES et lisibles, pour qu'une réponse incomplète
        # produise quand même une charte valide plutôt qu'un refus.
        "primaire": _couleur(brut.get("primaire"), "#1F4E79"),
        "accent": _couleur(brut.get("accent"), "#C8781E"),
        "police": (brut.get("police") if brut.get("police") in POLICES
                   else "systeme"),
        "densite": (brut.get("densite") if brut.get("densite") in DENSITES
                    else "normale"),
        "sombre": bool(brut.get("sombre", True)),
        "raison": str(brut.get("raison") or "").strip()[:300],
    }

    # LE CONTRASTE EST MESURÉ ICI, avant de montrer quoi que ce soit. Un
    # modèle n'a aucune idée de ce que sa proposition donne à l'écran ; le
    # rapport de luminance, lui, se calcule. On ne corrige pas d'autorité —
    # on le DIT, et l'utilisateur tranche devant l'aperçu.
    charte["contraste_primaire"] = round(contraste(charte["primaire"], "#FFFFFF"), 2)
    charte["contraste_accent"] = round(contraste(charte["accent"], "#FFFFFF"), 2)
    charte["alerte"] = ""
    if charte["contraste_primaire"] < 4.5:
        charte["alerte"] = (
            f"Le blanc sur la couleur principale ne donne qu'un rapport de "
            f"{charte['contraste_primaire']} pour 1, sous le seuil de 4,5 "
            f"exigé pour un texte lisible. Le générateur posera du texte "
            f"foncé, ou choisissez une teinte plus soutenue.")

    if journal:
        journal(f"  {charte['nom']} — {charte['primaire']} / "
                f"{charte['accent']}, contraste {charte['contraste_primaire']}")
    return charte


def en_charte(valeurs: dict) -> Charte:
    """Des valeurs relues vers l'objet que le générateur attend."""
    return Charte(
        nom=valeurs.get("nom") or "Thème",
        technical_name=valeurs.get("technique") or "mon_theme",
        primaire=valeurs.get("primaire") or "#1F4E79",
        accent=valeurs.get("accent") or "#C8781E",
        police=valeurs.get("police") or "systeme",
        densite=valeurs.get("densite") or "normale",
        sombre=bool(valeurs.get("sombre", True)),
    )
