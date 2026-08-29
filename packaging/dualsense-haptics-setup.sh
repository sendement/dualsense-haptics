#!/bin/bash
# DualSense Haptics - optional feature setup wizard.
#
# The base app/plugin install (pacman/makepkg, or Decky's install.sh) needs
# nothing beyond that. This script is only for the two OPTIONAL extras that
# otherwise need a manual command block from the README's "Other
# distributions" section: Trigger + Vibration Mix (a udev rule + a small
# setcap'd helper + one group membership) and SAxense (an external tool
# built from source). Uses zenity for the checklist/progress dialogs and
# pkexec for the one privileged step each needs, so nothing here requires a
# terminal beyond double-clicking dualsense-haptics-setup.desktop - the
# same "download it, double-click it, type your password once" shape as
# Decky Loader's own installer.
#
# Also runs standalone (no git clone needed at all): if this file is run on
# its own - e.g. downloaded straight from dualsense-haptics-bootstrap.desktop,
# with none of the repo's other files sitting next to it - it clones the repo
# itself into a temp dir the moment it actually needs a file from it.
set -uo pipefail

REPO_URL="https://github.com/sendement/dualsense-haptics.git"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAPPED_REPO_DIR=""
if [ ! -f "$REPO_DIR/packaging/src/dualsense-hidlock.c" ]; then
    REPO_DIR=""   # running standalone; cloned lazily, only if actually needed below
fi

ensure_repo() {
    if [ -n "$REPO_DIR" ]; then
        return 0
    fi
    BOOTSTRAPPED_REPO_DIR=$(mktemp -d)
    if ! git clone --depth=1 "$REPO_URL" "$BOOTSTRAPPED_REPO_DIR" 2>/dev/null; then
        rm -rf "$BOOTSTRAPPED_REPO_DIR"
        BOOTSTRAPPED_REPO_DIR=""
        return 1
    fi
    REPO_DIR="$BOOTSTRAPPED_REPO_DIR"
    return 0
}

if ! command -v zenity &>/dev/null; then
    MSG="This setup wizard needs 'zenity' (a small dialog tool most desktops already have).\n\nInstall it with your package manager - e.g. 'sudo pacman -S zenity' or 'sudo apt install zenity' - then run this again. Or follow the manual steps under the README's \"Other distributions\" section instead."
    if command -v kdialog &>/dev/null; then
        kdialog --title "DualSense Haptics Setup" --error "$MSG"
    else
        echo -e "$MSG" >&2
    fi
    exit 1
fi

CHOICES=$(zenity --list --checklist \
    --title="DualSense Haptics - Optional Setup" \
    --text="Pick the optional features to set up now. Each needs your admin password once. You can re-run this any time to add the other one later." \
    --column="" --column="Feature" --column="What it does" \
    --width=760 --height=260 \
    TRUE  "trigger_mix" "Trigger + Vibration Mix: lets vibration and native adaptive triggers work together over Bluetooth (installs a udev rule + a small helper, adds one group to your user)" \
    FALSE "saxense" "SAxense (experimental): higher-fidelity vibration over Bluetooth, builds a small external tool from source" \
    --separator="|" --hide-column=2 --print-column=2)
status=$?
[ $status -ne 0 ] && exit 0   # cancelled

if [ -z "$CHOICES" ]; then
    zenity --info --title="DualSense Haptics Setup" --text="Nothing selected - nothing to do."
    exit 0
fi

want_trigger_mix=0
want_saxense=0
IFS="|" read -ra SELECTED <<< "$CHOICES"
for item in "${SELECTED[@]}"; do
    case "$item" in
        trigger_mix) want_trigger_mix=1 ;;
        saxense) want_saxense=1 ;;
    esac
done

failures=""

if [ "$want_trigger_mix" = 1 ]; then
    (
        echo "5"; echo "# Fetching setup files..."
        if ! ensure_repo; then
            echo "100"; exit 1
        fi

        echo "10"; echo "# Compiling the helper..."
        HELPER_TMP=$(mktemp)
        if ! gcc -O2 -o "$HELPER_TMP" "$REPO_DIR/packaging/src/dualsense-hidlock.c"; then
            [ -n "$BOOTSTRAPPED_REPO_DIR" ] && rm -rf "$BOOTSTRAPPED_REPO_DIR"
            echo "100"; exit 1
        fi

        echo "50"; echo "# Requesting admin access..."
        PRIV_SCRIPT=$(mktemp)
        cat > "$PRIV_SCRIPT" <<EOF
#!/bin/bash
set -e
install -Dm755 "$HELPER_TMP" /usr/lib/dualsense-haptics/dualsense-hidlock
getent group dualsense-haptics >/dev/null || groupadd -r dualsense-haptics
setcap 'cap_fowner+ep' /usr/lib/dualsense-haptics/dualsense-hidlock
install -Dm644 "$REPO_DIR/packaging/71-dualsense-haptics-uhid.rules" /usr/lib/udev/rules.d/71-dualsense-haptics-uhid.rules
udevadm control --reload-rules
usermod -aG dualsense-haptics "$USER"
EOF
        chmod +x "$PRIV_SCRIPT"
        ok=1
        pkexec "$PRIV_SCRIPT" || ok=0
        rm -f "$PRIV_SCRIPT" "$HELPER_TMP"
        [ -n "$BOOTSTRAPPED_REPO_DIR" ] && rm -rf "$BOOTSTRAPPED_REPO_DIR"
        echo "100"
        [ "$ok" = 1 ] || exit 1
    ) | zenity --progress --title="Setting up Trigger + Vibration Mix" --auto-close --no-cancel --pulsate
    [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- Trigger + Vibration Mix"
fi

if [ "$want_saxense" = 1 ]; then
    (
        echo "10"; echo "# Cloning SAxense..."
        SRC_TMP=$(mktemp -d)
        if ! git clone --depth=1 https://github.com/egormanga/SAxense.git "$SRC_TMP" 2>/dev/null; then
            echo "100"; exit 1
        fi

        echo "50"; echo "# Building..."
        if ! make -C "$SRC_TMP" >/dev/null 2>&1; then
            rm -rf "$SRC_TMP"
            echo "100"; exit 1
        fi

        echo "80"; echo "# Installing (admin access)..."
        ok=1
        pkexec install -Dm755 "$SRC_TMP/SAxense" /usr/local/bin/SAxense || ok=0
        rm -rf "$SRC_TMP"
        echo "100"
        [ "$ok" = 1 ] || exit 1
    ) | zenity --progress --title="Setting up SAxense" --auto-close --no-cancel --pulsate
    [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- SAxense"
fi

if [ -n "$failures" ]; then
    zenity --error --title="Setup finished with errors" \
        --text="These steps didn't complete:$failures\n\nYou can run this again, or follow the manual steps in the README's \"Other distributions\" section."
else
    note=""
    [ "$want_trigger_mix" = 1 ] && note="\n\nLog out and back in (or reboot) before turning on Trigger + Vibration Mix in Advanced Settings, so your new group membership takes effect."
    zenity --info --title="Setup complete" --text="Done!$note"
fi
