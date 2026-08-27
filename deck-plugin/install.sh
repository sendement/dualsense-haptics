#!/bin/sh
# Installs (or updates) the DualSense Haptics Decky Loader plugin from this
# checkout into ~/homebrew/plugins - the same thing the Decky Store does for
# published plugins, just done by hand since this one isn't published there.
set -e

PLUGIN_NAME="dualsense-haptics-deck"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/homebrew/plugins/$PLUGIN_NAME"

if [ ! -d "$SCRIPT_DIR/dist" ]; then
    echo "dist/ not found next to this script. Build the frontend first:" >&2
    echo "  cd $SCRIPT_DIR && npm install && npm run build" >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl list-unit-files plugin_loader.service >/dev/null 2>&1; then
    echo "Decky Loader doesn't appear to be installed (no plugin_loader.service)." >&2
    echo "Install it first: https://github.com/SteamDeckHomebrew/decky-loader#-installation" >&2
    exit 1
fi

echo "Installing $PLUGIN_NAME to $TARGET..."
# ~/homebrew/plugins is owned by the plugin_loader service (root), not you.
sudo mkdir -p "$TARGET"
sudo rm -rf "$TARGET/dist" "$TARGET/py_modules"
sudo cp -r "$SCRIPT_DIR/plugin.json" "$SCRIPT_DIR/main.py" "$SCRIPT_DIR/package.json" \
           "$SCRIPT_DIR/dist" "$SCRIPT_DIR/py_modules" "$TARGET/"

echo "Restarting Decky Loader..."
sudo systemctl restart plugin_loader

cat <<EOF

Installed. Open (or reopen) Steam and check the Quick Access Menu for
"DualSense Haptics". If Steam was already running, restart it once so it
picks up Decky's browser hooks.

Optional, only needed for Advanced Settings -> Direct Audio -> Bluetooth:
  git clone https://github.com/egormanga/SAxense.git
  cd SAxense && make && sudo install -Dm755 SAxense /usr/local/bin/SAxense
EOF
