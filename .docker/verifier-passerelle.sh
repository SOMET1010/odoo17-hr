#!/usr/bin/env bash
#
# Recette de la passerelle HTTPS.
#
#   ./.docker/verifier-passerelle.sh [--keep]
#
# Elle éprouve le chemin réel — TLS, redirection, routage, session — sur
# « localhost », que Caddy signe avec son autorité interne. Le certificat est
# donc vérifié pour de bon, avec sa racine, et non contourné par « --insecure » :
# une recette qui désactive la vérification ne prouve pas le chiffrement, elle
# prouve qu'un serveur répond.
#
# Ce qu'elle cherche à mettre en défaut :
#   - un HTTPS qui « marche » parce qu'on a cessé de vérifier ;
#   - un port 80 laissé ouvert en clair ;
#   - une route qui mènerait au service d'installation ;
#   - un cookie de session perdu à la traversée du proxy ;
#   - Odoo qui, derrière un proxy, refabrique ses URL en http://.

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
export INSTALLATEUR_CLE_API=cle-de-recette-jetable
RACINE=/tmp/passerelle-racine.crt

nettoyer() {
  if [[ "$KEEP" == "0" ]]; then
    docker compose --profile passerelle --profile installateur down -v >/dev/null 2>&1
  fi
}
trap nettoyer EXIT

# ---------------------------------------------------------------- 1. config

titre "Étape 1 — La configuration est lisible par Caddy"

# « docker compose run » et non « docker run » : la validation doit voir
# EXACTEMENT l'environnement du service. Passer les variables à la main en
# validait une autre — celle où ATELIER_ACME_EMAIL est absente plutôt que
# vide — et la recette déclarait valide une configuration sur laquelle Caddy
# refusait ensuite de démarrer. Six contrôles échouaient plus loin pour une
# faute que celui-ci aurait dû nommer.
docker compose --profile passerelle run --rm --no-deps passerelle \
  caddy validate --config /etc/caddy/Caddyfile >/tmp/caddy-validate.log 2>&1
controle $? "Le Caddyfile est valide dans l'environnement du service." \
  "$(grep -i error /tmp/caddy-validate.log | head -2)"

# --------------------------------------------------------------- 2. montée

titre "Étape 2 — Démarrage de la pile avec passerelle"

docker compose --profile passerelle --profile installateur up -d --build \
  >/tmp/passerelle-up.log 2>&1
controle $? "Les conteneurs démarrent." "$(tail -5 /tmp/passerelle-up.log)"

docker compose run --rm odoo odoo -d ansut -i base --stop-after-init \
  --log-level=warn >/tmp/passerelle-base.log 2>&1
controle $? "La base « ansut » est créée." "$(tail -5 /tmp/passerelle-base.log)"
docker compose --profile passerelle --profile installateur up -d >/dev/null 2>&1

# « up -d » rend 0 dès que les conteneurs sont créés — un service qui redémarre
# en boucle passe donc ce contrôle sans broncher. C'est ce qui est arrivé :
# Caddy refusait sa configuration et repartait toutes les deux secondes, et
# rien ne l'a dit avant six échecs plus loin. On regarde donc l'état, un peu
# après, quand un redémarrage en boucle a eu le temps de se voir.
sleep 12
etat=$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep '^passerelle ')
grep -q "running" <<<"$etat"
controle $? "La passerelle tourne, et ne redémarre pas en boucle." \
  "état : ${etat:-absente} ; $(docker compose logs --tail=3 passerelle 2>&1 | grep -i error | head -1)"

# Caddy fabrique son autorité interne au premier démarrage ; elle n'existe pas
# encore à la seconde zéro.
for _ in $(seq 1 30); do
  docker compose cp passerelle:/data/caddy/pki/authorities/local/root.crt \
    "$RACINE" >/dev/null 2>&1 && break
  sleep 2
done
[[ -s "$RACINE" ]]
controle $? "L'autorité interne de Caddy est récupérée."

# ------------------------------------------------------------------ 3. TLS

titre "Étape 3 — Le certificat est vérifié, pas contourné"

reponse=""
for _ in $(seq 1 45); do
  reponse=$(curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" \
    -o /dev/null -w '%{http_code}' --max-time 5 \
    https://localhost/web/login 2>/tmp/curl-tls.log) && [[ "$reponse" == "200" ]] && break
  sleep 2
done
[[ "$reponse" == "200" ]]
TLS_REPOND=$?
controle $TLS_REPOND "https://localhost/web/login répond 200, certificat validé." \
  "code=$reponse ; $(tail -2 /tmp/curl-tls.log)"

# Le contrôle qui donne son sens au précédent : sans la racine, la connexion
# doit être refusée. Si elle passe, c'est que le certificat n'est pas vérifié.
#
# Mais il ne vaut QUE si le serveur répond par ailleurs : passerelle éteinte,
# la connexion échoue aussi, et ce contrôle passait au vert en ne prouvant
# rien. C'est exactement ce qui s'est produit — un contrôle qui réussit quand
# le serveur est mort est un contrôle qui mentira le jour où ça compte.
if [[ "$TLS_REPOND" -ne 0 ]]; then
  printf '  %bSANS OBJET%b Sans l'"'"'autorité, la connexion est refusée — '\
'indécidable tant que la passerelle ne répond pas.\n' "$JAUNE" "$FIN"
  ECHECS=$((ECHECS + 1))
else
  curl -sS -o /dev/null --max-time 5 https://localhost/web/login >/dev/null 2>&1
  [[ $? -ne 0 ]]
  controle $? "Sans l'autorité, la connexion est refusée (le TLS est réel)."
fi

entetes=$(curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" \
  -D - -o /dev/null --max-time 5 https://localhost/web/login 2>/dev/null)
grep -qi "strict-transport-security" <<<"$entetes"
controle $? "L'en-tête HSTS est présent."

# ------------------------------------------------------------ 4. clair et 80

titre "Étape 4 — Le port 80 ne sert pas le contenu"

code80=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
  http://localhost/web/login 2>/dev/null)
[[ "$code80" =~ ^30[812]$ ]]
controle $? "http://localhost redirige vers HTTPS (code $code80)."

# --------------------------------------------------------- 5. ce qui ne passe pas

titre "Étape 5 — Le service d'installation n'a aucune route"

sante=$(curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" \
  --max-time 5 https://localhost/sante 2>/dev/null)
grep -q '"etat"' <<<"$sante"
[[ $? -ne 0 ]]
controle $? "https://localhost/sante ne joint pas le service d'installation." \
  "reçu : ${sante:0:120}"

# Et il reste joignable là où il doit l'être : depuis la machine seulement.
curl -sS -o /dev/null --max-time 5 http://127.0.0.1:8090/sante >/dev/null 2>&1
controle $? "Le service d'installation répond toujours sur 127.0.0.1:8090."

# --------------------------------------------------------------- 6. session

titre "Étape 6 — La session survit à la traversée"

BISCUITS=/tmp/passerelle-cookies.txt
rm -f "$BISCUITS"
auth=$(curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" \
  -c "$BISCUITS" -H 'Content-Type: application/json' --max-time 15 \
  -d '{"jsonrpc":"2.0","params":{"db":"ansut","login":"admin","password":"admin"}}' \
  https://localhost/web/session/authenticate 2>/dev/null)
grep -q '"uid": *[0-9]' <<<"$auth"
controle $? "Authentification à travers la passerelle." "reçu : ${auth:0:160}"

lecture=$(curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" \
  -b "$BISCUITS" -H 'Content-Type: application/json' --max-time 15 \
  -d '{"jsonrpc":"2.0","method":"call","params":{"model":"res.users","method":"search_count","args":[[]],"kwargs":{}}}' \
  https://localhost/web/dataset/call_kw 2>/dev/null)
grep -q '"result"' <<<"$lecture"
controle $? "Le cookie de session est accepté à l'appel suivant." \
  "reçu : ${lecture:0:160}"

# ---------------------------------------------------------- 7. Odoo sait où il est

titre "Étape 7 — Odoo se sait derrière un proxy"

# Sans « --proxy-mode », Odoo ignore X-Forwarded-Proto et fabrique ses URL
# absolues en http:// — le navigateur les bloque alors comme contenu mixte,
# et la page se charge à moitié sans qu'aucune erreur ne soit visible.
options=$(docker compose exec -T odoo sh -c 'tr "\0" " " < /proc/1/cmdline' 2>/dev/null)
grep -q -- "--proxy-mode" <<<"$options"
controle $? "Odoo tourne avec --proxy-mode." "commande : ${options:0:120}"

# ---------------------------------------------------------------- verdict

titre "Verdict"
if [[ "$ECHECS" -eq 0 ]]; then
  printf '%bLa passerelle tient : HTTPS vérifié, rien d'"'"'autre exposé.%b\n' "$VERT" "$FIN"
  exit 0
fi
printf '%b%d contrôle(s) en échec.%b\n' "$ROUGE" "$ECHECS" "$FIN"
docker compose logs --tail=60 passerelle 2>&1 | tail -60
exit 1
