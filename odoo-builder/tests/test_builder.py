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
