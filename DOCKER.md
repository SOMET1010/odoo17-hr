# Odoo 17 en local

Instance Odoo persistante pour faire tourner les modules du dépôt : parcourir
les vues réelles, saisir des enregistrements, et alimenter l'atelier de
prototypage React en données réelles.

À ne pas confondre avec `.github/workflows/test-install.yml`, qui vérifie
seulement que les modules s'installent à chaque poussée, puis s'arrête
aussitôt.

## Démarrer

```bash
docker compose up -d
```

Au premier lancement, créer la base et installer les modules :

```bash
docker compose run --rm odoo odoo \
  -d ansut -i diligence_simple,theme_backend,ansut_rh --stop-after-init
```

Puis ouvrir <http://localhost:8069> et se connecter avec `admin` / `admin`.

Les données de démonstration sont installées par défaut : la base contient donc
des employés, des congés et des projets, ce qui évite de tout saisir à la main
pour prototyper. Pour une base vierge, ajouter `--without-demo=all` à la
commande d'installation ci-dessus.

## Travailler sur les modules

Le dépôt est monté en lecture seule dans le conteneur. Après modification d'un
module, il faut le mettre à jour :

```bash
docker compose run --rm odoo odoo -d ansut -u ansut_rh --stop-after-init
docker compose restart odoo
```

`dev_mode = reload,qweb,xml` est actif : les modifications de vues XML sont
rechargées sans redémarrage, mais un changement de modèle Python impose la mise
à jour ci-dessus.

## Brancher l'atelier React

L'atelier (dépôt `odoo-react-alchemy`) sait consommer une instance Odoo réelle
depuis son panneau « Connecter une instance Odoo » — l'aperçu affiche alors les
vrais enregistrements au lieu de listes vides.

Odoo n'émet aucun en-tête CORS : un appel direct du navigateur vers
`localhost:8069` depuis l'atelier servi sur `localhost:8080` est refusé.
L'atelier propose un proxy de développement qui supprime le problème en
plaçant les deux du même côté :

```bash
# dans le dépôt odoo-react-alchemy
VITE_ODOO_PROXY=http://localhost:8069 npm run dev
```

Puis, dans le panneau de connexion de l'atelier :

| Champ | Valeur |
| --- | --- |
| Instance Odoo | `http://localhost:8080` (l'atelier lui-même, qui relaie `/web`) |
| Base de données | `ansut` |
| Utilisateur | `admin` |
| Mot de passe | `admin` |

Renseigner directement `http://localhost:8069` ne fonctionnera pas depuis le
navigateur, faute d'en-têtes CORS côté Odoo.

## Arrêter et repartir de zéro

```bash
docker compose down          # arrête, conserve la base et le filestore
docker compose down -v       # supprime aussi les volumes : base repartie à neuf
```

## Dépannage

- **Le port 8069 est déjà pris** : changer le mappage dans `docker-compose.yml`
  (`"8070:8069"` par exemple), et adapter `VITE_ODOO_PROXY` en conséquence.
- **`database ansut does not exist`** : la commande d'installation n'a pas été
  jouée, voir « Démarrer ».
- **Un module n'apparaît pas dans la liste** : activer le mode développeur puis
  « Applications » → « Mettre à jour la liste des applications ».
- **Le démarrage est lent** : le dépôt contient de nombreux modules, dont Odoo
  lit tous les manifestes au lancement. C'est normal au premier démarrage.
