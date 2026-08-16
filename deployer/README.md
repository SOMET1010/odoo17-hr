# Déployer l'Atelier sur un serveur

Cible : une VM Linux **dédiée**, distincte de tout Odoo de production. Le
Builder installe, casse et recrée des modules ; une base de test peut y être
supprimée sans préavis. C'est le but, et c'est pourquoi la machine doit être
séparée.

## Dimensionner

Le dimensionnement suit la charge réelle — construire une image, faire tourner
Odoo et PostgreSQL, installer un module, jouer une recette — et non un prix.

| | Minimum de départ |
|---|---|
| Processeurs | 4 vCPU |
| Mémoire | 8 Go |
| Disque | SSD, 20 Go libres au moins |
| Système | Ubuntu (testé), Docker disponible |

Ce sont des seuils de démarrage pour un Atelier exploitable, pas une
infrastructure de production. Plusieurs bacs à sable simultanés demanderont
davantage ; on le mesurera plutôt que de l'anticiper.

## Installer

Une commande, sur la VM :

```bash
bash deployer/installer.sh --https    # interface chiffrée, certificat automatique
bash deployer/installer.sh --public   # publiée en clair
bash deployer/installer.sh --prive    # rien d'ouvert, tunnel SSH
```

Sans option, elle demande lequel des trois.

Elle vérifie la machine, installe Docker s'il manque, compose elle-même le
secret du service d'installation et le mot de passe administrateur d'Odoo,
demande la clé du service d'IA — **sans l'afficher** —, démarre la pile, crée
la base, remplace le mot de passe `admin` par défaut, et vérifie que tout
répond.

Rien à recopier ensuite, à une exception près : le mot de passe administrateur
s'affiche une seule fois à la fin. Il reste lisible dans
`~/.config/atelier-odoo/env`.

## Les trois accès possibles

L'installeur les propose, ou les prend en option.

### `--https` — chiffré, et seul à permettre le raccordement

```bash
bash deployer/installer.sh --https
bash deployer/installer.sh --domaine atelier.exemple.fr
```

Une passerelle Caddy devient le seul point d'entrée : elle obtient le
certificat, le renouvelle, et relaie vers Odoo. Le port 8069 n'est plus
publié — tout passe par le 443.

Ce n'est pas qu'une question de confidentialité. **Un navigateur sur une page
HTTPS refuse d'appeler un backend en clair.** Tant que l'Atelier parle à Odoo
en HTTP, aucune interface hébergée ailleurs ne pourra jamais l'atteindre. C'est
la condition d'existence du raccordement, pas un réglage de confort.

Sans `--domaine`, un nom est dérivé de l'adresse IP via **sslip.io** —
`62-238-99-108.sslip.io` résout vers `62.238.99.108`. Rien à acheter, rien à
configurer chez un registraire. Un vrai domaine reste préférable : il survit à
un changement d'adresse, pas celui-ci.

Deux conditions, que l'installeur vérifie plutôt que de les supposer : les
ports 80 et 443 doivent être libres, et joignables depuis Internet — l'autorité
de certification appelle sur le 80. Si le certificat n'arrive pas, l'installeur
le dit et nomme les causes usuelles au lieu d'annoncer une adresse qui ne
répond pas.

### `--public` — en clair

```bash
bash deployer/installer.sh --public
```

Odoo est publié directement sur `0.0.0.0:8069`, sans chiffrement. La seule
protection est le mot de passe administrateur tiré au hasard à l'installation.
Un mot de passe qui voyage en clair est un mot de passe public : à réserver à
un essai, sur des données qui ne valent rien.

### `--prive` — rien d'ouvert

```bash
bash deployer/installer.sh --prive
```

Aucun port sur l'extérieur. L'accès se fait par tunnel SSH :

```bash
ssh -N -L 8069:127.0.0.1:8069 utilisateur@serveur
```

Puis `http://localhost:8069`. Le plus sûr, mais il suppose un poste avec un
client SSH — un téléphone n'en a pas.

### Ce qui ne s'ouvre jamais

Le port **8090**, celui du service d'installation, est écrit en dur sur
`127.0.0.1` dans `docker-compose.yml` — sans variable. Ce service reçoit des
archives et installe du code : joignable depuis Internet, il devient une porte
d'entrée. La passerelle ne lui donne **aucune route**, et la recette
`.docker/verifier-passerelle.sh` vérifie qu'aucun chemin n'y mène.

Le gestionnaire de bases d'Odoo, qui permet de supprimer une base depuis un
navigateur, est lui **désactivé** (`list_db = False`) plutôt que protégé par un
mot de passe.

### Éprouver la passerelle

```bash
./.docker/verifier-passerelle.sh
```

Sur `localhost`, signé par l'autorité interne de Caddy. Le certificat est
vérifié **avec sa racine**, jamais contourné par `--insecure` : une recette qui
désactive la vérification ne prouve pas le chiffrement, elle prouve qu'un
serveur répond. Un contrôle s'assure d'ailleurs que la connexion échoue bien
quand on retire cette racine.

## Jouer le test d'acceptation

C'est le seul maillon qu'aucun test automatique ne couvre : l'appel réel au
modèle, qui transforme un besoin écrit en français en module Odoo installé et
exécuté.

```bash
bash deployer/acceptation.sh          # lance et rend la main aussitôt
bash deployer/acceptation.sh --voir   # affiche le résultat
```

Le test se détache de la session qui l'a lancé (`setsid`) : une coupure de la
liaison ne l'interrompt plus, et le résultat se relit par une connexion courte.
Sur un lien instable, c'est la différence entre un test qui aboutit et un test
qu'on relance indéfiniment.

## Ce que le script ne fait pas

- **Pas d'authentification devant Odoo.** La passerelle chiffre et relaie ;
  c'est le mot de passe d'Odoo qui protège. Un contrôle d'accès propre à
  l'Atelier viendra avec son raccordement.
- **Pas de sauvegarde.** Les volumes Docker survivent aux redémarrages, pas à
  la suppression de la VM.
- **Pas de mise à jour automatique.** `git pull` puis relancer le script.
- **Aucun durcissement du système** : pare-feu, `fail2ban`, clés SSH restent à
  votre charge ou à celle de votre hébergeur.
