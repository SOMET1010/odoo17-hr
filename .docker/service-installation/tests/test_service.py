"""Recette de l'API : authentification, plafonds, cycle de vie d'une demande.

Odoo est remplacé par une doublure : ce qui est vérifié ici, c'est le
service lui-même — qui il laisse entrer, ce qu'il refuse, et ce qu'il
rapporte. L'installation réelle est prouvée par l'étape 8 de
.docker/verifier-runtime.sh, sur une vraie pile.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.fabrique import MANIFESTE, ecrire_zip, module_valide

CLE = "cle-de-recette"
_ADDONS = tempfile.mkdtemp()
_SOURCES = tempfile.mkdtemp()

# La configuration est lue à l'import : elle doit être posée avant.
os.environ["CLE_API"] = CLE
os.environ["DOSSIER_ADDONS"] = _ADDONS
os.environ["DOSSIER_SOURCES"] = _SOURCES
os.environ["TAILLE_MAX_MO"] = "1"

import service  # noqa: E402 - import après configuration de l'environnement

PORT = 0
_serveur = None
INSTALLES: list[str] = []


def _installer_doublure(travail):
    """Doublure d'Odoo : échoue sur un module convenu, réussit sinon."""
    if travail.module == "module_casse":
        raise RuntimeError("Odoo refuse ce module")
    INSTALLES.append(travail.module)
    travail.tracer("Installation simulée.")


def setUpModule():
    global PORT, _serveur
    service.ouvrier.installer = _installer_doublure
    service.ouvrier.demarrer()
    _serveur = ThreadingHTTPServer(("127.0.0.1", 0), service.Poignee)
    PORT = _serveur.server_address[1]
    threading.Thread(target=_serveur.serve_forever, daemon=True).start()


def tearDownModule():
    if _serveur is not None:
        _serveur.shutdown()
    shutil.rmtree(_ADDONS, ignore_errors=True)
    shutil.rmtree(_SOURCES, ignore_errors=True)


def _appeler(methode: str, chemin: str, corps=None, cle=CLE):
    requete = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{chemin}", data=corps, method=methode
    )
    if cle is not None:
        requete.add_header("X-Cle-Api", cle)
    if corps is not None:
        requete.add_header("Content-Type", "application/zip")
    try:
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            return reponse.status, json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        return erreur.code, json.loads(erreur.read().decode("utf-8"))


def _deposer(chemin_zip: str, cle=CLE):
    with open(chemin_zip, "rb") as f:
        return _appeler("POST", "/modules", f.read(), cle)


def _attendre_fin(identifiant: str, limite: float = 10.0) -> dict:
    """Attend que la demande quitte les états transitoires."""
    echeance = time.time() + limite
    while time.time() < echeance:
        code, charge = _appeler("GET", f"/modules/{identifiant}")
        if charge.get("etat") in ("success", "failed"):
            return charge
        time.sleep(0.05)
    raise AssertionError(f"La demande {identifiant} n'est pas retombée à temps.")


class TestAuthentification(unittest.TestCase):
    def test_sante_ne_demande_pas_de_cle(self):
        code, charge = _appeler("GET", "/sante", cle=None)
        self.assertEqual(code, 200)
        self.assertEqual(charge["etat"], "ok")

    def test_depot_sans_cle_refuse(self):
        code, _ = _appeler("POST", "/modules", b"peu importe", cle=None)
        self.assertEqual(code, 401)

    def test_depot_avec_mauvaise_cle_refuse(self):
        code, _ = _appeler("POST", "/modules", b"peu importe", cle="mauvaise")
        self.assertEqual(code, 401)

    def test_consultation_sans_cle_refusee(self):
        code, _ = _appeler("GET", "/modules/inexistant", cle=None)
        self.assertEqual(code, 401)


class TestRoutes(unittest.TestCase):
    def test_route_inconnue(self):
        self.assertEqual(_appeler("GET", "/autre")[0], 404)

    def test_demande_inconnue(self):
        self.assertEqual(_appeler("GET", "/modules/inconnue")[0], 404)

    def test_corps_vide_refuse(self):
        self.assertEqual(_appeler("POST", "/modules", b"")[0], 400)


class TestDepot(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def test_module_valide_est_installe(self):
        chemin = module_valide(self.dossier, "module_bienvenu")
        code, charge = _deposer(chemin)
        self.assertEqual(code, 202)
        self.assertEqual(charge["etat"], "queued")
        self.assertEqual(charge["module"], "module_bienvenu")

        final = _attendre_fin(charge["id"])
        self.assertEqual(final["etat"], "success")
        self.assertIn("module_bienvenu", INSTALLES)
        # Le module doit être posé dans le volume d'addons dédié.
        self.assertTrue(
            os.path.isfile(
                os.path.join(_ADDONS, "module_bienvenu", "__manifest__.py")
            )
        )

    def test_echec_odoo_rapporte_en_failed(self):
        chemin = module_valide(self.dossier, "module_casse")
        code, charge = _deposer(chemin)
        self.assertEqual(code, 202)
        final = _attendre_fin(charge["id"])
        self.assertEqual(final["etat"], "failed")
        self.assertIn("refuse ce module", final["erreur"])

    def test_archive_malveillante_refusee_immediatement(self):
        chemin = ecrire_zip(
            os.path.join(self.dossier, "evasion.zip"),
            {
                "module_recette/__manifest__.py": MANIFESTE,
                "module_recette/../../evasion.py": "print('dehors')",
            },
        )
        code, charge = _deposer(chemin)
        self.assertEqual(code, 400)
        self.assertIn("Remontée", charge["erreur"])

    def test_archive_hors_gabarit_refusee(self):
        # Le plafond est à 1 Mio dans cette recette : on dépasse franchement.
        code, charge = _appeler("POST", "/modules", b"0" * (2 * 1024 * 1024))
        self.assertEqual(code, 413)

    def test_module_des_sources_git_refuse(self):
        os.makedirs(os.path.join(_SOURCES, "module_du_depot"), exist_ok=True)
        open(
            os.path.join(_SOURCES, "module_du_depot", "__manifest__.py"), "w"
        ).close()
        chemin = module_valide(self.dossier, "module_du_depot")
        code, charge = _deposer(chemin)
        self.assertEqual(code, 400)
        self.assertIn("sources Git", charge["erreur"])

    def test_reenvoi_remplace_le_module(self):
        """Un second dépôt du même module écrase proprement le premier."""
        premier = ecrire_zip(
            os.path.join(self.dossier, "v1.zip"),
            {
                "module_rejoue/__manifest__.py": MANIFESTE,
                "module_rejoue/ancien.py": "x = 1",
            },
        )
        _attendre_fin(_deposer(premier)[1]["id"])
        self.assertTrue(os.path.isfile(os.path.join(_ADDONS, "module_rejoue", "ancien.py")))

        second = ecrire_zip(
            os.path.join(self.dossier, "v2.zip"),
            {
                "module_rejoue/__manifest__.py": MANIFESTE,
                "module_rejoue/nouveau.py": "x = 2",
            },
        )
        final = _attendre_fin(_deposer(second)[1]["id"])
        self.assertEqual(final["etat"], "success")
        self.assertTrue(
            os.path.isfile(os.path.join(_ADDONS, "module_rejoue", "nouveau.py"))
        )
        # Le fichier de la version précédente ne doit pas survivre.
        self.assertFalse(
            os.path.isfile(os.path.join(_ADDONS, "module_rejoue", "ancien.py"))
        )

    def test_aucun_residu_de_transit(self):
        """Les dossiers de transit ne doivent pas s'accumuler dans l'addons_path."""
        _attendre_fin(_deposer(module_valide(self.dossier, "module_propre"))[1]["id"])
        residus = [n for n in os.listdir(_ADDONS) if n.startswith(".transit-")]
        self.assertEqual(residus, [])


if __name__ == "__main__":
    unittest.main()
