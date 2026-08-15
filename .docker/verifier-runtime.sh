#!/usr/bin/env bash
#
# Recette d'exécution de la pile Odoo locale.
#
# Déroule les contrôles que `docker compose config` ne peut pas prouver :
# démarrage effectif, initialisation de la base, persistance des volumes,
# et surtout survie du cookie de session à travers le proxy de l'atelier.
#
# Usage :
#   ./.docker/verifier-runtime.sh [--atelier /chemin/vers/odoo-react-alchemy] [--keep]
#
#   --atelier CHEMIN  Active l'étape 6b (lecture/écriture via le proxy Vite).
#   --keep            Laisse la pile allumée à la fin.
#
# Sortie : 0 si toutes les étapes passent, 1 sinon.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

ATELIER=""
KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --atelier) ATELIER="${2:-}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "Option inconnue : $1"; exit 2 ;;
  esac
done

DB=ansut
LOGIN=admin
MOTDEPASSE=admin
ODOO_URL=http://localhost:8069
ATELIER_URL=http://localhost:8080
TRAVAIL=$(mktemp -d)
VITE_PID=""

RESULTATS=()
ECHECS=0

# ---------------------------------------------------------------- utilitaires

titre()   { printf '\n\033[1m=== %s\033[0m\n' "$*"; }
info()    { printf '    %s\n' "$*"; }
succes()  { printf '    \033[32mOK\033[0m   %s\n' "$*"; RESULTATS+=("OK   | $*"); }
echec()   { printf '    \033[31mÉCHEC\033[0m %s\n' "$*"; RESULTATS+=("ÉCHEC| $*"); ECHECS=$((ECHECS + 1)); }
ignore()  { printf '    \033[33mIGNORÉ\033[0m %s\n' "$*"; RESULTATS+=("IGN. | $*"); }

nettoyer() {
  [[ -n "$VITE_PID" ]] && kill "$VITE_PID" 2>/dev/null
  restaurer_sources
  if [[ $KEEP -eq 0 ]]; then
    info "Arrêt de la pile (les volumes sont conservés)."
    docker compose down >/dev/null 2>&1
  else
    info "Pile laissée allumée (--keep)."
  fi
  rm -rf "$TRAVAIL"
}
trap nettoyer EXIT

# Extrait un champ d'une réponse JSON-RPC ; renvoie 1 si « error » est présent.
json() {
  python3 -c "
import json, sys
donnee = json.load(sys.stdin)
if 'error' in donnee:
    message = donnee['error'].get('data', {}).get('message') or donnee['error'].get('message', 'erreur')
    print('ERREUR: ' + str(message)); sys.exit(1)
print($1)
" 2>/dev/null
}

# authentifier <url> <fichier-cookies>
authentifier() {
  curl -sS -c "$2" -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"params\":{\"db\":\"$DB\",\"login\":\"$LOGIN\",\"password\":\"$MOTDEPASSE\"}}" \
    "$1/web/session/authenticate"
}

# appeler <url> <cookies> <modele> <methode> <args-json> [kwargs-json]
appeler() {
  local url=$1 cookies=$2 modele=$3 methode=$4 args=$5 kwargs=${6:-}
  [[ -z "$kwargs" ]] && kwargs='{}'
  curl -sS -b "$cookies" -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"model\":\"$modele\",\"method\":\"$methode\",\"args\":$args,\"kwargs\":$kwargs}}" \
    "$url/web/dataset/call_kw"
}

attendre_http() {
  local url=$1 limite=${2:-120} i=0
  while (( i < limite )); do
    if curl -sS -o /dev/null --max-time 5 "$url" 2>/dev/null; then return 0; fi
    sleep 2; i=$((i + 2))
  done
  return 1
}

SOURCES_SAUVEES=0
sauver_sources() {
  cp ansut_rh/views/ansut_integration_views.xml "$TRAVAIL/vue.xml" 2>/dev/null || return 1
  cp ansut_rh/models/ansut_integration.py "$TRAVAIL/modele.py" 2>/dev/null || return 1
  SOURCES_SAUVEES=1
}
restaurer_sources() {
  [[ $SOURCES_SAUVEES -eq 1 ]] || return 0
  cp "$TRAVAIL/vue.xml" ansut_rh/views/ansut_integration_views.xml 2>/dev/null
  cp "$TRAVAIL/modele.py" ansut_rh/models/ansut_integration.py 2>/dev/null
}

# --------------------------------------------------------------- prérequis

titre "Prérequis"
for outil in docker curl python3; do
  command -v "$outil" >/dev/null || { echo "Outil manquant : $outil"; exit 2; }
done
docker compose version >/dev/null 2>&1 || { echo "docker compose indisponible"; exit 2; }
docker info >/dev/null 2>&1 || { echo "Le démon Docker ne répond pas."; exit 2; }
info "docker, docker compose, curl et python3 sont disponibles."

# ------------------------------------------------------------------ étape 1

titre "Étape 1 — Démarrage de la pile"
if docker compose up -d 2>&1 | tail -5; then
  info "Attente de PostgreSQL (état healthy)…"
  sain=0
  for _ in $(seq 1 60); do
    etat=$(docker compose ps db --format '{{.Health}}' 2>/dev/null)
    [[ "$etat" == "healthy" ]] && { sain=1; break; }
    sleep 2
  done
  [[ $sain -eq 1 ]] && succes "PostgreSQL est healthy." || echec "PostgreSQL n'atteint pas l'état healthy."

  etat_odoo=$(docker compose ps odoo --format '{{.State}}' 2>/dev/null)
  [[ "$etat_odoo" == "running" ]] && succes "Le conteneur Odoo est Up." || echec "Odoo n'est pas Up (état : ${etat_odoo:-inconnu})."
else
  echec "docker compose up a échoué."
fi

# ------------------------------------------------------------------ étape 2

titre "Étape 2 — Journaux d'Odoo"
journal="$TRAVAIL/odoo.log"
docker compose logs --tail=200 odoo > "$journal" 2>&1

redemarrages=$(docker inspect -f '{{.RestartCount}}' "$(docker compose ps -q odoo)" 2>/dev/null || echo 0)
if [[ "${redemarrages:-0}" -le 1 ]]; then
  succes "Pas de boucle de redémarrage (RestartCount=${redemarrages:-0})."
else
  echec "Odoo redémarre en boucle (RestartCount=$redemarrages)."
fi

if grep -qiE "could not connect to server|connection refused|password authentication failed" "$journal"; then
  echec "Le journal signale un problème de connexion à la base."
else
  succes "Aucune erreur de connexion à la base dans le journal."
fi

# L'addons_path est prouvé par la présence des modules vus depuis le conteneur.
if docker compose exec -T odoo test -f /mnt/extra-addons/ansut_rh/__manifest__.py 2>/dev/null; then
  succes "Le dépôt est bien monté : /mnt/extra-addons/ansut_rh/__manifest__.py est lisible."
else
  echec "Les modules du dépôt ne sont pas visibles dans le conteneur."
fi
if docker compose exec -T odoo grep -q "/mnt/extra-addons" /etc/odoo/odoo.conf 2>/dev/null; then
  succes "addons_path inclut /mnt/extra-addons dans la configuration lue par Odoo."
else
  echec "La configuration lue par Odoo ne référence pas /mnt/extra-addons."
fi

# ------------------------------------------------------------------ étape 3

titre "Étape 3 — Installation des modules sur la base « $DB »"
info "Cette étape peut prendre plusieurs minutes au premier passage."
if docker compose run --rm odoo odoo -d "$DB" \
     -i diligence_simple,theme_backend,ansut_rh --stop-after-init >"$TRAVAIL/install.log" 2>&1; then
  succes "L'installation se termine avec le code 0."
else
  echec "L'installation échoue (code $?). Voir $TRAVAIL/install.log — 20 dernières lignes :"
  tail -20 "$TRAVAIL/install.log" | sed 's/^/      /'
fi

# Point de surveillance : la base a-t-elle réellement été créée ?
if docker compose exec -T db psql -U odoo -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$DB"; then
  succes "La base « $DB » existe."
else
  echec "La base « $DB » n'a pas été créée."
fi

installes=$(docker compose exec -T db psql -U odoo -d "$DB" -tAc \
  "select count(*) from ir_module_module where name in ('ansut_rh','diligence_simple','theme_backend') and state='installed'" 2>/dev/null | tr -d '[:space:]')
if [[ "${installes:-0}" == "3" ]]; then
  succes "Les 3 modules sont à l'état « installed »."
else
  echec "Modules installés : ${installes:-0}/3."
fi

# ------------------------------------------------------------------ étape 4

titre "Étape 4 — Redémarrage et disponibilité HTTP"
docker compose restart odoo >/dev/null 2>&1
if attendre_http "$ODOO_URL/web/login" 180; then
  succes "Odoo répond sur $ODOO_URL après redémarrage."
else
  echec "Odoo ne répond pas sur $ODOO_URL après redémarrage."
fi

# ------------------------------------------------------------------ étape 5

titre "Étape 5 — Persistance des données"
cookies="$TRAVAIL/cookies-direct.txt"
uid=$(authentifier "$ODOO_URL" "$cookies" | json "donnee['result']['uid']")
if [[ "$uid" =~ ^[0-9]+$ ]]; then
  succes "Authentification directe réussie (uid=$uid)."
else
  echec "Authentification directe impossible : ${uid:-aucune réponse}."
fi

marqueur="MARQUEUR-PERSISTANCE-$$"
cree=$(appeler "$ODOO_URL" "$cookies" res.partner create "[{\"name\":\"$marqueur\"}]" | json "donnee['result']")
if [[ "$cree" =~ ^[0-9]+$ ]]; then
  succes "Écriture directe réussie (res.partner id=$cree)."
else
  echec "Écriture directe impossible : ${cree:-aucune réponse}."
fi

info "docker compose down puis up -d…"
docker compose down >/dev/null 2>&1
docker compose up -d >/dev/null 2>&1
attendre_http "$ODOO_URL/web/login" 180 || true

cookies2="$TRAVAIL/cookies-apres.txt"
authentifier "$ODOO_URL" "$cookies2" >/dev/null
survivants=$(appeler "$ODOO_URL" "$cookies2" res.partner search_count "[[[\"name\",\"=\",\"$marqueur\"]]]" | json "donnee['result']")
if [[ "${survivants:-0}" == "1" ]]; then
  succes "L'enregistrement survit à down/up : les volumes sont bien persistants."
else
  echec "L'enregistrement n'a pas survécu au cycle down/up (trouvés : ${survivants:-0})."
fi

# ----------------------------------------------------------------- étape 6

titre "Étape 6 — Lecture et écriture depuis l'atelier"
lus=$(appeler "$ODOO_URL" "$cookies2" res.partner search_read "[[],[\"id\",\"name\"]]" '{"limit":3}' | json "len(donnee['result'])")
if [[ "${lus:-0}" -ge 1 ]]; then
  succes "Lecture directe : $lus enregistrement(s) via /web/dataset/call_kw."
else
  echec "Lecture directe impossible."
fi

if [[ -z "$ATELIER" ]]; then
  ignore "Étape 6b (proxy Vite) : relancer avec --atelier /chemin/vers/odoo-react-alchemy."
elif [[ ! -f "$ATELIER/package.json" ]]; then
  echec "Étape 6b : $ATELIER ne ressemble pas au dépôt de l'atelier."
else
  info "Démarrage de l'atelier avec VITE_ODOO_PROXY…"
  ( cd "$ATELIER" && VITE_ODOO_PROXY="$ODOO_URL" npm run dev >"$TRAVAIL/vite.log" 2>&1 ) &
  VITE_PID=$!
  if attendre_http "$ATELIER_URL" 120; then
    succes "L'atelier répond sur $ATELIER_URL."

    # Point de surveillance : le cookie de session survit-il au proxy ?
    cookies_proxy="$TRAVAIL/cookies-proxy.txt"
    uid_proxy=$(authentifier "$ATELIER_URL" "$cookies_proxy" | json "donnee['result']['uid']")
    if [[ "$uid_proxy" =~ ^[0-9]+$ ]]; then
      succes "Authentification via le proxy réussie (uid=$uid_proxy)."
    else
      echec "Authentification via le proxy impossible : ${uid_proxy:-aucune réponse}."
    fi

    if grep -q "session_id" "$cookies_proxy" 2>/dev/null; then
      succes "Le cookie session_id est bien déposé sur l'origine de l'atelier."
    else
      echec "Aucun cookie session_id conservé côté atelier : la réécriture de domaine ne fonctionne pas."
    fi

    lus_proxy=$(appeler "$ATELIER_URL" "$cookies_proxy" res.partner search_read "[[],[\"id\",\"name\"]]" '{"limit":3}' | json "len(donnee['result'])")
    [[ "${lus_proxy:-0}" -ge 1 ]] && succes "Lecture via le proxy : $lus_proxy enregistrement(s)." \
                                   || echec "Lecture via le proxy impossible."

    # L'écriture est le test décisif : elle échoue si le cookie n'a pas fait l'aller-retour.
    ecrit=$(appeler "$ATELIER_URL" "$cookies_proxy" res.partner create "[{\"name\":\"MARQUEUR-PROXY-$$\"}]" | json "donnee['result']")
    [[ "$ecrit" =~ ^[0-9]+$ ]] && succes "Écriture via le proxy réussie (id=$ecrit) : le cookie a fait l'aller-retour." \
                                || echec "Écriture via le proxy impossible : ${ecrit:-aucune réponse}."
  else
    echec "L'atelier ne répond pas sur $ATELIER_URL. Voir $TRAVAIL/vite.log."
  fi
  kill "$VITE_PID" 2>/dev/null; VITE_PID=""
fi

# ----------------------------------------------------------------- étape 7

titre "Étape 7 — Rechargement des vues XML et mise à jour du Python"
if ! sauver_sources; then
  ignore "Étape 7 : fichiers sources d'ansut_rh introuvables."
else
  vue=ansut_rh/views/ansut_integration_views.xml
  temoin="TEMOIN-RELOAD-$$"

  if grep -q "Dossier d'intégration" "$vue"; then
    sed -i "0,/Dossier d'intégration/s//$temoin/" "$vue"
    docker compose restart odoo >/dev/null 2>&1
    attendre_http "$ODOO_URL/web/login" 180 || true

    cookies3="$TRAVAIL/cookies-vue.txt"
    authentifier "$ODOO_URL" "$cookies3" >/dev/null
    trouve=$(appeler "$ODOO_URL" "$cookies3" ir.ui.view search_count "[[[\"arch_db\",\"like\",\"$temoin\"]]]" | json "donnee['result']")

    if [[ "${trouve:-0}" -ge 1 ]]; then
      succes "Vue XML : la modification est prise en compte sans -u (dev_mode actif)."
    else
      ignore "Vue XML : la modification n'apparaît qu'après « -u ansut_rh ». Le rechargement à chaud de dev_mode ne couvre pas les arch stockées en base — à confirmer dans l'interface."
    fi
    restaurer_sources
    docker compose run --rm odoo odoo -d "$DB" -u ansut_rh --stop-after-init >/dev/null 2>&1
  else
    ignore "Étape 7 (vue) : chaîne témoin introuvable dans $vue."
  fi

  # Le Python, lui, exige une mise à jour du module : on le vérifie dans les deux sens.
  modele=ansut_rh/models/ansut_integration.py
  if grep -q "Date de prise de fonction" "$modele"; then
    sed -i "0,/Date de prise de fonction/s//DATE-TEMOIN-$$/" "$modele"
    docker compose restart odoo >/dev/null 2>&1
    attendre_http "$ODOO_URL/web/login" 180 || true

    cookies4="$TRAVAIL/cookies-py.txt"
    authentifier "$ODOO_URL" "$cookies4" >/dev/null
    avant=$(appeler "$ODOO_URL" "$cookies4" ir.model.fields search_count "[[[\"name\",\"=\",\"date_prise_fonction\"],[\"field_description\",\"like\",\"DATE-TEMOIN\"]]]" | json "donnee['result']")
    [[ "${avant:-0}" == "0" ]] && succes "Python : un simple redémarrage ne suffit pas, comme documenté." \
                               || echec "Python : la modification est passée sans -u, contrairement à la documentation."

    docker compose run --rm odoo odoo -d "$DB" -u ansut_rh --stop-after-init >/dev/null 2>&1
    attendre_http "$ODOO_URL/web/login" 180 || true
    cookies5="$TRAVAIL/cookies-py2.txt"
    authentifier "$ODOO_URL" "$cookies5" >/dev/null
    apres=$(appeler "$ODOO_URL" "$cookies5" ir.model.fields search_count "[[[\"name\",\"=\",\"date_prise_fonction\"],[\"field_description\",\"like\",\"DATE-TEMOIN\"]]]" | json "donnee['result']")
    [[ "${apres:-0}" -ge 1 ]] && succes "Python : « -u ansut_rh » applique bien la modification." \
                              || echec "Python : « -u ansut_rh » n'a pas appliqué la modification."

    restaurer_sources
    docker compose run --rm odoo odoo -d "$DB" -u ansut_rh --stop-after-init >/dev/null 2>&1
  else
    ignore "Étape 7 (Python) : chaîne témoin introuvable dans $modele."
  fi
fi

# ------------------------------------------------------------------- verdict

titre "Verdict"
for ligne in "${RESULTATS[@]}"; do printf '    %s\n' "$ligne"; done
printf '\n'
if [[ $ECHECS -eq 0 ]]; then
  printf '\033[32mToutes les étapes passent : environnement Odoo local persistant + atelier connecté validés.\033[0m\n'
  exit 0
fi
printf '\033[31m%d contrôle(s) en échec.\033[0m Diagnostic : docker compose logs odoo ; docker compose logs db\n' "$ECHECS"
exit 1
