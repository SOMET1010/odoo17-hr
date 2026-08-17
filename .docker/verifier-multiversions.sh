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

# Le banc ne porte que les addons d'Odoo et le dépôt de l'Atelier. Le dépôt Git
# est une base de code Odoo 17 : ses manifestes empêchent Odoo 18 d'initialiser
# une base. Voir .docker/odoo-multiversions.conf.
export ODOO_CONF="${ODOO_CONF:-./.docker/odoo-multiversions.conf}"

VERT='\033[32m'; ROUGE='\033[31m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }

nettoyer() { docker compose --profile installateur down -v >/dev/null 2>&1; }
trap nettoyer EXIT

titre "Odoo $CIBLE (image odoo:$ODOO_TAG)"

# Sur échec, on montre LARGEMENT : une exception Python affiche sa cause avant
# le message qui l'enveloppe. Un « tail » trop court garde le « invalid
# manifest » et jette le « Invalid version '17.0.1.0.0' » qui l'explique —
# c'est-à-dire tout ce qui sert.
montrer() { printf '\n'; tail -80 "$1"; printf '\n%b%s%b\n' "$ROUGE" "$2" "$FIN"; }

docker compose --profile installateur up -d --build >/tmp/mv-up.log 2>&1 \
  || { montrer /tmp/mv-up.log "démarrage impossible"; exit 1; }

# La base est créée par l'Odoo de la version visée : c'est déjà un contrôle.
# Une version qui refuserait d'initialiser une base neuve échouerait ici,
# avant toute question de module.
docker compose run --rm odoo odoo -d ansut -i base --stop-after-init \
  --log-level=warn >/tmp/mv-base.log 2>&1 \
  || { montrer /tmp/mv-base.log "initialisation impossible"; exit 1; }
docker compose --profile installateur up -d >/dev/null 2>&1

for _ in $(seq 1 90); do
  curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8069/web/login 2>/dev/null && break
  sleep 2
done

printf '  version réellement servie : '
docker compose exec -T odoo odoo --version 2>/dev/null | head -1 || echo inconnue

# Ce qu'Odoo a RÉELLEMENT retenu comme chemin d'addons. Odoo 19 écarte
# silencieusement un dossier vide de « addons_path » : sans cette ligne, le
# module déposé devient introuvable sans que rien ne dise pourquoi.
printf '  chemin d'"'"'addons retenu : '
docker compose exec -T odoo python3 -c \
  "from odoo.tools import config; config.parse_config([]); print(config['addons_path'])" \
  2>/dev/null || echo "(non lisible)"

python3 odoo-builder/cli/verifier_cible.py "$SPEC" --cible "$CIBLE" 2>&1 | tee /tmp/mv-verdict.log
code=${PIPESTATUS[0]}

# Puis la GREFFE : un module qui n'invente aucun écran et s'accroche à celui
# d'Odoo. C'est le seul contrôle possible de l'ancre — « work_email » vit dans
# un module qu'on ne lit pas, et rien, hors d'un Odoo réel où « hr » est
# installé, ne peut dire qu'elle existe. Une ancre fausse fait échouer
# l'installation avec « Element cannot be located in parent view » ; ici, ça se
# verra ici, pas chez l'utilisateur.
if [[ "$code" -eq 0 ]]; then
  titre "Greffe sur un module d'Odoo, en $CIBLE"
  python3 odoo-builder/cli/verifier_cible.py \
    odoo-builder/specs/extension_employe.json --cible "$CIBLE" 2>&1 \
    | tee -a /tmp/mv-verdict.log
  code=${PIPESTATUS[0]}
fi

# Puis la conversion : un module écrit à la mode d'Odoo 12, relu et installé
# dans l'Odoo de la version visée. C'est la seule preuve qui vaille pour le
# convertisseur — « la spécification se génère » ne dit rien de ce qu'Odoo en
# pense, et c'est précisément là que les modules anciens échouent.
if [[ "$code" -eq 0 ]]; then
  titre "Conversion d'un module Odoo 12 vers $CIBLE"
  python3 odoo-builder/cli/verifier_cible.py odoo-builder/exemples/suivi_dossier \
    --cible "$CIBLE" 2>&1 | tee -a /tmp/mv-verdict.log
  code=${PIPESTATUS[0]}
fi

if [[ "$code" -ne 0 ]]; then
  titre "Journaux d'Odoo $CIBLE"
  # Les avertissements de manifeste se comptent par centaines sur une image
  # avec les addons Enterprise : ils noieraient la ligne qui compte.
  docker compose logs --tail=400 odoo 2>&1 \
    | grep -vE "Missing \`author\` key|Missing \`license\` key" \
    | tail -40

  # Le verdict est répété EN DERNIER. Vidé avant les journaux, il se retrouvait
  # à quarante lignes du bas, et la forge affichait un échec sans motif lisible.
  titre "Verdict d'Odoo $CIBLE"
  grep -E "ÉCHEC|Échec|Erreur|OK " /tmp/mv-verdict.log | tail -20
fi
exit "$code"
