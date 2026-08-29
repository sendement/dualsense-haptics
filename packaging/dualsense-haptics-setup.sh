#!/bin/bash
# DualSense Haptics - graphical installer/setup wizard.
#
# Lets a user install the app itself (Arch: builds+installs the package;
# other distros: a source checkout + a desktop launcher), the Steam Deck /
# Decky Loader plugin, and the two optional extras that otherwise need a
# manual command block from the README's "Other distributions" section:
# Trigger + Vibration Mix (a udev rule + a small setcap'd helper + one group
# membership) and SAxense (an external tool built from source). Uses zenity
# for the checklist/progress dialogs and pkexec for the privileged steps, so
# nothing here requires a terminal beyond double-clicking
# dualsense-haptics-setup.desktop - the same "download it, double-click it,
# type your password when asked" shape as Decky Loader's own installer.
#
# Also runs standalone (no git clone needed at all): if this file is run on
# its own - e.g. downloaded straight from dualsense-haptics-bootstrap.desktop,
# with none of the repo's other files sitting next to it - it clones the repo
# itself into a temp dir up front, and cleans it back up when it's done.
set -uo pipefail

REPO_URL="https://github.com/sendement/dualsense-haptics.git"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAPPED_REPO_DIR=""
if [ ! -f "$REPO_DIR/packaging/PKGBUILD" ]; then
    REPO_DIR=""   # running standalone; cloned lazily below, only if actually needed
fi

cleanup() {
    [ -n "$BOOTSTRAPPED_REPO_DIR" ] && rm -rf "$BOOTSTRAPPED_REPO_DIR"
}
trap cleanup EXIT

if ! command -v zenity &>/dev/null; then
    MSG="This setup wizard needs 'zenity' (a small dialog tool most desktops already have).\n\nInstall it with your package manager - e.g. 'sudo pacman -S zenity' or 'sudo apt install zenity' - then run this again. Or follow the manual steps in the README instead."
    if command -v kdialog &>/dev/null; then
        kdialog --title "DualSense Haptics Setup" --error "$MSG"
    else
        echo -e "$MSG" >&2
    fi
    exit 1
fi

CHOICES=$(zenity --list --checklist \
    --title="DualSense Haptics Setup" \
    --text="Pick what to set up now. Each step needs your admin password once. You can re-run this any time to add more later." \
    --column="" --column="Feature" --column="What it does" \
    --width=780 --height=320 \
    TRUE  "app"          "The DualSense Haptics app itself (Arch: builds+installs the package; other distros: a source checkout + an app launcher)" \
    FALSE "deck"         "Steam Deck / Decky Loader plugin - puts the essentials in the Quick Access Menu (needs Decky Loader already installed)" \
    TRUE  "trigger_mix"  "Trigger + Vibration Mix: lets vibration and native adaptive triggers work together over Bluetooth (installs a udev rule + a small helper, adds one group to your user)" \
    FALSE "saxense"      "SAxense (experimental): higher-fidelity vibration over Bluetooth, builds a small external tool from source" \
    --separator="|" --hide-column=2 --print-column=2)
status=$?
[ $status -ne 0 ] && exit 0   # cancelled

if [ -z "$CHOICES" ]; then
    zenity --info --title="DualSense Haptics Setup" --text="Nothing selected - nothing to do."
    exit 0
fi

want_app=0
want_deck=0
want_trigger_mix=0
want_saxense=0
IFS="|" read -ra SELECTED <<< "$CHOICES"
for item in "${SELECTED[@]}"; do
    case "$item" in
        app) want_app=1 ;;
        deck) want_deck=1 ;;
        trigger_mix) want_trigger_mix=1 ;;
        saxense) want_saxense=1 ;;
    esac
done

# app/deck/trigger_mix all need files out of the repo itself; saxense doesn't
# (it clones its own separate source). Resolve this once, up front, so every
# step below can just read $REPO_DIR.
if { [ "$want_app" = 1 ] || [ "$want_deck" = 1 ] || [ "$want_trigger_mix" = 1 ]; } && [ -z "$REPO_DIR" ]; then
    BOOTSTRAPPED_REPO_DIR=$(mktemp -d)
    if ! git clone --depth=1 "$REPO_URL" "$BOOTSTRAPPED_REPO_DIR" 2>/dev/null; then
        rm -rf "$BOOTSTRAPPED_REPO_DIR"
        BOOTSTRAPPED_REPO_DIR=""
        zenity --error --title="Setup failed" --text="Couldn't download the dualsense-haptics repository. Check your network connection and try again."
        exit 1
    fi
    REPO_DIR="$BOOTSTRAPPED_REPO_DIR"
fi

failures=""
app_pacman_installed=0

if [ "$want_app" = 1 ]; then
    if command -v pacman &>/dev/null; then
        (
            echo "10"; echo "# Building the package..."
            cd "$REPO_DIR/packaging" || exit 1
            rm -f dualsense-haptics-*.pkg.tar.zst
            if ! makepkg -f >/tmp/dualsense-haptics-makepkg.log 2>&1; then
                echo "100"; exit 1
            fi
            PKGFILE=$(ls -t dualsense-haptics-*.pkg.tar.zst 2>/dev/null | head -1)
            [ -z "$PKGFILE" ] && { echo "100"; exit 1; }

            echo "60"; echo "# Installing (admin access)..."
            PRIV_SCRIPT=$(mktemp)
            # Two known, harmless reasons the plain install can fail, both
            # retried in one go rather than parsed out of pacman's message:
            # dualsensectl is AUR-only, so a fresh machine without an AUR
            # helper run first won't have it (--nodeps - everything but
            # adaptive triggers works without it anyway); and the helper
            # binary/udev rule may already sit on disk unowned by any
            # package, from an earlier Trigger + Vibration Mix-only run
            # before "app" existed in this wizard (--overwrite - safe here,
            # they're files this project manages either way).
            cat > "$PRIV_SCRIPT" <<EOF
#!/bin/bash
set -e
pacman -S --needed --noconfirm python pyside6 python-evdev libpulse libcap || true
pacman -U --noconfirm "$PWD/$PKGFILE" || pacman -U --noconfirm --nodeps --overwrite '*' "$PWD/$PKGFILE"
EOF
            chmod +x "$PRIV_SCRIPT"
            ok=1
            pkexec "$PRIV_SCRIPT" >/tmp/dualsense-haptics-pacman.log 2>&1 || ok=0
            rm -f "$PRIV_SCRIPT"
            echo "100"
            [ "$ok" = 1 ] || exit 1
        ) | zenity --progress --title="Installing DualSense Haptics" --auto-close --no-cancel --pulsate
        if [ "${PIPESTATUS[0]}" -ne 0 ]; then
            failures="$failures\n- DualSense Haptics app"
            zenity --error --title="App install failed" --text="Building or installing the package failed - see /tmp/dualsense-haptics-makepkg.log and /tmp/dualsense-haptics-pacman.log.\n\nMake sure build tools are installed (sudo pacman -S base-devel), then try again. Adaptive triggers need dualsensectl too, which is AUR-only (paru -S dualsensectl or yay -S dualsensectl) - install it yourself if you want that; everything else works without it."
        else
            app_pacman_installed=1
        fi
    else
        (
            echo "20"; echo "# Copying application files..."
            INSTALL_DIR="$HOME/.local/share/dualsense-haptics"
            mkdir -p "$INSTALL_DIR"
            cp "$REPO_DIR"/*.py "$INSTALL_DIR/" 2>/dev/null
            [ -d "$REPO_DIR/assets" ] && cp -r "$REPO_DIR/assets" "$INSTALL_DIR/"

            echo "45"; echo "# Checking dependencies..."
            if command -v apt &>/dev/null; then
                pkexec apt install -y python3 python3-pyside6.qtwidgets python3-evdev pipewire-pulse || true
            fi

            echo "70"; echo "# Building dualsensectl..."
            if ! command -v dualsensectl &>/dev/null; then
                DSCTL_TMP=$(mktemp -d)
                if git clone --depth=1 https://github.com/nowrep/dualsensectl.git "$DSCTL_TMP" 2>/dev/null \
                    && make -C "$DSCTL_TMP" >/dev/null 2>&1; then
                    pkexec install -Dm755 "$DSCTL_TMP/dualsensectl" /usr/local/bin/dualsensectl || true
                fi
                rm -rf "$DSCTL_TMP"
            fi

            echo "90"; echo "# Creating an app launcher..."
            mkdir -p "$HOME/.local/share/applications"
            cat > "$HOME/.local/share/applications/dualsense-haptics.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DualSense Haptics
Comment=Audio-reactive haptics and adaptive triggers for the DualSense controller
Exec=python3 "$INSTALL_DIR/main.py"
Icon=input-gaming
Categories=Utility;Settings;
Terminal=false
EOF
            echo "100"
        ) | zenity --progress --title="Installing DualSense Haptics" --auto-close --no-cancel --pulsate
        [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- DualSense Haptics app"
        if ! command -v apt &>/dev/null; then
            zenity --info --title="Almost done" --text="Copied to ~/.local/share/dualsense-haptics and added an app launcher named \"DualSense Haptics\".\n\nYour distro isn't Debian/Ubuntu-based, so install the Python dependencies yourself if they're not already present - see the README's \"Other distributions\" section - then launch it from your app menu."
        fi
    fi
fi

if [ "$want_deck" = 1 ]; then
    if ! systemctl list-unit-files plugin_loader.service &>/dev/null; then
        zenity --error --title="Decky Loader not found" --text="Decky Loader doesn't appear to be installed on this device (no plugin_loader.service).\n\nInstall it first: https://github.com/SteamDeckHomebrew/decky-loader#-installation, then run this again."
        failures="$failures\n- Steam Deck plugin (Decky Loader not installed)"
    else
        (
            echo "20"; echo "# Installing the Decky plugin (admin access)..."
            PRIV_SCRIPT=$(mktemp)
            cat > "$PRIV_SCRIPT" <<EOF
#!/bin/bash
set -e
TARGET="$HOME/homebrew/plugins/dualsense-haptics-deck"
mkdir -p "\$TARGET"
rm -rf "\$TARGET/dist" "\$TARGET/py_modules"
cp -r "$REPO_DIR/deck-plugin/plugin.json" "$REPO_DIR/deck-plugin/main.py" "$REPO_DIR/deck-plugin/package.json" "$REPO_DIR/deck-plugin/dist" "$REPO_DIR/deck-plugin/py_modules" "\$TARGET/"
systemctl restart plugin_loader
EOF
            chmod +x "$PRIV_SCRIPT"
            ok=1
            pkexec "$PRIV_SCRIPT" || ok=0
            rm -f "$PRIV_SCRIPT"
            echo "100"
            [ "$ok" = 1 ] || exit 1
        ) | zenity --progress --title="Installing Steam Deck plugin" --auto-close --no-cancel --pulsate
        [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- Steam Deck plugin"
    fi
fi

if [ "$want_trigger_mix" = 1 ]; then
    if [ "$app_pacman_installed" = 1 ]; then
        # The Arch package's own .install hook already built/installed the
        # helper and the udev rule, and created the group - it just can't
        # safely learn which desktop user to add to that group. Redoing the
        # rest here would leave pacman's file database out of sync with
        # what's really on disk, so only do the part that's actually left.
        (
            echo "50"; echo "# Requesting admin access..."
            PRIV_SCRIPT=$(mktemp)
            cat > "$PRIV_SCRIPT" <<EOF
#!/bin/bash
set -e
usermod -aG dualsense-haptics "$USER"
EOF
            chmod +x "$PRIV_SCRIPT"
            ok=1
            pkexec "$PRIV_SCRIPT" || ok=0
            rm -f "$PRIV_SCRIPT"
            echo "100"
            [ "$ok" = 1 ] || exit 1
        ) | zenity --progress --title="Setting up Trigger + Vibration Mix" --auto-close --no-cancel --pulsate
        [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- Trigger + Vibration Mix"
    else
        (
            echo "10"; echo "# Compiling the helper..."
            HELPER_TMP=$(mktemp)
            if ! gcc -O2 -o "$HELPER_TMP" "$REPO_DIR/packaging/src/dualsense-hidlock.c"; then
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
            echo "100"
            [ "$ok" = 1 ] || exit 1
        ) | zenity --progress --title="Setting up Trigger + Vibration Mix" --auto-close --no-cancel --pulsate
        [ "${PIPESTATUS[0]}" -ne 0 ] && failures="$failures\n- Trigger + Vibration Mix"
    fi
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
        --text="These steps didn't complete:$failures\n\nYou can run this again, or follow the manual steps in the README."
else
    note=""
    [ "$want_trigger_mix" = 1 ] && note="$note\n\nLog out and back in (or reboot) before turning on Trigger + Vibration Mix in Advanced Settings, so your new group membership takes effect."
    [ "$want_deck" = 1 ] && note="$note\n\nOpen (or restart) Steam and check the Quick Access Menu for \"DualSense Haptics\"."
    zenity --info --title="Setup complete" --text="Done!$note"
fi
