#!/usr/bin/env bash
#
# Odoo voit-il les modules montés ?
#
#   bash deployer/verifier-entreprise.sh
#
# Monter un dossier d'addons ne suffit pas : Odoo tient sa propre liste de
# modules disponibles, et ne la rafraîchit pas de lui-même. Tant qu'elle n'est
# pas mise à jour, les modules sont sur le disque et invisibles — et un module
# qui hérite de « sign.request » échoue à l'installation sans que rien
# n'explique pourquoi.
#
# Ce script demande la mise à jour, puis compte ce qui est réellement connu.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

VERT='\033[32m'; ROUGE='\033[31m'; JAUNE='\033[33m'; GRAS='\033[1m'; FIN='\033[0m'
BASE="${ODOO_BASE:-ansut}"

printf '\n%bMise à jour de la liste des modules — une minute environ…%b\n' "$GRAS" "$FIN"

# Même procédé que l'installeur pour le mot de passe : « odoo shell » lit sur
# l'entrée standard. Rien à installer, rien à ouvrir.
sortie=$(printf '%s\n' \
  "env['ir.module.module'].update_list()" \
  "env.cr.commit()" \
  "total = env['ir.module.module'].search_count([])" \
  "temoins = ['account_accountant', 'sign', 'web_enterprise', 'documents', 'planning']" \
  "vus = env['ir.module.module'].search([('name', 'in', temoins)]).mapped('name')" \
  "maison = env['ir.module.module'].search_count([('name', 'in', ['diligence_simple', 'ansut_rh'])])" \
  "print('RESULTAT', total, '|', ','.join(sorted(vus)) or 'aucun', '|', maison)" \
  | docker compose run --rm -T odoo odoo shell -d "$BASE" --log-level=warn 2>/dev/null \
  | grep '^RESULTAT')

if [[ -z "$sortie" ]]; then
  printf '  %bÉCHEC%b Odoo n'"'"'a pas répondu. Base « %s » absente, ou pile arrêtée ?\n' \
    "$ROUGE" "$FIN" "$BASE"
  printf '        docker compose logs --tail=40 odoo\n'
  exit 1
fi

lu=${sortie#RESULTAT }
total=$(cut -d'|' -f1 <<<"$lu" | tr -d ' ')
temoins=$(cut -d'|' -f2 <<<"$lu" | sed 's/^ *//; s/ *$//')
maison=$(cut -d'|' -f3 <<<"$lu" | tr -d ' ')

printf '\n%b=== Ce qu'"'"'Odoo connaît%b\n' "$GRAS" "$FIN"
printf '  modules disponibles au total : %s\n' "$total"
printf '  témoins Enterprise trouvés   : %s\n' "$temoins"
printf '  modules du dépôt trouvés     : %s\n' "$maison"

printf '\n%b=== Verdict%b\n' "$GRAS" "$FIN"
if [[ "$temoins" == "aucun" ]]; then
  printf '  %bAucun module Enterprise visible.%b\n' "$JAUNE" "$FIN"
  printf '  Le dossier est-il bien monté ? Vérifier ADDONS_ENTREPRISE dans .env,\n'
  printf '  et que le chemin désigne le dossier CONTENANT les modules.\n'
  exit 1
fi
printf '  %bOdoo voit les modules Enterprise.%b\n' "$VERT" "$FIN"
printf '  Un module qui hérite de leurs modèles peut désormais s'"'"'installer.\n'
