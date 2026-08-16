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
# Trois accès possibles, demandés à l'installation ou passés en option :
#
#   --https                 passerelle HTTPS, certificat automatique. Sans
#   --domaine mon.site.fr   domaine fourni, un nom dérivé de l'adresse IP est
#                           employé (sslip.io) : rien à acheter.
#   --public                interface ouverte en clair, sans chiffrement.
#   --prive                 rien d'ouvert ; accès par tunnel SSH.
#
#   --addons-entreprise CHEMIN   dossier d'addons Odoo Enterprise, HORS du
#                                dépôt. Sous OEEL-1 : jamais versionnés, jamais
#                                copiés dans une image.
#   --addons-maison CHEMIN       vos modules de production, HORS du dépôt.
#
# Dans tous les cas le service d'installation reste sur 127.0.0.1 : il reçoit
# des archives et installe du code, il n'a rien à faire sur Internet.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

MODE=""        # https | http | ferme
DOMAINE=""
COURRIEL=""
ENTREPRISE=""
MAISON=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --https)    MODE="https"; shift ;;
    --domaine)  MODE="https"; DOMAINE="${2:-}"; shift 2 ;;
    --courriel) COURRIEL="${2:-}"; shift 2 ;;
    --public)   MODE="http";  shift ;;
    --prive)    MODE="ferme"; shift ;;
    --addons-entreprise) ENTREPRISE="${2:-}"; shift 2 ;;
    --addons-maison)     MAISON="${2:-}"; shift 2 ;;
    *) printf 'Option inconnue : %s\n' "$1" >&2; exit 1 ;;
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

  # Une clé ne dit pas à qui elle appartient : « sk-… » ne désigne personne, et
  # une clé Moonshot envoyée à OpenAI est refusée par un 401 qui ressemble à
  # une clé invalide. Plutôt que de laisser cette confusion pour plus tard, on
  # demande aux fournisseurs lequel la reconnaît.
  if [[ -n "${CLE_IA:-}" ]]; then
    info "recherche du fournisseur de cette clé…"
    if BUILDER_IA_CLE="$CLE_IA" python3 odoo-builder/cli/atelier_odoo.py \
         providers detect --adopter >/tmp/atelier-fournisseur.log 2>&1; then
      # shellcheck disable=SC1090
      . "$ENVFILE"
      ok "fournisseur reconnu : ${BUILDER_IA_URL:-inconnu}"
      info "modèle : ${BUILDER_IA_MODELE:-non précisé}"
    else
      avert "aucun fournisseur connu ne reconnaît cette clé."
      info  "Détail : /tmp/atelier-fournisseur.log"
      info  "L'installation continue ; la fabrication de modules attendra."
    fi
  fi
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

adresse=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -1)
[[ -n "$adresse" ]] || adresse=$(hostname -I 2>/dev/null | awk '{print $1}')

if [[ -z "$MODE" ]]; then
  printf '  %bhttps%b  interface chiffrée, certificat automatique — recommandé,\n' "$GRAS" "$FIN"
  printf '         et seule option qu'"'"'un navigateur laissera appeler depuis\n'
  printf '         une autre application web.\n'
  printf '  %bhttp%b   ouverte en clair. Un mot de passe qui voyage en clair est\n' "$GRAS" "$FIN"
  printf '         un mot de passe public.\n'
  printf '  %bferme%b  rien d'"'"'ouvert ; accès par tunnel SSH, donc pas depuis un\n' "$GRAS" "$FIN"
  printf '         téléphone.\n'
  read -r -p "  Quel accès ? [https/http/ferme] (Entrée = ferme) " reponse
  case "${reponse,,}" in
    http)  MODE="http" ;;
    ferme|fermé|"") MODE="ferme" ;;
    *)     MODE="https" ;;
  esac
fi

# Un dossier d'addons posé DANS le dépôt finirait tôt ou tard dans un commit —
# le premier « git add -A » suffirait. Pour les modules Enterprise c'est une
# faute de licence ; pour vos modules de production, c'est leur historique et
# leur visibilité qui changeraient à leur insu. On refuse avant, pas après.
verifier_addons() {
  local chemin="$1" etiquette="$2"
  local reel depot nombre
  reel=$(readlink -f "$chemin" 2>/dev/null || echo "")
  depot=$(readlink -f . 2>/dev/null || echo ".")
  [[ -n "$reel" && -d "$reel" ]] || fatal "dossier $etiquette introuvable : $chemin"
  if [[ "$reel" == "$depot"/* || "$reel" == "$depot" ]]; then
    fatal "refus : « $reel » est dans le dépôt. Ces modules ne doivent jamais y entrer."
  fi
  nombre=$(find "$reel" -maxdepth 2 -name "__manifest__.py" 2>/dev/null | wc -l)
  ok "addons $etiquette : $reel ($nombre module(s) détecté(s))"
  (( nombre > 0 )) || avert "aucun manifeste trouvé — le chemin pointe-t-il sur le bon dossier ?"
}

[[ -n "$ENTREPRISE" ]] && verifier_addons "$ENTREPRISE" "Enterprise"
[[ -n "$MAISON" ]] && verifier_addons "$MAISON" "maison"

BIND_ODOO="127.0.0.1"
PROFILS=(--profile installateur)
ODOO_OPTIONS=""

case "$MODE" in
  https)
    # Sans nom de domaine, aucune autorité ne peut délivrer de certificat.
    # sslip.io résout n'importe quelle adresse écrite dans le nom : rien à
    # acheter, rien à configurer chez un registraire. Un vrai domaine reste
    # préférable — il survit à un changement d'adresse, pas celui-ci.
    if [[ -z "$DOMAINE" ]]; then
      [[ -n "$adresse" ]] || fatal "adresse IP introuvable : préciser --domaine."
      DOMAINE="${adresse//./-}.sslip.io"
      info "aucun domaine fourni : « $DOMAINE » (dérivé de l'adresse)."
    fi
    for port in 80 443; do
      if ss -ltn 2>/dev/null | grep -q ":$port "; then
        fatal "le port $port est déjà pris ; la passerelle ne pourra pas l'ouvrir."
      fi
    done
    PROFILS+=(--profile passerelle)
    # Derrière la passerelle seulement : sur une instance directement exposée,
    # cette option ferait confiance à des en-têtes falsifiables.
    ODOO_OPTIONS="--proxy-mode"
    ok "HTTPS sur https://$DOMAINE — Odoo reste inaccessible en direct."
    ;;
  http)
    BIND_ODOO="0.0.0.0"
    avert "l'interface sera joignable en clair, sans chiffrement."
    info  "Le service d'installation, lui, reste sur 127.0.0.1."
    ;;
  *)
    ok "aucun port ouvert — accès par tunnel SSH."
    ;;
esac

# docker compose lit ce fichier tout seul : les réglages survivent à un
# redémarrage et à un « docker compose up » lancé à la main.
umask 077
{
  echo "# Écrit par deployer/installer.sh. Contient des secrets."
  echo "BIND_ODOO=$BIND_ODOO"
  echo "INSTALLATEUR_CLE_API=$INSTALLATEUR_CLE_API"
  echo "ODOO_ADMIN_MOTDEPASSE=$ODOO_ADMIN_MOTDEPASSE"
  echo "ODOO_OPTIONS=$ODOO_OPTIONS"
  [[ -n "$ENTREPRISE" ]] && echo "ADDONS_ENTREPRISE=$ENTREPRISE"
  [[ -n "$MAISON" ]] && echo "ADDONS_MAISON=$MAISON"
  [[ -n "$DOMAINE" ]] && echo "ATELIER_DOMAINE=$DOMAINE"
  # Directive complète, ou rien : « email » sans argument empêche Caddy
  # de démarrer, et une variable définie mais vide ne prend aucun défaut.
  [[ -n "$COURRIEL" ]] && echo "ATELIER_ACME_EMAIL=email $COURRIEL"
} > .env
chmod 600 .env

# ---------------------------------------------------------------- pile

titre "5. Démarrage de la pile"

info "construction et démarrage — quelques minutes au premier passage…"
if ! $DOCKER compose "${PROFILS[@]}" up -d --build >/tmp/atelier-demarrage.log 2>&1; then
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

$DOCKER compose "${PROFILS[@]}" up -d >/dev/null 2>&1

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

# Le certificat s'obtient auprès d'une autorité qui doit joindre cette machine
# sur le port 80. Beaucoup de choses peuvent l'en empêcher — pare-feu de
# l'hébergeur, nom qui ne pointe pas ici, port déjà pris. Annoncer une adresse
# HTTPS sans avoir vérifié qu'elle répond ferait perdre le temps qu'on croit
# gagner.
if [[ "$MODE" == "https" ]]; then
  info "attente du certificat pour $DOMAINE — jusqu'à une minute…"
  obtenu=0
  for _ in $(seq 1 30); do
    if curl -sS -o /dev/null --max-time 5 "https://$DOMAINE/web/login" 2>/dev/null; then
      obtenu=1; break
    fi
    sleep 2
  done
  if [[ "$obtenu" == "1" ]]; then
    ok "https://$DOMAINE répond, certificat valide"
  else
    avert "https://$DOMAINE ne répond pas encore."
    info  "Causes usuelles : le port 80 n'est pas ouvert côté hébergeur, ou le"
    info  "nom ne pointe pas vers ${adresse:-cette machine}."
    info  "Journal : $DOCKER compose logs passerelle"
  fi
fi

# ---------------------------------------------------------------- suite

titre "C'est prêt"

if [[ "$MODE" == "https" ]]; then
  printf '  %bLe back-office :%b https://%s\n\n' "$GRAS" "$FIN" "$DOMAINE"
  printf '      identifiant   admin\n'
  printf '      mot de passe  %s\n\n' "$ODOO_ADMIN_MOTDEPASSE"
  printf '  Notez ce mot de passe : il n'"'"'est réaffiché nulle part.\n'
  printf '  Le certificat est obtenu et renouvelé tout seul. Odoo n'"'"'est plus\n'
  printf '  joignable en direct : tout passe par la passerelle.\n\n'
elif [[ "$MODE" == "http" ]]; then
  printf '  %bLe back-office :%b http://%s:8069\n\n' "$GRAS" "$FIN" "${adresse:-<ip-du-serveur>}"
  printf '      identifiant   admin\n'
  printf '      mot de passe  %s\n\n' "$ODOO_ADMIN_MOTDEPASSE"
  printf '  Notez ce mot de passe : il n'"'"'est réaffiché nulle part.\n'
  printf '  %bEn clair, sans certificat.%b Pour chiffrer : rejouer avec --https\n' "$JAUNE" "$FIN"
  printf '  (ou --domaine mon.domaine.fr si vous en avez un).\n\n'
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
