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
bash deployer/installer.sh            # accès par tunnel SSH
bash deployer/installer.sh --public   # interface publiée sur Internet
```

Elle vérifie la machine, installe Docker s'il manque, compose elle-même le
secret du service d'installation et le mot de passe administrateur d'Odoo,
demande la clé du service d'IA — **sans l'afficher** —, démarre la pile, crée
la base, remplace le mot de passe `admin` par défaut, et vérifie que tout
répond.

Rien à recopier ensuite, à une exception près : le mot de passe administrateur
s'affiche une seule fois à la fin. Il reste lisible dans
`~/.config/atelier-odoo/env`.

## Les deux modes d'accès

### Fermé, par défaut

**Aucun port n'est ouvert sur l'extérieur** : Odoo et le service d'installation
n'écoutent que sur `127.0.0.1`. Un tunnel SSH suffit à y accéder, et ne demande
aucune configuration serveur :

```bash
ssh -N -L 8069:127.0.0.1:8069 utilisateur@serveur
```

Puis `http://localhost:8069` dans votre navigateur. C'est le mode le plus sûr,
mais il suppose un poste avec un client SSH — un téléphone n'en a pas.

### Ouvert, avec `--public`

L'interface Odoo, **et elle seule**, est publiée sur `0.0.0.0:8069`. Le
compromis est explicite : la liaison est en HTTP, sans certificat, et la seule
protection est le mot de passe administrateur tiré au hasard à l'installation.
Acceptable pour un atelier de fabrication de modules, pas pour des données
réelles.

Le HTTPS et l'authentification devant viendront avec le proxy inverse du
Preview Gateway ; ce mode est ce qui existe en attendant.

### Ce qui ne s'ouvre jamais

Le port **8090**, celui du service d'installation, est écrit en dur sur
`127.0.0.1` dans `docker-compose.yml` — sans variable. Ce service reçoit des
archives et installe du code : joignable depuis Internet, il devient une porte
d'entrée. Ouvrir l'interface ne doit pas pouvoir l'ouvrir par ricochet, et
l'installeur vérifie après coup qu'il ne l'est pas.

Le gestionnaire de bases d'Odoo, qui permet de supprimer une base depuis un
navigateur, est lui **désactivé** (`list_db = False`) plutôt que protégé par un
mot de passe.

## Ce que le script ne fait pas

- **Pas de HTTPS ni de proxy inverse.** C'est le chantier suivant, celui du
  Preview Gateway, et il mérite d'être conçu plutôt que bricolé ici. Tant
  qu'il n'existe pas, `--public` reste en clair.
- **Pas de sauvegarde.** Les volumes Docker survivent aux redémarrages, pas à
  la suppression de la VM.
- **Pas de mise à jour automatique.** `git pull` puis relancer le script.
- **Aucun durcissement du système** : pare-feu, `fail2ban`, clés SSH restent à
  votre charge ou à celle de votre hébergeur.
