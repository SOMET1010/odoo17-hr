"""Rendu d'un module Odoo à partir d'une spécification.

Entièrement déterministe : aucune IA n'intervient ici. Le modèle a produit la
spécification ; ce fichier la transforme en arborescence Odoo. C'est la
séparation demandée — le modèle décrit le métier, le code tient les invariants.

Sortie : un dictionnaire {chemin relatif: contenu}, sans écriture disque, pour
rester testable et pour que le packaging décide seul de ce qu'il fait.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from spec.expression import Expression
from spec.module_spec import Modele, ModuleSpec, Vue

ENTETE = "# -*- coding: utf-8 -*-\n"


def _litteral(valeur) -> str:
    """Rend une valeur Python littérale, telle qu'Odoo la lira."""
    if isinstance(valeur, str):
        return repr(valeur)
    if isinstance(valeur, bool):
        return "True" if valeur else "False"
    return repr(valeur)


class OdooModuleGenerator:
    def generate(self, spec: ModuleSpec) -> dict[str, str]:
        fichiers: dict[str, str] = {}
        racine = spec.technical_name

        # Une extension qui n'ajoute aucun champ n'a rien à déclarer : générer
        # une classe vide produirait du code mort et un import inutilisé.
        modeles_ecrits = [
            m for m in spec.models
            if m.tous_les_champs or m.constraints or not m.est_extension
        ]
        if modeles_ecrits:
            fichiers[f"{racine}/__init__.py"] = "from . import models\n"
            fichiers[f"{racine}/models/__init__.py"] = "".join(
                f"from . import {m.nom_fichier}\n" for m in modeles_ecrits
            )
            for modele in modeles_ecrits:
                fichiers[f"{racine}/models/{modele.nom_fichier}.py"] = self._modele(modele)
        else:
            fichiers[f"{racine}/__init__.py"] = ""

        données: list[str] = []

        vues_par_modele: dict[str, list[Vue]] = {}
        for vue in spec.views:
            vues_par_modele.setdefault(vue.model, []).append(vue)
        for modele, vues in vues_par_modele.items():
            nom = modele.replace(".", "_")
            chemin = f"views/{nom}_views.xml"
            actions = [a for a in spec.actions if a.model == modele]
            fichiers[f"{racine}/{chemin}"] = self._vues(spec, vues, actions)
            données.append(chemin)

        # Les actions d'un modèle sans vue déclarée doivent tout de même exister.
        orphelines = [a for a in spec.actions if a.model not in vues_par_modele]
        if orphelines:
            fichiers[f"{racine}/views/actions.xml"] = self._vues(spec, [], orphelines)
            données.append("views/actions.xml")

        if spec.menus:
            fichiers[f"{racine}/views/menus.xml"] = self._menus(spec)
            données.append("views/menus.xml")

        if spec.access:
            fichiers[f"{racine}/security/ir.model.access.csv"] = self._acces(spec)
            données.insert(0, "security/ir.model.access.csv")

        fichiers[f"{racine}/__manifest__.py"] = self._manifeste(spec, données)
        return fichiers

    # ------------------------------------------------------------- manifeste

    def _manifeste(self, spec: ModuleSpec, données: list[str]) -> str:
        lignes = [
            ENTETE,
            "{\n",
            f"    'name': {_litteral(spec.name)},\n",
            f"    'version': {_litteral(spec.version)},\n",
            f"    'category': {_litteral(spec.category)},\n",
            f"    'summary': {_litteral(spec.summary)},\n",
        ]
        if spec.description:
            lignes.append(f"    'description': {_litteral(spec.description)},\n")
        lignes += [
            f"    'depends': {_litteral(spec.depends)},\n",
            f"    'data': {_litteral(données)},\n",
            f"    'application': {_litteral(spec.application)},\n",
            "    'installable': True,\n",
            f"    'license': {_litteral(spec.license)},\n",
            "}\n",
        ]
        return "".join(lignes)

    # ---------------------------------------------------------------- modèles

    def _modele(self, modele: Modele) -> str:
        champs = modele.tous_les_champs
        calcules = [c for c in modele.fields if c.est_calcule]
        cycle = modele.lifecycle

        besoins = ["models"]
        if champs:
            besoins.insert(0, "fields")
        if calcules or modele.constraints:
            besoins.insert(0, "api")
        lignes = [ENTETE, f"\nfrom odoo import {', '.join(besoins)}\n"]
        if modele.constraints or (cycle and cycle.transitions):
            lignes.append("from odoo.exceptions import UserError, ValidationError\n")
        lignes.append("\n\n")
        lignes.append(f"class {modele.nom_classe}(models.Model):\n")
        if modele.est_extension:
            lignes.append(f"    _inherit = {_litteral(modele.inherit)}\n")
        else:
            lignes.append(f"    _name = {_litteral(modele.name)}\n")
            lignes.append(
                f"    _description = {_litteral(modele.description or modele.name)}\n"
            )
            if modele.rec_name:
                lignes.append(f"    _rec_name = {_litteral(modele.rec_name)}\n")
        lignes.append("\n")

        if not champs:
            lignes.append("    pass\n")
            return "".join(lignes)

        for champ in champs:
            lignes.append(f"    {champ.name} = {self._definition_champ(champ)}\n")

        for champ in calcules:
            lignes.append(self._methode_calcul(champ))
        for contrainte in modele.constraints:
            lignes.append(self._methode_contrainte(contrainte))
        if cycle:
            for transition in cycle.transitions:
                lignes.append(self._methode_transition(cycle, transition))

        return "".join(lignes)

    # ------------------------------------------------------------ comportement

    def _methode_calcul(self, champ) -> str:
        """@api.depends + boucle sur self, comme l'exige Odoo."""
        expression = champ.compute.compiler("enreg").en_python()
        depends = ", ".join(_litteral(d) for d in sorted(champ.compute.depends))
        return (
            f"\n    @api.depends({depends})\n"
            f"    def _compute_{champ.name}(self):\n"
            f"        for enreg in self:\n"
            f"            enreg.{champ.name} = {expression}\n"
        )

    def _methode_contrainte(self, contrainte) -> str:
        """La condition décrit l'état VALIDE : on lève quand elle est fausse."""
        expression = contrainte.compiler("enreg").en_python()
        depends = ", ".join(_litteral(d) for d in sorted(contrainte.depends))
        return (
            f"\n    @api.constrains({depends})\n"
            f"    def _check_{contrainte.name}(self):\n"
            f"        for enreg in self:\n"
            f"            if not {expression}:\n"
            f"                raise ValidationError({_litteral(contrainte.message)})\n"
        )

    def _methode_transition(self, cycle, transition) -> str:
        """Une transition devient une méthode : contrôles, puis changement d'état.

        Les contrôles sont générés depuis la spécification — l'état de départ,
        le groupe autorisé, les validations — jamais fournis en Python.
        """
        lignes = [
            f"\n    def action_{transition.name}(self):\n",
            f"        \"\"\"{transition.label}\"\"\"\n",
            "        for enreg in self:\n",
        ]
        depart = ", ".join(_litteral(e) for e in transition.from_states)
        lignes.append(f"            if enreg.{cycle.field_name} not in ({depart},):\n")
        lignes.append(
            f"                raise UserError({_litteral(transition.label)} + "
            f"\" : opération impossible depuis l'état courant.\")\n"
        )
        for groupe in transition.allowed_groups:
            lignes.append(f"            if not self.env.user.has_group({_litteral(groupe)}):\n")
            lignes.append(
                f"                raise UserError({_litteral(transition.label)} + "
                "\" : vous n'avez pas les droits nécessaires.\")\n"
            )
        for validation in transition.validations:
            condition = Expression(validation["condition"], "enreg").en_python()
            lignes.append(f"            if not {condition}:\n")
            lignes.append(
                f"                raise UserError({_litteral(validation['message'])})\n"
            )
        lignes.append(
            f"            enreg.{cycle.field_name} = {_litteral(transition.to_state)}\n"
        )
        lignes.append("        return True\n")
        return "".join(lignes)

    def _definition_champ(self, champ) -> str:
        arguments = [f"string={_litteral(champ.string)}"]
        constructeur = {
            "char": "Char", "text": "Text", "html": "Html", "integer": "Integer",
            "float": "Float", "monetary": "Monetary", "boolean": "Boolean",
            "date": "Date", "datetime": "Datetime", "selection": "Selection",
            "many2one": "Many2one", "one2many": "One2many", "many2many": "Many2many",
            "binary": "Binary", "image": "Image",
        }[champ.type]

        if champ.type in ("many2one", "many2many"):
            arguments.insert(0, f"comodel_name={_litteral(champ.comodel)}")
        elif champ.type == "one2many":
            arguments.insert(0, f"comodel_name={_litteral(champ.comodel)}")
            arguments.insert(1, f"inverse_name={_litteral(champ.inverse_name)}")
        elif champ.type == "selection":
            valeurs = "[" + ", ".join(
                f"({_litteral(v)}, {_litteral(l)})" for v, l in champ.selection
            ) + "]"
            arguments.insert(0, f"selection={valeurs}")

        if champ.est_calcule:
            # Odoo relie le champ à sa méthode par ce nom ; le stockage décide
            # si la valeur est persistée ou recalculée à la lecture.
            arguments.append(f"compute='_compute_{champ.name}'")
            arguments.append(f"store={_litteral(champ.compute.store)}")
        if champ.required:
            arguments.append("required=True")
        if champ.readonly:
            arguments.append("readonly=True")
        if champ.default is not None:
            arguments.append(f"default={_litteral(champ.default)}")
        if champ.help:
            arguments.append(f"help={_litteral(champ.help)}")

        return f"fields.{constructeur}({', '.join(arguments)})"

    # ------------------------------------------------------------------ vues

    def _identifiant_vue(self, vue: Vue) -> str:
        return f"view_{vue.model.replace('.', '_')}_{vue.type}"

    def _vues(self, spec: ModuleSpec, vues: list[Vue], actions: list) -> str:
        blocs = ["<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n"]

        for vue in vues:
            identifiant = self._identifiant_vue(vue)
            blocs.append(f'    <record id={quoteattr(identifiant)} model="ir.ui.view">\n')
            blocs.append(f'        <field name="name">{escape(vue.name)}</field>\n')
            blocs.append(f'        <field name="model">{escape(vue.model)}</field>\n')
            blocs.append('        <field name="arch" type="xml">\n')
            modele_lie = next((m for m in spec.models if m.name == vue.model), None)
            blocs.append(self._arch(vue, modele_lie))
            blocs.append("        </field>\n    </record>\n\n")

        for action in actions:
            blocs.append(f'    <record id={quoteattr(action.id)} model="ir.actions.act_window">\n')
            blocs.append(f'        <field name="name">{escape(action.name)}</field>\n')
            blocs.append(f'        <field name="res_model">{escape(action.model)}</field>\n')
            blocs.append(
                f'        <field name="view_mode">{escape(",".join(action.view_modes))}</field>\n'
            )
            blocs.append(f'        <field name="domain">{escape(action.domain)}</field>\n')
            blocs.append(f'        <field name="context">{escape(action.context)}</field>\n')
            if action.help:
                blocs.append(
                    f'        <field name="help" type="html"><p>{escape(action.help)}</p></field>\n'
                )
            blocs.append("    </record>\n\n")

        blocs.append("</odoo>\n")
        return "".join(blocs)

    def _arch(self, vue: Vue, modele=None) -> str:
        marge = " " * 12
        champs = "".join(
            f'{marge}    <field name={quoteattr(nom)}/>\n' for nom in vue.fields
        )
        # Les champs invisibles existent pour satisfaire les domaines : Odoo 17
        # refuse de charger une vue dont un domaine référence un champ absent.
        # C'est exactement ce qui a fait échouer l'installation de
        # diligence_simple, sur le formulaire puis sur la liste.
        attribut = "column_invisible" if vue.type == "tree" else "invisible"
        champs += "".join(
            f'{marge}    <field name={quoteattr(nom)} {attribut}="1"/>\n'
            for nom in vue.invisible_fields
        )

        if vue.type == "form":
            # Le cycle de vie se rend de lui-même : une barre d'état, et un
            # bouton par transition. Rien de tout cela n'est saisi à la main —
            # c'est la spécification du workflow qui le produit.
            entete = ""
            cycle = modele.lifecycle if modele else None
            if cycle and cycle.states:
                boutons = "".join(
                    f'{marge}        <button name={quoteattr("action_" + t.name)} '
                    f'string={quoteattr(t.label)} type="object" '
                    f'invisible={quoteattr(f"{cycle.field_name} not in {list(t.from_states)}")} '
                    f'class="btn-primary"/>\n'
                    for t in cycle.transitions
                )
                etats = ",".join(e.value for e in cycle.states if not e.is_final)
                entete = (
                    f"{marge}    <header>\n{boutons}"
                    f'{marge}        <field name={quoteattr(cycle.field_name)} '
                    f'widget="statusbar" statusbar_visible={quoteattr(etats)}/>\n'
                    f"{marge}    </header>\n"
                )
            return (
                f"{marge}<form>\n{entete}{marge}    <sheet>\n{marge}        <group>\n"
                + champs.replace(marge + "    ", marge + "            ")
                + f"{marge}        </group>\n{marge}    </sheet>\n{marge}</form>\n"
            )
        if vue.type == "kanban":
            return (
                f"{marge}<kanban>\n" + champs
                + f"{marge}    <templates>\n"
                f'{marge}        <t t-name="kanban-box">\n'
                f'{marge}            <div class="oe_kanban_global_click">\n'
                f'{marge}                <field name={quoteattr(vue.fields[0] if vue.fields else "display_name")}/>\n'
                f"{marge}            </div>\n{marge}        </t>\n"
                f"{marge}    </templates>\n{marge}</kanban>\n"
            )
        if vue.type == "search":
            return f"{marge}<search>\n{champs}{marge}</search>\n"
        balise = {"tree": "tree", "calendar": "calendar", "pivot": "pivot", "graph": "graph"}[vue.type]
        supplement = ""
        if vue.type == "calendar" and vue.fields:
            supplement = f' date_start={quoteattr(vue.fields[-1])}'
        return f"{marge}<{balise}{supplement}>\n{champs}{marge}</{balise}>\n"

    # ----------------------------------------------------------------- menus

    def _menus(self, spec: ModuleSpec) -> str:
        blocs = ["<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n"]
        for menu in spec.menus:
            attributs = [f"id={quoteattr(menu.id)}", f"name={quoteattr(menu.name)}"]
            if menu.parent:
                attributs.append(f"parent={quoteattr(menu.parent)}")
            if menu.action:
                attributs.append(f"action={quoteattr(menu.action)}")
            attributs.append(f'sequence="{menu.sequence}"')
            blocs.append(f"    <menuitem {' '.join(attributs)}/>\n")
        blocs.append("</odoo>\n")
        return "".join(blocs)

    # ---------------------------------------------------------------- droits

    def _acces(self, spec: ModuleSpec) -> str:
        lignes = ["id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"]
        for acces in spec.access:
            cle = acces.model.replace(".", "_")
            groupe = acces.group
            lignes.append(
                f"access_{cle}_{groupe.split('.')[-1]},"
                f"access.{acces.model},"
                f"model_{cle},"
                f"{groupe},"
                f"{int('r' in acces.perms)},{int('w' in acces.perms)},"
                f"{int('c' in acces.perms)},{int('d' in acces.perms)}\n"
            )
        return "".join(lignes)
