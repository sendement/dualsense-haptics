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
  won't fight the game.
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
- Your user needs read/write access to the controller's `evdev`/`hidraw`
  devices (normally granted via the `input`/`plugdev` group or a udev rule
  that ships with `hid-playstation`-aware distros; if in doubt, check
  `ls -l /dev/input/event*` and `/dev/hidraw*`)

Tested with the regular DualSense and DualSense Edge, over both USB and
Bluetooth.

## Installation

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

### Optional: experimental Bluetooth direct-audio

Not required for anything else in the app. Only needed if you want to turn
on **Advanced Settings → Direct Audio → Enable over Bluetooth
(experimental)**:

```sh
git clone https://github.com/egormanga/SAxense.git
cd SAxense && make && sudo install -Dm755 SAxense /usr/local/bin/SAxense
```

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
