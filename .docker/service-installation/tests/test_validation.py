"""Recette des barrières de sécurité : c'est la partie qui *est* le produit."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import validation
from tests.fabrique import MANIFESTE, ecrire_zip, module_valide, zip_avec_lien


class BaseTemporaire(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def refus(self, chemin, limites=None, proteges=()):
        with self.assertRaises(validation.Refus) as capture:
            validation.inspecter(chemin, limites, proteges)
        return capture.exception


class TestArchiveAcceptable(BaseTemporaire):
    def test_module_minimal_accepte(self):
        chemin = module_valide(self.dossier)
        self.assertEqual(validation.inspecter(chemin), "module_recette")

    def test_extraction_ecrit_les_fichiers(self):
        chemin = module_valide(self.dossier)
        cible = os.path.join(self.dossier, "sortie")
        module = validation.extraire(chemin, cible)
        self.assertEqual(module, "module_recette")
        self.assertTrue(
            os.path.isfile(
                os.path.join(cible, "module_recette", "__manifest__.py")
            )
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(cible, "module_recette", "models", "__init__.py")
            )
        )


class TestCheminsMalveillants(BaseTemporaire):
    def test_remontee_de_dossier_refusee(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "a.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette/../../evasion.py": "print('dehors')",
            },
        )
        self.assertIn("Remontée", str(self.refus(chemin)))

    def test_chemin_absolu_refuse(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "b.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "/etc/cron.d/charge": "* * * * * root sh",
            },
        )
        self.assertIn("absolu", str(self.refus(chemin)))

    def test_separateur_windows_refuse(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "c.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette\\..\\evasion.py": "x = 1",
            },
        )
        self.assertIn("Windows", str(self.refus(chemin)))

    def test_lien_symbolique_refuse(self):
        chemin = zip_avec_lien(self.dossier)
        self.assertIn("Lien symbolique", str(self.refus(chemin)))

    def test_extraction_ne_sort_pas_du_dossier(self):
        """Contrôle de bout en bout : rien ne doit être écrit au-dessus."""
        chemin = ecrire_zip(
            os.path.join(self.dossier, "d.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette/../../evasion.py": "print('dehors')",
            },
        )
        cible = os.path.join(self.dossier, "racine", "sortie")
        with self.assertRaises(validation.Refus):
            validation.extraire(chemin, cible)
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "evasion.py")))


class TestNomDeModule(BaseTemporaire):
    def test_deux_dossiers_racine_refuses(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "e.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "autre_module/__manifest__.py": MANIFESTE,
            },
        )
        self.assertIn("un seul dossier racine", str(self.refus(chemin)))

    def test_majuscules_refusees(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "f.zip"),
            {"ModuleRecette/__manifest__.py": MANIFESTE},
        )
        self.assertIn("Nom de module refusé", str(self.refus(chemin)))

    def test_nom_reserve_refuse(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "g.zip"),
            {"base/__manifest__.py": MANIFESTE},
        )
        self.assertIn("réservé", str(self.refus(chemin)))

    def test_module_des_sources_git_protege(self):
        chemin = module_valide(self.dossier, "ansut_rh")
        refus = self.refus(chemin, proteges=frozenset({"ansut_rh"}))
        self.assertIn("sources Git", str(refus))

    def test_modules_des_sources_repere_les_manifestes(self):
        sources = os.path.join(self.dossier, "sources")
        os.makedirs(os.path.join(sources, "ansut_rh"))
        os.makedirs(os.path.join(sources, "pas_un_module"))
        open(os.path.join(sources, "ansut_rh", "__manifest__.py"), "w").close()
        self.assertEqual(
            validation.modules_des_sources(sources), frozenset({"ansut_rh"})
        )


class TestManifeste(BaseTemporaire):
    def test_manifeste_absent_refuse(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "h.zip"),
            {"module_recette/__init__.py": ""},
        )
        self.assertIn("__manifest__.py", str(self.refus(chemin)))

    def test_manifeste_non_litteral_refuse(self):
        """Un manifeste qui exécute du code est refusé avant d'atteindre Odoo."""
        chemin = ecrire_zip(
            os.path.join(self.dossier, "i.zip"),
            {
                "module_recette/__manifest__.py": (
                    "__import__('os').system('id')\n{'name': 'x'}"
                )
            },
        )
        self.assertIn("littéral", str(self.refus(chemin)))

    def test_manifeste_sans_nom_refuse(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "j.zip"),
            {"module_recette/__manifest__.py": "{'version': '1.0'}"},
        )
        self.assertIn("name", str(self.refus(chemin)))


class TestPlafonds(BaseTemporaire):
    def test_archive_trop_grosse_refusee(self):
        chemin = module_valide(self.dossier)
        refus = self.refus(chemin, validation.Limites(taille_archive=10))
        self.assertEqual(refus.code, 413)

    def test_trop_de_fichiers_refuse(self):
        entrees = {"module_recette/__manifest__.py": MANIFESTE}
        for i in range(10):
            entrees[f"module_recette/f{i}.py"] = "x = 1"
        chemin = ecrire_zip(os.path.join(self.dossier, "k.zip"), entrees)
        refus = self.refus(chemin, validation.Limites(nombre_fichiers=3))
        self.assertEqual(refus.code, 413)

    def test_bombe_zip_refusee(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "l.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette/charge.bin": "0" * 2_000_000,
            },
        )
        self.assertIn("compression", str(self.refus(chemin)))

    def test_taille_decompressee_plafonnee(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "m.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette/charge.bin": "0" * 100_000,
            },
        )
        refus = self.refus(
            chemin,
            validation.Limites(taille_decompressee=1000, ratio_compression=10**9),
        )
        self.assertEqual(refus.code, 413)

    def test_fichier_illisible_refuse(self):
        chemin = os.path.join(self.dossier, "n.zip")
        with open(chemin, "wb") as f:
            f.write(b"ceci n'est pas une archive")
        self.assertIn("ZIP", str(self.refus(chemin)))

    def test_archive_vide_refusee(self):
        chemin = os.path.join(self.dossier, "o.zip")
        open(chemin, "wb").close()
        self.assertIn("vide", str(self.refus(chemin)))


if __name__ == "__main__":
    unittest.main()
