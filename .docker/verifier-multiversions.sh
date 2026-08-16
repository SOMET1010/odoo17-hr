#!/usr/bin/env bash
#
# La même spécification, sur un vrai Odoo de la version visée.
#
#   ODOO_TAG=18 CIBLE=18.0 ./.docker/verifier-multiversions.sh
#
# Le générateur sait viser 17, 18 et 19 ; savoir viser n'est pas atteindre.
# Les règles du dialecte restent des hypothèses tant qu'un Odoo réel ne les a
# pas acceptées — et une différence supposée est pire qu'une différence
# ignorée, parce qu'elle produit du code qui a l'air juste.
#
# Une version par exécution : c'est la matrice de la forge qui les enchaîne,
# chacune sur son runner. Mélanger trois Odoo sur une même machine ferait
# porter les échecs par l'isolement plutôt que par les versions.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

CIBLE="${CIBLE:-17.0}"
export ODOO_TAG="${ODOO_TAG:-${CIBLE%%.*}}"
export INSTALLATEUR_CLE_API="${INSTALLATEUR_CLE_API:-cle-de-recette-jetable}"
SPEC="${SPEC:-odoo-builder/specs/mission.json}"

VERT='\033[32m'; ROUGE='\033[31m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }

nettoyer() { docker compose --profile installateur down -v >/dev/null 2>&1; }
trap nettoyer EXIT

titre "Odoo $CIBLE (image odoo:$ODOO_TAG)"

docker compose --profile installateur up -d --build >/tmp/mv-up.log 2>&1 \
  || { tail -20 /tmp/mv-up.log; echo "démarrage impossible"; exit 1; }

# La base est créée par l'Odoo de la version visée : c'est déjà un contrôle.
# Une version qui refuserait d'initialiser une base neuve échouerait ici,
# avant toute question de module.
docker compose run --rm odoo odoo -d ansut -i base --stop-after-init \
  --log-level=warn >/tmp/mv-base.log 2>&1 \
  || { tail -20 /tmp/mv-base.log; echo "initialisation impossible"; exit 1; }
docker compose --profile installateur up -d >/dev/null 2>&1

for _ in $(seq 1 90); do
  curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8069/web/login 2>/dev/null && break
  sleep 2
done

printf '  version réellement servie : '
docker compose exec -T odoo odoo --version 2>/dev/null | head -1 || echo inconnue

python3 odoo-builder/cli/verifier_cible.py "$SPEC" --cible "$CIBLE"
code=$?

if [[ "$code" -ne 0 ]]; then
  titre "Journaux d'Odoo $CIBLE"
  docker compose logs --tail=60 odoo 2>&1 | tail -60
fi
exit "$code"
