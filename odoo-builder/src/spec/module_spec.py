"""Spécification d'un module Odoo.

C'est le contrat entre le modèle et le code classique. Le modèle produit ou
modifie *cette structure* — des éléments métier ; il n'écrit jamais de fichier
Odoo directement. Le rendu, les invariants et l'installation restent au code
déterministe.

La spécification est volontairement pauvre : tout ce qu'elle ne décrit pas ne
peut pas être généré, et c'est préférable à un champ libre que personne ne
sait valider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NOM_TECHNIQUE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
NOM_MODELE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
NOM_CHAMP = re.compile(r"^[a-z][a-z0-9_]*$")

TYPES_CHAMPS = {
    "char", "text", "html", "integer", "float", "monetary", "boolean",
    "date", "datetime", "selection", "many2one", "one2many", "many2many",
    "binary", "image",
}
TYPES_VUES = {"form", "tree", "kanban", "search", "calendar", "pivot", "graph"}


class SpecInvalide(Exception):
    """La spécification ne décrit pas un module réalisable."""


@dataclass
class Champ:
    name: str
    type: str
    string: str
    required: bool = False
    readonly: bool = False
    comodel: str | None = None          # many2one / one2many / many2many
    inverse_name: str | None = None     # one2many
    selection: list[tuple[str, str]] = field(default_factory=list)
    default: object | None = None
    help: str | None = None

    def valider(self, contexte: str) -> None:
        if not NOM_CHAMP.match(self.name):
            raise SpecInvalide(f"{contexte} : nom de champ invalide « {self.name} ».")
        if self.type not in TYPES_CHAMPS:
            raise SpecInvalide(f"{contexte} : type de champ inconnu « {self.type} ».")
        if self.type in ("many2one", "one2many", "many2many") and not self.comodel:
            raise SpecInvalide(
                f"{contexte} : le champ relationnel « {self.name} » n'a pas de comodèle."
            )
        if self.type == "one2many" and not self.inverse_name:
            raise SpecInvalide(
                f"{contexte} : le one2many « {self.name} » n'a pas d'inverse_name."
            )
        if self.type == "selection" and not self.selection:
            raise SpecInvalide(
                f"{contexte} : le champ selection « {self.name} » n'a aucune valeur."
            )


@dataclass
class Modele:
    name: str
    description: str = ""
    inherit: str | None = None          # renseigné => extension d'un modèle existant
    fields: list[Champ] = field(default_factory=list)
    rec_name: str | None = None

    @property
    def est_extension(self) -> bool:
        return bool(self.inherit)

    @property
    def nom_classe(self) -> str:
        return "".join(p.capitalize() for p in self.name.replace(".", "_").split("_"))

    @property
    def nom_fichier(self) -> str:
        return self.name.replace(".", "_")

    def valider(self) -> None:
        if not NOM_MODELE.match(self.name):
            raise SpecInvalide(f"Nom de modèle invalide « {self.name} ».")
        if self.inherit and self.inherit != self.name:
            raise SpecInvalide(
                f"« {self.name} » hérite de « {self.inherit} » : pour étendre un "
                "modèle, inherit doit valoir le même nom que le modèle."
            )
        if not self.est_extension and not self.fields:
            raise SpecInvalide(f"Le modèle « {self.name} » ne déclare aucun champ.")
        vus = set()
        for champ in self.fields:
            if champ.name in vus:
                raise SpecInvalide(f"{self.name} : champ « {champ.name} » en double.")
            vus.add(champ.name)
            champ.valider(self.name)


@dataclass
class Vue:
    model: str
    type: str
    name: str
    fields: list[str] = field(default_factory=list)
    # Champs à garder invisibles : indispensables quand un domaine les référence.
    invisible_fields: list[str] = field(default_factory=list)

    def valider(self) -> None:
        if self.type not in TYPES_VUES:
            raise SpecInvalide(f"Type de vue inconnu « {self.type} » sur {self.model}.")
        if not NOM_MODELE.match(self.model):
            raise SpecInvalide(f"Vue {self.name} : modèle invalide « {self.model} ».")


@dataclass
class Action:
    id: str
    name: str
    model: str
    view_modes: list[str] = field(default_factory=lambda: ["tree", "form"])
    domain: str = "[]"
    context: str = "{}"
    help: str | None = None

    def valider(self) -> None:
        if not NOM_CHAMP.match(self.id):
            raise SpecInvalide(f"Identifiant d'action invalide « {self.id} ».")
        for mode in self.view_modes:
            if mode not in TYPES_VUES:
                raise SpecInvalide(f"Action {self.id} : mode de vue inconnu « {mode} ».")


@dataclass
class Menu:
    id: str
    name: str
    parent: str | None = None
    action: str | None = None
    sequence: int = 10

    def valider(self) -> None:
        if not NOM_CHAMP.match(self.id):
            raise SpecInvalide(f"Identifiant de menu invalide « {self.id} ».")


@dataclass
class Acces:
    model: str
    group: str = "base.group_user"
    perms: str = "rw"          # sous-ensemble de r, w, c, d

    def valider(self) -> None:
        if set(self.perms) - set("rwcd"):
            raise SpecInvalide(f"Droits invalides « {self.perms} » sur {self.model}.")


@dataclass
class ModuleSpec:
    technical_name: str
    name: str
    summary: str = ""
    description: str = ""
    category: str = "Uncategorized"
    version: str = "17.0.1.0.0"
    license: str = "LGPL-3"
    depends: list[str] = field(default_factory=lambda: ["base"])
    application: bool = True
    models: list[Modele] = field(default_factory=list)
    views: list[Vue] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    menus: list[Menu] = field(default_factory=list)
    access: list[Acces] = field(default_factory=list)

    # ------------------------------------------------------------- chargement

    @staticmethod
    def depuis_dict(donnee: dict) -> "ModuleSpec":
        if not isinstance(donnee, dict):
            raise SpecInvalide("La spécification doit être un objet JSON.")

        def champs(liste):
            return [Champ(**c) for c in liste or []]

        try:
            spec = ModuleSpec(
                technical_name=donnee["technical_name"],
                name=donnee["name"],
                summary=donnee.get("summary", ""),
                description=donnee.get("description", ""),
                category=donnee.get("category", "Uncategorized"),
                version=donnee.get("version", "17.0.1.0.0"),
                license=donnee.get("license", "LGPL-3"),
                depends=donnee.get("depends") or ["base"],
                application=donnee.get("application", True),
                models=[
                    Modele(
                        name=m["name"],
                        description=m.get("description", ""),
                        inherit=m.get("inherit"),
                        rec_name=m.get("rec_name"),
                        fields=champs(m.get("fields")),
                    )
                    for m in donnee.get("models", [])
                ],
                views=[Vue(**v) for v in donnee.get("views", [])],
                actions=[Action(**a) for a in donnee.get("actions", [])],
                menus=[Menu(**m) for m in donnee.get("menus", [])],
                access=[Acces(**a) for a in donnee.get("access", [])],
            )
        except KeyError as manquant:
            raise SpecInvalide(f"Clé obligatoire absente : {manquant}.")
        except TypeError as erreur:
            raise SpecInvalide(f"Spécification mal formée : {erreur}.")

        spec.valider()
        return spec

    # -------------------------------------------------------------- contrôles

    def valider(self) -> None:
        if not NOM_TECHNIQUE.match(self.technical_name):
            raise SpecInvalide(
                f"Nom technique invalide « {self.technical_name} » : minuscules, "
                "chiffres et soulignés, de 3 à 64 caractères."
            )
        if not self.name:
            raise SpecInvalide("Le module doit déclarer un nom affichable.")
        if not self.depends:
            raise SpecInvalide("Le module doit déclarer au moins une dépendance.")

        for element in (*self.models, *self.views, *self.actions, *self.menus, *self.access):
            element.valider()

        connus = {m.name for m in self.models}
        for vue in self.views:
            if vue.model not in connus and not self._vient_d_une_dependance(vue.model):
                raise SpecInvalide(
                    f"La vue « {vue.name} » porte sur « {vue.model} », qui n'est ni "
                    "déclaré par le module ni fourni par une dépendance."
                )

        ids_actions = {a.id for a in self.actions}
        for menu in self.menus:
            if menu.action and menu.action not in ids_actions:
                raise SpecInvalide(
                    f"Le menu « {menu.id} » pointe vers l'action « {menu.action} », "
                    "qui n'est pas déclarée."
                )
        ids_menus = {m.id for m in self.menus}
        for menu in self.menus:
            # Un parent peut être externe (hr.menu_hr_root) : on ne contrôle que
            # les références internes, repérables à l'absence de point.
            if menu.parent and "." not in menu.parent and menu.parent not in ids_menus:
                raise SpecInvalide(
                    f"Le menu « {menu.id} » a pour parent « {menu.parent} », inconnu."
                )

    def _vient_d_une_dependance(self, modele: str) -> bool:
        """Un modèle non déclaré est admis s'il appartient à une dépendance.

        On ne peut pas le prouver sans Odoo ; on se contente d'exiger que le
        module l'étende explicitement, ce qui rend l'intention lisible.
        """
        return any(m.name == modele and m.est_extension for m in self.models)

    @property
    def modeles_nouveaux(self) -> list[Modele]:
        return [m for m in self.models if not m.est_extension]
