# API de l'Atelier.
#
# Comme le service d'installation : bibliothèque standard seulement, aucune
# dépendance à télécharger. Le code du Builder n'est pas copié dans l'image
# mais monté — le service et la ligne de commande exécutent ainsi exactement
# les mêmes fichiers, et ne peuvent pas diverger d'une version.
FROM python:3.12-slim

WORKDIR /app
COPY service.py travaux.py /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUILDER_SRC=/opt/odoo-builder/src

EXPOSE 8091

HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/sante', timeout=3)"

CMD ["python", "service.py"]
