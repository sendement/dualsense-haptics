# DualSense Haptics

Audio-reactive haptics and adaptive triggers for the Sony DualSense controller
on Linux, over Bluetooth **or** USB.

Windows has [DualSenseX](https://github.com/Paliverse/DualSenseX), which turns your
system audio into rumble on the DualSense's motors. There's no DSX for Linux
— this is that, built from scratch on top of the kernel's own force-feedback
API, with a full GUI on top: presets, per-user profiles, adaptive trigger
effects, per-button haptics, a system tray icon with battery %, autostart,
light/dark/system theming, and 9 languages.

![DualSense Haptics - home screen](docs/screenshot.png)

## How it works

Over **USB**, the DualSense exposes itself as a 4-channel USB Audio Class
device: front-left/front-right are its tiny internal speaker, and
rear-left/rear-right are literally the two haptic motors, wired up as
ordinary audio outputs. That's the exact mechanism DSX uses on Windows and
the PS5 itself uses internally — real PCM waveforms played straight onto
the actuators, not a synthesized effect. This app detects that device and,
by default, streams your live system audio (gain-staged and band-limited to
what the motors reproduce well) directly onto it — literal audio-to-haptics,
independently per motor. It can be tuned or turned off under **Advanced
Settings → Direct Audio (USB)**.

Over **Bluetooth**, that USB Audio interface doesn't exist, so by default the
app falls back to the same approach it always used: capturing your system's
default audio output, splitting it into a bass band and a treble band, and
driving the controller's two rumble motors (`FF_RUMBLE`) with an envelope
follower per band, with noise-gating so a constant background hum doesn't
drown out transients like footsteps or gunshots. It's not literal audio,
but it tracks impacts, bass, and voice noticeably better than a flat
"vibrate on any sound" approach.

There's also an **experimental, opt-in** literal-audio path over Bluetooth,
built on independent reverse-engineering of the DualSense's Bluetooth HID
haptics protocol by [egormanga/SAxense](https://github.com/egormanga/SAxense)
(much lower fidelity than the USB path — 8-bit, 3kHz combined — but still
real PCM, not a synthesized envelope, and the same per-motor precision holds
up in practice). It's off by default and needs the `SAxense` tool installed
separately; see [Installation](#installation) and
[Credits](#credits).

Adaptive trigger effects (L2/R2 resistance profiles) are applied via
[`dualsensectl`](https://github.com/nowrep/dualsensectl), since they're
one-shot HID reports rather than something worth reimplementing here.

Over Bluetooth, Steam grabs raw HID control of the controller for any game
with native adaptive-trigger support and keeps writing to it for as long as
Steam runs — this app's own rumble still gets sent, but gets silently
overwritten on the wire, so nothing reaches the motors even though trigger
effects keep working. **Trigger + Vibration Mix** (desktop only, opt-in
under **Advanced Settings**, off by default) fixes this: it clones the
controller via `/dev/uhid`, hides the real device from everyone else, and
merges its own audio-reactive rumble into whatever Steam separately writes
for triggers/lightbar before forwarding it to the real hardware — so both
work at once instead of one silently blocking the other. It needs the
udev rule and small setcap'd helper the Arch package installs
automatically (see [Installation](#installation)); without them it falls
back to the same "detect and report" behavior described in
[Limitations](#limitations).

## Features

- **Direct audio-to-haptics over USB** — live system audio streamed as
  literal PCM straight onto the two motors, the same mechanism DSX and the
  PS5 itself use. Falls back to the band-split envelope approach below over
  Bluetooth, where that hardware path doesn't exist — plus an experimental,
  opt-in literal-audio path over Bluetooth too, at much lower fidelity (see
  [How it works](#how-it-works) and [Credits](#credits)).
- **Audio-to-haptics (Bluetooth / fallback)** — band-split bass/treble
  envelope followers with adjustable attack/release, sensitivity, contrast
  (gamma), and background noise suppression, independently for each motor.
- **5 built-in presets** (Balanced, Cinema, Music, Voice & Podcasts, Maximum
  Sensitivity) plus your own saved profiles.
- **Adaptive triggers** — 7 resistance presets (soft resistance, hard wall,
  weapon trigger, bow, machine gun, ratchet, gallop), set independently per
  trigger (L2/R2), plus a **custom effect builder** to dial in the raw
  `dualsensectl` parameters (mode, position, strength, frequency, etc.) by
  hand and experiment beyond the presets. If a game is already driving the
  triggers itself, the app detects that the device is held open elsewhere
  and skips automatically re-applying its own effect on reconnect, so it
  won't fight the game — or, on Bluetooth, turn on **Trigger + Vibration
  Mix** (desktop only, see [How it works](#how-it-works)) so it doesn't
  need to skip anything in the first place.
- **Per-button haptics** — pick any face button, bumper, trigger click,
  stick click, or the D-pad to buzz lightly while held, mixed with the audio
  vibration, at its own strength, from the motor on that side of the pad.
- **Works over USB or Bluetooth**, with a badge on the home screen showing
  which one is active.
- **System tray icon** with live connection status and battery percentage.
- **Autostart** on login.
- **Light / dark / system theme**, and **9 languages** (English, Russian,
  Chinese, Spanish, German, French, Japanese, Portuguese, Korean) — both
  switchable live from Settings, no restart needed.
- **Steam Deck / SteamOS**: a [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
  plugin (see [`deck-plugin/`](deck-plugin/)) puts the essentials in the
  Quick Access Menu — no need to leave Game Mode.

## Requirements

- Linux with the kernel's `hid-playstation` driver (mainline since Linux
  5.16; handles both USB and Bluetooth and exposes the controller through
  the standard joystick force-feedback API — no special setup needed beyond
  having a reasonably current kernel).
- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/) (Qt6 bindings)
- [python-evdev](https://python-evdev.readthedocs.io/)
- PulseAudio or PipeWire with `pipewire-pulse` (needs `parec` on `PATH`)
- [`dualsensectl`](https://github.com/nowrep/dualsensectl) — only required
  for adaptive trigger effects; everything else works without it
- [SAxense](https://github.com/egormanga/SAxense) — optional, only needed
  for the experimental Bluetooth direct-audio mode (off by default)
- A udev rule and small setcap'd helper — optional, only needed for
  **Trigger + Vibration Mix** (off by default); the Arch package installs
  both automatically, see [Installation](#installation)
- Your user needs read/write access to the controller's `evdev`/`hidraw`
  devices (normally granted via the `input`/`plugdev` group or a udev rule
  that ships with `hid-playstation`-aware distros; if in doubt, check
  `ls -l /dev/input/event*` and `/dev/hidraw*`)

Tested with the regular DualSense and DualSense Edge, over both USB and
Bluetooth.

## Installation

### Easiest: the graphical setup wizard

One wizard installs anything you want - the app itself, the Steam Deck
plugin, and the two optional extras below - with a few clicks and your
admin password when needed:

- **No clone needed**: download
  [`dualsense-haptics-bootstrap.desktop`](packaging/dualsense-haptics-bootstrap.desktop)
  on its own and double-click it in a file manager - it fetches the setup
  wizard itself and takes it from there. No git clone, no terminal.
- **If you already cloned the repo**: run
  `packaging/dualsense-haptics-setup.sh`, or double-click
  `packaging/dualsense-haptics-setup.desktop`.

It shows a checklist of what to set up, then handles the
compiling/downloading/installing itself (needs
[`zenity`](https://gitlab.gnome.org/GNOME/zenity), already installed on
most desktops). On Arch it builds and installs the real package; on other
distros it sets up a source checkout under `~/.local/share/dualsense-haptics`
plus an app-menu launcher. You can re-run it any time to add more later.

The sections below cover the same steps by hand, if you'd rather not run
someone else's script, or don't have `zenity`.

### Arch Linux / pacman

A `PKGBUILD` is included under [`packaging/`](packaging/):

```sh
git clone https://github.com/sendement/dualsense-haptics.git
cd dualsense-haptics/packaging
makepkg -si
```

`dualsensectl` is AUR-only, so `makepkg -si` won't fetch it automatically —
install it first with an AUR helper:

```sh
paru -S dualsensectl   # or: yay -S dualsensectl
```

### Other distributions

No distro packaging beyond the Arch one exists yet — run it from source:

```sh
git clone https://github.com/sendement/dualsense-haptics.git
cd dualsense-haptics

# Debian/Ubuntu-style dependency names, adjust for your distro:
sudo apt install python3 python3-pyside6.qtwidgets python3-evdev pipewire-pulse

python3 main.py
```

Build `dualsensectl` from source if your distro doesn't package it — it's a
small C program with a `Makefile`:

```sh
git clone https://github.com/nowrep/dualsensectl.git
cd dualsensectl && make && sudo make install
```

### Optional: SAxense and Trigger + Vibration Mix

Neither is required for anything else in the app - only for **Advanced
Settings → Direct Audio → Enable over Bluetooth (experimental)** and
**Advanced Settings → Trigger + Vibration Mix** respectively. The Arch
package's `.install` hook already sets up Trigger + Vibration Mix
automatically; SAxense is never auto-installed anywhere, since it's a
separate project.

The [setup wizard](#easiest-the-graphical-setup-wizard) above handles both
of these too. To do it by hand instead:

```sh
# SAxense
git clone https://github.com/egormanga/SAxense.git
cd SAxense && make && sudo install -Dm755 SAxense /usr/local/bin/SAxense

# Trigger + Vibration Mix
sudo groupadd -r dualsense-haptics
sudo usermod -aG dualsense-haptics "$USER"    # log out and back in after this
sudo install -Dm755 packaging/src/dualsense-hidlock.c /tmp/dualsense-hidlock.c
gcc -O2 -o /usr/lib/dualsense-haptics/dualsense-hidlock /tmp/dualsense-hidlock.c
sudo setcap 'cap_fowner+ep' /usr/lib/dualsense-haptics/dualsense-hidlock
sudo install -Dm644 packaging/71-dualsense-haptics-uhid.rules \
    /usr/lib/udev/rules.d/71-dualsense-haptics-uhid.rules
sudo udevadm control --reload-rules
```

## Steam Deck / SteamOS (Decky Loader plugin)

A trimmed-down version lives under [`deck-plugin/`](deck-plugin/) as a
[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin -
a Quick Access Menu panel instead of a window, for using it without leaving
Game Mode. It shares the same engine as the desktop app (same
`haptics_engine.py`/`config.py`/`presets.py`, vendored unchanged) and reads
the same kind of config, just through a much smaller set of controls: an
on/off toggle, connection/battery status, presets, saved profiles (created
on desktop, selectable here), adaptive trigger presets, and the Direct
Audio USB/Bluetooth toggles. Per-button haptics, the custom trigger
builder, and Trigger + Vibration Mix are desktop-only - the first two are
deliberately left out to keep the QAM panel to a handful of widgets; the
proxy was tried on Deck too but pulled after live testing in Big
Picture/gamescope kept showing a duplicate controller icon with doubled
inputs on reconnect, traced to how Steam's own controller detection
handles the cloned device - see [How it works](#how-it-works) for what the
feature does on desktop, where this doesn't come up.

Requires [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader#-installation)
already installed. Easiest: pick "Steam Deck / Decky Loader plugin" in the
[setup wizard](#easiest-the-graphical-setup-wizard) above. By hand instead:

```sh
git clone https://github.com/sendement/dualsense-haptics.git
cd dualsense-haptics/deck-plugin
./install.sh
```

`install.sh` copies a prebuilt frontend (`dist/`, committed in this repo so
a Node toolchain isn't needed on the Deck itself) into
`~/homebrew/plugins/` and restarts the `plugin_loader` service. To rebuild
the frontend yourself after editing `src/index.tsx`: `npm install && npm
run build`, then re-run `install.sh`.

## Usage

Launch it (`dualsense-haptics` if installed via the package, or
`python3 main.py` from source) and it opens on the **Home** page, showing
connection status, active profile, trigger state, and battery. Pick a
preset under **Presets**, tune things further under **Advanced Settings**,
and save your own combination as a profile under **Profiles**. Adaptive
trigger effects and per-button vibration live on their own pages. Theme and
language are under **Settings**.

Closing the window minimizes it to the tray rather than quitting — use the
tray icon's context menu to reopen, toggle vibration, or quit. Check
**Autostart** in the sidebar to have it launch minimized to tray on login
(pass `--tray` manually to start minimized without going through autostart).

## Limitations

- Over Bluetooth, by default haptic quality depends on the DSP tuning in
  **Advanced Settings** rather than a 1:1 waveform — see
  [How it works](#how-it-works) for why, and for the experimental opt-in
  path that gets literal (if lower-fidelity) audio over Bluetooth too.
- Vibration/button-haptics needs the controller to expose a force-feedback
  `evdev` interface, which requires `hid-playstation`; very old kernels
  won't have it.
- Adaptive triggers depend on `dualsensectl` being installed; without it,
  everything else still works.
- Built and tested on Arch/Hyprland; should work anywhere with a recent
  kernel and PipeWire/PulseAudio, but other desktop environments and
  distros haven't been extensively tested.
- Trigger + Vibration Mix is desktop-only (not in the Decky plugin) — see
  [Steam Deck / SteamOS](#steam-deck--steamos-decky-loader-plugin) for why.

## Credits

- [`dualsensectl`](https://github.com/nowrep/dualsensectl) (nowrep) — used
  for adaptive trigger effects.
- [SAxense](https://github.com/egormanga/SAxense) (egormanga/Sdore) — the
  Bluetooth haptics-over-audio protocol used by the experimental direct
  audio mode is their independent reverse-engineering research; see their
  repo for details. Not bundled — installed and invoked separately (see
  [Installation](#installation)), and used here strictly as an external
  tool, unmodified.

## License

[MIT](LICENSE)
