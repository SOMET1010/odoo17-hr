#!/usr/bin/env bash
#
# Recette de l'API de l'Atelier — la surface que l'interface appellera.
#
#   ./.docker/verifier-atelier.sh [--keep]
#
# Elle passe par la passerelle, en HTTPS, parce que c'est le seul chemin qui
# existe : le service ne publie aucun port. Éprouver la route et éprouver l'API
# sont donc le même geste.
#
# Aucune clé de fournisseur n'est nécessaire : tout ce qui est vérifié ici est
# déterministe. Le chemin qui appelle le modèle est éprouvé ailleurs, par
# l'acceptation.
#
# Ce qu'elle cherche à mettre en défaut :
#   - une API ouverte, ou fermée par une clé qu'on peut deviner ;
#   - un CORS permissif qui laisserait n'importe quelle page appeler l'Atelier ;
#   - une route qui mènerait au service d'installation ;
#   - une spécification invalide installée quand même ;
#   - un échec rendu comme une panne plutôt que comme un refus.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
ECHECS=0
controle() {
  if [[ "$1" == "0" ]]; then
    printf '  %bOK%b    %s\n' "$VERT" "$FIN" "$2"
  else
    printf '  %bÉCHEC%b %s\n' "$ROUGE" "$FIN" "$2"
    [[ -n "${3:-}" ]] && printf '        %s\n' "$3"
    ECHECS=$((ECHECS + 1))
  fi
}

export ATELIER_DOMAINE=localhost
export ODOO_OPTIONS=--proxy-mode
export INSTALLATEUR_CLE_API=cle-installateur-jetable
export ATELIER_CLE_API=cle-atelier-jetable
export ORIGINES_AUTORISEES="https://atelier.exemple.fr,https://apercu.lovable.app"

PROFILS=(--profile installateur --profile atelier --profile passerelle)
RACINE=/tmp/atelier-racine.crt
ORIGINE_OK="https://atelier.exemple.fr"
ORIGINE_KO="https://mechant.exemple.fr"

nettoyer() {
  [[ "$KEEP" == "0" ]] && docker compose "${PROFILS[@]}" down -v >/dev/null 2>&1
}
trap nettoyer EXIT

# Appel à travers la passerelle, certificat vérifié avec la racine de Caddy.
appel() { curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" "$@"; }

# --------------------------------------------------------------- 1. montée

titre "Étape 1 — Démarrage"

docker compose "${PROFILS[@]}" up -d --build >/tmp/atelier-up.log 2>&1
controle $? "Les conteneurs démarrent." "$(tail -5 /tmp/atelier-up.log)"

docker compose run --rm odoo odoo -d ansut -i base --stop-after-init \
  --log-level=warn >/tmp/atelier-base.log 2>&1
controle $? "La base « ansut » est créée." "$(tail -5 /tmp/atelier-base.log)"
docker compose "${PROFILS[@]}" up -d >/dev/null 2>&1

sleep 12
etat=$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep '^atelier ')
grep -q "running" <<<"$etat"
controle $? "L'API de l'Atelier tourne." \
  "état : ${etat:-absente} ; $(docker compose "${PROFILS[@]}" logs --tail=5 atelier 2>&1 | tail -2)"

for _ in $(seq 1 30); do
  docker compose cp passerelle:/data/caddy/pki/authorities/local/root.crt \
    "$RACINE" >/dev/null 2>&1 && break
  sleep 2
done
[[ -s "$RACINE" ]]
controle $? "L'autorité interne de Caddy est récupérée."

# ------------------------------------------------------- 2. la route existe

titre "Étape 2 — L'API répond à travers la passerelle"

sante=""
for _ in $(seq 1 30); do
  sante=$(appel --max-time 5 https://localhost/atelier/sante 2>/dev/null)
  grep -q '"etat"' <<<"$sante" && break
  sleep 2
done
grep -q '"etat": *"ok"' <<<"$sante"
controle $? "GET /atelier/sante répond." "reçu : ${sante:0:160}"

# Le service ne publie aucun port : il ne doit exister aucun second chemin.
#
# Ce qu'on cherche est la flèche « -> », qui signale une PUBLICATION. Chercher
# « 8091 » était faux : « docker compose ps » affiche aussi « 8091/tcp » pour
# un port simplement déclaré par EXPOSE, qui n'ouvre rien du tout. Le contrôle
# accusait le Dockerfile d'une faute qu'il ne commettait pas.
ports=$(docker compose ps --format '{{.Service}} {{.Ports}}' 2>/dev/null | grep '^atelier ')
grep -q -- '->' <<<"$ports"
[[ $? -ne 0 ]]
controle $? "L'API ne publie aucun port : la passerelle est le seul chemin." \
  "ports : ${ports:-aucun}"

# ------------------------------------------------------------ 3. la clé

titre "Étape 3 — Rien ne passe sans la clé"

code=$(appel -o /dev/null -w '%{http_code}' --max-time 10 -X POST \
  -H 'Content-Type: application/json' -d '{"besoin":"x"}' \
  https://localhost/atelier/specifications 2>/dev/null)
[[ "$code" == "401" ]]
controle $? "Sans clé, POST /specifications rend 401 (reçu $code)."

code=$(appel -o /dev/null -w '%{http_code}' --max-time 10 -X POST \
  -H 'Content-Type: application/json' -H 'X-Cle-Api: mauvaise-cle' \
  -d '{"besoin":"x"}' https://localhost/atelier/specifications 2>/dev/null)
[[ "$code" == "401" ]]
controle $? "Avec une mauvaise clé, 401 (reçu $code)."

# /sante reste ouvert : une sonde ne doit pas connaître le secret.
code=$(appel -o /dev/null -w '%{http_code}' --max-time 5 \
  https://localhost/atelier/sante 2>/dev/null)
[[ "$code" == "200" ]]
controle $? "L'état de santé reste public (reçu $code)."

# --------------------------------------------------------------- 4. CORS

titre "Étape 4 — Seules les origines déclarées peuvent appeler"

entetes=$(appel -D - -o /dev/null --max-time 5 -H "Origin: $ORIGINE_OK" \
  https://localhost/atelier/sante 2>/dev/null)
grep -qi "access-control-allow-origin: $ORIGINE_OK" <<<"$entetes"
controle $? "Une origine déclarée est autorisée."

grep -qi "^vary:.*origin" <<<"$entetes"
controle $? "L'en-tête « Vary: Origin » accompagne la réponse."

entetes=$(appel -D - -o /dev/null --max-time 5 -H "Origin: $ORIGINE_KO" \
  https://localhost/atelier/sante 2>/dev/null)
grep -qi "access-control-allow-origin" <<<"$entetes"
[[ $? -ne 0 ]]
controle $? "Une origine inconnue n'obtient aucune autorisation."

code=$(appel -o /dev/null -w '%{http_code}' --max-time 5 -X OPTIONS \
  -H "Origin: $ORIGINE_OK" -H 'Access-Control-Request-Method: POST' \
  https://localhost/atelier/specifications 2>/dev/null)
[[ "$code" == "204" ]]
controle $? "Le pré-vol d'une origine déclarée passe (reçu $code)."

code=$(appel -o /dev/null -w '%{http_code}' --max-time 5 -X OPTIONS \
  -H "Origin: $ORIGINE_KO" -H 'Access-Control-Request-Method: POST' \
  https://localhost/atelier/specifications 2>/dev/null)
[[ "$code" == "403" ]]
controle $? "Le pré-vol d'une origine inconnue est refusé (reçu $code)."

# ------------------------------------------------ 5. ce qui n'a pas de route

titre "Étape 5 — Le service d'installation reste sans route"

for chemin in /atelier/../sante /sante /modules; do
  reponse=$(appel --max-time 5 "https://localhost${chemin}" 2>/dev/null)
  grep -q '"etat": *"ok".*addons\|/mnt/addons-installes' <<<"$reponse"
  [[ $? -ne 0 ]]
  controle $? "« $chemin » ne joint pas le service d'installation." \
    "reçu : ${reponse:0:100}"
done

# ------------------------------------------------------- 6. fabrication réelle

titre "Étape 6 — Une spécification valide devient un module installé"

# Le nom du module compte : le service d'installation refuse d'écraser un
# module livré par le dépôt, et « diligence_simple » en est un. La recette
# butait donc sur un garde-fou correct, pas sur un défaut.
python3 -c "
import json
spec = json.load(open('odoo-builder/specs/diligence_simple.json'))
spec['technical_name'] = 'atelier_recette'
spec['name'] = 'Recette de l\\'API Atelier'
open('/tmp/atelier-charge.json','w').write(json.dumps({'spec': spec}))
"
reponse=$(appel --max-time 20 -X POST -H 'Content-Type: application/json' \
  -H "X-Cle-Api: $ATELIER_CLE_API" --data @/tmp/atelier-charge.json \
  https://localhost/atelier/modules 2>/dev/null)
identifiant=$(python3 -c "
import json,sys
try: print(json.loads(sys.argv[1]).get('id',''))
except Exception: print('')
" "$reponse")
[[ -n "$identifiant" ]]
controle $? "POST /atelier/modules accepte et rend un identifiant." \
  "reçu : ${reponse:0:200}"

etat_final=""
if [[ -n "$identifiant" ]]; then
  for _ in $(seq 1 90); do
    suivi=$(appel --max-time 10 -H "X-Cle-Api: $ATELIER_CLE_API" \
      "https://localhost/atelier/modules/$identifiant" 2>/dev/null)
    etat_final=$(python3 -c "
import json,sys
try: print(json.loads(sys.argv[1]).get('etat',''))
except Exception: print('')
" "$suivi")
    [[ "$etat_final" == "success" || "$etat_final" == "failed" ]] && break
    sleep 2
  done
fi
[[ "$etat_final" == "success" ]]
controle $? "Le module est réellement installé (état : ${etat_final:-inconnu})." \
  "${suivi:0:300}"

# ------------------------------------------------------- 7. un refus reste un refus

titre "Étape 7 — Une spécification invalide est refusée, pas installée"

code=$(appel -o /tmp/atelier-refus.json -w '%{http_code}' --max-time 10 -X POST \
  -H 'Content-Type: application/json' -H "X-Cle-Api: $ATELIER_CLE_API" \
  -d '{"spec":{"technical_name":"Mauvais Nom","name":"x","depends":["base"],"models":[]}}' \
  https://localhost/atelier/modules 2>/dev/null)
[[ "$code" == "422" ]]
controle $? "Un nom technique invalide est refusé avant toute fabrication (reçu $code)."

grep -q "erreur" /tmp/atelier-refus.json 2>/dev/null
controle $? "Le refus nomme la cause." "$(head -c 200 /tmp/atelier-refus.json)"

# ---------------------------------------------------------------- verdict

titre "Verdict"
if [[ "$ECHECS" -eq 0 ]]; then
  printf '%bL'"'"'interface a une surface à appeler, fermée et éprouvée.%b\n' "$VERT" "$FIN"
  exit 0
fi
printf '%b%d contrôle(s) en échec.%b\n' "$ROUGE" "$ECHECS" "$FIN"
docker compose "${PROFILS[@]}" logs --tail=60 atelier 2>&1 | tail -60
exit 1
