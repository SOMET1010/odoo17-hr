"""Recette du Odoo Builder, sans Odoo ni réseau.

L'installation réelle est prouvée ailleurs (étape 8 de verifier-runtime.sh).
Ici on éprouve la partie déterministe : ce que le code garantit quel que soit
le modèle qui a produit la spécification.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))

from ai.provider import ScriptedProvider  # noqa: E402
from generator.odoo_module_generator import OdooModuleGenerator  # noqa: E402
from installer.odoo_install_client import empaqueter  # noqa: E402
from repair.repair_loop import RepairLoop, _en_dict  # noqa: E402
from spec.module_spec import Champ, ModuleSpec, SpecInvalide  # noqa: E402
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
    }, {
        # Le modèle porteur de « line_ids ». Il manquait : le jeu d'essai
        # décrivait une relation vers un modèle que personne ne créait, ce
        # qu'Odoo aurait refusé. Aucun test ne pouvait le dire tant que la
        # validation ignorait les relations.
        "name": "essai.ligne",
        "description": "Ligne",
        "fields": [
            {"name": "name", "type": "char", "string": "Libellé", "required": True},
            {"name": "amount", "type": "float", "string": "Montant"},
            {"name": "demande_id", "type": "many2one", "string": "Demande",
             "comodel": "essai.demande"},
        ],
    }],
    "views": [{"model": "essai.demande", "type": "form", "name": "Demande",
               "fields": ["name", "total"]}],
    "actions": [], "menus": [],
    "access": [{"model": "essai.demande", "group": "base.group_user", "perms": "rwcd"},
               {"model": "essai.ligne", "group": "base.group_user", "perms": "rwcd"}],
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


# ------------------------------------------------- invariants de sécurité

import inspect  # noqa: E402

from ai.provider import AIProvider, OpenAIProvider  # noqa: E402
from spec.drafter import SpecDrafter as _Drafter  # noqa: E402


class TestInvariantsDeSecurite(unittest.TestCase):
    """Trois invariants à conserver quand l'interface sera branchée.

    Ils sont vérifiés plutôt que documentés : une régression les casse ici,
    pas en production.
    """

    # --- 1. La clé reste dans l'environnement, jamais ailleurs.

    def test_la_cle_ne_se_passe_pas_en_argument_de_commande(self):
        """Une clé en argument fuirait dans l'historique et la liste des processus."""
        import cli.atelier_odoo as commande  # noqa: PLC0415
        source = inspect.getsource(commande)
        for interdit in ("--cle-api", "--api-key", "--openai-key", "--cle-openai"):
            self.assertNotIn(interdit, source)

    def test_la_cle_est_lue_dans_l_environnement(self):
        signature = inspect.getsource(OpenAIProvider.__init__)
        self.assertIn("OPENAI_API_KEY", signature)
        self.assertIn("os.environ", signature)

    def test_la_cle_ne_fuit_pas_dans_le_module_genere(self):
        secrete = "sk-test-CLE-QUI-NE-DOIT-PAS-FUIR"
        ancienne = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = secrete
        try:
            fichiers = OdooModuleGenerator().generate(spec_comportement())
            for chemin, contenu in fichiers.items():
                self.assertNotIn(secrete, contenu, chemin)
        finally:
            if ancienne is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = ancienne

    # --- 2. Le modèle n'a aucune capacité d'écriture.

    def test_le_contrat_du_fournisseur_n_expose_qu_une_methode(self):
        publiques = [
            n for n, _ in inspect.getmembers(AIProvider, inspect.isfunction)
            if not n.startswith("_")
        ]
        self.assertEqual(publiques, ["completer_json"])

    def test_le_modele_ne_recoit_que_du_texte(self):
        """Ni client d'installation, ni système de fichiers, ni connexion Odoo."""
        fournisseur = ScriptedProvider([json.loads(json.dumps(MINIMAL))])
        _Drafter(fournisseur).draft("un besoin")
        for consigne, contexte in fournisseur.appels:
            self.assertIsInstance(consigne, str)
            self.assertIsInstance(contexte, str)

    def test_le_redacteur_ne_touche_ni_disque_ni_reseau(self):
        source = inspect.getsource(_Drafter)
        for interdit in ("open(", "os.remove", "shutil", "subprocess", "urllib", "zipfile"):
            self.assertNotIn(interdit, source)

    def test_la_generation_reste_en_memoire(self):
        """Aucun fichier n'est écrit avant que la spécification soit validée."""
        source = inspect.getsource(OdooModuleGenerator)
        for interdit in ("open(", "os.makedirs", "shutil", "zipfile"):
            self.assertNotIn(interdit, source)
        fichiers = OdooModuleGenerator().generate(spec_comportement())
        self.assertIsInstance(fichiers, dict)
        self.assertTrue(all(isinstance(v, str) for v in fichiers.values()))

    # --- 3. Toute reprise repasse par le même validateur déterministe.

    def test_une_reparation_repasse_par_le_validateur(self):
        """Le modèle ne peut pas faire passer un module que le validateur refuse."""
        fautive = _en_dict(spec(access=[]))
        fournisseur = ScriptedProvider([fautive, fautive, fautive])
        boucle = RepairLoop(
            OdooModuleGenerator(), OdooStaticValidator(), None, fournisseur, tentatives_max=3
        )
        issue = boucle.executer(spec(access=[]))
        self.assertFalse(issue.reussi)
        # Chaque tentative a bien été validée, aucune n'a été laissée passer.
        self.assertEqual(len(issue.tentatives), 3)
        self.assertTrue(all(not t.validation_ok for t in issue.tentatives))

    def test_une_redaction_reprise_repasse_par_le_meme_controle(self):
        fautive = json.loads(json.dumps(MINIMAL))
        fautive["technical_name"] = "INVALIDE"
        fournisseur = ScriptedProvider([fautive, json.loads(json.dumps(MINIMAL))])
        rendue = _Drafter(fournisseur).draft("un besoin")
        # La reprise est validée par ModuleSpec, pas acceptée sur parole.
        self.assertEqual(rendue.technical_name, "mon_module")
        self.assertEqual(len(fournisseur.appels), 2)


class TestFournisseurConfigurable(unittest.TestCase):
    """Changer de fournisseur ne doit toucher aucun autre fichier."""

    def setUp(self):
        self.anciennes = {
            c: os.environ.get(c)
            for c in ("BUILDER_IA_CLE", "BUILDER_IA_URL", "BUILDER_IA_MODELE", "OPENAI_API_KEY")
        }
        for c in self.anciennes:
            os.environ.pop(c, None)

    def tearDown(self):
        for c, v in self.anciennes.items():
            if v is None:
                os.environ.pop(c, None)
            else:
                os.environ[c] = v

    def test_aucun_fournisseur_sans_cle(self):
        from ai.provider import fournisseur_depuis_environnement
        self.assertIsNone(fournisseur_depuis_environnement())

    def test_point_d_entree_et_modele_viennent_de_l_environnement(self):
        from ai.provider import fournisseur_depuis_environnement
        os.environ["BUILDER_IA_CLE"] = "cle-de-test"
        os.environ["BUILDER_IA_URL"] = "https://exemple.invalide/v1/chat/completions"
        os.environ["BUILDER_IA_MODELE"] = "un-autre-modele"
        fournisseur = fournisseur_depuis_environnement()
        self.assertEqual(fournisseur.url, "https://exemple.invalide/v1/chat/completions")
        self.assertEqual(fournisseur.modele, "un-autre-modele")

    def test_repli_sur_openai_par_defaut(self):
        from ai.provider import fournisseur_depuis_environnement
        os.environ["OPENAI_API_KEY"] = "cle-de-test"
        fournisseur = fournisseur_depuis_environnement()
        self.assertIn("api.openai.com", fournisseur.url)


# ------------------------------------------------------------------ routeur

from ai.provider import AnthropicProvider, ErreurFournisseur, extraire_json  # noqa: E402
from ai.routeur import (  # noqa: E402
    ConfigurationInvalide, Etape, RouterProvider, routeur_depuis_config,
)


class FournisseurEnPanne(AIProvider):
    """Indisponible : réseau, quota, 5xx — ce sur quoi le routeur bascule."""

    def __init__(self, motif="503"):
        self.motif = motif
        self.appels = 0

    def completer_json(self, consigne, contexte):
        self.appels += 1
        raise ErreurFournisseur(self.motif)


class FournisseurQuiRepond(AIProvider):
    def __init__(self, reponse):
        self.reponse = reponse
        self.appels = 0

    def completer_json(self, consigne, contexte):
        self.appels += 1
        return self.reponse


class TestRouteur(unittest.TestCase):
    def test_bascule_sur_le_suivant_quand_le_premier_est_en_panne(self):
        panne = FournisseurEnPanne("502 Bad Gateway")
        secours = FournisseurQuiRepond({"ok": True})
        routeur = RouterProvider(
            etapes=[Etape("kimi", panne), Etape("openai", secours)],
            journal=lambda _: None,
        )
        self.assertEqual(routeur.completer_json("c", "x"), {"ok": True})
        self.assertEqual(routeur.dernier_utilise, "openai")
        self.assertEqual(panne.appels, 1)
        self.assertEqual(len(routeur.incidents), 1)

    def test_l_ordre_est_respecte(self):
        premier = FournisseurQuiRepond({"source": "premier"})
        second = FournisseurQuiRepond({"source": "second"})
        routeur = RouterProvider(
            etapes=[Etape("a", premier), Etape("b", second)], journal=lambda _: None
        )
        self.assertEqual(routeur.completer_json("c", "x"), {"source": "premier"})
        self.assertEqual(second.appels, 0)

    def test_tous_en_panne_rend_une_erreur_qui_les_nomme(self):
        routeur = RouterProvider(
            etapes=[Etape("a", FournisseurEnPanne("429")),
                    Etape("b", FournisseurEnPanne("timeout"))],
            journal=lambda _: None,
        )
        with self.assertRaises(ErreurFournisseur) as capture:
            routeur.completer_json("c", "x")
        self.assertIn("429", str(capture.exception))
        self.assertIn("timeout", str(capture.exception))

    def test_une_specification_refusee_ne_fait_PAS_basculer(self):
        """Le point de conception : panne ≠ spécification perfectible.

        Un fournisseur qui répond correctement garde la main ; c'est le
        rédacteur qui lui renvoie le motif du refus. Sans cette distinction,
        une spécification simplement incomplète brûlerait toute la liste.
        """
        fautive = json.loads(json.dumps(MINIMAL))
        fautive["technical_name"] = "NOM-INVALIDE"      # refusé par ModuleSpec
        correcte = json.loads(json.dumps(MINIMAL))

        class Principal(AIProvider):
            """Se trompe d'abord, se corrige ensuite — comme un vrai modèle."""

            def __init__(self):
                self.appels = 0

            def completer_json(self, consigne, contexte):
                self.appels += 1
                return fautive if self.appels == 1 else correcte

        principal = Principal()
        secours = FournisseurQuiRepond(correcte)
        routeur = RouterProvider(
            etapes=[Etape("principal", principal), Etape("secours", secours)],
            journal=lambda _: None,
        )
        rendue = _Drafter(routeur, tentatives_max=2).draft("un besoin")

        self.assertEqual(rendue.technical_name, "mon_module")
        # Le rédacteur a bien renvoyé le motif au MÊME fournisseur…
        self.assertEqual(principal.appels, 2)
        # …et le secours n'a jamais été sollicité : ce n'était pas une panne.
        self.assertEqual(secours.appels, 0)


class TestConfigurationDuRouteur(unittest.TestCase):
    def setUp(self):
        self.anciennes = {c: os.environ.get(c) for c in ("CLE_A", "CLE_B")}
        os.environ["CLE_A"] = "valeur-a"
        os.environ.pop("CLE_B", None)

    def tearDown(self):
        for c, v in self.anciennes.items():
            if v is None:
                os.environ.pop(c, None)
            else:
                os.environ[c] = v

    def test_construit_depuis_une_description(self):
        routeur = routeur_depuis_config({"fournisseurs": [
            {"nom": "a", "protocole": "openai", "modele": "m", "cle_env": "CLE_A"},
        ]}, journal=lambda _: None)
        self.assertEqual(routeur.noms, ["a"])

    def test_ignore_un_fournisseur_dont_la_cle_manque(self):
        routeur = routeur_depuis_config({"fournisseurs": [
            {"nom": "absent", "modele": "m", "cle_env": "CLE_B"},
            {"nom": "present", "modele": "m", "cle_env": "CLE_A"},
        ]}, journal=lambda _: None)
        self.assertEqual(routeur.noms, ["present"])

    def test_une_cle_en_clair_dans_la_configuration_est_refusee(self):
        """La configuration reste versionnable : elle ne porte jamais de secret."""
        for champ in ("cle", "api_key", "token", "key"):
            with self.assertRaises(ConfigurationInvalide, msg=champ):
                routeur_depuis_config({"fournisseurs": [
                    {"nom": "a", "modele": "m", "cle_env": "CLE_A", champ: "sk-secret"},
                ]}, journal=lambda _: None, tolerant=False)

    def test_protocole_inconnu_refuse(self):
        with self.assertRaises(ConfigurationInvalide):
            routeur_depuis_config({"fournisseurs": [
                {"nom": "a", "protocole": "maison", "modele": "m", "cle_env": "CLE_A"},
            ]}, journal=lambda _: None, tolerant=False)

    def test_aucun_fournisseur_utilisable(self):
        with self.assertRaises(ConfigurationInvalide):
            routeur_depuis_config({"fournisseurs": [
                {"nom": "absent", "modele": "m", "cle_env": "CLE_B"},
            ]}, journal=lambda _: None)

    def test_l_exemple_livre_est_une_configuration_valide(self):
        chemin = os.path.join(RACINE, "routeur.example.json")
        with open(chemin, encoding="utf-8") as f:
            donnee = json.load(f)
        self.assertTrue(donnee["fournisseurs"])
        for entree in donnee["fournisseurs"]:
            self.assertIn("cle_env", entree)
            for interdit in ("cle", "api_key", "token", "key"):
                self.assertNotIn(interdit, entree)


class TestExtractionJson(unittest.TestCase):
    def test_json_nu(self):
        self.assertEqual(extraire_json('{"a": 1}'), {"a": 1})

    def test_json_entoure_de_balises(self):
        self.assertEqual(extraire_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_json_precede_de_bavardage(self):
        self.assertEqual(extraire_json('Voici :\n{"a": 1}\nVoilà.'), {"a": 1})

    def test_absence_de_json_signalee(self):
        with self.assertRaises(ErreurFournisseur):
            extraire_json("désolé, je ne peux pas")

    def test_le_protocole_anthropic_exige_une_cle(self):
        with self.assertRaises(ErreurFournisseur):
            AnthropicProvider(cle_api="").completer_json("c", "x")


# --------------------------------------------------------------- diagnostic

from ai.diagnostic import (  # noqa: E402
    AUTH, ENDPOINT, INDISPONIBLE, MODELE, PROTOCOLE, QUOTA, VARIABLE, Constat,
    verifier,
)


class FournisseurQuiEchoue(AIProvider):
    def __init__(self, code=None, corps=""):
        self.code, self.corps = code, corps

    def completer_json(self, consigne, contexte):
        raise ErreurFournisseur("échec simulé", code=self.code, corps=self.corps)


class TestDiagnostic(unittest.TestCase):
    """Un mauvais nom de modèle ne doit pas ressembler à un défaut du Builder."""

    def test_fournisseur_operationnel(self):
        constat = verifier("bon", FournisseurQuiRepond({"ok": True}))
        self.assertTrue(constat.ok)

    def test_cle_invalide_reconnue(self):
        for code in (401, 403):
            constat = verifier("x", FournisseurQuiEchoue(code))
            self.assertEqual(constat.cause, AUTH)
            self.assertFalse(constat.transitoire)

    def test_modele_inconnu_distingue_du_point_d_entree(self):
        """Le corps de la réponse nomme la cause ; le code seul ne suffit pas."""
        modele = verifier("x", FournisseurQuiEchoue(404, "The model `xyz` does not exist"))
        self.assertEqual(modele.cause, MODELE)
        endpoint = verifier("x", FournisseurQuiEchoue(404, "Not Found"))
        self.assertEqual(endpoint.cause, ENDPOINT)

    def test_modele_inconnu_sur_400_aussi(self):
        constat = verifier("x", FournisseurQuiEchoue(400, "unknown model name"))
        self.assertEqual(constat.cause, MODELE)

    def test_point_d_entree_injoignable(self):
        constat = verifier("x", FournisseurQuiEchoue(None))
        self.assertEqual(constat.cause, ENDPOINT)

    def test_quota_et_panne_sont_transitoires(self):
        """Rien à corriger dans le fichier : la configuration est bonne."""
        self.assertTrue(verifier("x", FournisseurQuiEchoue(429)).transitoire)
        self.assertTrue(verifier("x", FournisseurQuiEchoue(503)).transitoire)
        self.assertEqual(verifier("x", FournisseurQuiEchoue(429)).cause, QUOTA)

    def test_reponse_non_json_signalee_comme_protocole(self):
        class Bavard(AIProvider):
            def completer_json(self, consigne, contexte):
                return "je ne suis pas un objet"

        self.assertEqual(verifier("x", Bavard()).cause, PROTOCOLE)

    def test_une_cle_absente_n_est_pas_presentee_comme_un_defaut(self):
        ligne = Constat("local", False, VARIABLE, "LOCAL_LLM_KEY n'est pas définie").ligne()
        self.assertIn("non configuré", ligne)
        self.assertNotIn("à corriger", ligne)

    def test_la_sonde_emprunte_le_chemin_reel(self):
        """Un diagnostic qui passerait ailleurs ne prouverait rien."""
        temoin = FournisseurQuiRepond({"ok": True})
        verifier("x", temoin)
        self.assertEqual(temoin.appels, 1)


class TestTraceDuRouteur(unittest.TestCase):
    """Sans trace, une acceptation verte n'est pas reproductible."""

    def test_le_fournisseur_et_le_modele_sont_consignes(self):
        routeur = RouterProvider(
            etapes=[Etape("kimi", ScriptedProvider([{"ok": True}], modele="kimi-k3"))],
            journal=lambda _: None,
        )
        routeur.completer_json("c", "x")
        resume = routeur.resume()
        self.assertEqual(resume["fournisseur"], "kimi")
        self.assertEqual(resume["modele"], "kimi-k3")
        self.assertEqual(resume["basculements"], 0)

    def test_un_basculement_apparait_dans_la_trace(self):
        routeur = RouterProvider(
            etapes=[
                Etape("premier", FournisseurEnPanne("503")),
                Etape("second", ScriptedProvider([{"ok": True}], modele="gpt-x")),
            ],
            journal=lambda _: None,
        )
        routeur.completer_json("c", "x")
        resume = routeur.resume()
        self.assertEqual(resume["fournisseur"], "second")
        self.assertEqual(resume["modele"], "gpt-x")
        self.assertEqual(resume["basculements"], 1)
        # Les deux passages figurent, sous le même numéro d'appel.
        self.assertEqual([e["fournisseur"] for e in resume["trace"]], ["premier", "second"])
        self.assertEqual({e["appel"] for e in resume["trace"]}, {1})

    def test_les_corrections_successives_sont_comptees(self):
        fautive = json.loads(json.dumps(MINIMAL))
        fautive["technical_name"] = "INVALIDE"
        correcte = json.loads(json.dumps(MINIMAL))
        routeur = RouterProvider(
            etapes=[Etape("a", ScriptedProvider([fautive, correcte], modele="m"))],
            journal=lambda _: None,
        )
        redacteur = _Drafter(routeur, tentatives_max=2)
        redacteur.draft("un besoin")
        # Une tentative refusée puis une acceptée : une correction.
        self.assertEqual(len(redacteur.tentatives), 2)
        self.assertEqual(routeur.resume()["appels"], 2)

    def test_la_trace_ne_contient_aucun_secret(self):
        secrete = "sk-SECRET-QUI-NE-DOIT-PAS-APPARAITRE"
        os.environ["CLE_POUR_TRACE"] = secrete
        try:
            routeur = routeur_depuis_config({"fournisseurs": [
                {"nom": "a", "protocole": "openai",
                 "url": "http://127.0.0.1:9/v1/chat/completions",
                 "modele": "m", "cle_env": "CLE_POUR_TRACE"},
            ]}, journal=lambda _: None)
            with self.assertRaises(ErreurFournisseur):
                routeur.completer_json("c", "x")
            self.assertNotIn(secrete, json.dumps(routeur.resume(), ensure_ascii=False))
            self.assertNotIn(secrete, "\n".join(routeur.incidents))
        finally:
            os.environ.pop("CLE_POUR_TRACE", None)


# ------------------------------------------------------------- installation

import shutil as _shutil  # noqa: E402

from ai.installation import (  # noqa: E402
    FOURNISSEURS, InstallationImpossible, declarer_fournisseur, ecrire_routeur,
    ecrire_secrets, secret_installateur,
)


class TestInstallationGuidee(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(_shutil.rmtree, self.dossier, True)
        self.ancien = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.dossier, "config")

    def tearDown(self):
        if self.ancien is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.ancien

    def test_les_secrets_sont_ecrits_hors_du_depot(self):
        depot = os.path.join(self.dossier, "depot")
        os.makedirs(depot)
        chemin = ecrire_secrets({"MA_CLE": "sk-secrete"}, depot)
        self.assertFalse(chemin.startswith(os.path.abspath(depot)))

    def test_les_secrets_ne_sont_lisibles_que_par_leur_proprietaire(self):
        depot = os.path.join(self.dossier, "depot")
        os.makedirs(depot)
        chemin = ecrire_secrets({"MA_CLE": "sk-secrete"}, depot)
        self.assertEqual(oct(os.stat(chemin).st_mode)[-3:], "600")

    def test_refus_d_ecrire_des_secrets_dans_le_depot(self):
        depot = os.path.join(self.dossier, "depot")
        os.makedirs(depot)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(depot, "config")
        with self.assertRaises(InstallationImpossible):
            ecrire_secrets({"MA_CLE": "sk-secrete"}, depot)

    def test_le_routeur_ecrit_ne_contient_aucune_cle(self):
        chemin = os.path.join(self.dossier, "routeur.json")
        ecrire_routeur([("kimi", "kimi-k3")], chemin)
        brut = open(chemin, encoding="utf-8").read()
        self.assertNotIn("sk-", brut)
        donnee = json.loads(brut)
        entree = donnee["fournisseurs"][0]
        self.assertEqual(entree["cle_env"], "KIMI_API_KEY")
        for interdit in ("cle", "api_key", "token", "key"):
            self.assertNotIn(interdit, entree)

    def test_le_routeur_ecrit_est_accepte_par_le_routeur(self):
        """Ce que l'installation écrit doit être relisible sans retouche."""
        chemin = os.path.join(self.dossier, "routeur.json")
        ecrire_routeur([("kimi", "kimi-k3")], chemin)
        os.environ["KIMI_API_KEY"] = "cle-de-test"
        try:
            routeur = routeur_depuis_config(
                json.load(open(chemin, encoding="utf-8")), journal=lambda _: None
            )
            self.assertEqual(routeur.noms, ["kimi"])
        finally:
            os.environ.pop("KIMI_API_KEY", None)

    def test_le_secret_du_service_est_compose_par_l_outil(self):
        """Aucune raison de demander à l'utilisateur d'inventer une chaîne."""
        a, b = secret_installateur(), secret_installateur()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)

    def test_chaque_fournisseur_propose_a_un_nom_de_variable(self):
        for cle, details in FOURNISSEURS.items():
            self.assertTrue(details["cle_env"], cle)
            self.assertIn(details["protocole"], ("openai", "anthropic"))


# ------------------------------------------------- diagnostic en ligne de commande

sys.path.insert(0, os.path.join(RACINE, "cli"))
import atelier_odoo  # noqa: E402


class TestCommandeProviders(unittest.TestCase):
    """Le diagnostic doit voir ce que le Builder utilise, pas autre chose.

    Il réclamait un `routeur.json` alors que `fournisseur_configure` se rabat
    sur l'environnement. Toute machine installée par `deployer/installer.sh` —
    qui range la clé dans l'environnement sans écrire de fichier — se voyait
    donc répondre « configuration introuvable » avec une clé parfaitement
    valide.
    """

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.anciennes = {
            c: os.environ.get(c)
            for c in ("BUILDER_IA_ROUTEUR", "BUILDER_IA_CLE", "BUILDER_IA_URL",
                      "BUILDER_IA_MODELE", "OPENAI_API_KEY")
        }
        for c in self.anciennes:
            os.environ.pop(c, None)
        # Un chemin qui n'existe pas : le cas d'une machine sans routeur.
        os.environ["BUILDER_IA_ROUTEUR"] = os.path.join(self.dossier, "routeur.json")

        # Le diagnostic appelle le réseau ; on le remplace pour n'éprouver
        # que la décision, et on retient ce qu'on lui a demandé de vérifier.
        self.examinees = []
        self.vrai_verifier = atelier_odoo.verifier_etapes

        def faux_verifier(etapes, journal=None):
            self.examinees = list(etapes)
            return [Constat(e.nom, True, "OK") for e in etapes]

        atelier_odoo.verifier_etapes = faux_verifier

    def tearDown(self):
        atelier_odoo.verifier_etapes = self.vrai_verifier
        for c, v in self.anciennes.items():
            if v is None:
                os.environ.pop(c, None)
            else:
                os.environ[c] = v

    def test_sans_routeur_la_cle_de_l_environnement_suffit(self):
        os.environ["BUILDER_IA_CLE"] = "cle-de-test"
        code = atelier_odoo.commande_providers(None)
        self.assertEqual(code, 0)
        self.assertEqual([e.nom for e in self.examinees], ["environnement"])

    def test_sans_routeur_ni_cle_le_refus_nomme_les_deux_sources(self):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = atelier_odoo.commande_providers(None)
        self.assertEqual(code, 2)
        texte = sortie.getvalue()
        self.assertIn("BUILDER_IA_CLE", texte)
        self.assertIn("routeur", texte.lower())

    def test_le_routeur_ecrit_prend_le_pas_sur_l_environnement(self):
        chemin = os.environ["BUILDER_IA_ROUTEUR"]
        ecrire_routeur([("kimi", "kimi-k3")], chemin)
        os.environ["KIMI_API_KEY"] = "cle-de-test"
        os.environ["BUILDER_IA_CLE"] = "autre-cle"
        try:
            code = atelier_odoo.commande_providers(None)
        finally:
            os.environ.pop("KIMI_API_KEY", None)
        self.assertEqual(code, 0)
        self.assertEqual([e.nom for e in self.examinees], ["kimi"])

    def test_un_routeur_illisible_est_signale_et_non_contourne(self):
        """Un fichier cassé est une erreur à corriger, pas à ignorer."""
        chemin = os.environ["BUILDER_IA_ROUTEUR"]
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("{ceci n'est pas du json")
        os.environ["BUILDER_IA_CLE"] = "cle-de-test"
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = atelier_odoo.commande_providers(None)
        self.assertEqual(code, 2)
        self.assertIn(chemin, sortie.getvalue())


# --------------------------------------------------- à qui appartient la clé

from ai.detection import accepte, detecter, fournisseur_pour  # noqa: E402
from ai.diagnostic import OK  # noqa: E402


class FournisseurQuiRefuseLaCle(AIProvider):
    def completer_json(self, consigne, contexte):
        raise ErreurFournisseur(
            "401 Unauthorized — Incorrect API key provided", code=401,
            corps="Incorrect API key provided",
        )


class FournisseurQuiIgnoreLeModele(AIProvider):
    """Clé acceptée, modèle inconnu : le cas d'une table de modèles périmée."""

    def completer_json(self, consigne, contexte):
        raise ErreurFournisseur(
            "404 Not Found — The model `kimi-k3` does not exist", code=404,
            corps="The model `kimi-k3` does not exist",
        )


class TestDetectionDuFournisseur(unittest.TestCase):
    """Une clé refusée par OpenAI peut être excellente ailleurs."""

    TABLE = {
        "openai": {"libelle": "OpenAI", "protocole": "openai",
                   "url": "https://exemple.invalide/v1/chat/completions",
                   "cle_env": "OPENAI_API_KEY", "modele_suggere": "gpt-5.6"},
        "kimi": {"libelle": "Kimi / Moonshot", "protocole": "openai",
                 "url": "https://exemple.invalide/v1/chat/completions",
                 "cle_env": "KIMI_API_KEY", "modele_suggere": "kimi-k3"},
    }

    def test_un_refus_d_authentification_ecarte_le_fournisseur(self):
        constat = verifier("openai", FournisseurQuiRefuseLaCle())
        self.assertFalse(accepte(constat))

    def test_un_modele_inconnu_prouve_que_la_cle_est_acceptee(self):
        """Le serveur n'aurait pas examiné le modèle s'il refusait la clé."""
        constat = verifier("kimi", FournisseurQuiIgnoreLeModele())
        self.assertFalse(constat.ok)
        self.assertTrue(accepte(constat))

    def test_une_reponse_valide_vaut_acceptation(self):
        constat = Constat("kimi", True, OK, "réponse JSON reçue")
        self.assertTrue(accepte(constat))

    def test_la_detection_essaie_tous_les_fournisseurs_dans_l_ordre(self):
        essayes = []

        def faux_verifier(nom, fournisseur):
            essayes.append(nom)
            return Constat(nom, False, AUTH, "401")

        import ai.detection as detection
        vrai = detection.verifier
        detection.verifier = faux_verifier
        try:
            constats = detecter("sk-quelconque", table=self.TABLE)
        finally:
            detection.verifier = vrai
        self.assertEqual(essayes, ["openai", "kimi"])
        self.assertEqual(len(constats), 2)
        self.assertFalse(any(accepte(c) for c in constats))

    def test_le_client_construit_porte_la_cle_et_l_url_du_fournisseur(self):
        client = fournisseur_pour(self.TABLE["kimi"], "sk-essai")
        self.assertEqual(client.cle_api, "sk-essai")
        self.assertEqual(client.url, self.TABLE["kimi"]["url"])
        self.assertEqual(client.modele, "kimi-k3")

    def test_le_protocole_anthropic_donne_un_client_anthropic(self):
        details = {"libelle": "Anthropic", "protocole": "anthropic",
                   "url": "https://exemple.invalide/v1/messages",
                   "cle_env": "ANTHROPIC_API_KEY", "modele_suggere": "claude-sonnet-5"}
        self.assertIsInstance(fournisseur_pour(details, "sk-essai"), AnthropicProvider)


class TestDeclarationDuFournisseur(unittest.TestCase):
    """Ce que « detect --adopter » écrit doit rester relisible et unique."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.chemin = os.path.join(self.dossier, "env")

    def test_les_deux_lignes_sont_ecrites(self):
        declarer_fournisseur("https://exemple.invalide/v1/chat/completions",
                             "un-modele", self.chemin)
        with open(self.chemin, encoding="utf-8") as f:
            contenu = f.read()
        self.assertIn('export BUILDER_IA_URL="https://exemple.invalide/v1/chat/completions"',
                      contenu)
        self.assertIn('export BUILDER_IA_MODELE="un-modele"', contenu)

    def test_la_cle_existante_est_conservee(self):
        with open(self.chemin, "w", encoding="utf-8") as f:
            f.write('export BUILDER_IA_CLE="sk-secret"\n')
        declarer_fournisseur("https://a.invalide/v1/chat/completions", "m", self.chemin)
        with open(self.chemin, encoding="utf-8") as f:
            contenu = f.read()
        self.assertIn('export BUILDER_IA_CLE="sk-secret"', contenu)

    def test_une_seconde_declaration_remplace_la_premiere(self):
        """Deux « export BUILDER_IA_URL » rendraient tout diagnostic faux."""
        declarer_fournisseur("https://a.invalide/v1/chat/completions", "m1", self.chemin)
        declarer_fournisseur("https://b.invalide/v1/chat/completions", "m2", self.chemin)
        with open(self.chemin, encoding="utf-8") as f:
            contenu = f.read()
        self.assertEqual(contenu.count("export BUILDER_IA_URL="), 1)
        self.assertEqual(contenu.count("export BUILDER_IA_MODELE="), 1)
        self.assertIn("b.invalide", contenu)
        self.assertNotIn("a.invalide", contenu)

    def test_le_fichier_reste_lisible_par_son_seul_proprietaire(self):
        declarer_fournisseur("https://a.invalide/v1/chat/completions", "m", self.chemin)
        self.assertEqual(os.stat(self.chemin).st_mode & 0o777, 0o600)

    def test_un_fichier_sans_saut_de_ligne_final_ne_colle_pas_les_lignes(self):
        with open(self.chemin, "w", encoding="utf-8") as f:
            f.write('export BUILDER_IA_CLE="sk-secret"')  # sans \n
        declarer_fournisseur("https://a.invalide/v1/chat/completions", "m", self.chemin)
        with open(self.chemin, encoding="utf-8") as f:
            lignes = f.read().splitlines()
        self.assertIn('export BUILDER_IA_CLE="sk-secret"', lignes)


import acceptation  # noqa: E402


class TestIdentifiantsOdoo(unittest.TestCase):
    """Le compte qui éprouve le module n'est pas toujours « admin/admin ».

    L'installeur remplace ce mot de passe dès que le port 8069 est ouvert.
    Le supposer inchangé faisait échouer l'acceptation sur « Access Denied »
    alors que le module était installé et correct : l'échec accusait la
    fabrication, quand seule la connexion était en cause.
    """

    VARIABLES = ("ODOO_LOGIN", "ODOO_ADMIN_MOTDEPASSE", "ODOO_MOTDEPASSE")

    def setUp(self):
        self.anciennes = {c: os.environ.get(c) for c in self.VARIABLES}
        for c in self.VARIABLES:
            os.environ.pop(c, None)

    def tearDown(self):
        for c, v in self.anciennes.items():
            if v is None:
                os.environ.pop(c, None)
            else:
                os.environ[c] = v

    def test_sans_rien_le_defaut_de_developpement(self):
        self.assertEqual(acceptation.identifiants_odoo(), ("admin", "admin"))

    def test_le_mot_de_passe_de_l_installeur_est_pris(self):
        os.environ["ODOO_ADMIN_MOTDEPASSE"] = "tirage-aleatoire"
        self.assertEqual(acceptation.identifiants_odoo(), ("admin", "tirage-aleatoire"))

    def test_le_nom_utilise_par_docker_compose_convient_aussi(self):
        os.environ["ODOO_MOTDEPASSE"] = "par-compose"
        self.assertEqual(acceptation.identifiants_odoo(), ("admin", "par-compose"))

    def test_celui_de_l_installeur_l_emporte_sur_celui_de_compose(self):
        os.environ["ODOO_ADMIN_MOTDEPASSE"] = "installeur"
        os.environ["ODOO_MOTDEPASSE"] = "compose"
        self.assertEqual(acceptation.identifiants_odoo()[1], "installeur")

    def test_le_compte_peut_etre_autre_qu_admin(self):
        os.environ["ODOO_LOGIN"] = "atelier"
        self.assertEqual(acceptation.identifiants_odoo()[0], "atelier")

    def test_une_valeur_vide_ne_remplace_pas_le_defaut(self):
        """Une variable exportée vide est un oubli, pas un mot de passe vide."""
        os.environ["ODOO_ADMIN_MOTDEPASSE"] = ""
        self.assertEqual(acceptation.identifiants_odoo(), ("admin", "admin"))


class TestRelationsEtDependances(unittest.TestCase):
    """Une relation ne peut viser qu'un modèle réellement disponible.

    Défaut observé en production : le modèle avait décrit un lien vers
    « hr.employee » sans déclarer « hr » dans depends. Odoo n'a pas créé le
    champ, puis la vue l'a réclamé, et l'installation a échoué sur
    « Field employe_id does not exist in model mission.demande » — message qui
    accuse la vue alors que la faute est dans le manifeste. La validation
    statique laissait passer l'ensemble.
    """

    def _spec(self, depends, comodel):
        return ModuleSpec.depuis_dict({
            "technical_name": "gestion_missions", "name": "Gestion des missions",
            "depends": depends,
            "models": [{"name": "mission.demande", "description": "Demande",
                "fields": [
                    {"name": "name", "type": "char", "string": "Objet",
                     "required": True},
                    {"name": "employe_id", "type": "many2one", "string": "Employé",
                     "comodel": comodel},
                ]}],
            "views": [{"model": "mission.demande", "type": "tree",
                       "name": "Demandes", "fields": ["name", "employe_id"],
                       "invisible_fields": []}],
            "actions": [{"id": "a", "name": "Demandes", "model": "mission.demande",
                         "view_modes": ["tree", "form"]}],
            "menus": [{"id": "m", "name": "Missions", "action": "a"}],
            "access": [{"model": "mission.demande", "group": "base.group_user"}],
        })

    def _rapport(self, depends, comodel="hr.employee"):
        spec = self._spec(depends, comodel)
        return OdooStaticValidator().check(
            OdooModuleGenerator().generate(spec), spec
        )

    def test_relation_vers_un_module_non_declare_est_refusee(self):
        rapport = self._rapport(["base"])
        self.assertFalse(rapport.ok)
        self.assertIn("hr", rapport.texte())

    def test_la_meme_relation_passe_si_le_module_est_declare(self):
        self.assertTrue(self._rapport(["base", "hr"]).ok)

    def test_res_partner_ne_demande_que_base(self):
        """« res.* » vient de « base » : exiger un module « res » serait faux."""
        self.assertTrue(self._rapport(["base"], "res.partner").ok)

    def test_ir_attachment_ne_demande_que_base(self):
        self.assertTrue(self._rapport(["base"], "ir.attachment").ok)

    def test_un_module_tiers_est_reconnu_par_son_prefixe(self):
        self.assertFalse(self._rapport(["base"], "ansut.agent").ok)
        self.assertTrue(self._rapport(["base", "ansut"], "ansut.agent").ok)

    def test_une_relation_interne_au_module_ne_demande_rien(self):
        """Un modèle créé par le module lui-même est toujours disponible."""
        spec = ModuleSpec.depuis_dict({
            "technical_name": "gestion_missions", "name": "Missions",
            "depends": ["base"],
            "models": [
                {"name": "mission.demande", "description": "Demande", "fields": [
                    {"name": "name", "type": "char", "string": "Objet"},
                    {"name": "frais_ids", "type": "one2many", "string": "Frais",
                     "comodel": "mission.frais", "inverse_name": "demande_id"},
                ]},
                {"name": "mission.frais", "description": "Frais", "fields": [
                    {"name": "name", "type": "char", "string": "Libellé"},
                    {"name": "demande_id", "type": "many2one", "string": "Demande",
                     "comodel": "mission.demande"},
                ]},
            ],
            "views": [{"model": "mission.demande", "type": "tree", "name": "D",
                       "fields": ["name"], "invisible_fields": []}],
            "actions": [{"id": "a", "name": "D", "model": "mission.demande",
                         "view_modes": ["tree", "form"]}],
            "menus": [{"id": "m", "name": "Missions", "action": "a"}],
            "access": [{"model": "mission.demande", "group": "base.group_user"},
                       {"model": "mission.frais", "group": "base.group_user"}],
        })
        rapport = OdooStaticValidator().check(
            OdooModuleGenerator().generate(spec), spec
        )
        self.assertTrue(rapport.ok, rapport.texte())

    def test_le_contrat_enonce_la_regle_au_modele(self):
        """Le modèle doit connaître la règle avant, pas seulement après refus."""
        from spec.drafter import CONTRAT
        self.assertIn("hr.employee", CONTRAT)
        self.assertIn("depends", CONTRAT)


class FournisseurHttpSimule(OpenAIProvider):
    """Un OpenAIProvider dont on choisit la réponse HTTP, sans réseau."""

    def __init__(self, charge):
        super().__init__(cle_api="sk-essai")
        self.charge = charge

    def completer_json(self, consigne, contexte):
        import ai.provider as fournisseur_module
        vrai = fournisseur_module.urllib.request.urlopen
        classe = self.__class__

        class Reponse:
            def __init__(self, texte): self.texte = texte
            def read(self): return self.texte.encode("utf-8")
            def __enter__(self): return self
            def __exit__(self, *a): return False

        fournisseur_module.urllib.request.urlopen = \
            lambda *a, **k: Reponse(json.dumps(self.charge))
        try:
            return OpenAIProvider.completer_json(self, consigne, contexte)
        finally:
            fournisseur_module.urllib.request.urlopen = vrai


def _reponse(contenu, finish_reason=None):
    message = {"choices": [{"message": {"content": contenu}}]}
    if finish_reason:
        message["choices"][0]["finish_reason"] = finish_reason
    return message


class TestReponseDuFournisseur(unittest.TestCase):
    """« response_format: json_object » n'est pas honoré partout.

    Le chemin OpenAI faisait json.loads sur la réponse brute, quand le chemin
    Anthropic passait par extraire_json. Un service qui enrobe son JSON de
    ```json échouait donc sur « Expecting value: line 1 column 1 (char 0) » —
    message qui ne dit rien de ce qui a été reçu, et qu'on a mis un tour
    complet à comprendre.
    """

    def test_json_nu_est_lu(self):
        f = FournisseurHttpSimule(_reponse('{"a": 1}'))
        self.assertEqual(f.completer_json("c", "x"), {"a": 1})

    def test_json_enrobe_de_balises_est_lu(self):
        f = FournisseurHttpSimule(_reponse('```json\n{"a": 1}\n```'))
        self.assertEqual(f.completer_json("c", "x"), {"a": 1})

    def test_json_precede_d_une_phrase_est_lu(self):
        f = FournisseurHttpSimule(_reponse('Voici la spécification :\n{"a": 1}'))
        self.assertEqual(f.completer_json("c", "x"), {"a": 1})

    def test_une_reponse_vide_le_dit(self):
        f = FournisseurHttpSimule(_reponse(""))
        with self.assertRaises(ErreurFournisseur) as capture:
            f.completer_json("c", "x")
        self.assertIn("réponse vide", str(capture.exception))

    def test_l_erreur_montre_ce_qui_a_ete_recu(self):
        f = FournisseurHttpSimule(_reponse("<html>Portail d'authentification</html>"))
        with self.assertRaises(ErreurFournisseur) as capture:
            f.completer_json("c", "x")
        self.assertIn("html", str(capture.exception).lower())

    def test_une_reponse_tronquee_nomme_la_cause(self):
        """finish_reason distingue « le modèle a mal répondu » de « ça a coupé »."""
        f = FournisseurHttpSimule(_reponse('{"a": 1', finish_reason="length"))
        with self.assertRaises(ErreurFournisseur) as capture:
            f.completer_json("c", "x")
        self.assertIn("length", str(capture.exception))

    def test_une_charge_sans_choices_montre_la_charge(self):
        f = FournisseurHttpSimule({"error": {"message": "quota dépassé"}})
        with self.assertRaises(ErreurFournisseur) as capture:
            f.completer_json("c", "x")
        self.assertIn("quota", str(capture.exception))


class RuntimeSimule:
    """Un Odoo de papier : retient les créations, répond aux recherches."""

    def __init__(self, existants=()):
        self.existants = set(existants)
        self.crees = []

    def appeler(self, modele, methode, args, kwargs=None):
        if methode == "search":
            return [7] if modele in self.existants else []
        raise AssertionError(f"appel inattendu : {methode}")

    def creer(self, modele, valeurs):
        self.crees.append((modele, valeurs))
        return 100 + len(self.crees)


class TestValeursDuBancDEssai(unittest.TestCase):
    """Un many2one attend un entier, pas « Recette d'acceptation ».

    Le banc d'essai remplissait tout type inconnu avec une chaîne. PostgreSQL
    rejetait l'insertion sur « invalid input syntax for type integer », et le
    verdict accusait le module fabriqué alors que la faute était dans le test.
    """

    def _champ(self, **kw):
        base = {"name": "x", "type": "char", "string": "X", "selection": []}
        base.update(kw)
        return Champ(**base)

    def test_un_many2one_rend_l_identifiant_d_un_existant(self):
        runtime = RuntimeSimule(existants={"res.currency"})
        valeur = acceptation._valeur_exemple(
            self._champ(name="currency_id", type="many2one", comodel="res.currency"),
            runtime, None,
        )
        self.assertEqual(valeur, 7)

    def test_un_many2one_sans_existant_cree_dans_le_module(self):
        runtime = RuntimeSimule()
        spec = ModuleSpec.depuis_dict(MINIMAL)
        valeur = acceptation._valeur_exemple(
            self._champ(name="objet_id", type="many2one", comodel="mon.objet"),
            runtime, spec,
        )
        self.assertEqual(valeur, 101)
        self.assertEqual(runtime.crees[0][0], "mon.objet")

    def test_un_many2one_hors_module_et_sans_existant_est_omis(self):
        """Mieux vaut ne pas remplir un champ que le remplir faux."""
        runtime = RuntimeSimule()
        valeur = acceptation._valeur_exemple(
            self._champ(name="employe_id", type="many2one", comodel="hr.employee"),
            runtime, ModuleSpec.depuis_dict(MINIMAL),
        )
        self.assertIs(valeur, acceptation.SANS_VALEUR)

    def test_une_selection_prend_sa_premiere_valeur(self):
        champ = self._champ(name="etat", type="selection",
                            selection=[["brouillon", "Brouillon"], ["fait", "Fait"]])
        self.assertEqual(acceptation._valeur_exemple(champ), "brouillon")

    def test_les_relations_multiples_partent_vides(self):
        for type_ in ("one2many", "many2many"):
            champ = self._champ(name="lignes", type=type_, comodel="mon.objet")
            self.assertEqual(acceptation._valeur_exemple(champ), [])

    def test_une_boucle_de_relations_ne_tourne_pas_sans_fin(self):
        """Deux modèles qui se pointent l'un l'autre ne doivent pas boucler."""
        runtime = RuntimeSimule()
        spec = ModuleSpec.depuis_dict({
            **json.loads(json.dumps(MINIMAL)),
            "models": [{"name": "a.modele", "description": "A", "fields": [
                {"name": "b_id", "type": "many2one", "string": "B",
                 "comodel": "b.modele", "required": True}]},
                {"name": "b.modele", "description": "B", "fields": [
                    {"name": "a_id", "type": "many2one", "string": "A",
                     "comodel": "a.modele", "required": True}]}],
            "views": [], "actions": [], "menus": [],
            "access": [{"model": "a.modele", "group": "base.group_user"},
                       {"model": "b.modele", "group": "base.group_user"}],
        })
        valeur = acceptation._valeur_exemple(
            self._champ(name="b_id", type="many2one", comodel="b.modele"),
            runtime, spec,
        )
        # « a.modele » est créé en premier, sans le b_id qu'on renonce à
        # remplir ; « b.modele » suit, en le pointant. Deux créations, et
        # pas d'appels sans fin.
        self.assertEqual([m for m, _ in runtime.crees], ["a.modele", "b.modele"])
        self.assertEqual(valeur, 102)

    def test_les_champs_calcules_ne_sont_jamais_fournis(self):
        spec = ModuleSpec.depuis_dict(AVEC_COMPORTEMENT)
        modele = spec.models[0]
        valeurs = acceptation._valeurs_obligatoires(
            RuntimeSimule(existants={"res.currency"}), spec, modele
        )
        self.assertNotIn("total", valeurs)


class TestSecoursIllusoire(unittest.TestCase):
    """Un fournisseur déclaré mais inutilisable n'est pas un secours.

    Tant que le premier répond, personne ne s'en aperçoit ; le jour où il
    tombe, le routeur bascule vers rien. « --exigeant » le fait dire avant
    d'en avoir besoin, plutôt qu'au pire moment.
    """

    class Args:
        def __init__(self, exigeant=False):
            self.action = "check"
            self.exigeant = exigeant
            self.adopter = False

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.ancien_routeur = os.environ.get("BUILDER_IA_ROUTEUR")
        self.chemin = os.path.join(self.dossier, "routeur.json")
        os.environ["BUILDER_IA_ROUTEUR"] = self.chemin
        ecrire_routeur([("kimi", "kimi-k3"), ("openai", "gpt-4o")], self.chemin)
        for nom in ("KIMI_API_KEY", "OPENAI_API_KEY"):
            os.environ[nom] = "cle-de-test"
        self.vrai = atelier_odoo.verifier_etapes

    def tearDown(self):
        atelier_odoo.verifier_etapes = self.vrai
        for nom in ("KIMI_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(nom, None)
        if self.ancien_routeur is None:
            os.environ.pop("BUILDER_IA_ROUTEUR", None)
        else:
            os.environ["BUILDER_IA_ROUTEUR"] = self.ancien_routeur

    def _repondre(self, par_nom):
        def faux(etapes, journal=None):
            return [par_nom[e.nom] for e in etapes]
        atelier_odoo.verifier_etapes = faux

    def test_un_modele_inconnu_chez_le_secours_fait_echouer(self):
        self._repondre({
            "kimi": Constat("kimi", True, OK),
            "openai": Constat("openai", False, MODELE, "le modèle n'existe pas"),
        })
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = atelier_odoo.commande_providers(self.Args(exigeant=True))
        self.assertEqual(code, 1)
        self.assertIn("Secours illusoire", sortie.getvalue())

    def test_sans_exigence_le_meme_cas_passe(self):
        """Le comportement par défaut ne change pas : un fournisseur suffit."""
        self._repondre({
            "kimi": Constat("kimi", True, OK),
            "openai": Constat("openai", False, MODELE, "le modèle n'existe pas"),
        })
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(atelier_odoo.commande_providers(self.Args()), 0)

    def test_une_panne_passagere_n_est_pas_un_secours_casse(self):
        """Un 503 se répare tout seul ; rien à corriger dans la configuration."""
        self._repondre({
            "kimi": Constat("kimi", True, OK),
            "openai": Constat("openai", False, INDISPONIBLE, "503", transitoire=True),
        })
        with contextlib.redirect_stdout(io.StringIO()):
            code = atelier_odoo.commande_providers(self.Args(exigeant=True))
        self.assertEqual(code, 0)

    def test_deux_fournisseurs_sains_passent(self):
        self._repondre({
            "kimi": Constat("kimi", True, OK),
            "openai": Constat("openai", True, OK),
        })
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(atelier_odoo.commande_providers(self.Args(exigeant=True)), 0)


# ------------------------------------------------------------- multi-versions

from generator.dialecte import CIBLES, CibleInconnue, Dialecte  # noqa: E402


class TestDialecte(unittest.TestCase):
    """Ce qui change d'une version à l'autre, et rien d'autre.

    Chaque règle ici doit être vérifiée par l'installation réelle dans l'image
    correspondante. Une différence supposée est pire qu'une différence
    ignorée : elle produit du code qui a l'air juste.
    """

    def test_la_balise_liste_change_en_18(self):
        self.assertEqual(Dialecte("17.0").balise_liste, "tree")
        self.assertEqual(Dialecte("18.0").balise_liste, "list")
        self.assertEqual(Dialecte("19.0").balise_liste, "list")

    def test_le_mode_de_vue_suit_la_balise(self):
        """Une action en « tree » ouvrirait une vue introuvable en 18."""
        self.assertEqual(Dialecte("17.0").mode_vue("tree"), "tree")
        self.assertEqual(Dialecte("18.0").mode_vue("tree"), "list")

    def test_les_autres_modes_ne_bougent_pas(self):
        for cible in CIBLES:
            for mode in ("form", "kanban", "calendar", "pivot", "graph"):
                self.assertEqual(Dialecte(cible).mode_vue(mode), mode)

    def test_la_version_du_manifeste_porte_celle_d_odoo(self):
        """C'est ce préfixe qui dit à Odoo qu'un module doit être mis à jour."""
        self.assertEqual(Dialecte("18.0").version_manifeste("1.0.0"), "18.0.1.0.0")

    def test_une_cible_non_eprouvee_est_refusee(self):
        with self.assertRaises(CibleInconnue):
            Dialecte("16.0")


class TestGenerationMultiVersions(unittest.TestCase):
    """Une même spécification, trois modules, une seule logique métier."""

    def _pour(self, cible):
        donnee = json.loads(json.dumps(MINIMAL))
        donnee["cible"] = cible
        spec = ModuleSpec.depuis_dict(donnee)
        return spec, OdooModuleGenerator().generate(spec)

    def _fichier(self, fichiers, suffixe):
        return next(c for n, c in fichiers.items() if n.endswith(suffixe))

    def test_la_balise_de_vue_suit_la_cible(self):
        self.assertIn("<tree", self._fichier(self._pour("17.0")[1], "_views.xml"))
        for cible in ("18.0", "19.0"):
            vues = self._fichier(self._pour(cible)[1], "_views.xml")
            self.assertIn("<list", vues)
            self.assertNotIn("<tree", vues)

    def test_le_manifeste_prefixe_la_version_d_odoo(self):
        for cible in CIBLES:
            manifeste = self._fichier(self._pour(cible)[1], "__manifest__.py")
            self.assertIn(f"'version': '{cible}.", manifeste)

    def test_les_trois_versions_passent_la_validation(self):
        for cible in CIBLES:
            spec, fichiers = self._pour(cible)
            rapport = OdooStaticValidator().check(fichiers, spec)
            self.assertTrue(rapport.ok, f"{cible} : {rapport.texte()}")

    def test_le_python_est_identique_d_une_version_a_l_autre(self):
        """La logique métier ne se duplique pas : dupliquée, elle divergerait.

        Seule la présentation change. Si un jour le Python devait différer, ce
        test tomberait — et ce serait une décision à prendre, pas un effet de
        bord à découvrir.
        """
        modeles = {}
        for cible in CIBLES:
            fichiers = self._pour(cible)[1]
            modeles[cible] = {n: c for n, c in fichiers.items()
                              if n.endswith(".py") and "models/" in n}
        reference = modeles[CIBLES[0]]
        for cible in CIBLES[1:]:
            self.assertEqual(modeles[cible], reference, f"le Python diffère en {cible}")


class TestCibleDansLaSpecification(unittest.TestCase):
    """L'ancienne forme « 17.0.1.0.0 » portait deux notions d'un coup."""

    def test_l_ancienne_forme_est_coupee_en_deux(self):
        spec = ModuleSpec.depuis_dict({**json.loads(json.dumps(MINIMAL)),
                                       "version": "17.0.2.3.4"})
        self.assertEqual(spec.cible, "17.0")
        self.assertEqual(spec.version, "2.3.4")

    def test_la_nouvelle_forme_est_prise_telle_quelle(self):
        spec = ModuleSpec.depuis_dict({**json.loads(json.dumps(MINIMAL)),
                                       "cible": "19.0", "version": "2.3.4"})
        self.assertEqual((spec.cible, spec.version), ("19.0", "2.3.4"))

    def test_une_version_fonctionnelle_courte_n_est_pas_coupee(self):
        """« 1.0.0 » n'est pas une version d'Odoo suivie d'un reste."""
        spec = ModuleSpec.depuis_dict({**json.loads(json.dumps(MINIMAL)),
                                       "version": "1.0.0"})
        self.assertEqual((spec.cible, spec.version), ("17.0", "1.0.0"))

    def test_une_cible_inconnue_est_refusee_a_la_lecture(self):
        with self.assertRaises(SpecInvalide):
            ModuleSpec.depuis_dict({**json.loads(json.dumps(MINIMAL)), "cible": "16.0"})

    def test_le_defaut_reste_17_pour_ne_rien_casser(self):
        self.assertEqual(ModuleSpec.depuis_dict(json.loads(json.dumps(MINIMAL))).cible, "17.0")


class TestAmorceDuDepotDAddons(unittest.TestCase):
    """Le dossier de dépôt ne doit jamais être vide au démarrage d'Odoo.

    Odoo 19 filtre « addons_path » au démarrage et écarte tout dossier ne
    contenant aucun module (odoo/tools/config.py, _is_addons_path). Le dépôt
    de l'Atelier étant vide sur une instance neuve, il en disparaissait — et
    le premier module déposé restait introuvable, « update_list » répondant
    200 sans rien voir. Aucune trace, aucune erreur : le pire des symptômes.

    Ces contrôles tiennent la parade. Elle est invisible à l'exécution : rien
    d'autre ne signalerait qu'on l'a cassée.
    """

    AMORCE = os.path.join(os.path.dirname(RACINE), ".docker", "depot-amorce")

    @staticmethod
    def _est_un_chemin_d_addons(chemin):
        """Copie fidèle de _is_addons_path d'Odoo 19."""
        for f in os.listdir(chemin):
            modpath = os.path.join(chemin, f)

            def a_le_fichier(nom):
                return os.path.isfile(os.path.join(modpath, nom))

            if a_le_fichier("__init__.py") and a_le_fichier("__manifest__.py"):
                return True
        return False

    def test_odoo_19_reconnaitrait_le_dossier_d_amorce(self):
        self.assertTrue(os.path.isdir(self.AMORCE), "dossier d'amorce absent")
        self.assertTrue(
            self._est_un_chemin_d_addons(self.AMORCE),
            "Odoo 19 écarterait ce dossier de son chemin d'addons.",
        )

    def test_la_version_du_marqueur_convient_a_toutes_les_series(self):
        """Une version préfixée ferait du marqueur un module d'une seule série.

        Odoo 18 refuse un manifeste dont la version porte une autre série que
        la sienne — et ce refus empêche l'initialisation de la base, pas
        seulement l'installation du module. Le marqueur étant sur le chemin
        d'addons de TOUTES les versions, sa version doit rester sans préfixe :
        Odoo y ajoute alors la sienne, quelle qu'elle soit.
        """
        import ast

        chemin = os.path.join(self.AMORCE, "atelier_depot", "__manifest__.py")
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
        manifeste = ast.literal_eval(texte[texte.index("{"):])

        version = manifeste["version"]
        for cible in CIBLES:
            self.assertFalse(
                version.startswith(cible.split(".")[0]),
                f"« {version} » attacherait le marqueur à une seule série d'Odoo.",
            )
        # Deux ou trois composants : la forme qu'Odoo préfixe de sa série.
        self.assertRegex(version, r"^\d+\.\d+(\.\d+)?$")
        self.assertFalse(manifeste["installable"], "le marqueur n'a rien à installer")


# ---------------------------------------------------------------- conversion

from converter.extraction import (  # noqa: E402
    ConversionImpossible, Extracteur, convertir,
)
from converter.rapport import COMPORTEMENT, OBSOLETE, STRUCTURE  # noqa: E402


def _ecrire_module(racine, fichiers):
    """Pose une arborescence de module sur disque, telle que le générateur la rend."""
    for chemin, contenu in fichiers.items():
        complet = os.path.join(racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w", encoding="utf-8") as f:
            f.write(contenu)
    return os.path.join(racine, sorted(fichiers)[0].split("/")[0])


class TestAllerRetour(unittest.TestCase):
    """Générer, relire, regénérer : la conversion doit être l'inverse du rendu.

    C'est le contrôle qui donne sa valeur au convertisseur. Sans lui, on sait
    seulement qu'il produit « quelque chose » — pas qu'il a compris ce qu'il
    lisait.

    L'égalité porte sur ce que la spécification sait décrire. Le comportement
    (méthodes, transitions) n'en fait délibérément pas partie : le
    convertisseur ne l'infère pas, et le test doit dire la même chose que le
    convertisseur, pas l'inverse.
    """

    def _spec_structurelle(self):
        return ModuleSpec.depuis_dict({
            "technical_name": "atelier_essai",
            "name": "Essai d'aller-retour",
            "summary": "Un module sans comportement, pour éprouver la relecture.",
            "category": "Tools",
            "cible": "17.0",
            "version": "2.3.4",
            "license": "LGPL-3",
            "depends": ["base"],
            "application": True,
            "models": [{
                "name": "essai.dossier",
                "description": "Dossier d'essai",
                "fields": [
                    {"name": "name", "type": "char", "string": "Référence",
                     "required": True},
                    {"name": "quantite", "type": "integer", "string": "Quantité"},
                    {"name": "actif", "type": "boolean", "string": "Actif",
                     "default": True},
                    {"name": "categorie", "type": "selection", "string": "Catégorie",
                     "selection": [["a", "Première"], ["b", "Seconde"]]},
                    {"name": "partenaire_id", "type": "many2one",
                     "string": "Partenaire", "comodel": "res.partner"},
                ],
            }],
            "views": [
                {"model": "essai.dossier", "type": "tree", "name": "Dossiers",
                 "fields": ["name", "quantite", "categorie"]},
                {"model": "essai.dossier", "type": "form", "name": "Dossier",
                 "fields": ["name", "quantite", "actif", "categorie", "partenaire_id"]},
            ],
            "actions": [{"id": "action_essai_dossier", "name": "Dossiers",
                         "model": "essai.dossier", "view_modes": ["tree", "form"]}],
            "menus": [
                {"id": "menu_essai_racine", "name": "Essais", "sequence": 30},
                {"id": "menu_essai_dossiers", "name": "Dossiers",
                 "parent": "menu_essai_racine", "action": "action_essai_dossier"},
            ],
            "access": [{"model": "essai.dossier", "group": "base.group_user",
                        "perms": "rwcd"}],
        })

    def test_le_module_regenere_est_identique(self):
        origine = self._spec_structurelle()
        origine.valider()
        rendu = OdooModuleGenerator().generate(origine)

        with tempfile.TemporaryDirectory() as dossier:
            racine = _ecrire_module(dossier, rendu)
            relue, rapport = convertir(racine, "17.0")

        relue.valider()
        self.assertEqual(
            OdooModuleGenerator().generate(relue), rendu,
            "la relecture n'a pas retrouvé le module d'origine",
        )
        self.assertEqual(rapport.comportements_perdus, [],
                         "un module sans comportement n'a rien à perdre")

    def test_la_relecture_survit_au_changement_de_version(self):
        """Un module 17 relu et visé en 19 doit donner le module 19.

        C'est la promesse entière du convertisseur, et elle se vérifie sans
        Odoo : le module 19 obtenu par conversion doit être celui qu'on aurait
        généré en visant 19 dès le départ.
        """
        origine = self._spec_structurelle()
        rendu17 = OdooModuleGenerator().generate(origine)

        direct = self._spec_structurelle()
        direct.cible = "19.0"
        attendu19 = OdooModuleGenerator().generate(direct)

        with tempfile.TemporaryDirectory() as dossier:
            racine = _ecrire_module(dossier, rendu17)
            relue, _ = convertir(racine, "19.0")
        relue.valider()

        self.assertEqual(OdooModuleGenerator().generate(relue), attendu19)

    def test_la_version_fonctionnelle_traverse_la_conversion(self):
        """« 17.0.2.3.4 » relu et visé en 19 donne « 19.0.2.3.4 ».

        Sans la séparation cible / version, on obtiendrait « 19.0.17.0.2.3.4 »
        ou une version repartie de zéro — dans les deux cas, l'historique du
        module serait perdu au premier passage de version.
        """
        rendu = OdooModuleGenerator().generate(self._spec_structurelle())
        with tempfile.TemporaryDirectory() as dossier:
            racine = _ecrire_module(dossier, rendu)
            relue, rapport = convertir(racine, "19.0")
        self.assertEqual(relue.version, "2.3.4")
        self.assertEqual(rapport.version_origine, "17.0.2.3.4")
        self.assertIn("'19.0.2.3.4'",
                      OdooModuleGenerator().generate(relue)["atelier_essai/__manifest__.py"])


# Le module d'exemple vit sur DISQUE, dans exemples/suivi_dossier, et la
# recette multi-versions lit le même dossier. Le recopier ici en donnerait deux
# versions, et l'une se corrigerait sans l'autre — c'est exactement ce que la
# règle « importer, jamais recopier » interdit ailleurs dans ce dépôt.
EXEMPLE_V12 = os.path.join(RACINE, "exemples", "suivi_dossier")


def _copier_exemple(vers, remplacements=None):
    """Recopie le module d'exemple, en substituant éventuellement un fichier."""
    remplacements = remplacements or {}
    for dossier, _, noms in os.walk(EXEMPLE_V12):
        for nom in noms:
            source = os.path.join(dossier, nom)
            relatif = os.path.relpath(source, EXEMPLE_V12)
            cible = os.path.join(vers, relatif)
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(source, encoding="utf-8") as f:
                contenu = f.read()
            with open(cible, "w", encoding="utf-8") as f:
                f.write(remplacements.pop(relatif, contenu))
    for relatif, contenu in remplacements.items():
        cible = os.path.join(vers, relatif)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        with open(cible, "w", encoding="utf-8") as f:
            f.write(contenu)


class TestConversionV12(unittest.TestCase):
    """Un module écrit à la mode d'Odoo 12, relu pour Odoo 19."""

    def _convertir(self, cible="19.0", fichiers=None):
        self._dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self._dossier.cleanup)
        racine = os.path.join(self._dossier.name, "suivi_dossier")
        _copier_exemple(racine, dict(fichiers or {}))
        return convertir(racine, cible)

    def _quoi(self, rapport):
        return " | ".join(m.quoi for m in rapport.manques)

    # ------------------------------------------------------ ce qui est repris

    def test_le_module_converti_est_valide_et_se_genere(self):
        spec, _ = self._convertir()
        spec.valider()
        fichiers = OdooModuleGenerator().generate(spec)
        self.assertTrue(OdooStaticValidator().check(fichiers, spec).ok)

    def test_le_premier_positionnel_n_est_pas_lu_comme_un_comodele(self):
        """« fields.Many2one('res.partner', 'Client') » : deux sens différents.

        Lire le second argument comme un comodèle donnerait un modèle nommé
        « Client », et l'installation échouerait sur un modèle introuvable —
        loin d'ici, et sans rapport apparent avec la conversion.
        """
        spec, _ = self._convertir()
        modele = spec.models[0]
        client = next(c for c in modele.fields if c.name == "client_id")
        self.assertEqual(client.comodel, "res.partner")
        self.assertEqual(client.string, "Client")
        nom = next(c for c in modele.fields if c.name == "name")
        self.assertEqual(nom.string, "Référence")

    def test_la_version_perd_la_serie_et_garde_la_sienne(self):
        spec, rapport = self._convertir()
        self.assertEqual(rapport.version_origine, "12.0.1.3.0")
        self.assertEqual(spec.version, "1.3.0")
        self.assertIn(
            "'19.0.1.3.0'",
            OdooModuleGenerator().generate(spec)["suivi_dossier/__manifest__.py"],
        )

    def test_la_vue_liste_de_v12_devient_une_liste_de_19(self):
        """« tree » chez l'un, « list » chez l'autre : le dialecte tranche."""
        spec, _ = self._convertir("19.0")
        rendu = OdooModuleGenerator().generate(spec)
        vues = rendu["suivi_dossier/views/suivi_dossier_views.xml"]
        self.assertIn("<list>", vues)
        self.assertNotIn("<tree>", vues)

    # -------------------------------------------------- ce qui est signalé

    def test_un_champ_calcule_est_abandonne_et_non_degrade(self):
        """Le pire résultat possible serait de le garder.

        Conservé sans son calcul, « total » serait une colonne toujours vide
        qu'un écran afficherait comme une valeur juste. Le module s'installe,
        se comporte mal, et rien ne le dit.
        """
        spec, rapport = self._convertir()
        noms = {c.name for c in spec.models[0].fields}
        self.assertNotIn("total", noms)
        self.assertIn("champ « total » (compute=…)", self._quoi(rapport))
        # ...et la vue qui le citait ne le cite plus.
        liste = next(v for v in spec.views if v.type == "tree")
        self.assertNotIn("total", liste.fields)

    def test_un_defaut_illisible_ne_fait_pas_perdre_le_champ(self):
        """Un défaut en Python ne fausse rien : le champ démarre vide, c'est tout."""
        spec, rapport = self._convertir()
        noms = {c.name for c in spec.models[0].fields}
        self.assertIn("etiquette", noms)
        manque = next(m for m in rapport.manques if "etiquette" in m.quoi)
        self.assertEqual(manque.genre, STRUCTURE)

    def test_les_methodes_sont_nommees_une_par_une(self):
        spec, rapport = self._convertir()
        quoi = self._quoi(rapport)
        self.assertIn("action_valider", quoi)
        self.assertIn("_compute_total", quoi)
        transition = next(m for m in rapport.manques if "action_valider" in m.quoi)
        self.assertEqual(transition.genre, COMPORTEMENT)
        # On dit ce que la méthode écrit, sans prétendre l'avoir portée.
        self.assertIn("state", transition.conduite)
        self.assertIn("valide", transition.conduite)
        self.assertIsNone(spec.models[0].lifecycle,
                          "le convertisseur ne doit jamais inventer un cycle de vie")

    def test_les_tournures_perimees_sont_signalees(self):
        _, rapport = self._convertir()
        perimees = {m.quoi for m in rapport.manques if m.genre == OBSOLETE}
        joint = " | ".join(perimees)
        for attendu in ("__openerp__.py", "openerp", "<openerp>",
                        "@api.multi", "attrs", "view_type"):
            self.assertIn(attendu, joint, f"« {attendu} » n'a pas été signalé")

    def test_un_champ_de_vue_inexistant_est_retire(self):
        """Odoo refuse une vue citant un champ absent : on coupe près de la cause."""
        spec, rapport = self._convertir()
        liste = next(v for v in spec.views if v.type == "tree")
        self.assertNotIn("inexistant", liste.fields)
        self.assertIn("inexistant", self._quoi(rapport))

    def test_les_contraintes_sql_sont_signalees_comme_comportement(self):
        _, rapport = self._convertir()
        manque = next(m for m in rapport.manques if "_sql_constraints" in m.quoi)
        self.assertEqual(manque.genre, COMPORTEMENT)

    def test_un_bouton_sans_sa_methode_est_signale(self):
        _, rapport = self._convertir()
        self.assertIn("bouton « action_valider »", self._quoi(rapport))

    # ------------------------------------------------------------- refus nets

    def test_un_dossier_sans_manifeste_est_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            with self.assertRaises(ConversionImpossible):
                convertir(dossier, "19.0")

    def test_le_code_lu_n_est_jamais_execute(self):
        """Convertir un module ne doit pas être une façon de l'exécuter.

        Un module converti vient d'ailleurs — d'un client, du dépôt d'Odoo.
        Si la lecture l'importait, il suffirait de faire convertir un module
        pour faire tourner ce qu'il contient.
        """
        with open(os.path.join(EXEMPLE_V12, "models", "dossier.py"),
                  encoding="utf-8") as f:
            original = f.read()
        piege = {"models/dossier.py":
                 "import os\nos.environ['ATELIER_CODE_EXECUTE'] = 'oui'\n" + original}
        os.environ.pop("ATELIER_CODE_EXECUTE", None)
        self._convertir(fichiers=piege)
        self.assertNotIn("ATELIER_CODE_EXECUTE", os.environ)

    def test_les_droits_inventes_sont_annonces_comme_tels(self):
        """C'est la seule chose qui rende le converti plus ouvert que l'original.

        Le module d'origine ne déclare aucun droit : chez lui, seul le
        super-utilisateur voit le modèle. Le converti l'ouvre aux utilisateurs
        internes. Une décision de sécurité prise par un outil doit être
        écrite en toutes lettres, jamais déduite du silence.
        """
        spec, rapport = self._convertir()
        self.assertEqual([a.model for a in spec.access], ["suivi.dossier"])
        manque = next(m for m in rapport.manques if "droits inventés" in m.quoi)
        self.assertEqual(manque.genre, COMPORTEMENT)
        self.assertIn("PLUS permissif", manque.pourquoi)
        self.assertIn("restreindre", manque.conduite)

    def test_des_droits_existants_ne_sont_pas_remplaces(self):
        avec_droits = {"security/ir.model.access.csv": (
            "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
            "acc_dossier,acc.dossier,model_suivi_dossier,base.group_system,1,0,0,0\n"
        )}
        spec, rapport = self._convertir(fichiers=avec_droits)
        self.assertEqual(spec.access[0].group, "base.group_system")
        self.assertEqual(spec.access[0].perms, "r")
        self.assertNotIn("droits inventés", self._quoi(rapport))

    def test_les_renommages_documentes_sont_nommes_par_leur_nouveau_nom(self):
        """« argument inconnu » n'aide personne ; « renommé aggregator » si.

        Relevé dans le journal officiel de l'ORM (odoo/documentation 19.0,
        backend/orm/changelog.rst, Odoo Online 17.2), puis vérifié en source.
        """
        _, rapport = self._convertir()
        manque = next(m for m in rapport.manques if "group_operator" in m.quoi)
        self.assertEqual(manque.genre, OBSOLETE)
        self.assertIn("aggregator", manque.pourquoi)

    def test_une_methode_disparue_n_est_pas_donnee_a_reecrire(self):
        """Réécrite à l'identique, « name_get » ne serait plus appelée."""
        _, rapport = self._convertir()
        disparue = next(m for m in rapport.manques
                        if m.genre == OBSOLETE and "name_get" in m.quoi)
        self.assertIn("display_name", disparue.pourquoi)

    def test_les_contraintes_sql_disent_qu_odoo_19_les_ignore(self):
        """Le point décisif n'est pas la conversion, c'est Odoo 19 lui-même.

        « _sql_constraints » n'y est plus appliqué : Odoo journalise un
        avertissement et la contrainte disparaît sans erreur
        (odoo/orm/model_classes.py, 19.0). Recopier le code ne la sauverait
        donc pas — et c'est précisément ce qu'un lecteur du rapport
        supposerait si on ne le disait pas.
        """
        _, rapport = self._convertir()
        manque = next(m for m in rapport.manques if "_sql_constraints" in m.quoi)
        self.assertEqual(manque.genre, COMPORTEMENT)
        self.assertIn("Odoo 19 ne l'applique plus", manque.pourquoi)
        self.assertIn("sans erreur", manque.pourquoi)


from converter.apports import ACQUIS, A_SAISIR, CATALOGUE, calculer, par_version  # noqa: E402


class TestApportsDeVersion(unittest.TestCase):
    """Ce que la version d'arrivée fait nativement là où le module fait à la main.

    C'est l'autre moitié d'une migration : porter fidèlement un contournement
    de v12 vers la v19 revient à réimplanter à grands frais ce que la v19
    offre. Encore faut-il que la liste soit une information et non un
    prospectus — d'où les deux règles que ces contrôles tiennent.
    """

    def _observations(self, module=None):
        from converter.extraction import Extracteur
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        racine = os.path.join(dossier.name, "suivi_dossier")
        _copier_exemple(racine, dict(module or {}))
        extracteur = Extracteur(racine, "17.0")
        extracteur.convertir()
        return extracteur.observations

    def test_un_apport_absent_de_la_cible_n_est_pas_promis(self):
        """« models.Constraint » n'existe qu'en 19 : le promettre en 17 serait faux.

        C'est la règle qui donne son sens à la comparaison entre versions. Sans
        elle, les trois cibles diraient la même chose, et l'outil ne
        répondrait plus à « qu'est-ce que la 19 m'apporte de plus ».
        """
        observations = self._observations()
        motifs = {a.regle.marqueur for a in calculer(observations, "17.0")}
        self.assertNotIn("sql_constraints", motifs)
        self.assertNotIn("group_operator", motifs)
        self.assertIn("sql_constraints", {a.regle.marqueur
                                          for a in calculer(observations, "19.0")})

    def test_chaque_version_ajoute_a_la_precedente_sans_rien_retirer(self):
        """Un apport acquis en 17 ne disparaît pas en 19."""
        tables = par_version(self._observations())
        for precedente, suivante in (("17.0", "18.0"), ("18.0", "19.0")):
            avant = {a.regle.marqueur for a in tables[precedente]}
            apres = {a.regle.marqueur for a in tables[suivante]}
            self.assertTrue(avant <= apres,
                            f"{sorted(avant - apres)} perdu(s) entre "
                            f"{precedente} et {suivante}")
        self.assertGreater(len(tables["19.0"]), len(tables["17.0"]))

    def test_rien_n_est_annonce_que_le_module_ne_contienne(self):
        """Pas de « saviez-vous que ». Chaque apport est ancré dans le module.

        Un module qui ne fait rien à l'ancienne n'a rien à gagner : le dire
        quand même transformerait le rapport en argumentaire, et personne ne
        le lirait plus.
        """
        propre = ModuleSpec.depuis_dict({
            "technical_name": "atelier_propre", "name": "Propre",
            "cible": "17.0",
            "models": [{"name": "propre.chose", "fields": [
                {"name": "name", "type": "char", "string": "Nom"}]}],
        })
        rendu = OdooModuleGenerator().generate(propre)
        with tempfile.TemporaryDirectory() as dossier:
            racine = _ecrire_module(dossier, rendu)
            _, rapport = convertir(racine, "19.0")
        self.assertEqual(rapport.apports, [],
                         "un module déjà moderne n'a aucun apport à recevoir")

    def test_chaque_apport_ancre_son_motif_dans_un_fichier(self):
        for apport in calculer(self._observations(), "19.0"):
            self.assertTrue(apport.fichier, f"{apport.regle.marqueur} sans fichier")

    def test_les_apports_distinguent_l_acquis_du_reste(self):
        """« <list> » est acquis par régénération ; « aggregator » demande une réécriture.

        Confondre les deux ferait croire que la conversion a modernisé du code
        qu'elle n'a même pas repris.
        """
        apports = {a.regle.marqueur: a.regle.genre
                   for a in calculer(self._observations(), "19.0")}
        self.assertEqual(apports["balise_tree"], ACQUIS)
        self.assertEqual(apports["attrs"], ACQUIS)
        self.assertEqual(apports["group_operator"], A_SAISIR)
        self.assertEqual(apports["sql_constraints"], A_SAISIR)

    def test_chaque_regle_du_catalogue_porte_sa_verification(self):
        """Une règle qu'on ne sait pas justifier n'a rien à faire dans le catalogue.

        C'est la même discipline que pour le dialecte : une différence
        supposée est pire qu'une différence ignorée, parce qu'elle produit une
        recommandation qui a l'air juste.
        """
        for regle in CATALOGUE:
            self.assertTrue(regle.verification.strip(),
                            f"« {regle.marqueur} » sans vérification")
            self.assertIn(regle.depuis, (17, 18, 19))
            self.assertIn(regle.genre, (ACQUIS, A_SAISIR))


class TestLireEstPlusLargeQueEcrire(unittest.TestCase):
    """Nos contrôles étaient plus stricts qu'Odoo, et refusaient du code légal.

    Six modules de production sur dix étaient inconvertibles — non parce
    qu'Odoo les refuserait, mais parce que la spécification imposait des
    conventions que la plateforme n'applique pas elle-même. Un outil de
    conversion qui refuse ce qu'Odoo accepte n'est pas rigoureux : il est
    inutilisable.

    Desserrer un contrôle est l'opération la plus risquée qui soit. Ces
    contrôles disent exactement jusqu'où, et pas plus loin.
    """

    def _minimal(self, **remplacements):
        base = {
            "technical_name": "atelier_lecture", "name": "Lecture",
            "cible": "17.0",
            "models": [{"name": "essai.chose", "fields": [
                {"name": "name", "type": "char", "string": "Nom"}]}],
        }
        base.update(remplacements)
        return ModuleSpec.depuis_dict(base)

    def test_un_nom_de_champ_avec_majuscules_est_accepte(self):
        """Un nom de champ est un attribut Python ; Odoo n'impose rien de plus."""
        self._minimal(models=[{"name": "essai.chose", "fields": [
            {"name": "reading_and_validation_of_the_CR", "type": "char",
             "string": "Lecture et validation du CR"}]}]).valider()

    def test_un_nom_de_champ_reste_un_identifiant(self):
        """Desserré, pas supprimé : « 2eme-champ » n'est toujours pas un nom."""
        for mauvais in ("2eme", "champ-tiret", "champ espace", ""):
            with self.assertRaises(SpecInvalide, msg=mauvais):
                self._minimal(models=[{"name": "essai.chose", "fields": [
                    {"name": mauvais, "type": "char", "string": "X"}]}]).valider()

    def test_un_nom_de_modele_sans_point_est_accepte(self):
        """« _name = 'suivi_diligence' » s'installe très bien en Odoo."""
        self._minimal(models=[{"name": "suivi_diligence", "fields": [
            {"name": "name", "type": "char", "string": "Nom"}]}]).valider()

    def test_un_nom_de_modele_reste_contraint(self):
        for mauvais in ("Suivi.Diligence", "suivi diligence", ".suivi", "1suivi"):
            with self.assertRaises(SpecInvalide, msg=mauvais):
                self._minimal(models=[{"name": mauvais, "fields": [
                    {"name": "name", "type": "char", "string": "N"}]}]).valider()

    def test_un_module_sans_donnees_reste_valide(self):
        """Une extension purement Python n'a aucun fichier de données.

        Exiger « data » non vide refusait des modules qu'Odoo installe sans
        broncher — et le refus tombait à la conversion, loin de sa cause.
        """
        spec = self._minimal(models=[{"name": "res.partner", "inherit": "res.partner",
                                      "fields": [{"name": "x_note", "type": "char",
                                                  "string": "Note"}]}])
        fichiers = OdooModuleGenerator().generate(spec)
        rapport = OdooStaticValidator().check(fichiers, spec)
        self.assertTrue(rapport.ok, rapport.texte())

    def test_un_manifeste_sans_cle_data_reste_refuse(self):
        """Absente n'est pas vide : Odoo lit « data », il faut que la clé existe."""
        spec = self._minimal()
        fichiers = OdooModuleGenerator().generate(spec)
        chemin = "atelier_lecture/__manifest__.py"
        fichiers[chemin] = fichiers[chemin].replace("'data':", "'donnees':")
        rapport = OdooStaticValidator().check(fichiers, spec)
        self.assertFalse(rapport.ok)
        self.assertIn("data", rapport.texte())

    def test_le_fournisseur_d_un_modele_consulte_les_dependances(self):
        """« quick.meetings » vient de « quick_meetings », pas d'un module « quick ».

        La correspondance nom de modèle / nom de module est une convention,
        pas une règle. La prendre pour une règle faisait accuser une
        dépendance manquante en citant un module qui n'existe pas.
        """
        from validator.odoo_static_validator import module_fournisseur
        self.assertEqual(module_fournisseur("quick.meetings", {"quick_meetings"}),
                         "quick_meetings")
        self.assertEqual(module_fournisseur("hr.employee", {"hr"}), "hr")
        # Sans dépendance qui corresponde, la convention reprend ses droits.
        self.assertEqual(module_fournisseur("quick.meetings", set()), "quick")

    def test_une_relation_vraiment_absente_est_toujours_refusee(self):
        """Desserré, pas aveugle."""
        spec = self._minimal(depends=["base"], models=[{"name": "essai.chose", "fields": [
            {"name": "agent_id", "type": "many2one", "string": "Agent",
             "comodel": "hr.employee"}]}])
        fichiers = OdooModuleGenerator().generate(spec)
        rapport = OdooStaticValidator().check(fichiers, spec)
        self.assertFalse(rapport.ok)
        self.assertIn("hr", rapport.texte())


class TestConversionNeCasseRienEnAval(unittest.TestCase):
    """Ce que le convertisseur écarte doit partir avec tout ce qui en dépend."""

    def _convertir(self, fichiers):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        racine = os.path.join(dossier.name, "suivi_dossier")
        _copier_exemple(racine, dict(fichiers))
        return convertir(racine, "19.0")

    def test_un_menu_perd_sa_cible_avec_l_action_ecartee(self):
        """Un menu sans cible fait échouer le CHARGEMENT du module.

        Et le message d'Odoo parle d'une référence externe introuvable : rien
        n'indique que c'est la conversion qui a retiré l'action.
        """
        vues = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="action_gantt" model="ir.actions.act_window">
    <field name="name">Planning</field>
    <field name="res_model">suivi.dossier</field>
    <field name="view_mode">gantt</field>
  </record>
  <menuitem id="menu_gantt" name="Planning" action="suivi_dossier.action_gantt"/>
</odoo>
"""
        spec, rapport = self._convertir({"views/dossier_view.xml": vues})
        spec.valider()
        self.assertEqual(spec.menus, [], "le menu devait partir avec son action")
        self.assertIn("modes ['gantt']", " | ".join(m.quoi for m in rapport.manques))

    def test_une_reference_pointee_vers_son_propre_module_est_interne(self):
        """« mails_tracker.action_x » écrit dans « mails_tracker » vise sa propre action."""
        vues = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="action_dossier" model="ir.actions.act_window">
    <field name="name">Dossiers</field>
    <field name="res_model">suivi.dossier</field>
    <field name="view_mode">tree,form</field>
  </record>
  <menuitem id="menu_dossier" name="Dossiers" action="suivi_dossier.action_dossier"/>
</odoo>
"""
        spec, _ = self._convertir({"views/dossier_view.xml": vues})
        spec.valider()
        self.assertEqual([m.action for m in spec.menus], ["action_dossier"])

    def test_une_vue_de_type_inconnu_n_invalide_pas_le_module(self):
        """Un seul écran exotique empêchait la conversion du module entier."""
        vues = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="vue_gantt" model="ir.ui.view">
    <field name="name">planning</field>
    <field name="model">suivi.dossier</field>
    <field name="arch" type="xml"><gantt date_start="montant"/></field>
  </record>
</odoo>
"""
        spec, rapport = self._convertir({"views/dossier_view.xml": vues})
        spec.valider()
        self.assertEqual([v.type for v in spec.views], [])
        self.assertIn("type « gantt »", " | ".join(m.quoi for m in rapport.manques))


class TestAtelierLocal(unittest.TestCase):
    """L'Atelier assemble la chaîne ; ces contrôles tiennent ses invariants.

    Ce ne sont pas des contrôles d'affichage : ils portent sur les trois
    promesses qui font qu'on peut confier un besoin à cet outil — la clé reste
    au serveur, le modèle n'écrit que de la spécification, et rien n'est
    montré qui n'ait passé le validateur.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "cli"))
        import atelier
        self.module = atelier
        self.atelier = atelier.Atelier()

    def test_la_page_ne_contient_aucune_valeur_de_cle(self):
        """La page nomme les variables d'environnement ; elle ne les lit pas.

        Nommer « BUILDER_IA_CLE » aide l'utilisateur à démarrer. En livrer la
        valeur mettrait une clé d'API dans le presse-papier de quiconque
        ouvre le code source de la page.
        """
        from interface_web import PAGE
        for temoin in ("sk-", "BUILDER_IA_CLE=", "OPENAI_API_KEY="):
            self.assertNotIn(temoin, PAGE, f"« {temoin} » ne doit pas figurer")
        # Le NOM, lui, doit y être : sans lui, personne ne sait quoi définir.
        self.assertIn("BUILDER_IA_CLE", PAGE)

    def test_rien_n_est_retenu_qui_ne_valide_pas(self):
        """Montrer une spécification invalide reviendrait à la faire approuver."""
        with self.assertRaises(SpecInvalide):
            self.atelier.charger({"technical_name": "x", "name": "X",
                                  "models": [{"name": "mauvais nom"}]}, "17.0")
        self.assertIsNone(self.atelier.spec)

    def test_une_conversion_alimente_l_apercu_et_l_archive(self):
        origine = ModuleSpec.depuis_dict({
            "technical_name": "atelier_boucle", "name": "Boucle",
            "cible": "17.0",
            "models": [{"name": "boucle.chose", "description": "Chose",
                        "fields": [{"name": "name", "type": "char",
                                    "string": "Nom", "required": True}]}],
            "views": [{"model": "boucle.chose", "type": "form", "name": "Chose",
                       "fields": ["name"]}],
            "access": [{"model": "boucle.chose"}],
        })
        with tempfile.TemporaryDirectory() as dossier:
            racine = _ecrire_module(dossier, OdooModuleGenerator().generate(origine))
            resume = self.atelier.convertir(racine, "19.0")

        self.assertEqual(resume["cible"], "19.0")
        self.assertTrue(resume["valide"])
        self.assertIn("conversion", resume)

        apercu = self.atelier.apercu().decode("utf-8")
        self.assertIn("data-modele=\"boucle.chose\"", apercu)
        self.assertNotIn("eval(", apercu)

        with zipfile.ZipFile(io.BytesIO(self.atelier.archive())) as z:
            noms = z.namelist()
            self.assertIn("atelier_boucle/__manifest__.py", noms)
            manifeste = z.read("atelier_boucle/__manifest__.py").decode("utf-8")
        self.assertIn("'19.0.1.0.0'", manifeste)

    def test_concevoir_sans_fournisseur_dit_quoi_faire(self):
        """Un outil qui ne peut pas travailler doit dire pourquoi, pas échouer."""
        garde = {c: os.environ.pop(c, None) for c in
                 ("BUILDER_IA_CLE", "OPENAI_API_KEY", "KIMI_API_KEY", "ANTHROPIC_API_KEY")}
        try:
            with self.assertRaises(RuntimeError) as boite:
                self.atelier.concevoir("un besoin quelconque assez long", "17.0")
            self.assertIn("BUILDER_IA_CLE", str(boite.exception))
            self.assertIn("jamais dans le navigateur", str(boite.exception))
        finally:
            for cle, valeur in garde.items():
                if valeur is not None:
                    os.environ[cle] = valeur

    def test_ce_qui_est_declare_cache_le_reste_vraiment(self):
        """« hidden » doit l'emporter sur toute règle d'affichage.

        Une classe posant « display:flex » écrase l'attribut « hidden » du
        HTML : l'Atelier affichait un bouton « Télécharger le module » avant
        qu'aucun module n'existe, et le cliquer donnait une erreur. Le défaut
        ne se lit pas dans la source — il naît de la cascade, et seul un
        contrôle explicite l'empêche de revenir.
        """
        from interface_web import PAGE
        self.assertIn("[hidden]{display:none !important}", PAGE)
        # Les blocs concernés doivent bien porter l'attribut au départ.
        for identifiant in ('id="carte-resume"', 'id="carte-journal"', 'id="erreur"'):
            debut = PAGE.index(identifiant)
            self.assertIn("hidden", PAGE[debut:debut + 120],
                          f"{identifiant} devrait démarrer caché")


class TestMemoireDeLAtelier(unittest.TestCase):
    """Un projet doit survivre à la fermeture d'un onglet.

    C'est ce qui sépare un outil qu'on lance d'une application qu'on habite.
    Sans mémoire, changer de poste ou revenir le lendemain fait tout
    recommencer — et un outil qu'on doit recommencer, on cesse de l'utiliser.
    """

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self._dossier.cleanup)
        sys.path.insert(0, os.path.join(RACINE, "src"))
        from persistance.depot import Depot
        self.depot = Depot(os.path.join(self._dossier.name, "essai.sqlite"))

    def test_un_projet_se_retrouve_apres_fermeture(self):
        identifiant = self.depot.enregistrer(
            nom="Missions", genre="module", cible="17.0",
            technique="mission_management", contenu={"technical_name": "x"},
            horodatage="2026-08-16T10:00:00", motif="première")
        # Un second dépôt sur le MÊME fichier : c'est la situation réelle,
        # un processus qui redémarre.
        from persistance.depot import Depot
        autre = Depot(self.depot.chemin)
        projet = autre.ouvrir(identifiant)
        self.assertIsNotNone(projet)
        self.assertEqual(projet.nom, "Missions")
        self.assertEqual(projet.contenu["technical_name"], "x")

    def test_chaque_enregistrement_laisse_une_trace(self):
        """Sans historique, corriger écrase la version qui marchait."""
        identifiant = self.depot.enregistrer(
            nom="A", genre="module", cible="17.0", technique="a",
            contenu={"v": 1}, horodatage="2026-08-16T10:00:00", motif="départ")
        self.depot.enregistrer(
            nom="A", genre="module", cible="17.0", technique="a",
            contenu={"v": 2}, horodatage="2026-08-16T11:00:00",
            identifiant=identifiant, motif="correction")

        self.assertEqual(self.depot.ouvrir(identifiant).contenu, {"v": 2})
        historique = self.depot.historique(identifiant)
        self.assertEqual(len(historique), 2)
        self.assertEqual([h["motif"] for h in historique], ["correction", "départ"])
        # On doit pouvoir revenir à l'état d'avant.
        ancienne = historique[-1]["id"]
        self.assertEqual(self.depot.revision(identifiant, ancienne), {"v": 1})

    def test_une_revision_ne_se_lit_pas_depuis_un_autre_projet(self):
        """Connaître un numéro ne doit pas suffire à lire ailleurs."""
        premier = self.depot.enregistrer(
            nom="A", genre="module", cible="17.0", technique="a",
            contenu={"secret": "A"}, horodatage="2026-08-16T10:00:00")
        second = self.depot.enregistrer(
            nom="B", genre="module", cible="17.0", technique="b",
            contenu={"secret": "B"}, horodatage="2026-08-16T10:01:00")
        numero = self.depot.historique(premier)[0]["id"]
        self.assertEqual(self.depot.revision(premier, numero), {"secret": "A"})
        self.assertIsNone(self.depot.revision(second, numero))

    def test_supprimer_un_projet_emporte_ses_revisions(self):
        """Sans les clés étrangères actives, elles resteraient orphelines."""
        identifiant = self.depot.enregistrer(
            nom="A", genre="module", cible="17.0", technique="a",
            contenu={"v": 1}, horodatage="2026-08-16T10:00:00")
        self.assertTrue(self.depot.supprimer(identifiant))
        self.assertIsNone(self.depot.ouvrir(identifiant))
        self.assertEqual(self.depot.historique(identifiant), [])
        self.assertFalse(self.depot.supprimer(identifiant))

    def test_les_projets_sortent_du_plus_recent_au_plus_ancien(self):
        for numero, heure in enumerate(("10:00:00", "12:00:00", "11:00:00")):
            self.depot.enregistrer(
                nom=f"P{numero}", genre="module", cible="17.0",
                technique=f"p{numero}", contenu={},
                horodatage=f"2026-08-16T{heure}")
        self.assertEqual([p.nom for p in self.depot.lister()], ["P1", "P2", "P0"])
