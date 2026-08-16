# Emplacement de repli — aucun module Enterprise ici

Ce dossier est **vide à dessein**. Il est monté sur `/mnt/entreprise` quand
aucun dossier d'addons Enterprise n'est déclaré, pour que le chemin existe
toujours et qu'Odoo démarre sans se plaindre.

Les modules Odoo Enterprise sont sous licence `OEEL-1` : leur redistribution
est interdite. Ils ne doivent donc **jamais** être copiés ici, ni ailleurs
dans ce dépôt, ni dans une image Docker — ce dépôt est publiable, ces modules
ne le sont pas.

Pour les mettre à disposition de l'Atelier, on déclare un dossier **hors du
dépôt** :

    ADDONS_ENTREPRISE=/opt/odoo-entreprise

ou, à l'installation :

    bash deployer/installer.sh --https --addons-entreprise /opt/odoo-entreprise

L'installeur refuse un chemin situé à l'intérieur du dépôt : ce serait le
premier pas vers un commit accidentel.
