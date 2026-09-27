#!/usr/bin/env bash
# Remove the mcpvectordb-chatgpt systemd user service installed by
# setup-chatgpt-linux.sh. Data directories are kept unless you confirm deletion.
set -euo pipefail
# shellcheck source=scripts/_common-linux.sh
source "$(dirname "$0")/_common-linux.sh"

SERVICE=mcpvectordb-chatgpt
UNIT_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$SERVICE.service"

step "Removing service '$SERVICE'..."
if [[ -f "$UNIT_FILE" ]]; then
    systemctl --user disable --now "$SERVICE" || true
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload
    ok "Service '$SERVICE' removed"
else
    warn "Service '$SERVICE' not found — nothing to remove."
fi

printf '\n'
read -r -p "Delete data directories ($DATA_DIR)? This removes your LanceDB index and cached model. [y/N] " answer || answer=""
if [[ "$answer" == [yY] ]]; then
    rm -rf -- "$DATA_DIR"
    ok "Deleted $DATA_DIR"
else
    ok "Data directories preserved at $DATA_DIR"
fi

cat <<EOF

  Uninstall complete.
  Stop exposing the port if you used Tailscale:  tailscale serve reset
  Lingering (loginctl enable-linger) is left on; other user services may rely on it.
  Remember to remove the URL from ChatGPT's Developer mode settings.
EOF
