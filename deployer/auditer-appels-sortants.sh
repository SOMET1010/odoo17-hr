#!/usr/bin/env bash
#
# Que votre Odoo envoie-t-il, à qui, et quand ?
#
#   bash deployer/auditer-appels-sortants.sh
#
# STRICTEMENT EN LECTURE. Aucune écriture, aucune mise à jour de liste de
# modules, aucun redémarrage. Ce script est fait pour être joué sur une
# production sans rien y changer — c'est la condition pour qu'il serve.
#
# Il répond à trois questions, et seulement à celles-là :
#   1. vers où les appels sortants sont configurés ;
#   2. lesquels des modules qui appellent sont réellement installés ;
#   3. quand la tâche planifiée doit repartir.
#
# Ce qu'il ne fait pas : juger. Un appel sortant n'est pas une faute en soi —
# certains sont le service que vous avez acheté. Il donne les faits.

set -uo pipefail

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
info()  { printf '        %s\n' "$*"; }
avert() { printf '  %bNOTE%b  %s\n' "$JAUNE" "$FIN" "$*"; }

# Les modules qui, dans les sources d'Odoo 17/18, contiennent du code d'appel
# sortant. Un module absent de votre base ne peut rien envoyer : la liste sert
# à distinguer ce qui est possible de ce qui est effectif.
SORTANTS="account_invoice_extract hr_expense_extract hr_recruitment_extract \
iap iap_extract iot l10n_br_avatax l10n_br_edi l10n_fr_reports l10n_pe_edi \
mail_enterprise mail_mobile sale_amazon social_push_notifications social_twitter \
website_generator partner_autocomplete snailmail sms"

# Ceux qui, en plus, ont une tâche planifiée : ils partent sans que personne
# ne clique.
PLANIFIES="account_invoice_extract hr_expense_extract hr_recruitment_extract \
l10n_fr_reports sale_amazon website_generator mail"

# --------------------------------------------------------------- 1. la config

titre "1. Le fichier de configuration"

CONF=""
for c in /etc/odoo/odoo.conf /etc/odoo.conf /etc/odoo/odoo-server.conf \
         /opt/odoo/odoo.conf "${ODOO_CONF:-}"; do
  [[ -n "$c" && -r "$c" ]] && CONF="$c" && break
done
# Sinon, demander au processus lui-même quel fichier il utilise.
if [[ -z "$CONF" ]]; then
  ligne=$(tr '\0' ' ' < /proc/$(pgrep -f "odoo-bin|odoo " | head -1)/cmdline 2>/dev/null)
  CONF=$(grep -oE '(-c|--config)[= ]+[^ ]+' <<<"$ligne" | awk '{print $NF}' | tr -d '=' | head -1)
fi

if [[ -n "$CONF" && -r "$CONF" ]]; then
  info "trouvé : $CONF"
  url=$(grep -E '^\s*publisher_warranty_url' "$CONF" 2>/dev/null | cut -d= -f2- | xargs)
  if [[ -n "$url" ]]; then
    printf '  publisher_warranty_url : %b%s%b\n' "$GRAS" "$url" "$FIN"
  else
    printf '  publisher_warranty_url : %bnon défini → défaut %s%b\n' \
      "$JAUNE" "services.odoo.com/publisher-warranty/" "$FIN"
  fi
else
  avert "fichier de configuration introuvable ; Odoo tourne-t-il dans un conteneur ?"
  info  "Dans ce cas, rejouer depuis l'hôte du conteneur, ou préciser :"
  info  "    ODOO_CONF=/chemin/odoo.conf bash $0"
fi

# ----------------------------------------------------------------- 2. la base

titre "2. Ce qui est réellement installé"

# Les identifiants de connexion viennent du fichier de configuration : on ne
# demande rien qui ne soit déjà écrit sur la machine.
lire() { grep -E "^\s*$1" "$CONF" 2>/dev/null | cut -d= -f2- | xargs; }
HOTE=$(lire db_host); HOTE=${HOTE:-localhost}
UTIL=$(lire db_user); UTIL=${UTIL:-odoo}
MDP=$(lire db_password)
PORT=$(lire db_port);  PORT=${PORT:-5432}
BASE="${ODOO_BASE:-$(lire db_name)}"

if ! command -v psql >/dev/null 2>&1; then
  avert "psql absent : je ne peux pas interroger la base depuis ici."
  info  "Rejouer sur la machine de la base, ou dans son conteneur."
  exit 0
fi
if [[ -z "$BASE" ]]; then
  avert "nom de base inconnu. Le préciser : ODOO_BASE=votrebase bash $0"
  exit 0
fi

export PGPASSWORD="$MDP"
psqlq() { psql -h "$HOTE" -p "$PORT" -U "$UTIL" -d "$BASE" -tAqc "$1" 2>/dev/null; }

if ! psqlq "select 1" >/dev/null; then
  avert "connexion à la base « $BASE » impossible avec les identifiants du fichier."
  exit 0
fi

liste=$(tr ' ' '\n' <<<"$SORTANTS" | grep -v '^$' | sed "s/.*/'&'/" | paste -sd,)
installes=$(psqlq "select name from ir_module_module where state='installed' and name in ($liste) order by name")

if [[ -z "$installes" ]]; then
  printf '  %bAucun module à appel sortant n'"'"'est installé.%b\n' "$VERT" "$FIN"
else
  printf '  Modules installés qui contiennent du code d'"'"'appel sortant :\n\n'
  while read -r m; do
    [[ -z "$m" ]] && continue
    if grep -qw "$m" <<<"$PLANIFIES"; then
      printf '    %b%-32s appelle AUSSI sans action humaine%b\n' "$JAUNE" "$m" "$FIN"
    else
      printf '    %-32s sur action explicite\n' "$m"
    fi
  done <<<"$installes"
fi

# ------------------------------------------------------- 3. les destinations

titre "3. Destinations configurées dans la base"

for p in iap.endpoint iap_extract_endpoint database.expiration_date \
         database.expiration_reason web.base.url; do
  v=$(psqlq "select value from ir_config_parameter where key='$p'")
  printf '  %-28s %s\n' "$p" "${v:-<non défini>}"
done

# ---------------------------------------------------- 4. la tâche hebdomadaire

titre "4. L'appel hebdomadaire"

cron=$(psqlq "select c.active, c.nextcall from ir_cron c join ir_act_server a on a.id=c.ir_actions_server_id where a.code like '%update_notification%' limit 1")
if [[ -z "$cron" ]]; then
  cron=$(psqlq "select active, nextcall from ir_cron where id in (select res_id from ir_model_data where module='mail' and name='ir_cron_module_update_notification')")
fi
if [[ -n "$cron" ]]; then
  actif=$(cut -d'|' -f1 <<<"$cron"); suivant=$(cut -d'|' -f2 <<<"$cron")
  printf '  active   : %s\n' "$([[ "$actif" == t ]] && echo oui || echo non)"
  printf '  prochain : %s\n' "$suivant"
else
  info "tâche introuvable — nommée autrement dans cette version, ou absente."
fi

titre "Ce que ça veut dire"
printf '  Un module non installé n'"'"'envoie rien : la troisième colonne du point 2\n'
printf '  est le seul inventaire qui compte pour votre exposition réelle.\n'
printf '  Les destinations du point 3 sont des paramètres, modifiables sans\n'
printf '  toucher au code — mais changer celle de la garantie éditeur revient à\n'
printf '  empêcher la vérification d'"'"'abonnement, avec les conséquences que cela\n'
printf '  emporte sur une base Enterprise.\n'
