# Service d'installation de modules Odoo.
#
# Aucune dépendance à installer : le service n'utilise que la bibliothèque
# standard. L'image se construit donc sans accès au réseau au-delà de
# l'image de base, et démarre en une seconde.
FROM python:3.12-slim

WORKDIR /app
COPY service.py validation.py client_odoo.py travaux.py /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/sante', timeout=3)"

CMD ["python", "service.py"]
