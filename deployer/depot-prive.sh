#!/usr/bin/env bash
#
# Prépare le serveur à tirer depuis un dépôt privé.
#
#   bash deployer/depot-prive.sh                       ce dépôt-ci
#   bash deployer/depot-prive.sh SOMET1010/odoo_versions  un autre
#
# À jouer AVANT de passer le dépôt en privé : tant qu'il est public, on peut
# tout mettre en place et vérifier que ça marche. L'inverse — basculer puis
# découvrir que « git pull » refuse — laisse le serveur sans mise à jour.
#
# Le moyen retenu est une clé de déploiement : une paire de clés SSH propre à
# CE dépôt et à CETTE machine, en lecture seule.
#
#   - un jeton d'accès personnel donnerait accès à tous vos dépôts, et se
#     retrouverait en clair dans l'URL du dépôt, visible par « git remote -v » ;
#   - une clé de déploiement ne vaut que pour un dépôt, se révoque sans toucher
#     au reste, et sa partie privée ne quitte jamais cette machine.
#
# Le script ne fait rien d'irréversible et peut être rejoué sans dommage.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }
ok()    { printf '  %bOK%b    %s\n' "$VERT" "$FIN" "$*"; }
info()  { printf '        %s\n' "$*"; }
avert() { printf '  %bNOTE%b  %s\n' "$JAUNE" "$FIN" "$*"; }
fatal() { printf '  %bARRÊT%b %s\n' "$ROUGE" "$FIN" "$*"; exit 1; }

# ------------------------------------------------------- 1. de quel dépôt

titre "1. Le dépôt"

if [[ -n "${1:-}" ]]; then
  # Un dépôt nommé : on prépare seulement sa clé, sans toucher à l'origine
  # d'ici. GitHub veut une clé de déploiement DIFFÉRENTE par dépôt — la même
  # ne peut pas servir deux fois, il la refuse.
  chemin="${1%.git}"
  [[ "$chemin" == */* ]] || fatal "attendu « PROPRIETAIRE/DEPOT », reçu « $1 »."
  ICI=0
  url=""
else
  url=$(git remote get-url origin 2>/dev/null) || fatal "aucun dépôt Git ici."
  # Accepte les deux formes : https://github.com/PROPRIO/NOM(.git) et
  # git@…:PROPRIO/NOM(.git). On veut « PROPRIO/NOM ».
  chemin=$(sed -E 's#^https://[^/]+/##; s#^[^:]+:##; s#\.git$##' <<<"$url")
  [[ "$chemin" == */* ]] || fatal "impossible de lire le dépôt depuis « $url »."
  ICI=1
  info "origine actuelle : $url"
fi

# Une clé par dépôt, nommée d'après lui : sans quoi la seconde écraserait la
# première, et le premier dépôt cesserait de répondre sans qu'on comprenne.
SUFFIXE=$(tr -c 'A-Za-z0-9' '_' <<<"$chemin" | sed 's/_*$//')
CLE="$HOME/.ssh/atelier_$SUFFIXE"
ALIAS="github-$SUFFIXE"
info "dépôt : $chemin"
info "clé   : $CLE"

# ------------------------------------------------------ 2. la clé

titre "2. Clé de déploiement"

mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"

if [[ -f "$CLE" ]]; then
  ok "clé existante conservée : $CLE"
else
  ssh-keygen -t ed25519 -N '' -f "$CLE" -C "atelier-$(hostname)" >/dev/null 2>&1 \
    || fatal "la génération de la clé a échoué."
  chmod 600 "$CLE"
  ok "clé créée : $CLE (la partie privée ne quittera jamais cette machine)"
fi

# ------------------------------------------------ 3. l'hôte, et sa vérification

titre "3. Reconnaître github.com"

CONNUS="$HOME/.ssh/known_hosts"
if ! ssh-keygen -F github.com -f "$CONNUS" >/dev/null 2>&1; then
  ssh-keyscan -t ed25519 github.com >> "$CONNUS" 2>/dev/null
  ok "clé d'hôte de github.com enregistrée"
  # On ne l'affirme pas : on l'affiche pour que vous la compariez à la source.
  empreinte=$(ssh-keyscan -t ed25519 github.com 2>/dev/null | ssh-keygen -lf - 2>/dev/null | awk '{print $2}')
  info "empreinte reçue : ${empreinte:-inconnue}"
  info "à comparer avec la liste publiée par GitHub :"
  info "https://docs.github.com/authentication/keeping-your-account-secure/githubs-ssh-key-fingerprints"
else
  ok "github.com était déjà connu"
fi

# ---------------------------------------------------------- 4. la configuration

titre "4. Configuration SSH"

CONFIG="$HOME/.ssh/config"
touch "$CONFIG" && chmod 600 "$CONFIG"
if grep -q "^Host $ALIAS\$" "$CONFIG" 2>/dev/null; then
  ok "l'alias « $ALIAS » existait déjà"
else
  cat >> "$CONFIG" <<EOF

# Écrit par deployer/depot-prive.sh — accès en lecture seule au dépôt de l'Atelier.
Host $ALIAS
    HostName github.com
    User git
    IdentityFile $CLE
    IdentitiesOnly yes
EOF
  ok "alias « $ALIAS » ajouté à $CONFIG"
fi

# ------------------------------------------------------------- 5. à faire

titre "5. Ce qu'il reste à faire, et que je ne peux pas faire"

printf '\n  Ouvrez cette page :\n'
printf '  %bhttps://github.com/%s/settings/keys/new%b\n\n' "$GRAS" "$chemin" "$FIN"
printf '  Title : %bAtelier — %s%b\n' "$GRAS" "$(hostname)" "$FIN"
printf '  Key   : la ligne ci-dessous, en entier\n'
printf '  %bNe cochez PAS « Allow write access »%b — la lecture suffit.\n\n' "$GRAS" "$FIN"
printf '%b\n\n' "$(cat "$CLE.pub")"

read -r -p "  Appuyez sur Entrée une fois la clé ajoutée… " _

# --------------------------------------------------------- 6. la vérification

titre "6. Vérification"

nouvelle="git@$ALIAS:$chemin.git"
ancienne="$url"
[[ "$ICI" == "1" ]] && git remote set-url origin "$nouvelle"

if git ls-remote --exit-code "$nouvelle" HEAD >/dev/null 2>&1; then
  ok "le dépôt répond par la clé de déploiement"
  if [[ "$ICI" == "1" ]]; then
    info "origine : $nouvelle"
    printf '\n  %bVous pouvez passer le dépôt en privé.%b\n' "$GRAS" "$FIN"
    printf '  Settings → General → Danger Zone → Change visibility\n\n'
    printf '  Ensuite, « git pull » continuera de fonctionner ici sans rien demander.\n'
  else
    printf '\n  Pour le cloner :\n'
    printf '      git clone %s /opt/%s\n' "$nouvelle" "${chemin##*/}"
  fi
else
  # On remet l'origine d'avant : mieux vaut un serveur qui tire encore qu'un
  # serveur bloqué par une configuration à moitié faite.
  [[ "$ICI" == "1" ]] && git remote set-url origin "$ancienne"
  avert "le dépôt ne répond pas encore par cette clé."
  [[ "$ICI" == "1" ]] && info "L'origine a été remise sur $ancienne : rien n'est cassé."
  info  "Causes usuelles : clé pas encore ajoutée, ou collée incomplète."
  info  "Pour voir le détail : ssh -T git@$ALIAS"
  exit 1
fi
