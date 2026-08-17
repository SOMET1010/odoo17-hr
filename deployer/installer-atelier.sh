#!/usr/bin/env bash
#
# Met l'Atelier en ligne, sur une machine neuve, en une commande.
#
#   bash deployer/installer-atelier.sh --domaine atelier.exemple.fr \
#                                      --courriel vous@exemple.fr
#
# SANS DOMAINE, ça marche quand même : un nom dérivé de l'adresse IP est
# employé (sslip.io), et le certificat s'obtient dessus. Rien à acheter.
#
#   bash deployer/installer-atelier.sh
#
# CE QUE CE SCRIPT INSTALLE, ET CE QU'IL N'INSTALLE PAS. L'Atelier seul :
# l'interface et sa passerelle HTTPS. Ni Odoo, ni PostgreSQL — il n'en a
# besoin ni de l'un ni de l'autre, et c'est ce qui permet la plus petite
# machine qu'on puisse louer (2 vCPU, 4 Go). Pour la pile complète, avec Odoo
# et le service d'installation, c'est deployer/installer.sh.
#
# UNE CLÉ DE MODÈLE, ET CHEZ QUI. « --cle-ia » suffit pour OpenAI. Pour tout
# autre fournisseur parlant le même protocole — Moonshot/Kimi, un service
# local — ajoutez « --url » et « --modele ».
#
# LE CODE D'INSTALLATION. Le premier compte créé sera administrateur. Sur une
# adresse publique, le premier arrivé n'est pas forcément vous : le script
# tire un code au sort, l'affiche à la fin, et l'Atelier le réclame pour ce
# seul premier compte. Sans code, l'inscription est refusée — une instance
# qu'on n'arrive pas à amorcer se répare, une instance prise par un inconnu,
# non.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

DOMAINE=""
COURRIEL=""
CLE_IA=""
URL_IA=""
MODELE_IA=""
SANS_QUESTION=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domaine)  DOMAINE="${2:-}"; shift 2 ;;
    --courriel) COURRIEL="${2:-}"; shift 2 ;;
    --cle-ia)   CLE_IA="${2:-}"; shift 2 ;;
    # Tout fournisseur parlant le protocole OpenAI convient — Moonshot/Kimi,
    # un service local, un proxy d'entreprise. Sans ces deux options, c'est
    # OpenAI et « gpt-4o ». Les poser ici évite d'aller éditer un fichier sur
    # le serveur, ce qui est exactement ce qu'un installeur doit éviter.
    --url)      URL_IA="${2:-}"; shift 2 ;;
    --modele)   MODELE_IA="${2:-}"; shift 2 ;;
    --sans-question) SANS_QUESTION=1; shift ;;
    *) printf 'Option inconnue : %s\n' "$1" >&2; exit 1 ;;
  esac
done

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
ok()    { printf '  %bOK%b    %s\n' "$VERT" "$FIN" "$*"; }
info()  { printf '        %s\n' "$*"; }
avert() { printf '  %bNOTE%b  %s\n' "$JAUNE" "$FIN" "$*"; }
fatal() { printf '  %bARRÊT%b %s\n' "$ROUGE" "$FIN" "$*"; exit 1; }

PILE=(compose -f docker-compose.atelier.yml)

# ------------------------------------------------------------- 1. machine

titre "1. La machine"

[[ "$(uname -s)" == "Linux" ]] || fatal "ce script vise une machine Linux."
if [[ -r /etc/os-release ]]; then . /etc/os-release; info "système : ${PRETTY_NAME:-inconnu}"; fi
memoire_mo=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
info "mémoire : ${memoire_mo} Mo"
# L'Atelier tourne en Python, sans base de données : il tient largement dans
# 2 Go. Le seuil est là pour la CONSTRUCTION de l'image, pas pour le service.
(( memoire_mo >= 1700 )) || avert "moins de 2 Go : la construction de l'image peut échouer."

# -------------------------------------------------------------- 2. docker

titre "2. Docker"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "déjà installé — $(docker --version | cut -d, -f1)"
else
  info "installation via le dépôt officiel Docker…"
  # « A || B && C » se lit « (A || B) && C » : écrite en une ligne, cette
  # condition installait curl même quand il était là, et l'installait quand
  # même si la mise à jour du dépôt avait échoué. Un « if » dit ce qu'on veut.
  if ! command -v curl >/dev/null 2>&1; then
    sudo apt-get update -qq \
      && sudo apt-get install -y -qq curl \
      || fatal "curl est introuvable et n'a pas pu être installé."
  fi
  curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1 \
    || fatal "l'installation de Docker a échoué. Voir https://docs.docker.com/engine/install/"
  ok "Docker installé"
fi

if docker info >/dev/null 2>&1; then
  DOCKER="docker"; ok "le démon Docker répond"
elif sudo docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
  avert "Docker exige sudo pour cet utilisateur."
  info  "Pour l'éviter : sudo usermod -aG docker ${USER:-root}, puis rouvrez la session."
else
  fatal "le démon Docker ne répond pas."
fi

# --------------------------------------------------------------- 3. le nom

titre "3. Le nom du site"

if [[ -z "$DOMAINE" ]]; then
  # sslip.io répond à « 1.2.3.4.sslip.io » par 1.2.3.4 : un nom valide, donc
  # un certificat possible, sans rien acheter ni configurer.
  adresse=$(curl -sS --max-time 5 https://api.ipify.org 2>/dev/null \
    || ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
  [[ -n "${adresse:-}" ]] || fatal "adresse publique introuvable : passez --domaine."
  DOMAINE="${adresse}.sslip.io"
  avert "aucun domaine fourni : « $DOMAINE » sera employé."
  info  "Un nom à vous se pose plus tard, en relançant avec --domaine."
fi
ok "site : https://$DOMAINE"

# ------------------------------------------------------------ 4. secrets

titre "4. Secrets"

# Alphanumérique : ce code traverse un shell, une commande Docker et une
# chaîne JSON. Sans ponctuation, il n'y a rien à échapper — et il se recopie
# sans erreur depuis une console.
hasard() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-24}"; }

# Lire un réglage SANS l'exécuter. « source » sur un fichier de configuration
# fait de chaque ligne une commande : « ATELIER_ACME_EMAIL=email vous@ex.fr »
# posait la variable à « email », puis tentait de lancer votre adresse comme un
# programme. Un fichier de réglages ne doit rien pouvoir exécuter — et cette
# lecture-ci accepte aussi bien les valeurs entre guillemets que sans.
lire_reglage() {                       # lire_reglage FICHIER CLÉ
  [[ -f "$1" ]] || return 0
  sed -n "s/^$2=//p" "$1" | tail -1 | sed -e 's/^"//' -e 's/"$//'
}

ATELIER_INSCRIPTION="$(lire_reglage .env.atelier ATELIER_INSCRIPTION)"
if [[ -f .env.atelier ]]; then
  ok "configuration existante conservée : .env.atelier"
  # Ce qui n'est pas redonné en option est REPRIS du fichier. Sans cela, une
  # relance pour changer de domaine effacerait la clé d'IA et le code
  # d'installation — et le code, lui, ne se retrouve nulle part.
  CLE_IA="${CLE_IA:-$(lire_reglage .env.atelier BUILDER_IA_CLE)}"
  URL_IA="${URL_IA:-$(lire_reglage .env.atelier BUILDER_IA_URL)}"
  MODELE_IA="${MODELE_IA:-$(lire_reglage .env.atelier BUILDER_IA_MODELE)}"
  COURRIEL="${COURRIEL:-$(lire_reglage .env.atelier ATELIER_ACME_EMAIL | sed 's/^email //')}"
fi
if [[ -z "$ATELIER_INSCRIPTION" ]]; then
  # Absent du fichier, ou fichier neuf. En tirer un nouveau n'ouvre rien :
  # il ne sert qu'au PREMIER compte, et dès qu'un compte existe l'Atelier
  # cesse de le réclamer.
  ATELIER_INSCRIPTION=$(hasard 24)
  if [[ -z "$CLE_IA" && "$SANS_QUESTION" == "0" ]]; then
    printf '\n  Clé du service d'"'"'IA qui rédigera les spécifications.\n'
    printf '  Laissez vide pour la configurer plus tard.\n'
    read -r -s -p "  Clé : " CLE_IA; printf '\n'
  fi
fi

umask 077
{
  echo "# Écrit par deployer/installer-atelier.sh. Contient des secrets."
  # Entre guillemets : docker compose les retire à la lecture, et une valeur
  # à espaces — « email vous@exemple.fr » — cesse d'être un piège pour qui
  # relirait ce fichier avec un shell.
  echo "ATELIER_DOMAINE=\"$DOMAINE\""
  echo "ATELIER_INSCRIPTION=\"$ATELIER_INSCRIPTION\""
  [[ -n "$CLE_IA" ]] && echo "BUILDER_IA_CLE=\"$CLE_IA\""
  [[ -n "$URL_IA" ]] && echo "BUILDER_IA_URL=\"$URL_IA\""
  [[ -n "$MODELE_IA" ]] && echo "BUILDER_IA_MODELE=\"$MODELE_IA\""
  # Directive complète, ou rien : « email » sans argument empêche Caddy de
  # démarrer, en boucle, et une variable définie mais vide ne prend pas son
  # défaut.
  [[ -n "$COURRIEL" ]] && echo "ATELIER_ACME_EMAIL=\"email $COURRIEL\""
} > .env.atelier
chmod 600 .env.atelier
ok "secrets écrits dans .env.atelier (600)"

# docker compose lit « .env », pas « .env.atelier » : on l'y verse, sans
# écraser une pile complète éventuellement installée sur la même machine.
if [[ -f .env ]] && grep -q 'INSTALLATEUR_CLE_API' .env 2>/dev/null; then
  avert "un .env de la pile complète existe : les réglages y sont ajoutés."
  grep -v '^ATELIER_DOMAINE=\|^ATELIER_INSCRIPTION=\|^ATELIER_ACME_EMAIL=\|^BUILDER_IA_CLE=\|^BUILDER_IA_URL=\|^BUILDER_IA_MODELE=' \
    .env > /tmp/env-fusion 2>/dev/null
  cat /tmp/env-fusion .env.atelier > .env && rm -f /tmp/env-fusion
else
  cp .env.atelier .env
fi
chmod 600 .env

# ---------------------------------------------------------------- 5. pare-feu

titre "5. Ports"

if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow 80/tcp  >/dev/null 2>&1
  sudo ufw allow 443/tcp >/dev/null 2>&1
  ok "80 et 443 ouverts dans ufw"
else
  info "pas de ufw actif — rien à ouvrir localement."
fi
info "L'interface, elle, ne publie aucun port : la passerelle est le seul chemin."

# ----------------------------------------------------------------- 6. pile

titre "6. Démarrage"

info "construction et démarrage — quelques minutes au premier passage…"
if ! $DOCKER "${PILE[@]}" up -d --build >/tmp/atelier-en-ligne.log 2>&1; then
  tail -20 /tmp/atelier-en-ligne.log
  fatal "le démarrage a échoué. Journal : /tmp/atelier-en-ligne.log"
fi
ok "conteneurs démarrés"

info "attente du certificat et de la première réponse…"
joignable=0
for _ in $(seq 1 60); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
    "https://$DOMAINE/sante" 2>/dev/null)
  [[ "$code" == "200" ]] && { joignable=1; break; }
  sleep 3
done

if [[ "$joignable" == "1" ]]; then
  ok "https://$DOMAINE répond"
else
  avert "l'adresse ne répond pas encore."
  info  "Causes usuelles : le DNS n'a pas encore propagé, ou le port 443 est"
  info  "filtré par le pare-feu du fournisseur (pas seulement par ufw)."
  info  "Journal : $DOCKER ${PILE[*]} logs passerelle"
fi

# -------------------------------------------------------------- 7. verdict

titre "C'est en ligne"

printf '\n  %bL'"'"'Atelier :%b https://%s\n\n' "$GRAS" "$FIN" "$DOMAINE"
printf '  %bCode d'"'"'installation :%b %s\n' "$GRAS" "$FIN" "$ATELIER_INSCRIPTION"
printf '        Il n'"'"'est demandé que pour créer le PREMIER compte, qui sera\n'
printf '        administrateur. Faites-le maintenant : tant qu'"'"'aucun compte\n'
printf '        n'"'"'existe, l'"'"'instance attend le sien.\n\n'
if [[ -z "$CLE_IA" ]]; then
  printf '  %bSans clé d'"'"'IA%b, le bouton « Concevoir » restera muet. La conversion\n' \
    "$GRAS" "$FIN"
  printf '        d'"'"'un module existant et les thèmes, eux, fonctionnent sans.\n'
  printf '        Pour l'"'"'ajouter : relancez avec --cle-ia, ou éditez .env.atelier.\n\n'
fi
printf '        Sauvegarde : un seul fichier porte tout, projets et comptes.\n'
printf '        « iterdump » lit dans une transaction — donc pendant que ça tourne,\n'
printf '        sans copier un fichier à moitié écrit :\n'
printf '            %s %s exec -T atelier-web python -c \\\n' "$DOCKER" "${PILE[*]}"
printf '              "import sqlite3,sys;[sys.stdout.write(l+chr(10)) for l in \\\n'
printf '               sqlite3.connect('"'"'/var/lib/atelier/atelier.sqlite3'"'"').iterdump()]" \\\n'
printf '              > sauvegarde.sql\n\n'
