# Odoo Builder

Fabrique un module Odoo 17 à partir d'une spécification, l'installe réellement,
et rend le statut et les journaux.

```
spécification → génération → validation statique → archive
              → install-service → installation réelle → statut/journaux
              → réparation éventuelle → nouvelle tentative
```

C'est la moitié manquante de l'Atelier : le bac à sable existe déjà
(`.docker/service-installation` + `docker-compose.yml`), le générateur non.

## Le partage des rôles

| Le modèle | Le code déterministe |
|---|---|
| produit et corrige la **spécification** | rend les fichiers Odoo |
| décrit le **métier** | tient les **invariants** |
| — | construit l'archive, appelle le bac à sable |
| — | interprète les statuts, pilote les tentatives |

Le modèle n'écrit jamais un fichier Odoo et n'est jamais responsable d'un
invariant. Sa correction repasse par le générateur et le validateur : une
réparation ne peut donc pas contourner les contrôles.

## Usage

```bash
# Validation seule, sans bac à sable
python3 cli/atelier_odoo.py build specs/diligence_simple.json \
        --sans-installation --sortie /tmp/module

# Chaîne complète, contre le service d'installation
export INSTALLATEUR_CLE_API="…"
docker compose --profile installateur up -d --build installateur
python3 cli/atelier_odoo.py build specs/diligence_simple.json
```

Sortie attendue :

```
Module diligence_simple — Diligences
Génération du module (tentative 1/3)…
Validation statique : PASS
Installation sur Odoo 17…
Installation : SUCCESS

Module diligence_simple is running.
```

## Le fournisseur de modèle

Le reste du Builder ne connaît que l'interface `AIProvider`. Changer de
fournisseur ne touche aucun autre fichier.

| Implémentation | Usage |
|---|---|
| `OpenAIProvider` | production — `OPENAI_API_KEY`, appel HTTP direct, sans SDK |
| `ScriptedProvider` | recettes et mode hors ligne — réponses déterministes |

Sans `OPENAI_API_KEY`, la chaîne fonctionne toujours : seule la réparation
automatique est désactivée. Une spécification correcte n'a pas besoin de modèle.

## Les invariants du validateur

Ils viennent d'échecs réellement observés, pas de la documentation.

| Contrôle | Pourquoi |
|---|---|
| domaine ne citant qu'un champ **présent dans la vue** | le défaut exact qui a empêché `diligence_simple` de s'installer, deux fois |
| tout modèle créé a un droit d'accès | un modèle sans ACL est inutilisable, même installé |
| tout fichier `.xml`/`.csv` est déclaré dans `data` | sinon il n'est jamais chargé, en silence |
| tout fichier de `data` existe | erreur d'installation immédiate |
| manifeste = littéral Python, clés obligatoires | Odoo le lit sans l'exécuter |
| Python compile (`ast`), XML est bien formé et enraciné sur `<odoo>` | évite un aller-retour avec le bac à sable |
| champ de vue déclaré par le modèle (modèles créés) | « Field … does not exist » |

## Recettes

```bash
python3 -m unittest discover -s tests -t .     # 25 contrôles, sans Odoo ni réseau
```

L'installation réelle est prouvée par l'**étape 9** de
`.docker/verifier-runtime.sh` : une spécification y devient un module
effectivement installé, vérifié dans `ir_module_module` et `ir_model`.

## Limites connues

- La spécification ne décrit pas les **champs calculés**, les contraintes, ni
  les méthodes métier. Le `project_task.py` du vrai `diligence_simple` n'est
  donc pas reproductible en l'état.
- Ni README, ni icône, ni feuille de style dans les modules générés.
- L'héritage de vue (`xpath`) n'est pas géré : les vues sont créées, jamais
  greffées sur une vue existante.
- L'étape « besoin en langage naturel → spécification » n'est pas branchée :
  `AIProvider` sert aujourd'hui à la réparation. L'entrée est un `spec.json`.
