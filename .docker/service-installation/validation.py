"""Barrières de sécurité du service d'installation de modules.

Tout ce qui décide « cette archive est-elle acceptable ? » vit ici, sans
dépendance ni accès réseau, pour rester vérifiable par des tests qui
tournent sans Docker.

Le service qui appelle ces fonctions n'a pas accès au socket Docker : la
seule chose qu'il puisse faire d'une archive, c'est l'écrire dans le volume
d'addons dédié. Ces contrôles sont donc la barrière principale, pas un
filtre de confort.
"""

from __future__ import annotations

import ast
import os
import shutil
import zipfile
from dataclasses import dataclass
import re

# Un nom de module Odoo : minuscules, chiffres et soulignés. Le motif sert
# aussi de nom de dossier sur le disque, d'où la sévérité.
NOM_MODULE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

# Écraser l'un de ces modules casserait l'instance : on refuse toujours.
NOMS_RESERVES = frozenset({"base", "web", "odoo", "openerp", "bus", "mail"})

# Bits de type de fichier stockés dans les 16 bits hauts d'external_attr.
_MASQUE_TYPE = 0o170000
_TYPE_FICHIER = 0o100000
_TYPE_DOSSIER = 0o040000
_TYPE_LIEN = 0o120000


@dataclass(frozen=True)
class Limites:
    """Plafonds appliqués à une archive. Tous en octets, sauf indication."""

    taille_archive: int = 20 * 1024 * 1024
    taille_decompressee: int = 100 * 1024 * 1024
    nombre_fichiers: int = 2000
    # Une archive qui gonfle plus que ça à la décompression est une bombe zip.
    ratio_compression: int = 200


class Refus(Exception):
    """Archive refusée. Le message est destiné à l'appelant du service."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def _type_entree(info: zipfile.ZipInfo) -> int:
    """Type unix de l'entrée, ou 0 si l'archive ne le renseigne pas."""
    return (info.external_attr >> 16) & _MASQUE_TYPE


def verifier_chemin(nom: str) -> tuple[str, ...]:
    """Découpe un nom d'entrée en segments sûrs, ou lève Refus.

    On refuse tout ce qui pourrait sortir du dossier de destination :
    chemin absolu, remontée « .. », séparateur Windows (ambigu selon la
    plateforme qui déballe), lettre de lecteur, octet nul.
    """
    if not nom:
        raise Refus("L'archive contient une entrée sans nom.")
    if "\x00" in nom:
        raise Refus("L'archive contient un nom d'entrée avec un octet nul.")
    if nom.startswith("/") or nom.startswith("\\"):
        raise Refus(f"Chemin absolu refusé dans l'archive : {nom!r}.")
    if "\\" in nom:
        raise Refus(f"Séparateur Windows refusé dans l'archive : {nom!r}.")
    if re.match(r"^[A-Za-z]:", nom):
        raise Refus(f"Lettre de lecteur refusée dans l'archive : {nom!r}.")

    segments = tuple(p for p in nom.split("/") if p not in ("", "."))
    if not segments:
        raise Refus(f"Entrée sans chemin exploitable : {nom!r}.")
    if any(p == ".." for p in segments):
        raise Refus(f"Remontée de dossier refusée dans l'archive : {nom!r}.")
    return segments


def inspecter(
    chemin_zip: str,
    limites: Limites | None = None,
    modules_proteges: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> str:
    """Contrôle une archive sans rien extraire et renvoie le nom du module.

    Lève Refus au premier problème. Les contrôles sont volontairement
    ordonnés du moins coûteux au plus coûteux.
    """
    limites = limites or Limites()

    taille = os.path.getsize(chemin_zip)
    if taille > limites.taille_archive:
        raise Refus(
            f"Archive trop volumineuse : {taille} octets, "
            f"maximum {limites.taille_archive}.",
            code=413,
        )
    if taille == 0:
        raise Refus("Archive vide.")

    try:
        archive = zipfile.ZipFile(chemin_zip)
    except zipfile.BadZipFile:
        raise Refus("Le fichier envoyé n'est pas une archive ZIP lisible.")

    with archive:
        entrees = archive.infolist()
        if not entrees:
            raise Refus("L'archive ne contient aucune entrée.")
        if len(entrees) > limites.nombre_fichiers:
            raise Refus(
                f"L'archive contient {len(entrees)} entrées, "
                f"maximum {limites.nombre_fichiers}.",
                code=413,
            )

        racines: set[str] = set()
        total_decompresse = 0
        chemins: set[tuple[str, ...]] = set()

        for info in entrees:
            segments = verifier_chemin(info.filename)

            type_entree = _type_entree(info)
            if type_entree == _TYPE_LIEN:
                raise Refus(
                    f"Lien symbolique refusé dans l'archive : {info.filename!r}."
                )
            if type_entree not in (0, _TYPE_FICHIER, _TYPE_DOSSIER):
                raise Refus(
                    f"Entrée d'un type non pris en charge : {info.filename!r}."
                )

            # Deux entrées vers le même chemin : on ne veut pas d'écrasement
            # dépendant de l'ordre de déballage.
            if not info.is_dir():
                if segments in chemins:
                    raise Refus(
                        f"L'archive contient deux fois le chemin {info.filename!r}."
                    )
                chemins.add(segments)

            total_decompresse += info.file_size
            if total_decompresse > limites.taille_decompressee:
                raise Refus(
                    "L'archive dépasse la taille décompressée autorisée "
                    f"({limites.taille_decompressee} octets).",
                    code=413,
                )
            if (
                info.compress_size > 0
                and info.file_size / info.compress_size > limites.ratio_compression
            ):
                raise Refus(
                    f"Taux de compression anormal sur {info.filename!r} : "
                    "archive refusée par précaution."
                )

            racines.add(segments[0])

        if len(racines) != 1:
            raise Refus(
                "L'archive doit contenir un seul dossier racine, le module. "
                f"Trouvé : {sorted(racines)}."
            )

        module = racines.pop()
        if not NOM_MODULE.match(module):
            raise Refus(
                f"Nom de module refusé : {module!r}. Attendu : minuscules, "
                "chiffres et soulignés, de 3 à 64 caractères."
            )
        if module in NOMS_RESERVES:
            raise Refus(f"Le nom de module {module!r} est réservé.")
        if module in set(modules_proteges):
            raise Refus(
                f"Le module {module!r} provient des sources Git de l'instance : "
                "il ne peut pas être remplacé par un envoi."
            )

        if (module, "__manifest__.py") not in {
            (s[0], s[-1]) for s in chemins if len(s) == 2
        }:
            raise Refus(
                f"Le module {module!r} ne contient pas de __manifest__.py à sa racine."
            )

        # Le manifeste doit être un littéral Python : c'est ce qu'Odoo lit,
        # et le valider ici évite un échec d'installation plus coûteux.
        with archive.open(f"{module}/__manifest__.py") as f:
            brut = f.read(256 * 1024)
        verifier_manifeste(brut, module)

    return module


def verifier_manifeste(brut: bytes, module: str) -> dict:
    """Analyse le manifeste et renvoie le dictionnaire qu'il déclare."""
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError:
        raise Refus(f"Le __manifest__.py de {module!r} n'est pas en UTF-8.")
    try:
        declare = ast.literal_eval(texte)
    except (ValueError, SyntaxError):
        raise Refus(
            f"Le __manifest__.py de {module!r} n'est pas un dictionnaire "
            "Python littéral."
        )
    if not isinstance(declare, dict):
        raise Refus(f"Le __manifest__.py de {module!r} ne déclare pas un dictionnaire.")
    if not declare.get("name"):
        raise Refus(f"Le __manifest__.py de {module!r} ne déclare pas de « name ».")
    return declare


def extraire(
    chemin_zip: str,
    destination: str,
    limites: Limites | None = None,
    modules_proteges: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> str:
    """Valide puis extrait l'archive dans `destination`, et renvoie le module.

    L'extraction est faite entrée par entrée à partir des segments déjà
    validés : on n'appelle pas extractall, dont le comportement sur les
    entrées exotiques dépend de la version de Python.
    """
    limites = limites or Limites()
    module = inspecter(chemin_zip, limites, modules_proteges)

    racine = os.path.realpath(destination)
    os.makedirs(racine, exist_ok=True)

    with zipfile.ZipFile(chemin_zip) as archive:
        for info in archive.infolist():
            segments = verifier_chemin(info.filename)
            cible = os.path.join(racine, *segments)

            # Ceinture et bretelles : après assemblage, la cible doit rester
            # sous la racine. Un chemin validé ne peut pas en sortir, mais ce
            # contrôle est le dernier rempart si la validation change un jour.
            if (
                os.path.commonpath([racine, os.path.abspath(cible)]) != racine
            ):  # pragma: no cover - défense en profondeur
                raise Refus(f"Chemin hors du dossier de destination : {info.filename!r}.")

            if info.is_dir():
                os.makedirs(cible, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with archive.open(info) as source, open(cible, "wb") as sortie:
                shutil.copyfileobj(source, sortie, 64 * 1024)
            os.chmod(cible, 0o644)

    # Un lien symbolique n'a pas pu être créé — on n'écrit que des fichiers
    # réguliers — mais on le vérifie plutôt que de le supposer.
    for dossier, _, fichiers in os.walk(racine):
        for nom in fichiers:
            if os.path.islink(os.path.join(dossier, nom)):  # pragma: no cover
                raise Refus("Lien symbolique détecté après extraction.")

    return module


def modules_des_sources(dossier_sources: str) -> frozenset[str]:
    """Noms des modules livrés par Git, qu'un envoi ne doit jamais écraser."""
    if not os.path.isdir(dossier_sources):
        return frozenset()
    trouves = set()
    for nom in os.listdir(dossier_sources):
        if os.path.isfile(os.path.join(dossier_sources, nom, "__manifest__.py")):
            trouves.add(nom)
    return frozenset(trouves)
