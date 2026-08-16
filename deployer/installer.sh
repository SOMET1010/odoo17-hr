#!/usr/bin/env bash
#
# Installe l'Atelier Odoo sur une VM Ubuntu neuve, en une commande.
#
#   bash deployer/installer.sh
#
# Ce script suppose une machine dédiée. Il ne doit PAS être joué sur un serveur
# qui héberge un Odoo de production : le Builder installe, casse et recrée des
# modules, et une base de test peut être supprimée sans préavis.
#
# Il ne demande rien d'autre que la clé du service d'IA, et n'expose aucun port
# sur l'extérieur : l'accès se fait par tunnel SSH, ou par un proxy inverse
# placé devant, décidé séparément.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
ok()    { printf '  %bOK%b    %s\n' "$VERT" "$FIN" "$*"; }
info()  { printf '        %s\n' "$*"; }
avert() { printf '  %bNOTE%b  %s\n' "$JAUNE" "$FIN" "$*"; }
fatal() { printf '  %bARRÊT%b %s\n' "$ROUGE" "$FIN" "$*"; exit 1; }

# ------------------------------------------------------------- prérequis

titre "1. La machine"

[[ "$(uname -s)" == "Linux" ]] || fatal "ce script vise une machine Linux."
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  info "système : ${PRETTY_NAME:-inconnu}"
fi

processeurs=$(nproc 2>/dev/null || echo 0)
memoire_mo=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
info "processeurs : ${processeurs}   mémoire : ${memoire_mo} Mo"

# Seuils tirés de la charge réelle : construire une image, démarrer Odoo et
# PostgreSQL, installer un module et jouer une recette.
(( processeurs >= 4 )) || avert "moins de 4 cœurs : les recettes seront lentes."
(( memoire_mo >= 7500 )) || avert "moins de 8 Go : Odoo et PostgreSQL peuvent manquer de mémoire."

espace_go=$(df -BG --output=avail . 2>/dev/null | tail -1 | tr -dc '0-9')
(( ${espace_go:-0} >= 20 )) || avert "moins de 20 Go libres : les images Docker en occupent une bonne part."

# -------------------------------------------------------------- docker

titre "2. Docker"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "déjà installé — $(docker --version | cut -d, -f1)"
else
  info "installation via le dépôt officiel Docker…"
  if ! command -v curl >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y -qq curl || fatal "curl introuvable."
  fi
  curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1 \
    || fatal "l'installation de Docker a échoué. Voir https://docs.docker.com/engine/install/"
  ok "Docker installé"
fi

if ! docker info >/dev/null 2>&1; then
  if sudo docker info >/dev/null 2>&1; then
    avert "Docker exige sudo pour cet utilisateur."
    info  "Pour l'éviter à l'avenir : sudo usermod -aG docker ${USER:-root}"
    info  "puis fermez et rouvrez votre session. Le script continue avec sudo."
    DOCKER="sudo docker"
  else
    fatal "le démon Docker ne répond pas."
  fi
else
  DOCKER="docker"
  ok "le démon Docker répond"
fi

# ------------------------------------------------------------- secrets

titre "3. Secrets"

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/atelier-odoo"
ENVFILE="$CONFIG/env"
mkdir -p "$CONFIG" && chmod 700 "$CONFIG"

if [[ -f "$ENVFILE" ]]; then
  ok "configuration existante conservée : $ENVFILE"
  # shellcheck disable=SC1090
  . "$ENVFILE"
else
  info "Le secret du service d'installation est composé automatiquement."
  INSTALLATEUR_CLE_API=$(head -c 32 /dev/urandom | base64 | tr -d '\n=/+' | head -c 40)

  printf '\n  Clé du service d'"'"'IA qui rédigera les spécifications.\n'
  printf '  Laissez vide pour la configurer plus tard.\n'
  read -r -s -p "  Clé : " CLE_IA; printf '\n'

  umask 077
  {
    echo "# Secrets de l'Atelier Odoo — ne pas partager, ne pas versionner."
    echo "export INSTALLATEUR_CLE_API=\"$INSTALLATEUR_CLE_API\""
    [[ -n "${CLE_IA:-}" ]] && echo "export BUILDER_IA_CLE=\"$CLE_IA\""
  } > "$ENVFILE"
  chmod 600 "$ENVFILE"
  ok "secrets écrits dans $ENVFILE (lisible par vous seul)"
  # shellcheck disable=SC1090
  . "$ENVFILE"
fi

# ---------------------------------------------------------------- pile

titre "4. Démarrage de la pile"

info "construction et démarrage — quelques minutes au premier passage…"
if ! INSTALLATEUR_CLE_API="$INSTALLATEUR_CLE_API" \
     $DOCKER compose --profile installateur up -d --build >/tmp/atelier-demarrage.log 2>&1; then
  tail -20 /tmp/atelier-demarrage.log
  fatal "le démarrage a échoué. Journal complet : /tmp/atelier-demarrage.log"
fi
ok "conteneurs démarrés"

info "attente d'Odoo…"
for _ in $(seq 1 90); do
  curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8069/web/login 2>/dev/null && break
  sleep 2
done
curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8069/web/login 2>/dev/null \
  && ok "Odoo répond" || avert "Odoo ne répond pas encore ; il finit peut-être de démarrer."

# Réinstaller un module déjà installé est sans effet : pas de condition à poser.
info "création de la base « ansut » et installation des modules…"
$DOCKER compose run --rm odoo odoo -d ansut \
  -i diligence_simple,theme_backend,ansut_rh --stop-after-init \
  >/tmp/atelier-modules.log 2>&1 && ok "modules installés" \
  || avert "installation partielle — voir /tmp/atelier-modules.log"
$DOCKER compose --profile installateur up -d >/dev/null 2>&1

# ------------------------------------------------------------ vérification

titre "5. Vérification"

curl -sS -o /dev/null --max-time 5 http://127.0.0.1:8090/sante 2>/dev/null \
  && ok "service d'installation joignable" \
  || avert "service d'installation muet — $DOCKER compose logs installateur"

exposes=$($DOCKER compose ps --format '{{.Ports}}' 2>/dev/null | grep -c '0\.0\.0\.0' || true)
if [[ "${exposes:-0}" -eq 0 ]]; then
  ok "aucun port exposé sur l'extérieur"
else
  avert "$exposes service(s) écoutent sur toutes les interfaces — vérifier BIND_ADRESSE."
fi

# ---------------------------------------------------------------- suite

titre "C'est prêt"

printf '  L'"'"'Atelier tourne, et n'"'"'est joignable que depuis cette machine.\n\n'
printf '  %bDepuis votre poste%b, ouvrez un tunnel puis allez sur http://localhost:8069\n' "$GRAS" "$FIN"
printf '      ssh -N -L 8069:127.0.0.1:8069 %s@%s\n\n' "${USER:-root}" "$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '  %bSur cette machine%b, à chaque session :\n' "$GRAS" "$FIN"
printf '      source %s\n\n' "$ENVFILE"
if [[ -z "${BUILDER_IA_CLE:-}" ]]; then
  printf '  %bIl reste à déclarer la clé du service d'"'"'IA :%b\n' "$JAUNE" "$FIN"
  printf '      python3 odoo-builder/cli/atelier_odoo.py setup\n\n'
else
  printf '  Fabriquer un module depuis un besoin :\n'
  printf '      python3 odoo-builder/cli/atelier_odoo.py providers check\n'
  printf '      python3 odoo-builder/cli/acceptation.py\n\n'
fi
