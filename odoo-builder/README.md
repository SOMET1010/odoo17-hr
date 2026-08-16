# Odoo Builder

Fabrique un module Odoo 17 à partir d'une spécification, l'installe réellement,
et rend le statut et les journaux.

```
spécification → génération → validation statique → archive
              → install-service → installation réelle → statut/journaux
              → réparation éventuelle → nouvelle tentative
```

Ou depuis un besoin en français, que le modèle traduit en spécification :

```
besoin → ModuleSpec → génération → validation → installation → Odoo
```

Le bac à sable vit à côté (`.docker/service-installation` + `docker-compose.yml`).

## Le partage des rôles

| Le modèle | Le code déterministe |
|---|---|
| rédige et corrige la **spécification** | rend les fichiers Odoo |
| décrit le **métier** | tient les **invariants** |
| — | construit l'archive, appelle le bac à sable |
| — | interprète les statuts, pilote les tentatives |

Le modèle n'écrit jamais un fichier Odoo et n'est jamais responsable d'un
invariant. Sa correction repasse par le générateur et le validateur : une
réparation ne peut donc pas contourner les contrôles.

## Usage

```bash
# Depuis un besoin en français : le modèle en rédige la spécification
export OPENAI_API_KEY="…"
python3 cli/atelier_odoo.py build \
        --besoin "Gestion des missions : demande, frais, total calculé,
                  workflow brouillon → soumis, interdit de soumettre sans frais" \
        --ecrire-spec /tmp/mission.json

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
| `OpenAIProvider` | production — protocole OpenAI, appel HTTP direct, sans SDK |
| `ScriptedProvider` | recettes et mode hors ligne — réponses déterministes |

Le **protocole** est celui d'OpenAI ; l'**hôte**, le **modèle** et la **clé**
viennent de l'environnement. N'importe quel service exposant une API
compatible OpenAI convient — un autre fournisseur, un service local, un proxy
d'entreprise — sans toucher une ligne du Builder :

```bash
export BUILDER_IA_CLE="…"
export BUILDER_IA_URL="https://…/v1/chat/completions"
export BUILDER_IA_MODELE="…"
```

À défaut, `OPENAI_API_KEY` et les valeurs OpenAI par défaut s'appliquent.
Aucune de ces valeurs n'est acceptée en argument de commande.

Sans `OPENAI_API_KEY`, la chaîne fonctionne toujours à partir d'un `spec.json` :
seules la rédaction depuis un besoin et la réparation automatique sont
désactivées.

### La laisse du modèle

Le modèle intervient à deux endroits — rédiger une spécification, en corriger
une — et **ne produit jamais autre chose qu'une ModuleSpec**. Pas de Python,
pas de XML, pas d'archive. Sa sortie traverse ensuite exactement le même
pipeline déterministe qu'une spécification écrite à la main.

C'est ce qui rend l'ensemble sûr : une mauvaise réponse ne peut pas injecter de
code dans Odoo, elle ne peut que décrire un module qui échoue à la validation.
Une expression comme `__import__('os').system('id')` est refusée par le
langage d'expression avant qu'aucun fichier ne soit écrit — un test le vérifie.

## Les invariants du validateur

Ils viennent d'échecs réellement observés, pas de la documentation.

| Contrôle | Pourquoi |
|---|---|
| domaine ne citant qu'un champ **présent dans la vue** | le défaut exact qui a empêché `diligence_simple` de s'installer, deux fois |
| champ monétaire ⇒ `currency_id` sur le modèle | sinon le registre Odoo refuse de se construire |
| `depends` cite exactement ce que l'expression lit | un `depends` incomplet ne casse rien : il empêche seulement le recalcul |
| état non final ni atteint ni quitté | un cycle de vie qui ne vit pas |
| champ calculé **et** obligatoire | Odoo ne peut pas exiger ce qu'il calcule |
| tout modèle créé a un droit d'accès | un modèle sans ACL est inutilisable, même installé |
| tout fichier `.xml`/`.csv` est déclaré dans `data` | sinon il n'est jamais chargé, en silence |
| tout fichier de `data` existe | erreur d'installation immédiate |
| manifeste = littéral Python, clés obligatoires | Odoo le lit sans l'exécuter |
| Python compile (`ast`), XML bien formé, enraciné sur `<odoo>` | évite un aller-retour avec le bac à sable |
| champ de vue déclaré par le modèle (modèles créés) | « Field … does not exist » |

## Le comportement, pas seulement la structure

La spécification décrit **champs calculés, contraintes, états et transitions** —
ce dont un module Odoo est réellement fait. Sans jamais contenir de Python :
les expressions appartiennent à un langage restreint (`src/spec/expression.py`),
analysé sans être exécuté, puis traduit.

```
sum(line_ids.amount)   →  @api.depends('line_ids.amount')
                          enreg.total = sum(enreg.line_ids.mapped('amount'))

submit: draft → submitted, si total > 0
                       →  def action_submit(self): … gardes … état
```

Un cycle de vie produit de lui-même le champ d'état, la barre de statut, et un
bouton par transition visible depuis les seuls états d'où elle part.

## Les trois invariants de sécurité

Ils sont **vérifiés par des tests**, pas seulement écrits ici : une régression
les casse dans la recette, pas en production. Ils doivent tenir lorsque
l'interface Atelier sera branchée.

| Invariant | Comment il est tenu |
|---|---|
| La clé reste dans l'environnement du backend | aucune option de commande ne l'accepte — elle fuirait dans l'historique et la liste des processus ; elle n'apparaît dans aucun fichier généré |
| Le modèle n'écrit ni dans le dépôt ni dans Odoo | `AIProvider` n'expose qu'une méthode, `completer_json`, qui ne reçoit et ne rend que du texte ; le rédacteur n'importe ni `open`, ni `urllib`, ni `zipfile`, ni `subprocess` |
| Toute reprise repasse par le même validateur | une spécification corrigée est revalidée par `ModuleSpec` puis par `OdooStaticValidator` ; aucun chemin ne les contourne |

S'y ajoute un invariant du même esprit : **la génération reste en mémoire**.
`generate()` rend un dictionnaire ; rien n'est écrit sur disque avant que la
spécification ait passé la validation complète.

## Recettes

```bash
python3 -m unittest discover -s tests -t .     # 57 contrôles, sans Odoo ni réseau
```

### Le test d'acceptation, manuel

Le seul maillon que les 57 contrôles ne couvrent pas est l'appel réel au
fournisseur. Il se joue à la main, jamais en CI — dépendance réseau, coût et
variabilité du modèle n'ont pas leur place dans un socle de non-régression.

```bash
export OPENAI_API_KEY="…"
export INSTALLATEUR_CLE_API="…"
docker compose --profile installateur up -d --build installateur
python3 cli/acceptation.py
```

Il soumet le besoin des missions en français, sans retouche du JSON, et exige
que la chaîne aille jusqu'à l'exécution : module installé, champ calculé égal à
la somme des lignes, transition qui change l'état en base. Verdict binaire.

L'installation réelle est prouvée par l'**étape 9** de
`.docker/verifier-runtime.sh`, qui va jusqu'à l'exécution : elle installe le
module des missions, crée une demande, ajoute un frais, vérifie que le champ
calculé vaut la somme, déclenche la transition et relit l'état en base.

## Limites connues

- Ni README, ni icône, ni feuille de style dans les modules générés.
- L'héritage de vue (`xpath`) n'est pas géré : les vues sont créées, jamais
  greffées sur une vue existante.
- Le passage besoin → spécification n'a pas encore été joué contre une vraie
  API : il est éprouvé de bout en bout avec un fournisseur simulé, mais aucun
  appel réseau à OpenAI n'a été fait dans cet environnement.
