#!/usr/bin/env bash
#
# Recette de l'Atelier en ligne.
#
#   ./.docker/verifier-atelier-en-ligne.sh [--keep]
#
# Elle éprouve la pile telle qu'elle tournera : HTTPS réel sur « localhost »,
# signé par l'autorité interne de Caddy et VÉRIFIÉ avec sa racine — jamais
# contourné par « --insecure », qui ne prouverait que l'existence d'un serveur.
#
# Ce qu'elle cherche à mettre en défaut, dans l'ordre où ça coûte cher :
#   - une instance en ligne dont le premier visiteur devient administrateur ;
#   - une porte qui laisse passer sans compte ;
#   - un cookie de session sans « Secure » ni « HttpOnly » ;
#   - un second chemin en clair vers l'interface (port publié par mégarde) ;
#   - la conversion PAR CHEMIN restée ouverte, qui lirait le serveur ;
#   - un dépôt qui ne survit pas à la recréation du conteneur ;
#   - les projets d'un compte visibles par un autre.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
ECHECS=0
RATES=()
controle() {
  if [[ "$1" == "0" ]]; then
    printf '  %bOK%b    %s\n' "$VERT" "$FIN" "$2"
  else
    printf '  %bÉCHEC%b %s\n' "$ROUGE" "$FIN" "$2"
    [[ -n "${3:-}" ]] && printf '        %s\n' "$3"
    ECHECS=$((ECHECS + 1))
    # Retenu pour être REDIT à la toute fin. Les journaux des conteneurs font
    # des centaines de lignes ; sans ce rappel, il faut les remonter pour
    # savoir ce qui a échoué. C'est une leçon déjà payée sur une autre recette.
    RATES+=("$2")
  fi
}

PILE=(docker compose -f docker-compose.atelier.yml)
export ATELIER_DOMAINE=localhost
export ATELIER_INSCRIPTION=code-de-recette-jetable
RACINE=/tmp/atelier-racine.crt
BISCUITS=/tmp/atelier-cookies.txt
AUTRE=/tmp/atelier-cookies-autre.txt

# Toutes les requêtes passent par le même chemin que le navigateur : TLS
# vérifié avec la racine, et le nom résolu vers la boucle locale.
appel() { curl -sS --cacert "$RACINE" --resolve "localhost:443:127.0.0.1" "$@"; }

# Attendre un VRAI 200. « curl » rend 0 sur un 502 : la passerelle répond,
# même quand l'interface derrière elle est morte. Une boucle qui se contente du
# code de sortie de curl sort donc au premier essai, en croyant le service levé.
attendre_200() {
  for _ in $(seq 1 "${2:-45}"); do
    [[ "$(appel -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null)" == "200" ]] \
      && return 0
    sleep 2
  done
  return 1
}

nettoyer() {
  if [[ "$KEEP" == "0" ]]; then
    "${PILE[@]}" down -v >/dev/null 2>&1
    rm -f "$BISCUITS" "$AUTRE" /tmp/atelier-exemple.zip
  fi
}
trap nettoyer EXIT

# ---------------------------------------------------------------- 1. config

titre "Étape 1 — La configuration est lisible par Caddy"

# « compose run » et non « docker run » : la validation doit voir EXACTEMENT
# l'environnement du service. Passer les variables à la main en validerait un
# autre — celui où ATELIER_ACME_EMAIL est absente plutôt que vide.
"${PILE[@]}" run --rm --no-deps passerelle \
  caddy validate --config /etc/caddy/Caddyfile >/tmp/atelier-caddy.log 2>&1
controle $? "Le Caddyfile est valide dans l'environnement du service." \
  "$(grep -i error /tmp/atelier-caddy.log | head -2)"

# --------------------------------------------------------------- 2. montée

titre "Étape 2 — La pile démarre"

"${PILE[@]}" up -d --build >/tmp/atelier-up.log 2>&1
controle $? "Les conteneurs démarrent." "$(tail -5 /tmp/atelier-up.log)"

# « up -d » rend 0 dès que les conteneurs sont CRÉÉS : un service qui redémarre
# en boucle passe ce contrôle sans broncher. On regarde donc l'état un peu
# après, quand un redémarrage en boucle a eu le temps de se voir.
sleep 12
for service in atelier-web passerelle; do
  etat=$("${PILE[@]}" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
    | grep "^${service} ")
  grep -q "running" <<<"$etat"
  controle $? "« ${service} » tourne, et ne redémarre pas en boucle." \
    "état : ${etat:-absent} ; $("${PILE[@]}" logs --tail=3 "$service" 2>&1 | tail -1)"
done

# L'autorité interne n'existe pas à la seconde zéro : Caddy la fabrique au
# premier démarrage.
for _ in $(seq 1 30); do
  "${PILE[@]}" cp passerelle:/data/caddy/pki/authorities/local/root.crt \
    "$RACINE" >/dev/null 2>&1 && break
  sleep 2
done
[[ -s "$RACINE" ]]
controle $? "L'autorité interne de Caddy est récupérée."

# ------------------------------------------------------------------ 3. TLS

titre "Étape 3 — Le chiffrement est réel, pas contourné"

code=""
for _ in $(seq 1 45); do
  code=$(appel -o /dev/null -w '%{http_code}' --max-time 5 \
    https://localhost/sante 2>/tmp/atelier-tls.log) && [[ "$code" == "200" ]] && break
  sleep 2
done
[[ "$code" == "200" ]]
TLS_REPOND=$?
controle $TLS_REPOND "https://localhost/sante répond 200, certificat validé." \
  "code=$code ; $(tail -2 /tmp/atelier-tls.log)"

# Ce contrôle-ci donne son sens au précédent : sans la racine, la connexion
# doit être REFUSÉE. Mais il ne vaut que si le serveur répond par ailleurs —
# passerelle éteinte, la connexion échoue aussi et le contrôle passerait au
# vert en ne prouvant rien.
if [[ "$TLS_REPOND" -ne 0 ]]; then
  printf '  %bSANS OBJET%b Indécidable tant que la passerelle ne répond pas.\n' \
    "$JAUNE" "$FIN"
  ECHECS=$((ECHECS + 1))
else
  curl -sS -o /dev/null --max-time 5 https://localhost/sante >/dev/null 2>&1
  [[ $? -ne 0 ]]
  controle $? "Sans l'autorité, la connexion est refusée (le TLS est réel)."
fi

code80=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
  http://localhost/ 2>/dev/null)
[[ "$code80" =~ ^30[812]$ ]]
controle $? "http://localhost redirige vers HTTPS (code $code80)."

appel -D - -o /dev/null --max-time 5 https://localhost/ 2>/dev/null \
  | grep -qi "strict-transport-security"
controle $? "L'en-tête HSTS est présent."

# ------------------------------------------------- 4. aucun second chemin

titre "Étape 4 — L'interface n'est joignable que par la passerelle"

# Le port 8100 ne doit être publié nulle part : la passerelle est le seul
# chemin, et il est chiffré.
#
# « compose port » et non « compose ps » : la colonne Ports affiche aussi les
# ports EXPOSÉS — ceux du Dockerfile, joignables des seuls conteneurs voisins.
# Y chercher « 8100 » ferait échouer une configuration parfaitement close.
# « port » ne rend une adresse que s'il existe une PUBLICATION vers l'hôte.
# Et on lit sa réponse pour ce qu'elle est : faute de publication, « port »
# n'écrit pas rien — il écrit « :0 », un port zéro qui ne désigne aucune
# publication. Tester la seule vacuité de la réponse déclarait donc publié un
# service qui ne l'était pas.
publie=$("${PILE[@]}" port atelier-web 8100 2>/dev/null | tr -d '[:space:]')
[[ -z "$publie" || "$publie" == ":0" || "$publie" == *":0" ]]
controle $? "Aucun port 8100 n'est publié sur l'hôte." "« port » a répondu : ${publie:-(rien)}"

curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8100/sante >/dev/null 2>&1
[[ $? -ne 0 ]]
controle $? "http://127.0.0.1:8100 ne répond pas."

# ---------------------------------------------------------- 5. la porte

titre "Étape 5 — Sans compte, on n'entre pas"

sante=$(appel --max-time 5 https://localhost/sante 2>/dev/null)
grep -q '"ouvert": *true' <<<"$sante"
controle $? "L'instance se sait en ligne." "reçu : ${sante:0:160}"
grep -q '"code_requis": *true' <<<"$sante"
controle $? "Elle réclame un code d'installation pour le premier compte."

code=$(appel -o /dev/null -w '%{http_code}' --max-time 5 \
  https://localhost/projets 2>/dev/null)
[[ "$code" == "401" ]]
controle $? "Un visiteur anonyme reçoit 401 sur /projets (code $code)."

# ------------------------------------------ 6. la course au premier compte

titre "Étape 6 — Le premier compte demande le code d'installation"

sans_code=$(appel -X POST -H 'Content-Type: application/json' --max-time 10 \
  -d '{"nom":"intrus","motdepasse":"motdepasse-tres-long"}' \
  https://localhost/inscription 2>/dev/null)
grep -qi 'code d.installation' <<<"$sans_code"
controle $? "Sans code, l'inscription est refusée." "reçu : ${sans_code:0:160}"

faux=$(appel -X POST -H 'Content-Type: application/json' --max-time 10 \
  -d '{"nom":"intrus","motdepasse":"motdepasse-tres-long","code":"au-hasard"}' \
  https://localhost/inscription 2>/dev/null)
grep -qi 'incorrect' <<<"$faux"
controle $? "Avec un mauvais code, l'inscription est refusée." \
  "reçu : ${faux:0:160}"

court=$(appel -X POST -H 'Content-Type: application/json' --max-time 10 \
  -d "{\"nom\":\"pierre\",\"motdepasse\":\"court\",\"code\":\"$ATELIER_INSCRIPTION\"}" \
  https://localhost/inscription 2>/dev/null)
grep -qi '12 caract' <<<"$court"
controle $? "Un mot de passe trop court est refusé." "reçu : ${court:0:160}"

rm -f "$BISCUITS"
premier=$(appel -c "$BISCUITS" -D /tmp/atelier-entetes.txt \
  -X POST -H 'Content-Type: application/json' --max-time 20 \
  -d "{\"nom\":\"pierre\",\"motdepasse\":\"une-phrase-dont-je-me-souviens\",\"code\":\"$ATELIER_INSCRIPTION\"}" \
  https://localhost/inscription 2>/dev/null)
grep -q '"role": *"administrateur"' <<<"$premier"
controle $? "Le premier compte est créé, et il est administrateur." \
  "reçu : ${premier:0:200}"

# Le cookie, tel que le navigateur le recevra. « HttpOnly » interdit au
# JavaScript de la page de lire le jeton ; « Secure » interdit de le renvoyer
# en clair. Sans « Secure », il suffirait d'une requête HTTP pour le capter.
biscuit=$(grep -i '^set-cookie' /tmp/atelier-entetes.txt | head -1)
grep -qi 'HttpOnly' <<<"$biscuit"
controle $? "Le cookie de session est HttpOnly." "reçu : ${biscuit:0:200}"
grep -qi 'Secure' <<<"$biscuit"
controle $? "Le cookie de session est Secure (l'Atelier se sait en HTTPS)."
grep -qi 'SameSite=Lax' <<<"$biscuit"
controle $? "Le cookie de session est SameSite=Lax."

# La porte se referme derrière le premier : l'inscription ne doit plus être
# ouverte à qui possède le code — il a servi une fois.
apres=$(appel -X POST -H 'Content-Type: application/json' --max-time 10 \
  -d "{\"nom\":\"second\",\"motdepasse\":\"motdepasse-tres-long\",\"code\":\"$ATELIER_INSCRIPTION\"}" \
  https://localhost/inscription 2>/dev/null)
grep -qi 'administrateur peut' <<<"$apres"
controle $? "L'inscription est refermée : seul un administrateur crée un compte." \
  "reçu : ${apres:0:160}"

sante=$(appel --max-time 5 https://localhost/sante 2>/dev/null)
grep -q '"code_requis": *false' <<<"$sante"
controle $? "Le code d'installation n'est plus réclamé."

# --------------------------------------------------- 7. la route par chemin

titre "Étape 7 — La conversion par chemin est fermée en ligne"

# Le chemin désignerait un dossier du SERVEUR. On ferme la route plutôt que de
# filtrer des chemins — exercice qu'on perd toujours.
parchemin=$(appel -b "$BISCUITS" -X POST -H 'Content-Type: application/json' \
  --max-time 10 -d '{"chemin":"/etc","cible":"17.0"}' \
  https://localhost/convertir 2>/dev/null)
grep -qi 'archive' <<<"$parchemin"
controle $? "/convertir par chemin est refusé, avec le motif." \
  "reçu : ${parchemin:0:200}"

# ------------------------------------------------------- 8. le dépôt de ZIP

titre "Étape 8 — Une archive déposée devient un projet"

(cd odoo-builder/exemples && zip -qr /tmp/atelier-exemple.zip suivi_dossier)
[[ -s /tmp/atelier-exemple.zip ]]
controle $? "L'archive d'exemple est fabriquée."

televerse=$(appel -b "$BISCUITS" --max-time 60 \
  -F "cible=17.0" -F "fichier=@/tmp/atelier-exemple.zip" \
  https://localhost/televerser 2>/dev/null)
grep -q '"technique"' <<<"$televerse"
controle $? "L'archive est convertie en spécification." \
  "reçu : ${televerse:0:240}"

projets=$(appel -b "$BISCUITS" --max-time 10 https://localhost/projets 2>/dev/null)
grep -q '"projets": *\[ *{' <<<"$projets"
controle $? "Le projet apparaît dans la liste du compte." \
  "reçu : ${projets:0:200}"

archive=$(appel -b "$BISCUITS" -o /tmp/atelier-livrable.zip \
  -w '%{http_code}' --max-time 60 https://localhost/module.zip 2>/dev/null)
[[ "$archive" == "200" ]] && unzip -l /tmp/atelier-livrable.zip \
  | grep -q '__manifest__.py'
controle $? "Le module se télécharge, et contient un manifeste." \
  "code=$archive"

# ------------------------------------------------------ 9. chacun chez soi

titre "Étape 9 — Les projets d'un compte ne sont pas ceux d'un autre"

second=$(appel -b "$BISCUITS" -X POST -H 'Content-Type: application/json' \
  --max-time 20 -d '{"nom":"marie","motdepasse":"une-autre-phrase-secrete"}' \
  https://localhost/inscription 2>/dev/null)
grep -q '"nom": *"marie"' <<<"$second"
controle $? "L'administrateur crée un second compte." "reçu : ${second:0:160}"

rm -f "$AUTRE"
appel -c "$AUTRE" -X POST -H 'Content-Type: application/json' --max-time 20 \
  -d '{"nom":"marie","motdepasse":"une-autre-phrase-secrete"}' \
  https://localhost/connexion >/dev/null 2>&1
liste=$(appel -b "$AUTRE" --max-time 10 https://localhost/projets 2>/dev/null)
grep -q '"projets": *\[\]' <<<"$liste"
controle $? "Le second compte ne voit aucun projet du premier." \
  "reçu : ${liste:0:200}"

# ------------------------------------------------- 10. le dépôt survit

titre "Étape 10 — Les comptes et les projets survivent au conteneur"

"${PILE[@]}" up -d --force-recreate atelier-web >/tmp/atelier-recreate.log 2>&1
attendre_200 https://localhost/sante
controle $? "L'interface répond de nouveau après recréation." \
  "$("${PILE[@]}" logs --tail=5 atelier-web 2>&1 | tail -3)"
apres=$(appel -b "$BISCUITS" --max-time 10 https://localhost/projets 2>/dev/null)
grep -q '"projets": *\[ *{' <<<"$apres"
controle $? "Après recréation du conteneur, le projet est toujours là." \
  "reçu : ${apres:0:200}"

sante=$(appel --max-time 5 https://localhost/sante 2>/dev/null)
grep -q '"comptes_existants": *true' <<<"$sante"
controle $? "Les comptes aussi (le volume porte le dépôt, pas l'image)."

# ---------------------------------------------------------------- verdict

titre "Verdict"
if [[ "$ECHECS" -eq 0 ]]; then
  printf '%bL'"'"'Atelier tient en ligne : HTTPS vérifié, porte fermée, dépôt durable.%b\n' \
    "$VERT" "$FIN"
  exit 0
fi
printf '%b%d contrôle(s) en échec.%b\n' "$ROUGE" "$ECHECS" "$FIN"
"${PILE[@]}" logs --tail=60 atelier-web 2>&1 | tail -60
"${PILE[@]}" logs --tail=30 passerelle 2>&1 | tail -30

# Le verdict EN DERNIER, après les journaux : c'est la dernière chose qu'on
# lit, et la première qu'on cherche.
printf '\n%b=== Ce qui a échoué%b\n' "$GRAS" "$FIN"
for rate in "${RATES[@]}"; do
  printf '  %b·%b %s\n' "$ROUGE" "$FIN" "$rate"
done
exit 1
