#!/usr/bin/env bash
#
# Un parc de modules, un vrai Odoo, un verdict par module.
#
#   PARC=/chemin/vers/les/addons CIBLE=19.0 ODOO_TAG=19 ./.docker/verifier-parc.sh
#
# « Se convertit » n'est pas « marche ». La validation statique dit que le
# module est cohérent ; seul Odoo dit qu'il s'installe. Entre les deux, il y a
# tout ce qu'un fichier ne peut pas savoir : une relation vers un modèle
# absent, une vue qu'un module dépendant redéfinit, une colonne dont le type
# ne passe pas.
#
# Ce banc monte l'Odoo de la version visée UNE FOIS, puis y fait passer chaque
# module converti : installation, mise à jour, création d'un enregistrement.
# Une base par module serait plus propre et beaucoup plus lent ; on garde donc
# une base commune, ce qui a un effet de bord qu'il faut connaître — un module
# installé reste installé pour les suivants. C'est le cas réel : sur une
# instance de production, les modules cohabitent.
#
# Les archives ZIP sont déballées dans un dossier temporaire, jamais à côté de
# leur source : un dépôt de livraison n'a pas à se peupler de dossiers que
# personne n'a demandés.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PARC="${PARC:?PARC=/chemin/vers/les/addons est obligatoire}"
CIBLE="${CIBLE:-19.0}"
export ODOO_TAG="${ODOO_TAG:-${CIBLE%%.*}}"
export INSTALLATEUR_CLE_API="${INSTALLATEUR_CLE_API:-cle-de-recette-jetable}"
export ODOO_CONF="${ODOO_CONF:-./.docker/odoo-multiversions.conf}"

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
titre() { printf '\n%b=== %s%b\n' "$GRAS" "$*" "$FIN"; }

TEMPO=$(mktemp -d)
nettoyer() {
  docker compose --profile installateur down -v >/dev/null 2>&1
  rm -rf "$TEMPO"
}
trap nettoyer EXIT

titre "Parc « $PARC » sur Odoo $CIBLE (image odoo:$ODOO_TAG)"

# --- Les modules : dossiers déballés et archives.
mapfile -t MODULES < <(
  python3 - "$PARC" "$TEMPO" <<'PY'
import os, sys, zipfile
racine, tempo = sys.argv[1], sys.argv[2]
trouves = []
for dossier, sous, noms in os.walk(racine):
    sous[:] = [s for s in sous if s not in (".git", "__pycache__", "node_modules")]
    if "__manifest__.py" in noms or "__openerp__.py" in noms:
        trouves.append(dossier); sous[:] = []; continue
    for nom in sorted(noms):
        if not nom.endswith(".zip"):
            continue
        archive = os.path.join(dossier, nom)
        cible = os.path.join(tempo, os.path.relpath(archive, racine))
        try:
            os.makedirs(cible, exist_ok=True)
            zipfile.ZipFile(archive).extractall(cible)
        except Exception:
            continue
        for sd, _, sn in os.walk(cible):
            if "__manifest__.py" in sn or "__openerp__.py" in sn:
                trouves.append(sd); break
print("\n".join(sorted(trouves)))
PY
)
printf '  %d module(s) à éprouver\n' "${#MODULES[@]}"
[[ ${#MODULES[@]} -eq 0 ]] && { printf '%bAucun module.%b\n' "$ROUGE" "$FIN"; exit 2; }

# --- L'Odoo de la version visée, une fois pour tout le parc.
titre "Montage de l'instance"
docker compose --profile installateur up -d --build >/tmp/parc-up.log 2>&1 \
  || { tail -40 /tmp/parc-up.log; printf '%bdémarrage impossible%b\n' "$ROUGE" "$FIN"; exit 1; }

docker compose run --rm odoo odoo -d ansut -i base --stop-after-init \
  --log-level=warn >/tmp/parc-base.log 2>&1 \
  || { tail -60 /tmp/parc-base.log; printf '%binitialisation impossible%b\n' "$ROUGE" "$FIN"; exit 1; }
docker compose --profile installateur up -d >/dev/null 2>&1

for _ in $(seq 1 120); do
  curl -sS -o /dev/null --max-time 3 http://127.0.0.1:8069/web/login 2>/dev/null && break
  sleep 2
done
printf '  version servie : '
docker compose exec -T odoo odoo --version 2>/dev/null | head -1 || echo inconnue

# --- Un module à la fois.
declare -a REUSSIS ECHOUES
for chemin in "${MODULES[@]}"; do
  nom=$(basename "$chemin")
  titre "$nom"
  if python3 odoo-builder/cli/verifier_cible.py "$chemin" --cible "$CIBLE" \
       >"/tmp/parc-$nom.log" 2>&1; then
    REUSSIS+=("$nom")
    grep -E "OK    (Installation|Mise à jour|Création|Relecture)" "/tmp/parc-$nom.log" \
      | sed 's/^/  /'
  else
    ECHOUES+=("$nom")
    # Le motif, pas le roman : la ligne d'échec et ce qui l'explique.
    grep -E "ÉCHEC|Erreur :|Échec :" "/tmp/parc-$nom.log" | head -6 | sed 's/^/  /'
  fi
done

titre "Verdict du parc — Odoo $CIBLE"
printf '  %b%d installé(s)%b : %s\n' "$VERT" "${#REUSSIS[@]}" "$FIN" "${REUSSIS[*]:-—}"
if [[ ${#ECHOUES[@]} -gt 0 ]]; then
  printf '  %b%d en échec%b   : %s\n' "$ROUGE" "${#ECHOUES[@]}" "$FIN" "${ECHOUES[*]}"
  printf '  Journal détaillé : /tmp/parc-<module>.log\n'
fi

titre "Ce que ce verdict dit, et ce qu'il ne dit pas"
printf '  Il dit qu%bOdoo accepte le module converti : schéma créé, vues\n' "'"
printf '  chargées, enregistrement écrit puis relu.\n'
printf '  Il ne dit RIEN du comportement non porté — les méthodes, les\n'
printf '  contraintes, les assistants. Un module peut s%binstaller parfaitement\n' "'"
printf '  et ne plus rien faire de ce pour quoi il avait été écrit.\n'

[[ ${#ECHOUES[@]} -eq 0 ]]
