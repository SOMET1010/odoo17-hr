#!/usr/bin/env bash
#
# Joue le test d'acceptation sans dépendre de la session qui l'a lancé.
#
#   bash deployer/acceptation.sh          lance, puis rend la main aussitôt
#   bash deployer/acceptation.sh --voir   affiche le journal
#
# Raison d'être : sur une liaison instable, « nohup … & » suivi d'un tail
# oblige à rester connecté pour voir quoi que ce soit, et une coupure pendant
# le lancement perd tout. Ici le test tourne dans sa propre session (setsid),
# survit à la fermeture du terminal, et le résultat s'obtient par une
# connexion courte qui ne fait que lire un fichier.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

JOURNAL="${ATELIER_JOURNAL:-/var/log/atelier-acceptation.log}"
ENVFILE="${XDG_CONFIG_HOME:-$HOME/.config}/atelier-odoo/env"
BUILDER="odoo-builder/cli"

# --------------------------------------------------------------- lecture

if [[ "${1:-}" == "--voir" ]]; then
  [[ -f "$JOURNAL" ]] || { echo "Aucun journal : le test n'a jamais été lancé."; exit 1; }
  cat "$JOURNAL"
  if pgrep -f "$BUILDER/acceptation.py" >/dev/null 2>&1; then
    echo
    echo "--- test toujours en cours ---"
  fi
  exit 0
fi

# ----------------------------------------------------------- exécution réelle

if [[ "${1:-}" == "--executer" ]]; then
  # shellcheck disable=SC1090
  [[ -f "$ENVFILE" ]] && . "$ENVFILE"

  echo "=== Diagnostic des fournisseurs ==="
  python3 "$BUILDER/atelier_odoo.py" providers check
  echo

  echo "=== Acceptation : besoin en français → module Odoo exécutable ==="
  python3 "$BUILDER/acceptation.py"
  code=$?

  echo
  echo "=== Terminé — code de sortie $code ==="
  exit "$code"
fi

# --------------------------------------------------------------- lancement

if pgrep -f "$BUILDER/acceptation.py" >/dev/null 2>&1; then
  echo "Un test tourne déjà. Pour le suivre :"
  echo "    bash deployer/acceptation.sh --voir"
  exit 1
fi

if [[ ! -f "$ENVFILE" ]]; then
  echo "Configuration introuvable : $ENVFILE"
  echo "Rejouer deployer/installer.sh."
  exit 1
fi

# setsid détache de la session SSH : une coupure de la liaison n'envoie plus
# rien au processus, qui n'a de toute façon plus de terminal de contrôle.
setsid nohup bash "$0" --executer >"$JOURNAL" 2>&1 </dev/null &
disown 2>/dev/null

adresse=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -1)
[[ -n "$adresse" ]] || adresse=$(hostname -I 2>/dev/null | awk '{print $1}')

echo "Test lancé. Il continue même si cette connexion tombe."
echo
echo "  Pour lire le résultat, depuis votre poste, à tout moment :"
echo "      ssh root@${adresse:-<ip>} \"bash $PWD/deployer/acceptation.sh --voir\""
echo
echo "  Journal : $JOURNAL"
