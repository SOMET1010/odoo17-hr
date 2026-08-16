# Service d'installation de modules

Reçoit une archive ZIP authentifiée, la vérifie, l'écrit dans un volume
d'addons dédié, puis demande à Odoo de l'installer et rend l'état de
l'opération.

Périmètre volontairement étroit : **pas d'iframe, pas de multi-utilisateur,
pas de place de marché**. C'est un service privé, pour une instance.

## Le point important : pas de socket Docker

L'approche évidente — lancer `docker compose run odoo -i mon_module` —
obligerait à monter `/var/run/docker.sock` dans le service. Un service
exposé qui tient le socket Docker équivaut à donner la racine de la machine
hôte à quiconque franchit son authentification.

À la place, le service :

1. écrit le module dans un volume d'addons, et
2. appelle Odoo en JSON-RPC — `update_list()` puis `button_immediate_install()`,
   exactement ce que fait le bouton « Installer » de l'interface.

Il n'a donc besoin que d'écrire un volume et de parler HTTP. Conséquence
assumée : le journal remonté vient d'Odoo (message d'erreur JSON-RPC et sa
trace), pas de la sortie standard d'une commande.

## Les barrières *sont* le produit

Elles vivent dans `validation.py`, sans dépendance ni accès réseau, et sont
couvertes par `tests/test_validation.py`.

| Barrière | Refus |
|---|---|
| Clé d'API (`X-Cle-Api`, comparaison à temps constant) | 401 |
| Taille de l'archive (20 Mio par défaut) | 413 |
| Taille décompressée (100 Mio) et nombre d'entrées (2000) | 413 |
| Taux de compression anormal (bombe zip) | 400 |
| Chemin absolu, remontée `../`, séparateur Windows, octet nul | 400 |
| Lien symbolique ou entrée d'un type exotique | 400 |
| Plusieurs dossiers racine, ou nom hors `^[a-z][a-z0-9_]{2,63}$` | 400 |
| Nom réservé (`base`, `web`, `mail`…) | 400 |
| Module livré par les sources Git — jamais écrasable par un envoi | 400 |
| `__manifest__.py` absent, non littéral, ou sans `name` | 400 |

Deux choix méritent d'être explicités :

- Le manifeste est validé par `ast.literal_eval`, jamais exécuté. Un
  `__manifest__.py` qui contient du code est refusé **avant** d'atteindre
  Odoo.
- L'extraction se fait entrée par entrée à partir des chemins déjà validés,
  sans `extractall`, dont le traitement des entrées exotiques dépend de la
  version de Python. Le module est déballé dans un dossier de transit puis
  basculé d'un coup : une extraction interrompue ne laisse pas un module à
  moitié écrit dans l'`addons_path`.

## API

| Route | Rôle |
|---|---|
| `GET /sante` | État du service, sans authentification |
| `POST /modules` | Dépôt d'une archive (`Content-Type: application/zip`) |
| `GET /modules/<id>` | État d'une demande |

États d'une demande : `queued` → `installing` → `success` ou `failed`.

Les installations sont sérialisées par un fil d'exécution unique : deux
installations simultanées se disputeraient le registre d'Odoo.

## Mise en route

Le service est sous profil Compose : `docker compose up` ne le démarre pas.

```bash
export INSTALLATEUR_CLE_API="une-cle-longue-et-secrete"
docker compose --profile installateur up -d --build installateur
```

Dépôt d'un module :

```bash
curl -sS -X POST \
  -H "X-Cle-Api: $INSTALLATEUR_CLE_API" \
  -H 'Content-Type: application/zip' \
  --data-binary @mon_module.zip \
  http://localhost:8090/modules
# {"id":"…","module":"mon_module","etat":"queued",…}

curl -sS -H "X-Cle-Api: $INSTALLATEUR_CLE_API" \
  http://localhost:8090/modules/<id>
```

L'archive doit contenir **un seul dossier racine**, portant le nom du
module, avec son `__manifest__.py` à la racine de ce dossier.

## Réglages

| Variable | Défaut | Rôle |
|---|---|---|
| `CLE_API` | *(aucun)* | Clé d'API. **Sans elle, le service refuse de démarrer.** |
| `ODOO_URL` | `http://odoo:8069` | Instance visée |
| `ODOO_BASE` | `ansut` | Base de données |
| `ODOO_LOGIN` / `ODOO_MOTDEPASSE` | `admin` / `admin` | Compte d'installation |
| `DOSSIER_ADDONS` | `/mnt/addons-installes` | Volume d'écriture |
| `DOSSIER_SOURCES` | `/mnt/extra-addons` | Sources Git à protéger |
| `TAILLE_MAX_MO` | `20` | Taille maximale d'une archive |
| `PORT` | `8090` | Port d'écoute |

## Recette

Les barrières et l'API, sans Docker ni Odoo (Odoo est doublé) :

```bash
cd .docker/service-installation
python3 -m unittest discover -s tests -t . -v
```

L'installation réelle, sur une vraie pile, est l'**étape 8** de
`.docker/verifier-runtime.sh` : elle vérifie qu'un module déposé finit
`installed` dans `ir_module_module`, que les trois refus attendus tombent
bien, et que le conteneur n'a pas accès au socket Docker.

## Limites connues

- Le processus tourne en `root` dans son conteneur : il doit écrire un
  volume Docker dont la racine appartient à `root`. Le conteneur n'a ni
  socket Docker, ni accès à la base.
- Les identifiants Odoo sont passés en variables d'environnement. Pour une
  mise en service, les sortir vers un gestionnaire de secrets.
- L'état des demandes est en mémoire : un redémarrage du service les oublie
  (les modules installés, eux, restent installés).
