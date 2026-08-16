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
# Par défaut il n'expose aucun port sur l'extérieur : l'accès se fait par
# tunnel SSH. Avec --public, l'interface Odoo — et elle seule — est publiée
# sur Internet, protégée par un mot de passe administrateur tiré au hasard.
# Le service d'installation, lui, reste toujours sur 127.0.0.1.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PUBLIC=""
for argument in "$@"; do
  case "$argument" in
    --public) PUBLIC="oui" ;;
    --prive)  PUBLIC="non" ;;
    *) printf 'Option inconnue : %s\n' "$argument" >&2; exit 1 ;;
  esac
done

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

# Alphanumérique seulement : ce mot de passe traverse un shell, une commande
# Docker et une chaîne Python. Sans ponctuation, il n'y a rien à échapper.
hasard() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }

if [[ -f "$ENVFILE" ]]; then
  ok "configuration existante conservée : $ENVFILE"
  # shellcheck disable=SC1090
  . "$ENVFILE"
else
  info "Le secret du service d'installation est composé automatiquement."
  INSTALLATEUR_CLE_API=$(hasard 40)
  ODOO_ADMIN_MOTDEPASSE=$(hasard 24)

  printf '\n  Clé du service d'"'"'IA qui rédigera les spécifications.\n'
  printf '  Laissez vide pour la configurer plus tard.\n'
  read -r -s -p "  Clé : " CLE_IA; printf '\n'

  umask 077
  {
    echo "# Secrets de l'Atelier Odoo — ne pas partager, ne pas versionner."
    echo "export INSTALLATEUR_CLE_API=\"$INSTALLATEUR_CLE_API\""
    echo "export ODOO_ADMIN_MOTDEPASSE=\"$ODOO_ADMIN_MOTDEPASSE\""
    [[ -n "${CLE_IA:-}" ]] && echo "export BUILDER_IA_CLE=\"$CLE_IA\""
  } > "$ENVFILE"
  chmod 600 "$ENVFILE"
  ok "secrets écrits dans $ENVFILE (lisible par vous seul)"
  # shellcheck disable=SC1090
  . "$ENVFILE"
fi

# Une installation antérieure à cette version n'a pas de mot de passe Odoo.
if [[ -z "${ODOO_ADMIN_MOTDEPASSE:-}" ]]; then
  ODOO_ADMIN_MOTDEPASSE=$(hasard 24)
  umask 077
  echo "export ODOO_ADMIN_MOTDEPASSE=\"$ODOO_ADMIN_MOTDEPASSE\"" >> "$ENVFILE"
  ok "mot de passe administrateur Odoo ajouté à la configuration"
fi

# ------------------------------------------------------------- exposition

titre "4. Accès"

if [[ -z "$PUBLIC" ]]; then
  printf '  Sans ouverture, l'"'"'Atelier n'"'"'est joignable que par tunnel SSH —\n'
  printf '  impossible depuis un téléphone. Avec ouverture, l'"'"'interface Odoo\n'
  printf '  est publiée sur Internet en HTTP, derrière son mot de passe.\n'
  read -r -p "  Ouvrir l'interface sur Internet ? [o/N] " reponse
  [[ "${reponse,,}" == o* ]] && PUBLIC="oui" || PUBLIC="non"
fi

if [[ "$PUBLIC" == "oui" ]]; then
  BIND_ODOO="0.0.0.0"
  avert "l'interface sera joignable depuis Internet, sans HTTPS."
  info  "Le service d'installation, lui, reste sur 127.0.0.1."
else
  BIND_ODOO="127.0.0.1"
  ok "aucun port ouvert — accès par tunnel SSH."
fi

# docker compose lit ce fichier tout seul : les réglages survivent à un
# redémarrage et à un « docker compose up » lancé à la main.
umask 077
{
  echo "# Écrit par deployer/installer.sh. Contient des secrets."
  echo "BIND_ODOO=$BIND_ODOO"
  echo "INSTALLATEUR_CLE_API=$INSTALLATEUR_CLE_API"
  echo "ODOO_ADMIN_MOTDEPASSE=$ODOO_ADMIN_MOTDEPASSE"
} > .env
chmod 600 .env

# ---------------------------------------------------------------- pile

titre "5. Démarrage de la pile"

info "construction et démarrage — quelques minutes au premier passage…"
if ! $DOCKER compose --profile installateur up -d --build >/tmp/atelier-demarrage.log 2>&1; then
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

# Odoo crée le compte « admin » avec le mot de passe « admin ». Le laisser
# serait une porte ouverte dès que le port 8069 l'est. On le remplace ici,
# et non plus tard : le service d'installation s'authentifie avec.
info "pose du mot de passe administrateur…"
printf "%s\n" \
  "env['res.users'].search([('login','=','admin')]).write({'password': '$ODOO_ADMIN_MOTDEPASSE'})" \
  "env.cr.commit()" \
  | $DOCKER compose run --rm -T odoo odoo shell -d ansut --log-level=warn \
    >/tmp/atelier-motdepasse.log 2>&1 && ok "mot de passe administrateur posé" \
    || avert "mot de passe inchangé — voir /tmp/atelier-motdepasse.log"

$DOCKER compose --profile installateur up -d >/dev/null 2>&1

# ------------------------------------------------------------ vérification

titre "6. Vérification"

curl -sS -o /dev/null --max-time 5 http://127.0.0.1:8090/sante 2>/dev/null \
  && ok "service d'installation joignable" \
  || avert "service d'installation muet — $DOCKER compose logs installateur"

# Le seul port dont l'ouverture serait une faute, quel que soit le mode.
if $DOCKER compose ps --format '{{.Ports}}' 2>/dev/null | grep -q '0\.0\.0\.0:8090'; then
  avert "le service d'installation écoute sur toutes les interfaces — à corriger."
else
  ok "service d'installation confiné à la machine"
fi

# Le mot de passe ne compte que s'il est vraiment posé. On le vérifie des
# deux côtés : le nouveau doit passer, l'ancien doit être refusé.
connexion() {
  curl -sS --max-time 10 -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"params\":{\"db\":\"ansut\",\"login\":\"admin\",\"password\":\"$1\"}}" \
    http://127.0.0.1:8069/web/session/authenticate 2>/dev/null | grep -q '"uid": *[0-9]'
}
if connexion "$ODOO_ADMIN_MOTDEPASSE"; then
  if connexion admin; then
    avert "le mot de passe « admin » fonctionne encore."
  else
    ok "compte administrateur protégé"
  fi
else
  avert "connexion administrateur impossible — voir /tmp/atelier-motdepasse.log"
fi

# ---------------------------------------------------------------- suite

titre "C'est prêt"

adresse=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -1)
[[ -n "$adresse" ]] || adresse=$(hostname -I 2>/dev/null | awk '{print $1}')

if [[ "$PUBLIC" == "oui" ]]; then
  printf '  %bLe back-office :%b http://%s:8069\n\n' "$GRAS" "$FIN" "${adresse:-<ip-du-serveur>}"
  printf '      identifiant   admin\n'
  printf '      mot de passe  %s\n\n' "$ODOO_ADMIN_MOTDEPASSE"
  printf '  Notez ce mot de passe : il n'"'"'est réaffiché nulle part.\n'
  printf '  La liaison est en HTTP, sans certificat — bon pour un atelier,\n'
  printf '  pas pour des données réelles. Le HTTPS viendra avec le proxy.\n\n'
else
  printf '  L'"'"'Atelier tourne, et n'"'"'est joignable que depuis cette machine.\n\n'
  printf '  %bDepuis votre poste%b, ouvrez un tunnel puis allez sur http://localhost:8069\n' "$GRAS" "$FIN"
  printf '      ssh -N -L 8069:127.0.0.1:8069 %s@%s\n\n' "${USER:-root}" "${adresse:-<ip-du-serveur>}"
  printf '      identifiant   admin\n'
  printf '      mot de passe  %s\n\n' "$ODOO_ADMIN_MOTDEPASSE"
fi

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
