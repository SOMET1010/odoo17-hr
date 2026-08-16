# L'interface de l'Atelier, en ligne.
#
# Comme les deux autres services : bibliothèque standard seulement. Rien à
# télécharger au démarrage, donc rien qui puisse manquer le jour où le réseau
# du serveur est restreint — et aucune dépendance tierce à corriger en urgence.
#
# Le code du Builder n'est PAS copié dans l'image : il est monté. Le service en
# ligne et la ligne de commande exécutent ainsi exactement les mêmes fichiers,
# et ne peuvent pas diverger d'une version à l'autre.
FROM python:3.12-slim

# Le dépôt SQLite vit dans un volume, jamais dans la couche d'image : une
# reconstruction effacerait sinon tous les projets et tous les comptes.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ATELIER_DEPOT=/var/lib/atelier/atelier.sqlite3

WORKDIR /opt/odoo-builder

EXPOSE 8100

# « /sante » ne demande ni compte ni session : c'est précisément ce qu'il faut
# pour un contrôle de vie. Il ne dit jamais quel fournisseur ni quelle clé.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/sante', timeout=3)"

# « --ouvert » est une décision explicite, et elle est prise ICI, dans un
# conteneur qui ne publie aucun port : la seule façon de l'atteindre est la
# passerelle HTTPS. Voir docker-compose.atelier.yml.
CMD ["python", "cli/atelier.py", "--port", "8100", "--ouvert"]
