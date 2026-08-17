# Déployer l'Atelier sur un serveur

Cible : une VM Linux **dédiée**, distincte de tout Odoo de production. Le
Builder installe, casse et recrée des modules ; une base de test peut y être
supprimée sans préavis. C'est le but, et c'est pourquoi la machine doit être
séparée.

## Deux déploiements, et il faut choisir le bon

|  | `installer-atelier.sh` | `installer.sh` |
|---|---|---|
| Ce qui tourne | l'interface + HTTPS | + Odoo, PostgreSQL, service d'installation |
| Ce qu'on peut faire | décrire, convertir, thème, aperçu, **télécharger le ZIP** | tout cela, **et installer le module dans un vrai Odoo** |
| Machine | 2 vCPU, 4 Go — ~4 €/mois | 4 vCPU, 8 Go — ~35 €/mois |
| Fichier | `docker-compose.atelier.yml` | `docker-compose.yml` |

La suite de ce document décrit le **second**. Pour le premier, il n'y a
presque rien à dire :

```bash
bash deployer/installer-atelier.sh --domaine atelier.exemple.fr \
                                   --courriel vous@exemple.fr
```

Sans `--domaine`, un nom dérivé de l'adresse IP est employé (sslip.io) et le
certificat s'obtient dessus : rien à acheter.

**Mais pas pour un usage à plusieurs.** `sslip.io` est un service de DNS
générique très employé par l'hameçonnage : les filtrages d'entreprise le
bloquent en bloc, Microsoft Defender compris, sans regarder ni le certificat ni
le contenu. L'instance marche, et vos collègues lisent « ce contenu est bloqué
par votre organisation ». Dès qu'on partage l'adresse, il faut un vrai nom :
un enregistrement **A** vers l'adresse du serveur, puis une relance avec
`--domaine`. sslip.io reste parfait pour éprouver seul, tout de suite. Le script affiche à la fin un
**code d'installation** — il ne sert qu'à créer le premier compte, qui sera
administrateur. Faites-le tout de suite : sur une adresse publique, le premier
arrivé n'est pas forcément vous, et c'est précisément ce que ce code empêche.

L'interface ne publie aucun port : la passerelle est le seul chemin. Tout —
projets et comptes — tient dans un fichier SQLite porté par un volume ; la
commande de sauvegarde s'affiche à la fin de l'installation.

Recette de cette pile : `.docker/verifier-atelier-en-ligne.sh`, jouée par la
forge à chaque envoi.

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
`203-0-113-10.sslip.io` résout vers `203.0.113.10`. Rien à acheter, rien à
configurer chez un registraire. Un vrai domaine reste préférable : il survit à
un changement d'adresse, pas celui-ci.

L'adresse ci-dessus vient de la plage que la RFC 5737 réserve à la
documentation. C'est délibéré : une IP réelle citée en exemple finit par
désigner la machine de quelqu'un d'autre le jour où on rend la sienne, et le
lecteur d'une documentation ne devrait jamais pouvoir toucher un serveur
inconnu en recopiant ce qu'il lit.

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

## Utiliser des modules Odoo Enterprise

Les modules Enterprise sont sous licence **`OEEL-1`**, qui interdit leur
redistribution. Ce dépôt est publiable ; ils ne le sont pas. Ils ne doivent
donc **jamais** y entrer, ni être copiés dans une image Docker.

L'Atelier les utilise sans jamais les détenir : un dossier de la machine, monté
en lecture seule.

```bash
bash deployer/installer.sh --https --addons-entreprise /opt/odoo-entreprise
```

L'installeur **refuse un chemin situé dans le dépôt** — ce serait le premier
pas vers un commit accidentel — et compte les manifestes trouvés pour dire tout
de suite si le chemin désigne le bon dossier.

Sans cette option, un dossier vide occupe la place : le chemin `/mnt/entreprise`
existe toujours, et Odoo démarre normalement chez qui n'a pas d'abonnement.

### Ce que ça change, et ce que ça ne change pas

Avec ces addons, le bac à sable peut installer et éprouver des modules qui
**étendent** des modèles Enterprise. Sans eux, il ne connaît que l'édition
communautaire, et un module qui hérite de `sign.request` échouera à
l'installation — faute que rien d'autre ne saurait expliquer.

En revanche la forge, elle, ne les aura jamais : ses journaux sont publics et y
téléverser du code sous OEEL-1 serait le publier. Les recettes automatiques
restent donc en édition communautaire, et ce qui dépend d'Enterprise se vérifie
sur votre serveur. C'est une limite assumée, pas un oubli.

## Apporter vos propres modules

Vos modules de production se montent comme les addons Enterprise : depuis un
dossier **hors du dépôt**.

```bash
scp -r "C:\chemin\vers\vos modules" root@serveur:/opt/odoo-maison
bash deployer/installer.sh --https --addons-maison /opt/odoo-maison
```

Pourquoi hors du dépôt, alors qu'ils vous appartiennent ? Deux raisons. Ils
prendraient l'historique et la visibilité de ce dépôt, qui ne les concernent
pas. Et surtout, **le service d'installation refuse d'écraser un module présent
dans les sources Git** : les y verser empêcherait l'Atelier d'en produire une
version corrigée — exactement ce qu'on veut faire d'eux.

## Passer le dépôt en privé

Ce dépôt contient des modules sous `OEEL-1`, dont la redistribution est
interdite. S'il est public, ils le sont aussi.

Le basculement casserait une chose : le serveur tire ses mises à jour par un
`git pull` anonyme. On prépare donc l'accès **avant** de basculer, tant que le
dépôt est encore public et qu'on peut vérifier que ça marche.

```bash
cd /opt/atelier && bash deployer/depot-prive.sh
```

Le script crée une **clé de déploiement** — une paire SSH propre à ce dépôt et
à cette machine, en lecture seule — affiche la partie publique à coller dans
GitHub, puis vérifie que le dépôt répond par cette clé. Si la vérification
échoue, il **remet l'origine d'avant** : un serveur qui tire encore vaut mieux
qu'un serveur bloqué par une configuration à moitié faite.

Pourquoi pas un jeton d'accès personnel : il ouvrirait *tous* vos dépôts, et se
retrouverait en clair dans l'URL du dépôt, que `git remote -v` affiche à qui
passe. Une clé de déploiement ne vaut que pour un dépôt, se révoque seule, et
sa partie privée ne quitte jamais la machine.

Une fois le script au vert, le basculement se fait dans GitHub :
**Settings → General → Danger Zone → Change visibility.**

### Installer une machine neuve, dépôt déjà privé

La commande d'installation en une ligne clone anonymement : elle ne marchera
plus. Il faut donner sa clé à la machine avant qu'elle puisse lire le dépôt :

```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/atelier_depot -C "atelier-$(hostname)"
cat ~/.ssh/atelier_depot.pub          # à coller dans Deploy keys, sans écriture
printf 'Host github-atelier\n    HostName github.com\n    User git\n    IdentityFile ~/.ssh/atelier_depot\n    IdentitiesOnly yes\n' >> ~/.ssh/config
git clone -b claude/odoo-react-alchemy-handoff-hmig21 git@github-atelier:SOMET1010/odoo17-hr.git /opt/atelier
bash /opt/atelier/deployer/installer.sh --https
```

### Ce que le privé change aussi

Les exécutions de la forge cessent d'être gratuites : sur un dépôt public,
GitHub Actions ne consomme aucun quota ; sur un dépôt privé, chaque minute est
décomptée d'un forfait mensuel. Nos recettes durent deux à quatre minutes
chacune — c'est tenable, mais ce n'est plus illimité, et il vaut mieux le
savoir avant de voir les exécutions s'arrêter en milieu de mois.

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
