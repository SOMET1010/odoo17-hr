"""Recette du Odoo Builder, sans Odoo ni réseau.

L'installation réelle est prouvée ailleurs (étape 8 de verifier-runtime.sh).
Ici on éprouve la partie déterministe : ce que le code garantit quel que soit
le modèle qui a produit la spécification.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from ai.provider import ScriptedProvider  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import empaqueter  # noqa: E402
from repair.repair_loop import RepairLoop, _en_dict  # noqa: E402
from spec.module_spec import ModuleSpec, SpecInvalide  # noqa: E402
from validator.odoo_static_validator import OdooStaticValidator  # noqa: E402

MINIMAL = {
    "technical_name": "mon_module",
    "name": "Mon module",
    "depends": ["base"],
    "models": [
        {
            "name": "mon.objet",
            "description": "Objet",
            "fields": [
                {"name": "name", "type": "char", "string": "Nom", "required": True},
                {"name": "etat", "type": "selection", "string": "État",
                 "selection": [["brouillon", "Brouillon"], ["fait", "Fait"]]},
            ],
        }
    ],
    "views": [
        {"model": "mon.objet", "type": "tree", "name": "Objets", "fields": ["name", "etat"]}
    ],
    "actions": [
        {"id": "action_objet", "name": "Objets", "model": "mon.objet"}
    ],
    "menus": [
        {"id": "menu_racine", "name": "Mon module"},
        {"id": "menu_objet", "name": "Objets", "parent": "menu_racine", "action": "action_objet"},
    ],
    "access": [{"model": "mon.objet", "group": "base.group_user", "perms": "rwcd"}],
}


def spec(**remplacements) -> ModuleSpec:
    donnee = json.loads(json.dumps(MINIMAL))
    donnee.update(remplacements)
    return ModuleSpec.depuis_dict(donnee)


class TestSpecification(unittest.TestCase):
    def test_specification_minimale_acceptee(self):
        self.assertEqual(spec().technical_name, "mon_module")

    def test_nom_technique_refuse(self):
        with self.assertRaises(SpecInvalide):
            spec(technical_name="Mon-Module")

    def test_relation_sans_comodele_refusee(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec(models=[{"name": "mon.objet", "fields": [
                {"name": "partenaire", "type": "many2one", "string": "Partenaire"}]}])
        self.assertIn("comodèle", str(capture.exception))

    def test_menu_vers_action_inexistante_refuse(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec(menus=[{"id": "menu_x", "name": "X", "action": "action_fantome"}])
        self.assertIn("action_fantome", str(capture.exception))

    def test_vue_sur_modele_inconnu_refusee(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec(views=[{"model": "res.partner", "type": "tree", "name": "P", "fields": ["name"]}])
        self.assertIn("res.partner", str(capture.exception))

    def test_parent_de_menu_externe_accepte(self):
        # hr.menu_hr_root appartient au coeur d'Odoo : la référence est légitime.
        module = spec(menus=[
            {"id": "menu_greffe", "name": "Greffé", "parent": "hr.menu_hr_root"}
        ])
        self.assertEqual(module.menus[0].parent, "hr.menu_hr_root")


class TestGenerateur(unittest.TestCase):
    def setUp(self):
        self.generateur = OdooModuleGenerator()

    def test_arborescence_attendue(self):
        fichiers = self.generateur.generate(spec())
        for attendu in (
            "mon_module/__manifest__.py",
            "mon_module/__init__.py",
            "mon_module/models/mon_objet.py",
            "mon_module/views/mon_objet_views.xml",
            "mon_module/views/menus.xml",
            "mon_module/security/ir.model.access.csv",
        ):
            self.assertIn(attendu, fichiers)

    def test_manifeste_est_un_litteral(self):
        import ast
        fichiers = self.generateur.generate(spec())
        brut = fichiers["mon_module/__manifest__.py"]
        sans_commentaire = "\n".join(
            l for l in brut.splitlines() if not l.strip().startswith("#")
        )
        declare = ast.literal_eval(sans_commentaire)
        self.assertEqual(declare["name"], "Mon module")
        self.assertIn("security/ir.model.access.csv", declare["data"])

    def test_extension_sans_champ_ne_produit_pas_de_classe_vide(self):
        fichiers = self.generateur.generate(spec(
            models=[{"name": "project.task", "inherit": "project.task"}],
            views=[{"model": "project.task", "type": "tree", "name": "T", "fields": ["name"]}],
            access=[],
        ))
        self.assertNotIn("mon_module/models/project_task.py", fichiers)

    def test_champ_selection_rendu(self):
        code = self.generateur.generate(spec())["mon_module/models/mon_objet.py"]
        self.assertIn("fields.Selection(", code)
        self.assertIn("'brouillon'", code)

    def test_champs_invisibles_selon_le_type_de_vue(self):
        fichiers = self.generateur.generate(spec(views=[
            {"model": "mon.objet", "type": "tree", "name": "L",
             "fields": ["name"], "invisible_fields": ["etat"]},
            {"model": "mon.objet", "type": "form", "name": "F",
             "fields": ["name"], "invisible_fields": ["etat"]},
        ]))
        xml = fichiers["mon_module/views/mon_objet_views.xml"]
        # Odoo 17 distingue les deux attributs : column_invisible en liste.
        self.assertIn('<field name="etat" column_invisible="1"/>', xml)
        self.assertIn('<field name="etat" invisible="1"/>', xml)

    def test_apostrophe_dans_un_libelle_ne_casse_pas_le_xml(self):
        from xml.etree import ElementTree
        fichiers = self.generateur.generate(spec(menus=[
            {"id": "menu_racine", "name": "Aujourd'hui & demain <test>"}
        ]))
        ElementTree.fromstring(fichiers["mon_module/views/menus.xml"])


class TestValidateur(unittest.TestCase):
    def setUp(self):
        self.generateur = OdooModuleGenerator()
        self.validateur = OdooStaticValidator()

    def test_module_genere_est_valide(self):
        module = spec()
        rapport = self.validateur.check(self.generateur.generate(module), module)
        self.assertTrue(rapport.ok, rapport.texte())

    def test_domaine_referencant_un_champ_absent_est_signale(self):
        """C'est le défaut exact qui a empêché diligence_simple de s'installer."""
        module = spec()
        fichiers = self.generateur.generate(module)
        fichiers["mon_module/views/mon_objet_views.xml"] = (
            "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n"
            '  <record id="v" model="ir.ui.view">\n'
            '    <field name="model">mon.objet</field>\n'
            '    <field name="arch" type="xml">\n'
            "      <form>\n"
            '        <field name="name" domain="[(\'company_id\', \'=\', company_id)]"/>\n'
            "      </form>\n"
            "    </field>\n  </record>\n</odoo>\n"
        )
        rapport = self.validateur.check(fichiers, module)
        self.assertFalse(rapport.ok)
        self.assertTrue(
            any("company_id" in str(a) for a in rapport.anomalies), rapport.texte()
        )

    def test_modele_sans_droit_acces_est_signale(self):
        module = spec(access=[])
        rapport = self.validateur.check(self.generateur.generate(module), module)
        self.assertTrue(any("droit d'accès" in str(a) for a in rapport.anomalies))

    def test_champ_inconnu_dans_une_vue_est_signale(self):
        module = spec(views=[
            {"model": "mon.objet", "type": "tree", "name": "L", "fields": ["name", "fantome"]}
        ])
        rapport = self.validateur.check(self.generateur.generate(module), module)
        self.assertTrue(any("fantome" in str(a) for a in rapport.anomalies))

    def test_python_invalide_est_signale(self):
        module = spec()
        fichiers = self.generateur.generate(module)
        fichiers["mon_module/models/mon_objet.py"] = "class Cassé(\n"
        rapport = self.validateur.check(fichiers, module)
        self.assertTrue(any("Python invalide" in str(a) for a in rapport.anomalies))

    def test_fichier_non_declare_dans_data_est_signale(self):
        module = spec()
        fichiers = self.generateur.generate(module)
        fichiers["mon_module/views/oublie.xml"] = "<odoo/>\n"
        rapport = self.validateur.check(fichiers, module)
        self.assertTrue(any("jamais chargé" in str(a) for a in rapport.anomalies))


class TestArchive(unittest.TestCase):
    def test_archive_a_un_seul_dossier_racine(self):
        """Le service d'installation refuse toute archive à plusieurs racines."""
        octets = empaqueter(OdooModuleGenerator().generate(spec()))
        import io
        with zipfile.ZipFile(io.BytesIO(octets)) as archive:
            racines = {n.split("/")[0] for n in archive.namelist()}
            self.assertEqual(racines, {"mon_module"})
            self.assertIn("mon_module/__manifest__.py", archive.namelist())


class TestBoucleDeReparation(unittest.TestCase):
    def setUp(self):
        self.generateur = OdooModuleGenerator()
        self.validateur = OdooStaticValidator()

    def test_sans_installateur_la_validation_suffit(self):
        boucle = RepairLoop(self.generateur, self.validateur, None, None)
        issue = boucle.executer(spec())
        self.assertTrue(issue.reussi)
        self.assertEqual(len(issue.tentatives), 1)

    def test_sans_fournisseur_aucune_reparation_n_est_tentee(self):
        boucle = RepairLoop(self.generateur, self.validateur, None, None)
        issue = boucle.executer(spec(access=[]))
        self.assertFalse(issue.reussi)
        self.assertIn("Aucun fournisseur", issue.diagnostic)
        self.assertEqual(len(issue.tentatives), 1)

    def test_le_modele_repare_la_specification_et_la_boucle_aboutit(self):
        # Départ fautif : aucun droit d'accès. Le modèle rend la version corrigée.
        corrigee = _en_dict(spec())
        fournisseur = ScriptedProvider([corrigee])
        boucle = RepairLoop(self.generateur, self.validateur, None, fournisseur)
        issue = boucle.executer(spec(access=[]))
        self.assertTrue(issue.reussi, issue.texte())
        self.assertEqual(len(issue.tentatives), 2)
        self.assertTrue(issue.tentatives[0].reparation_demandee)

    def test_la_boucle_s_arrete_au_plafond(self):
        # Le modèle rend obstinément la même spécification fautive.
        fautive = _en_dict(spec(access=[]))
        fournisseur = ScriptedProvider([fautive, fautive, fautive])
        boucle = RepairLoop(self.generateur, self.validateur, None, fournisseur, tentatives_max=3)
        issue = boucle.executer(spec(access=[]))
        self.assertFalse(issue.reussi)
        self.assertEqual(len(issue.tentatives), 3)
        self.assertIn("Abandon après 3 tentatives", issue.diagnostic)

    def test_le_modele_ne_recoit_que_les_fichiers_concernes(self):
        fournisseur = ScriptedProvider([_en_dict(spec())])
        boucle = RepairLoop(self.generateur, self.validateur, None, fournisseur)
        boucle.executer(spec(access=[]))
        _, contexte = fournisseur.appels[0]
        # L'erreur porte sur le CSV des droits : le modèle ne doit pas recevoir
        # les vues ni les modèles du projet entier.
        self.assertIn("ir.model.access.csv", contexte)
        self.assertNotIn("mon_objet_views.xml", contexte)


class TestSerialisation(unittest.TestCase):
    def test_aller_retour_sans_perte(self):
        depart = spec()
        arrivee = ModuleSpec.depuis_dict(_en_dict(depart))
        self.assertEqual(_en_dict(depart), _en_dict(arrivee))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- comportement

from spec.behavior import ComportementInvalide  # noqa: E402
from spec.expression import Expression, ExpressionInvalide  # noqa: E402

AVEC_COMPORTEMENT = {
    "technical_name": "avec_comportement",
    "name": "Avec comportement",
    "depends": ["base"],
    "models": [{
        "name": "essai.demande",
        "description": "Demande",
        "fields": [
            {"name": "name", "type": "char", "string": "Objet", "required": True},
            {"name": "currency_id", "type": "many2one", "string": "Devise",
             "comodel": "res.currency"},
            {"name": "line_ids", "type": "one2many", "string": "Lignes",
             "comodel": "essai.ligne", "inverse_name": "demande_id"},
            {"name": "total", "type": "monetary", "string": "Total",
             "compute": {"expression": "sum(line_ids.amount)",
                         "depends": ["line_ids.amount"], "store": True}},
        ],
        "constraints": [{"name": "total_positif", "condition": "total >= 0",
                         "message": "Le total ne peut pas être négatif.",
                         "depends": ["total"]}],
        "lifecycle": {
            "states": [{"value": "draft", "label": "Brouillon", "is_initial": True},
                       {"value": "done", "label": "Terminé", "is_final": True}],
            "transitions": [{"name": "valider", "label": "Valider",
                             "from_states": ["draft"], "to_state": "done",
                             "validations": [{"condition": "total > 0",
                                              "message": "Total nul."}]}],
        },
    }],
    "views": [{"model": "essai.demande", "type": "form", "name": "Demande",
               "fields": ["name", "total"]}],
    "actions": [], "menus": [],
    "access": [{"model": "essai.demande", "group": "base.group_user", "perms": "rwcd"}],
}


def spec_comportement(**modifs):
    donnee = json.loads(json.dumps(AVEC_COMPORTEMENT))
    donnee.update(modifs)
    return ModuleSpec.depuis_dict(donnee)


class TestExpression(unittest.TestCase):
    def test_agregat_traduit_en_mapped(self):
        self.assertEqual(
            Expression("sum(line_ids.amount)").en_python(),
            "sum(enreg.line_ids.mapped('amount'))",
        )

    def test_comparaison_traduite(self):
        self.assertEqual(Expression("amount > 0").en_python(), "(enreg.amount > 0)")

    def test_chemins_excluent_les_noms_de_fonctions(self):
        self.assertEqual(Expression("abs(total - paid)").chemins(), {"total", "paid"})

    def test_code_arbitraire_refuse(self):
        for mauvais in ["__import__('os').system('id')", "[x for x in y]",
                        "open('/etc/passwd')", "eval('1')"]:
            with self.assertRaises(ExpressionInvalide, msg=mauvais):
                Expression(mauvais)


class TestComportement(unittest.TestCase):
    def test_depends_incomplet_refuse(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec_comportement(models=[{
                **AVEC_COMPORTEMENT["models"][0],
                "fields": [
                    {"name": "a", "type": "float", "string": "A"},
                    {"name": "b", "type": "float", "string": "B"},
                    {"name": "t", "type": "float", "string": "T",
                     "compute": {"expression": "a + b", "depends": ["a"]}},
                ],
                "constraints": [], "lifecycle": None,
            }])
        self.assertIn("depends", str(capture.exception))

    def test_champ_calcule_et_obligatoire_refuse(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec_comportement(models=[{
                "name": "essai.demande", "description": "D",
                "fields": [
                    {"name": "a", "type": "float", "string": "A"},
                    {"name": "t", "type": "float", "string": "T", "required": True,
                     "compute": {"expression": "a", "depends": ["a"]}},
                ],
            }])
        self.assertIn("calculé et obligatoire", str(capture.exception))

    def test_transition_vers_etat_inconnu_refusee(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec_comportement(models=[{
                **AVEC_COMPORTEMENT["models"][0],
                "lifecycle": {
                    "states": [{"value": "draft", "label": "B", "is_initial": True}],
                    "transitions": [{"name": "v", "label": "V",
                                     "from_states": ["draft"], "to_state": "fantome"}],
                },
            }])
        self.assertIn("fantome", str(capture.exception))

    def test_etat_cul_de_sac_refuse(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec_comportement(models=[{
                **AVEC_COMPORTEMENT["models"][0],
                "lifecycle": {
                    "states": [{"value": "draft", "label": "B", "is_initial": True},
                               {"value": "perdu", "label": "Perdu"}],
                    "transitions": [],
                },
            }])
        self.assertIn("perdu", str(capture.exception))

    def test_monetaire_sans_devise_refuse(self):
        with self.assertRaises(SpecInvalide) as capture:
            spec_comportement(models=[{
                "name": "essai.demande", "description": "D",
                "fields": [{"name": "m", "type": "monetary", "string": "M"}],
            }])
        self.assertIn("currency_id", str(capture.exception))


class TestGenerationComportement(unittest.TestCase):
    def setUp(self):
        self.fichiers = OdooModuleGenerator().generate(spec_comportement())
        self.code = self.fichiers["avec_comportement/models/essai_demande.py"]

    def test_le_python_genere_compile(self):
        import ast
        ast.parse(self.code)

    def test_champ_calcule_rendu(self):
        self.assertIn("@api.depends('line_ids.amount')", self.code)
        self.assertIn("def _compute_total(self):", self.code)
        self.assertIn("enreg.total = sum(enreg.line_ids.mapped('amount'))", self.code)
        self.assertIn("compute='_compute_total'", self.code)

    def test_contrainte_rendue(self):
        self.assertIn("@api.constrains('total')", self.code)
        self.assertIn("raise ValidationError", self.code)

    def test_transition_rendue_avec_ses_gardes(self):
        self.assertIn("def action_valider(self):", self.code)
        self.assertIn("if enreg.state not in ('draft',):", self.code)
        self.assertIn("raise UserError('Total nul.')", self.code)
        self.assertIn("enreg.state = 'done'", self.code)

    def test_champ_etat_derive_du_cycle_de_vie(self):
        self.assertIn("state = fields.Selection(", self.code)
        self.assertIn("default='draft'", self.code)

    def test_formulaire_porte_la_barre_et_les_boutons(self):
        xml = self.fichiers["avec_comportement/views/essai_demande_views.xml"]
        self.assertIn('widget="statusbar"', xml)
        self.assertIn('name="action_valider"', xml)

    def test_module_genere_est_valide(self):
        module = spec_comportement()
        rapport = OdooStaticValidator().check(
            OdooModuleGenerator().generate(module), module
        )
        self.assertTrue(rapport.ok, rapport.texte())

    def test_le_comportement_survit_a_la_serialisation(self):
        """Une réparation ne doit pas effacer calculs, contraintes et workflow."""
        depart = spec_comportement()
        arrivee = ModuleSpec.depuis_dict(_en_dict(depart))
        self.assertEqual(_en_dict(depart), _en_dict(arrivee))
        modele = _en_dict(arrivee)["models"][0]
        self.assertTrue(any("compute" in c for c in modele["fields"]))
        self.assertTrue(modele["constraints"])
        self.assertTrue(modele["lifecycle"]["transitions"])


# --------------------------------------------------- besoin -> spécification

from spec.drafter import RedactionImpossible, SpecDrafter  # noqa: E402


class TestRedaction(unittest.TestCase):
    """Le modèle ne produit qu'une ModuleSpec, et elle passe les mêmes contrôles."""

    def test_specification_valide_du_premier_coup(self):
        fournisseur = ScriptedProvider([json.loads(json.dumps(MINIMAL))])
        spec_rendue = SpecDrafter(fournisseur).draft("un module d'objets")
        self.assertEqual(spec_rendue.technical_name, "mon_module")
        # Le besoin est bien transmis au modèle.
        _, contexte = fournisseur.appels[0]
        self.assertIn("un module d'objets", contexte)

    def test_specification_refusee_puis_corrigee(self):
        fautive = json.loads(json.dumps(MINIMAL))
        fautive["access"] = []          # modèle sans droit d'accès
        fautive["models"][0]["fields"].append(
            {"name": "montant", "type": "monetary", "string": "Montant"}
        )                                # monétaire sans currency_id
        fournisseur = ScriptedProvider([fautive, json.loads(json.dumps(MINIMAL))])
        spec_rendue = SpecDrafter(fournisseur).draft("des objets avec un montant")
        self.assertEqual(spec_rendue.technical_name, "mon_module")
        # La deuxième demande doit porter le motif du refus.
        _, contexte = fournisseur.appels[1]
        self.assertIn("MOTIF DU REFUS", contexte)
        self.assertIn("currency_id", contexte)

    def test_abandon_apres_le_plafond(self):
        fautive = json.loads(json.dumps(MINIMAL))
        fautive["technical_name"] = "Nom-Invalide"
        fournisseur = ScriptedProvider([fautive, fautive, fautive])
        with self.assertRaises(RedactionImpossible) as capture:
            SpecDrafter(fournisseur, tentatives_max=3).draft("peu importe")
        self.assertIn("3 tentatives", str(capture.exception))
        self.assertEqual(len(fournisseur.appels), 3)

    def test_le_modele_ne_peut_pas_injecter_de_code(self):
        """Le point qui rend la séparation intéressante.

        Même si le modèle tente de glisser du Python dans une expression, la
        spécification est refusée avant toute génération : rien n'atteint Odoo.
        """
        hostile = json.loads(json.dumps(MINIMAL))
        hostile["models"][0]["fields"].append({
            "name": "piege", "type": "float", "string": "Piège",
            "compute": {"expression": "__import__('os').system('id')",
                        "depends": []},
        })
        fournisseur = ScriptedProvider([hostile, hostile, hostile])
        with self.assertRaises(RedactionImpossible):
            SpecDrafter(fournisseur, tentatives_max=3).draft("un module piégé")

    def test_du_python_rendu_a_la_place_du_json_est_refuse(self):
        fournisseur = ScriptedProvider([
            {"code": "class Foo(models.Model): _name = 'foo'"},
        ])
        with self.assertRaises(RedactionImpossible):
            SpecDrafter(fournisseur, tentatives_max=1).draft("un module")

    def test_la_chaine_complete_depuis_un_besoin(self):
        """besoin → spécification → génération → validation, sans Odoo."""
        fournisseur = ScriptedProvider([json.loads(json.dumps(AVEC_COMPORTEMENT))])
        spec_rendue = SpecDrafter(fournisseur).draft(
            "des demandes avec des lignes, un total calculé et un workflow"
        )
        fichiers = OdooModuleGenerator().generate(spec_rendue)
        rapport = OdooStaticValidator().check(fichiers, spec_rendue)
        self.assertTrue(rapport.ok, rapport.texte())
        code = fichiers["avec_comportement/models/essai_demande.py"]
        self.assertIn("@api.depends('line_ids.amount')", code)
        self.assertIn("def action_valider(self):", code)
