# Suspendre le serveur, et le reprendre

Ce fichier existe pour qu'éteindre l'Atelier ne soit jamais une décision
lourde. Tant que le rétablir tient en une commande, le suspendre ne coûte
rien — et un serveur qu'on n'ose pas éteindre finit par se payer pour rien.

## Le piège de facturation, d'abord

**Éteindre un serveur Hetzner ne suspend pas sa facturation.** Les ressources
restent réservées ; la note continue de courir au tarif plein. C'est écrit
dans leurs conditions, et c'est contre-intuitif — la plupart des gens
supposent l'inverse.

Seule la **suppression** arrête le compteur.

| Geste | Facturation | Ce qu'on garde |
|---|---|---|
| Éteindre (*Power off*) | **tarif plein** | tout |
| Instantané puis supprimer | ~0,01 €/Go/mois | tout, restaurable en un clic |
| Supprimer | **rien** | rien sur la machine |

## Ce qu'il y a réellement à perdre

Presque rien, et c'est le fruit d'une décision prise dès le départ : rien
d'unique ne vit sur ce serveur.

| Ce qui s'y trouve | Où il vit aussi |
|---|---|
| La pile de l'Atelier | ce dépôt |
| Les modules du dépôt | ce dépôt |
| Les addons Odoo Enterprise | votre dépôt `odoo_versions` |
| Vos modules de production | votre dépôt `addons_odoo17_mtnd` |
| La base Odoo de démonstration | **nulle part** — données d'essai |
| La clé d'API et le mot de passe admin | régénérés à chaque installation |

Le seul élément non reproductible est la base de démonstration : des
enregistrements créés à la main pour éprouver l'installation. Si elle compte,
prendre un instantané ; sinon, supprimer sans regret.

## Suspendre

1. `console.hetzner.com` → projet **atelier-odoo** → le serveur.
2. Facultatif, si la base de démonstration compte : onglet **Snapshots** →
   *Take snapshot*. Attendre la fin avant l'étape suivante.
3. Menu **⋯** en haut à droite → **Delete** → confirmer en tapant le nom du
   serveur.

La facturation s'arrête à la suppression, à l'heure près.

## Reprendre — l'Atelier seul, à ~4 €/mois

C'est le cas le plus fréquent, et le moins cher : mettre l'**interface** en
ligne, pour y accéder de n'importe quelle machine. Ni Odoo ni PostgreSQL, donc
le plus petit serveur suffit (**CX22**, 2 vCPU, 4 Go).

```bash
# Sur le serveur neuf, en root
apt-get update && apt-get install -y git
git clone -b claude/odoo-react-alchemy-handoff-hmig21 \
  https://github.com/SOMET1010/odoo17-hr && cd odoo17-hr

bash deployer/installer-atelier.sh --courriel votre@courriel
```

Sans `--domaine`, l'installeur lit l'adresse publique de la machine et
emploie `<ip>.sslip.io` : rien à acheter, rien à configurer chez un
registrar. Il affiche à la fin un **code d'installation** — il ne sert qu'à
créer le premier compte, qui sera administrateur. À faire tout de suite : sur
une adresse publique, le premier arrivé n'est pas forcément vous, et c'est
exactement ce que ce code empêche.

Ce qu'il y a à sauvegarder tient dans un fichier : `atelier.sqlite3`, porté
par un volume Docker, contient les projets **et** les comptes. La commande de
sauvegarde s'affiche à la fin de l'installation.

## Reprendre — la pile complète, avec Odoo

Un serveur neuf, puis une commande. Compter dix minutes, dont huit d'attente.

```bash
# Sur le serveur neuf, en root
apt-get update && apt-get install -y git
git clone https://github.com/SOMET1010/odoo17-hr && cd odoo17-hr

# Les addons Enterprise, hors du dépôt — l'installeur refuse un chemin qui
# s'y trouve, et il a raison : ils ne doivent pas entrer dans son historique.
git clone https://github.com/SOMET1010/odoo_versions /opt/odoo-versions

bash deployer/installer.sh \
  --domaine <IP-avec-des-tirets>.sslip.io \
  --courriel votre@courriel \
  --addons-entreprise /opt/odoo-versions/odoo17/addons
```

L'installeur produit une clé d'API et un mot de passe administrateur
nouveaux, les écrit dans `.env` (droits 600), applique le mot de passe à
Odoo, vérifie les deux sens, et attend le certificat avant d'annoncer
l'adresse. Il n'y a rien à reporter d'une installation à l'autre.

`sslip.io` résout n'importe quelle IP écrite avec des tirets : le certificat
suit l'adresse du nouveau serveur sans qu'aucun domaine soit à posséder.

## Quand le rallumer

Deux cas, et deux seulement.

**L'intégration Enterprise.** L'aperçu jouable ne connaît que ce que la
spécification décrit. Un module qui hérite de `hr.leave` ou de `sign.request`
ne peut être éprouvé que là où ces modules existent — c'est-à-dire sur une
instance avec votre abonnement.

**La démonstration.** Montrer un Odoo vivant n'est pas montrer un aperçu.

Pour tout le reste — juger un écran, un circuit, un calcul, une règle —
l'aperçu jouable suffit et ne coûte rien. Et les preuves d'installation sur
17, 18 et 19 tournent dans la forge à chaque envoi, gratuitement : elles
n'ont jamais eu besoin de ce serveur.
