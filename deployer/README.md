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
bash deployer/installer.sh
```

Elle vérifie la machine, installe Docker s'il manque, compose elle-même le
secret du service d'installation, demande la clé du service d'IA — **sans
l'afficher** —, démarre la pile, crée la base et vérifie que tout répond.

Rien à recopier ensuite.

## Ce qui n'est joignable que depuis la machine

Par défaut, **aucun port n'est ouvert sur l'extérieur** : Odoo et le service
d'installation n'écoutent que sur `127.0.0.1`.

Ce n'est pas de la prudence excessive. Le service d'installation reçoit des
archives et installe du code : joignable depuis Internet, il devient une porte
d'entrée. Et le gestionnaire de bases d'Odoo, qui permet de supprimer une base
depuis un navigateur, est **désactivé** (`list_db = False`) plutôt que protégé
par un mot de passe.

### Y accéder depuis votre poste

Un tunnel SSH suffit, et ne demande aucune configuration serveur :

```bash
ssh -N -L 8069:127.0.0.1:8069 utilisateur@serveur
```

Puis `http://localhost:8069` dans votre navigateur.

### Ouvrir volontairement

Quand l'interface Atelier devra appeler ce backend, il faudra un proxy inverse
devant, avec HTTPS et authentification. En attendant, l'ouverture directe
existe mais doit rester un choix conscient :

```bash
BIND_ADRESSE=0.0.0.0 docker compose --profile installateur up -d
```

N'ouvrez jamais le port 8090 ainsi : c'est celui du service d'installation.

## Ce que le script ne fait pas

- **Pas de HTTPS ni de proxy inverse.** C'est le chantier suivant, celui du
  Preview Gateway, et il mérite d'être conçu plutôt que bricolé ici.
- **Pas de sauvegarde.** Les volumes Docker survivent aux redémarrages, pas à
  la suppression de la VM.
- **Pas de mise à jour automatique.** `git pull` puis relancer le script.
- **Aucun durcissement du système** : pare-feu, `fail2ban`, clés SSH restent à
  votre charge ou à celle de votre hébergeur.
