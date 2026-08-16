# Emplacement de repli — aucun module maison ici

Dossier **vide à dessein**, monté sur `/mnt/maison` quand aucun dossier de
modules maison n'est déclaré, pour que le chemin existe toujours.

Vos modules à vous se montent depuis un dossier **hors du dépôt** :

    ADDONS_MAISON=/opt/odoo-maison

ou, à l'installation :

    bash deployer/installer.sh --https --addons-maison /opt/odoo-maison

Pourquoi hors du dépôt, alors qu'ils vous appartiennent : parce que ce sont vos
modules de production. Les verser dans ce dépôt les soumettrait à son
historique, à sa visibilité et à ses recettes — trois choses qui n'ont rien à
voir avec eux. Et le service d'installation refuse d'écraser un module présent
dans les sources Git : les y mettre empêcherait l'Atelier d'en produire une
version corrigée.
