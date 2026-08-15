"""Fabrique d'archives de test.

Les barrières du service se jugent sur des archives réellement malveillantes,
pas sur des chaînes de caractères : on construit donc de vrais ZIP.
"""

from __future__ import annotations

import os
import zipfile

MANIFESTE = """{
    'name': "Module de recette",
    'version': '17.0.1.0.0',
    'depends': ['base'],
}
"""


def ecrire_zip(chemin: str, entrees: dict[str, bytes | str]) -> str:
    """Écrit un ZIP dont les clés sont les noms d'entrée."""
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, contenu in entrees.items():
            archive.writestr(nom, contenu)
    return chemin


def module_valide(dossier: str, nom: str = "module_recette") -> str:
    """Archive d'un module Odoo minimal mais complet."""
    chemin = os.path.join(dossier, f"{nom}.zip")
    return ecrire_zip(
        chemin,
        {
            f"{nom}/__manifest__.py": MANIFESTE,
            f"{nom}/__init__.py": "",
            f"{nom}/models/__init__.py": "",
        },
    )


def zip_avec_lien(dossier: str, nom: str = "module_lien") -> str:
    """Archive contenant un lien symbolique, que le service doit refuser."""
    chemin = os.path.join(dossier, "lien.zip")
    with zipfile.ZipFile(chemin, "w") as archive:
        archive.writestr(f"{nom}/__manifest__.py", MANIFESTE)
        info = zipfile.ZipInfo(f"{nom}/passwd")
        # 0o120000 = lien symbolique dans les bits de type unix.
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "/etc/passwd")
    return chemin
