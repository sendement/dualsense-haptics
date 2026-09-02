"""
Core audio-to-haptics engine for the DualSense, decoupled from any GUI.

Captures the system's default audio output and drives the DualSense's two
rumble motors (FF_RUMBLE strong=bass, weak=treble) through the standard
Linux force-feedback (evdev) API. See README.md for the DSP rationale.

Runs in its own thread; `config` is a plain nested dict that the GUI can
mutate directly for live tuning (each analysis chunk re-reads it, so no
locking is needed - worst case one 20ms frame uses a slightly stale value).
"""
import collections
import fcntl
import glob
import math
import os
import pwd
import queue
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time

import evdev
from evdev import ecodes, ff

import bt_hid_proxy

RATE = 8000
CHANNELS = 2
CHUNK_MS = 20
CHUNK_SAMPLES = RATE * CHUNK_MS // 1000
CHUNK_BYTES = CHUNK_SAMPLES * CHANNELS * 2  # s16le
REPLAY_LEN_MS = 60

# Direct-audio (USB) path: plays live audio as literal PCM straight onto the
# two motors instead of synthesizing an envelope, so it uses a real audio
# rate rather than the coarse control-rate above. See find_dualsense_sink().
RATE_DIRECT = 48000
CHUNK_MS_DIRECT = 20
CHUNK_SAMPLES_DIRECT = RATE_DIRECT * CHUNK_MS_DIRECT // 1000
BUTTON_CLICK_HZ = 150
# User-adjustable per-button click tone range - see _button_click_targets()
# and DEFAULT_CONFIG's button_haptics comment. Low end reads as a dull/muffled
# thump, high end as a bright/ringing tick.
BUTTON_CLICK_HZ_MIN = 60
BUTTON_CLICK_HZ_MAX = 400

# Direct-audio (Bluetooth) path: same idea, over a community-reverse-
# engineered BT HID haptics protocol (github.com/egormanga/SAxense) rather
# than the USB Audio Class interface - opt-in and far lower fidelity (8-bit,
# combined 3kHz for both channels) but still literal PCM, not a synthesized
# envelope. See find_dualsense_hidraw() and HapticsEngine._session_bt_direct_audio.
BT_RATE = 3000
BT_CHUNK_MS = 20
BT_CHUNK_SAMPLES = BT_RATE * BT_CHUNK_MS // 1000
BT_BUTTON_CLICK_HZ = 150
# User-adjustable range for direct_audio.bt_chunk_ms (see _session_bt_direct_
# audio/_run_bt_proxy_saxense, where the configured value overrides
# BT_CHUNK_MS above) - smaller trades latency for more Bluetooth reports/sec
# (undoing the traffic work in forward_trigger_only()'s dedup), larger trades
# the reverse. Bounded to values close to the tested default rather than
# letting either tradeoff run unchecked.
BT_CHUNK_MS_MIN = 10
BT_CHUNK_MS_MAX = 30
# Exposed as a 3-way choice rather than a free slider - the fine-grained
# range was more knobs than this setting actually needed, and the Decky
# plugin's slider control couldn't render its drag handle for this one at
# all (see deck-plugin/src/index.tsx's own history on that).
BT_CHUNK_MS_CHOICES = (BT_CHUNK_MS_MIN, BT_CHUNK_MS, BT_CHUNK_MS_MAX)

DEFAULT_CONFIG = {
    "master_gain": 1.0,
    "bass_cutoff_hz": 90,
    "treble_cutoff_hz": 500,
    "bass": {"attack": 0.95, "release": 0.5, "lo": 0.010, "hi": 0.12, "gamma": 1.3},
    "treble": {"attack": 0.95, "release": 0.55, "lo": 0.003, "hi": 0.045, "gamma": 0.7},
    "bass_ceiling": {"attack_s": 0.08, "release_s": 2.5},
    "treble_ceiling": {"attack_s": 0.05, "release_s": 2.0},
    # button code (str, JSON-friendly) -> {"enabled": bool, "strength": float,
    # "click_hz": float}. click_hz only matters on the literal-PCM sessions
    # (_session_direct_audio/_session_bt_direct_audio/_run_bt_proxy_saxense),
    # which mix the click straight into the outgoing audio and so can give it
    # any tone (BUTTON_CLICK_HZ_MIN..MAX); _session_ff/_run_bt_proxy_envelope
    # drive a single fixed-frequency FF_RUMBLE effect instead and ignore it.
    # Empty by default - no button feedback until the user picks one.
    "button_haptics": {},
    # USB only - see find_dualsense_sink() and HapticsEngine._session_direct_audio.
    # bt_enabled is separate and opt-in (default off) - see BT_RATE above.
    # parec_restart_on_stall is also opt-in (default off): confirmed on real
    # hardware to briefly drop controller input each time it fires (see
    # PAREC_RESTART_STALL_CHUNKS), so it trades that off against recovering
    # cleanly from a persistent audio stall instead of just riding it out.
    "direct_audio": {"enabled": True, "gain": 5.0, "cutoff_hz": 500, "bt_enabled": False,
                      "bt_chunk_ms": BT_CHUNK_MS, "parec_restart_on_stall": False},
    # Bluetooth only, opt-in - see bt_hid_proxy.py and HapticsEngine._session_bt_proxy.
    "bt_hid_proxy": {"enabled": False},
    # Requires bt_hid_proxy (exclusive device access to safely fight Steam's
    # own lightbar/LED writes) - see bt_hid_proxy.apply_led_visualizer().
    # attack/release/gamma tune _led_smooth() (deliberately separate from
    # each band's own haptic shape()/ceiling_step() envelopes, which are
    # tuned for how a hit should *feel* rather than how color should
    # *look* - confirmed on real hardware that feeding the raw per-tick
    # haptic magnitude straight into the lightbar read as a flickery
    # "disco" effect, not mood lighting); bass_priority tunes
    # bt_hid_proxy.apply_led_visualizer()'s own bass-vs-mid/treble ducking.
    "led_visualizer": {"enabled": False, "attack": 0.5, "release": 0.08, "gamma": 1.8, "bass_priority": 0.6},
}

BUTTON_ATTACK = 0.7
BUTTON_RELEASE = 0.5


def _button_click_targets(cfg, held_keys, default_hz, held_scale=None):
    """Per side, the strength (and matching click_hz tone) of whichever held,
    enabled button currently has the highest strength on that side - shared
    by every session (FF_RUMBLE included - the tone it computes just goes
    unused there) so button_haptics only has one place its target-selection
    logic lives. Picking one tone per side (not mixing every held button's
    own tone together) keeps this simple and matches how the strength itself
    already collapses to a single per-side value via max().

    held_scale (optional) multiplies a code's configured strength by a 0..1
    factor instead of applying it at fixed intensity - used for
    LEFT_STICK_VIRTUAL_CODE/RIGHT_STICK_VIRTUAL_CODE so a stick's feedback
    actually tracks how far it's tilted rather than being all-or-nothing
    like a real button."""
    strong_target = weak_target = 0.0
    strong_hz = weak_hz = default_hz
    for code_str, entry in cfg["button_haptics"].items():
        code = int(code_str)
        if not entry.get("enabled") or not held_keys.get(code, False):
            continue
        side = BUTTON_SIDE.get(code, "weak")
        strength = entry.get("strength", 0.4)
        if held_scale is not None:
            strength *= held_scale.get(code, 1.0)
        click_hz = entry.get("click_hz", default_hz)
        if side == "strong":
            if strength >= strong_target:
                strong_target, strong_hz = strength, click_hz
        else:
            if strength >= weak_target:
                weak_target, weak_hz = strength, click_hz
    return strong_target, strong_hz, weak_target, weak_hz


def _led_smooth(mag, env, attack, release, gamma):
    """Fast attack so a real peak still pops instantly; slow release so it
    fades out instead of jittering tick-to-tick; a >1 gamma on top so a
    strong hit reads as a clear, saturated color while ambient/background
    level stays visibly muted rather than a constant wash of color - see
    DEFAULT_CONFIG's led_visualizer comment for the full rationale."""
    env += (mag - env) * (attack if mag > env else release)
    return env, env ** gamma

# Which motor a held button feeds: the strong motor sits on the left side of
# the controller, the weak one on the right, so left-side buttons vibrate the
# left/strong motor (kept light via each button's own strength) and
# right-side buttons the right/weak motor - vibration comes from the side
# the button is actually on, instead of always the same motor.
BUTTON_SIDE = {
    ecodes.BTN_TL: "strong", ecodes.BTN_TL2: "strong",
    ecodes.BTN_THUMBL: "strong", ecodes.BTN_SELECT: "strong",
    ecodes.BTN_TR: "weak", ecodes.BTN_TR2: "weak",
    ecodes.BTN_THUMBR: "weak", ecodes.BTN_START: "weak",
    ecodes.BTN_SOUTH: "weak", ecodes.BTN_EAST: "weak",
    ecodes.BTN_NORTH: "weak", ecodes.BTN_WEST: "weak",
    ecodes.BTN_MODE: "weak",
}

# The D-pad isn't a button - it's two EV_ABS hat axes (ABS_HAT0X/Y) - so it
# can't share a code with real buttons. This sentinel (no real evdev code is
# negative) represents "any D-pad direction held" as a single virtual entry.
DPAD_VIRTUAL_CODE = -1
BUTTON_SIDE[DPAD_VIRTUAL_CODE] = "strong"

# Same idea as DPAD_VIRTUAL_CODE, for the analog sticks (ABS_X/Y left,
# ABS_RX/RY right) - "held" is deflection past STICK_DEADZONE, and unlike a
# real button, button_haptics' own "strength" gets scaled by how far the
# stick is currently pushed (see _button_click_targets' held_scale param and
# _analog_held_scale()) rather than applied at a fixed level. Same idea for
# the analog triggers (L2/R2's *pull amount*, not the digital press already
# covered by btn_l2_press/btn_r2_press/BTN_TL2/BTN_TR2 above).
LEFT_STICK_VIRTUAL_CODE = -2
RIGHT_STICK_VIRTUAL_CODE = -3
LEFT_TRIGGER_VIRTUAL_CODE = -4
RIGHT_TRIGGER_VIRTUAL_CODE = -5
BUTTON_SIDE[LEFT_STICK_VIRTUAL_CODE] = "strong"
BUTTON_SIDE[RIGHT_STICK_VIRTUAL_CODE] = "weak"
BUTTON_SIDE[LEFT_TRIGGER_VIRTUAL_CODE] = "strong"
BUTTON_SIDE[RIGHT_TRIGGER_VIRTUAL_CODE] = "weak"
STICK_DEADZONE = 0.15


# Sticks are bipolar (rest at their own center, ABS_X/Y/RX/RY); the analog
# triggers are unipolar (rest at their own min, ABS_Z=L2/ABS_RZ=R2) - both
# get normalized to 0..1 the same way (see _init_analog_raw's axis_info),
# just with a different (base, scale) pair per axis shape.
_ANALOG_STICK_AXES = (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY)
_ANALOG_TRIGGER_AXES = (ecodes.ABS_Z, ecodes.ABS_RZ)


def _init_analog_raw(dev):
    """Queried once per session (the axis range doesn't change mid-session,
    same reasoning as find_led_paths()'s own one-time call) - a raw per-
    axis-code dict seeded at each axis's own resting value, plus the (base,
    scale) pair needed to normalize later reads to 0..1 via (raw - base) /
    scale, keyed by the same evdev axis codes. See _analog_held_scale()."""
    raw, axis_info = {}, {}
    for code in _ANALOG_STICK_AXES:
        info = dev.absinfo(code)
        base = (info.min + info.max) / 2.0
        axis_info[code] = (base, (info.max - info.min) / 2.0 or 1.0)
        raw[code] = base
    for code in _ANALOG_TRIGGER_AXES:
        info = dev.absinfo(code)
        axis_info[code] = (info.min, (info.max - info.min) or 1.0)
        raw[code] = info.min
    return raw, axis_info


def _deadzone_rescale(norm, deadzone):
    """0..1 in, 0..1 out - ramps from 0 right past `deadzone` up to 1.0 at
    norm=1, instead of jumping straight to `deadzone`. Shared by every
    analog axis this app turns into proportional button-haptics feedback."""
    if norm < deadzone:
        return 0.0
    return min(1.0, (norm - deadzone) / (1.0 - deadzone))


def _analog_held_scale(raw, axis_info, deadzone=STICK_DEADZONE):
    """held_scale dict (see _button_click_targets) for all four analog
    virtual codes at once - LEFT/RIGHT_STICK_VIRTUAL_CODE (2D deflection
    magnitude) and LEFT/RIGHT_TRIGGER_VIRTUAL_CODE (1D pull amount)."""
    def axis_norm(code):
        base, scale = axis_info[code]
        return (raw[code] - base) / scale
    left_stick = _deadzone_rescale(math.hypot(axis_norm(ecodes.ABS_X), axis_norm(ecodes.ABS_Y)), deadzone)
    right_stick = _deadzone_rescale(math.hypot(axis_norm(ecodes.ABS_RX), axis_norm(ecodes.ABS_RY)), deadzone)
    left_trigger = _deadzone_rescale(axis_norm(ecodes.ABS_Z), deadzone)
    right_trigger = _deadzone_rescale(axis_norm(ecodes.ABS_RZ), deadzone)
    return {
        LEFT_STICK_VIRTUAL_CODE: left_stick, RIGHT_STICK_VIRTUAL_CODE: right_stick,
        LEFT_TRIGGER_VIRTUAL_CODE: left_trigger, RIGHT_TRIGGER_VIRTUAL_CODE: right_trigger,
    }


# Sony's USB vendor/product ID for the DualSense - matched instead of the
# device name, since the kernel reports a different name per transport
# ("DualSense Wireless Controller" over Bluetooth vs. "Sony Interactive
# Entertainment DualSense Wireless Controller" over USB). Both the regular
# DualSense and the Edge report the same evdev FF_RUMBLE interface, just
# under a different product ID (confirmed against dualsensectl's own
# device table, which recognizes the same two IDs).
SONY_VENDOR_ID = 0x054C
DUALSENSE_PRODUCT_IDS = {0x0CE6, 0x0DF2}  # DualSense, DualSense Edge


def _audio_subprocess_prefix():
    """Argv prefix needed to run parec/paplay when this process itself is
    running as root - which only happens for the Decky plugin backend, and
    only once it opts into Decky's "root" manifest flag (needed for
    /dev/uhid access - see bt_hid_proxy.py). PipeWire/PulseAudio's client
    library refuses a root connection to a non-root user's runtime dir
    outright ("XDG_RUNTIME_DIR is not owned by us (uid 0)... Don't do
    that."), regardless of the env var being set correctly - confirmed
    empirically. The desktop app is never root, so this is always a no-op
    there. DUALSENSE_AUDIO_USER is set by deck-plugin/main.py from
    decky.DECKY_USER (the actual logged-in desktop user, not whatever this
    already-root process's own uid says) and inherited down through
    headless_runner.py's subprocess environment."""
    if os.geteuid() != 0:
        return []
    user = os.environ.get("DUALSENSE_AUDIO_USER")
    if not user:
        return []
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return []
    return ["sudo", "-u", user, "env", f"XDG_RUNTIME_DIR=/run/user/{uid}"]


def find_ff_device():
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.uniq == bt_hid_proxy.CLONE_UNIQ:
            # Our own proxy clone (see bt_hid_proxy.py) advertises the same
            # vendor/product/FF_RUMBLE capability as the real DualSense on
            # purpose (so Steam can't tell them apart), which means this
            # function can't either without an explicit check - confirmed on
            # real hardware that once the real device disconnects (leaving
            # only the still-alive clone - see BtHidProxySession.detach()),
            # this would otherwise pick the clone right back up as "the"
            # controller and hand it to _session() as if freshly connected,
            # rather than falling through to _service_bt_proxy_idle()'s
            # detached-servicing path. Note d.phys is *not* a reliable way
            # to detect this: it reads back blank for a uhid-backed input
            # device regardless of what build_create2() set at the HID
            # level, unlike d.uniq which does correctly reflect CLONE_UNIQ.
            continue
        if (ecodes.EV_FF in d.capabilities()
                and d.info.vendor == SONY_VENDOR_ID
                and d.info.product in DUALSENSE_PRODUCT_IDS):
            return d
    return None


def find_clone_ff_device():
    """The proxy clone's own evdev interface - opposite filter from
    find_ff_device(). Needed because BtHidProxySession.attach() can lock the
    real device's nodes (chmod 0600, see its own comment on why this has to
    happen before Steam can grab them) well before the real device's evdev
    interface is even visible to find_ff_device() - and once locked, not
    even this same unprivileged process can freshly open it again, only the
    fd attach() already had open beforehand. Confirmed on real hardware:
    without this, run() gets stuck treating an already-internally-attached
    proxy session as "still searching" forever, since find_ff_device() can
    no longer see the (now correctly excluded) clone as a stand-in the way
    it accidentally did before that exclusion was added. Reading input from
    the clone instead is sound: BtHidProxySession.relay_input() mirrors the
    real device's raw input reports onto it continuously once attached, so
    the clone's own resulting evdev events are the same as the real
    device's."""
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.uniq == bt_hid_proxy.CLONE_UNIQ and ecodes.EV_FF in d.capabilities():
            return d
    return None


def connection_kind(dev):
    """"usb" / "bluetooth" / None, read from the evdev bus type - the same
    controller (and evdev name) shows up over either transport, only the
    kernel-reported bustype tells them apart."""
    bustype = dev.info.bustype
    if bustype == ecodes.BUS_USB:
        return "usb"
    if bustype == ecodes.BUS_BLUETOOTH:
        return "bluetooth"
    return None


_PLAYER_LED_RE = re.compile(r".*:white:player-(\d)$")

# write_led_sysfs() touches up to 6 separate LED class device files (the
# lightbar's multi_intensity plus 5 player-indicator brightness files) each
# time it's called - each write has the kernel driver send its own fresh HID
# output report over the wire. Calling it every audio tick (every 20ms, i.e.
# up to 300 extra BT reports/sec) was confirmed on real hardware to destroy
# the controller's Bluetooth connection within a couple of seconds on a Deck
# - presumably a channel already busier than a desktop's, per direct-audio's
# own crackle discussion. Throttled to this interval instead; still visually
# smooth since _led_smooth()'s own attack/release envelope is what actually
# produces the perceived motion, not the raw write rate.
LED_WRITE_INTERVAL_S = 0.08

# Caps how many clone /dev/uhid reports get drained in a single go (see the
# three call sites below) - draining unconditionally "while readable"
# fixed the queue-overflow warnings, but confirmed on real hardware to
# introduce a worse problem under a genuinely sustained (not just bursty)
# write rate from Steam: that loop could run indefinitely, starving
# relay_input() (the real controller's own input forwarding) in the same
# tick - and Steam disconnects a clone whose input goes quiet for too long,
# exactly the "Controller device closed after hid_read failure" behavior
# documented elsewhere in this file. 32 matches the kernel's own uhid queue
# depth (UHID_BUFSIZE in drivers/hid/uhid.c) - there's never anything left
# to gain by draining more than that in one pass anyway.
UHID_MAX_DRAIN_PER_TICK = 32

# Fallback for when UHID_MAX_DRAIN_PER_TICK isn't enough - i.e. Steam is
# issuing GET_REPORTs faster than one tick's budget of HIDIOCGFEATURE calls
# (each already bounded by hidiocgfeature_bounded(), but still not free) can
# keep up with. Rather than keep paying that per-report cost, drain the rest
# with relay_output_or_get_report(fast=True), which skips it (see that
# method's docstring for why only HIDIOCGFEATURE, not the OUTPUT pass-
# through, is safe to skip this way - the pass-through has its own,
# different protection against a slow real device: see
# BtHidProxySession._write_real_async()). Bounded rather than "while
# readable" so a sustained flood can't turn this fallback into its own
# unbounded stall - one tick's worth of even the cheap fast path is enough to
# catch back up to one tick's queue depth.
UHID_FAST_DRAIN_CAP = 512


def find_led_paths(dev):
    """Sysfs LED class device paths for this DualSense's lightbar (an RGB
    "multi-color" LED, its `multi_intensity` file taking "R G B" 0-255 each)
    and its 5 player-indicator LEDs (each a plain on/off `brightness` file)
    - hid-playstation registers these as ordinary Linux LED class devices,
    sibling to the hid device's own sysfs node. That node is two levels up
    from /sys/class/input/<event>/device's own target (event -> input core
    -> the hid device itself) - a standard evdev/input-core relationship,
    nothing DualSense-specific.

    This is the mechanism the Immersive Lighting visualizer uses wherever
    the Bluetooth HID Proxy isn't available to safely own report bytes
    (see bt_hid_proxy.apply_led_visualizer()) - namely the Decky plugin,
    which dropped that proxy entirely (see _session_bt_proxy's own history)
    - since it drives the device through the kernel's own LED subsystem
    instead of a raw hidraw write, with no exclusive-access dance needed.
    Returns ((multi_intensity_path, brightness_path, max_brightness),
    [5 player paths, in order]); the lightbar tuple (or any of its
    elements) is None, and each player path is None, if this kernel's
    hid-playstation doesn't expose it (older kernels don't). The lightbar's
    own `brightness` is the multi-color LED's master scaling factor - a
    multi_intensity write alone was confirmed on real hardware to stay
    invisible whenever this starts out (or gets set to) 0, e.g. a device
    that's never had anything else address it as a multi-color LED before -
    write_led_sysfs() forces it to max_brightness on every write rather
    than assume the kernel's own default already has it there."""
    try:
        input_dir = os.path.realpath(f"/sys/class/input/{os.path.basename(dev.path)}/device")
        leds_dir = os.path.join(os.path.dirname(os.path.dirname(input_dir)), "leds")
        names = os.listdir(leds_dir)
    except OSError:
        return None, [None] * 5
    lightbar = None
    players = [None] * 5
    for name in names:
        if name.endswith(":rgb:indicator"):
            led_dir = os.path.join(leds_dir, name)
            try:
                with open(os.path.join(led_dir, "max_brightness")) as f:
                    max_brightness = f.read().strip()
            except OSError:
                max_brightness = "255"
            lightbar = (os.path.join(led_dir, "multi_intensity"), os.path.join(led_dir, "brightness"), max_brightness)
        else:
            m = _PLAYER_LED_RE.match(name)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < 5:
                    players[idx] = os.path.join(leds_dir, name, "brightness")
    return lightbar, players


def write_led_sysfs(lightbar, player_paths, led):
    """Applies led_rgb_and_bar(led) via find_led_paths()'s sysfs files
    instead of a hidraw report - see find_led_paths() for when/why. Missing
    paths (kernel without LED class support) are silently skipped rather
    than raising, same as a report-byte write would just be a no-op on
    hardware that doesn't support it."""
    rgb, lit = bt_hid_proxy.led_rgb_and_bar(led)
    if lightbar:
        multi_intensity_path, brightness_path, max_brightness = lightbar
        try:
            with open(brightness_path, "w") as f:
                f.write(max_brightness)
        except OSError:
            pass
        try:
            with open(multi_intensity_path, "w") as f:
                f.write(f"{rgb[0]} {rgb[1]} {rgb[2]}")
        except OSError:
            pass
    for i, path in enumerate(player_paths):
        if path:
            try:
                with open(path, "w") as f:
                    f.write("1" if i < lit else "0")
            except OSError:
                pass


def find_dualsense_sink():
    """Name of the DualSense's 4-channel "Direct" USB Audio Class sink, if
    connected over USB and PipeWire/PulseAudio has already picked it up.
    front-left/front-right are the tiny internal speaker; rear-left/
    rear-right are literally the two haptic motors, wired up as ordinary
    audio outputs - confirmed by ear (er, by hand) against real hardware.
    This is the same USB descriptor Windows uses for DSX's audio-to-haptics,
    and the same mechanism Sony's own PS5 SDK uses internally. Matched by
    vendor/product id and channel count rather than by sink name, since the
    name embeds the USB product string (see find_ff_device())."""
    try:
        out = subprocess.run(
            ["pactl", "list", "sinks"], capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    vendor_needle = f'device.vendor.id = "0x{SONY_VENDOR_ID:04x}"'
    product_needles = [f'device.product.id = "0x{pid:04x}"' for pid in DUALSENSE_PRODUCT_IDS]
    for block in out.split("\n\n"):
        if vendor_needle not in block or not any(needle in block for needle in product_needles):
            continue
        if 'audio.channels = "4"' not in block:
            continue
        m = re.search(r"^\s*Name:\s*(\S+)", block, re.MULTILINE)
        if m:
            return m.group(1)
    return None


def find_dualsense_hidraw():
    """/dev/hidrawN for a Bluetooth-connected DualSense/Edge, resolved from
    the kernel's uhid sysfs tree (hid-playstation creates one such node per
    bonded/connected BT device). Only meaningful together with the SAxense
    binary - see _session_bt_direct_audio."""
    for pid in DUALSENSE_PRODUCT_IDS:
        pattern = f"/sys/devices/virtual/misc/uhid/0005:{SONY_VENDOR_ID:04X}:{pid:04X}.*/hidraw/hidraw*"
        matches = glob.glob(pattern)
        if matches:
            return f"/dev/{matches[0].rsplit('/', 1)[-1]}"
    return None


class _AsyncStalePipeWriter:
    """Non-blocking hand-off for writes into a subprocess's stdin pipe (used
    for SAxense's), so a downstream stall in that *subprocess* - not
    anything we control - can't block this session's own tick loop the
    inline `proc.stdin.write(); proc.stdin.flush()` used to.

    SAxense's own write of the finished HID report to the clone's hidraw is
    just as exposed to a congested Bluetooth link as our own real-device
    writes are (see bt_hid_proxy.BtHidProxySession._write_real_async(),
    the original version of this exact pattern) - and when it's blocked
    there, SAxense stops draining its stdin, which backs up the OS pipe
    between us and it, which then blocks *our* write into that pipe once
    it fills. Confirmed on real hardware as a stable (not growing, but not
    recovering either) roughly one-second added lag under sustained
    congestion - one write-into-SAxense's-stdin call taking about that long,
    repeating tick after tick, once SAxense's own downstream write settles
    into that rhythm.

    Same small age-bounded ring buffer as _write_real_async(): depth 3
    absorbs one stuck tick's worth of jitter, and anything older than
    stale_age_s gets skipped in favor of the newest chunk once the writer
    thread is free, instead of working through a backlog in arrival order."""

    def __init__(self, write_fn, depth=3, stale_age_s=0.2):
        self._write_fn = write_fn
        self._stale_age_s = stale_age_s
        self._pending = collections.deque(maxlen=depth)
        self._lock = threading.Lock()
        self._available = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def write(self, data):
        with self._lock:
            self._pending.append((time.monotonic(), data))
        self._available.set()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            if not self._available.wait(timeout=0.2):
                continue
            with self._lock:
                item = self._pending.popleft() if self._pending else None
                if not self._pending:
                    self._available.clear()
            if item is None:
                continue
            enqueued_at, data = item
            if time.monotonic() - enqueued_at > self._stale_age_s:
                continue
            try:
                self._write_fn(data)
            except Exception:
                # Broad on purpose - a stale/closed pipe during teardown can
                # raise more than just OSError (e.g. ValueError on a fd
                # already released), same tolerance as
                # bt_hid_proxy.hidiocgfeature_bounded()'s background thread.
                pass


def _drain_stale_audio(stdout, chunk_bytes):
    """If more than one chunk's worth of audio is already sitting in
    parec's stdout pipe, read and discard the extra so the caller's own
    following read() returns the most recent chunk instead of the oldest
    still-buffered one. A stall anywhere else in a session's tick loop (a
    slow write, a scheduling hiccup, the real device briefly dropping...)
    doesn't pause parec - it keeps writing into this pipe the whole time,
    and the kernel's pipe buffer (64KB by default) doesn't drop anything on
    its own once full. Without this, a session's plain sequential reads
    just keep replaying that backlog forever once behind, one real-time
    chunk per tick, with nothing to ever catch back up: confirmed on real
    hardware as a rock-steady several-second SAxense vibration/LED lag that
    persisted long after whatever caused the original stall had cleared,
    matching almost exactly how many seconds of audio a full 64KB pipe
    holds at BT_RATE's byte rate (this is the audio-input-side counterpart
    to bt_hid_proxy.BtHidProxySession._write_real_async()'s staleness
    handling on the output side - a stall on either side of this session
    can bloat a buffer that nothing else is watching).

    FIONREAD reports what's already buffered without consuming it, so this
    never touches bytes that haven't been written yet - it can't race a
    concurrent parec into blocking on a full pipe.

    Returns the number of bytes actually discarded (0 if none, or if
    FIONREAD itself failed) - callers use this as a direct, non-guessy
    signal that a real stall just happened upstream, as opposed to routine
    single-chunk jitter, to decide whether it's worth respawning parec
    entirely (see PAREC_RESTART_STALL_CHUNKS)."""
    try:
        available = struct.unpack("I", fcntl.ioctl(stdout, termios.FIONREAD, b"\0\0\0\0"))[0]
    except OSError:
        return 0
    extra = (available // chunk_bytes - 1) * chunk_bytes
    if extra > 0:
        os.read(stdout.fileno(), extra)
    return max(extra, 0)


def _spawn_stereo_parec(audio_prefix, rate):
    """Shared by every BT/SAxense session (both use identical parec args) -
    also reused to respawn parec in place after a large stall (see
    PAREC_RESTART_STALL_CHUNKS) without duplicating this call."""
    return subprocess.Popen(
        audio_prefix + ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
                         f"--rate={rate}", "--channels=2", "--raw", "--latency-msec=20"],
        # bufsize=0: an io.BufferedReader on stdout would eagerly pull ahead
        # into its own userspace buffer on .read(), hiding stale audio there
        # where _drain_stale_audio()'s FIONREAD check (which only sees the
        # kernel pipe) can never find it. Unbuffered makes every .read(n) a
        # direct syscall for exactly n bytes, so FIONREAD stays an accurate
        # picture of what's actually backed up.
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )


# A stall big enough to discard this many whole chunks is treated as a real
# disruption (confirmed audible as a click-then-crackle through SAxense's
# literal-PCM motor drive) rather than routine single-chunk scheduling
# jitter, and is worth respawning parec for - a fresh client re-negotiates
# with PipeWire from scratch, in case the stall left the old one in a
# degraded state (e.g. an elevated quantum) that _drain_stale_audio() alone
# can't fix. Only ever replaces the parec subprocess itself: the uhid clone,
# the real device fd and SAxense all live in `session`/`hidraw_file` above
# this loop and are never touched, so Steam never sees the controller itself
# drop - but confirmed on real hardware that the restart still briefly stalls
# the tick loop enough for controller INPUT to visibly drop for a moment, so
# this is gated behind direct_audio.parec_restart_on_stall (opt-in, off by
# default - see DEFAULT_CONFIG and ui.py's checkbox/warning for it).
PAREC_RESTART_STALL_CHUNKS = 4
PAREC_RESTART_COOLDOWN_S = 2.0


def peak(samples):
    if not samples:
        return 0.0
    return max(abs(x) for x in samples) / 32768.0


def lowpass_block(samples, y, cutoff_hz, rate):
    dt = 1.0 / rate
    rc = 1.0 / (2 * math.pi * max(cutoff_hz, 1))
    a = dt / (rc + dt)
    out = [0.0] * len(samples)
    for i, x in enumerate(samples):
        y += a * (x - y)
        out[i] = y
    return y, out


def ceiling_step(level, ceiling, attack_s, release_s, update_hz):
    attack_alpha = 1 - math.exp(-1.0 / (max(attack_s, 1e-3) * update_hz))
    release_alpha = 1 - math.exp(-1.0 / (max(release_s, 1e-3) * update_hz))
    delta = max(0.0, level - ceiling)
    alpha = attack_alpha if level > ceiling else release_alpha
    ceiling += (level - ceiling) * alpha
    return ceiling, delta


def shape(level, env, params):
    k = params["attack"] if level > env else params["release"]
    env = env + (level - env) * k
    lo, hi = params["lo"], params["hi"]
    x = (env - lo) / (hi - lo) if hi > lo else 0.0
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return env, x ** params["gamma"]


class HapticsEngine(threading.Thread):
    """One engine instance = one connect-capture-play session. Call .stop()
    to end it. Reports status strings and live motor levels for a GUI via
    thread-safe queues (queue.Queue, not Qt signals, so this module has no
    GUI dependency)."""

    def __init__(self, config):
        super().__init__(daemon=True, name="HapticsEngine")
        self.config = config
        self.status_queue = queue.Queue()
        self.level_queue = queue.Queue(maxsize=1)
        self.connection_queue = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        # Persists across reconnects - see _session_bt_proxy() and
        # _teardown_bt_proxy_session(). Only ever destroyed (not just
        # detached) when the feature is disabled or the engine stops.
        self._bt_proxy_session = None

    def stop(self):
        self._stop_event.set()

    def _teardown_bt_proxy_session(self):
        if self._bt_proxy_session is None:
            return
        while True:
            try:
                self._bt_proxy_session.destroy()
                break
            except KeyboardInterrupt:
                continue
        self._bt_proxy_session = None

    def _emit_status(self, status):
        self.status_queue.put(status)

    def _emit_levels(self, strong, weak):
        try:
            self.level_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.level_queue.put_nowait((strong, weak))
        except queue.Full:
            pass

    def _emit_connection(self, kind):
        try:
            self.connection_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.connection_queue.put_nowait(kind)
        except queue.Full:
            pass

    def _service_bt_proxy_idle(self, timeout):
        """Waits up to `timeout` seconds, like _stop_event.wait() (which this
        replaces at both call sites in run()), but does two extra things for
        the Bluetooth HID proxy:

        1. Drains the persistent clone's uhid_fd if one exists, so a
           detached clone (real device gone - see
           BtHidProxySession.detach()) doesn't starve and back up the
           kernel's bounded uhid event queue from Steam's own continuing
           writes against a clone it still thinks is present ("Output queue
           is full" in dmesg, confirmed on real hardware).
        2. While the proxy is enabled and not currently attached, polls for
           the real device's sysfs path directly, on a fast ~100ms cadence,
           and attaches (locks it down) the instant it appears - rather than
           waiting for run()'s own find_ff_device() to succeed, which needs
           the real device's evdev interface to finish registering with
           FF_RUMBLE capability and lagged its hidraw registration by
           several seconds on real hardware.
        3. While detached, periodically replays the clone's last known
           INPUT report (see BtHidProxySession.heartbeat_input()) instead of
           sending nothing. Confirmed via Steam's own controller.txt log
           that during a stable, still-attached session Steam never touches
           its open device handle at all, but the moment relay_input()
           traffic stops (a real disconnect) Steam's own hidraw read times
           out ("Controller device closed after hid_read failure").

        Steam's Big Picture/gamescope controller UI can still show a
        duplicate icon with doubled inputs on a live reconnect even with
        all of the above in place and the real device's own hidraw/evdev
        nodes independently confirmed locked the entire time - this
        appears to be Steam's own HIDAPI fork not tracking a stable serial
        for a uhid-backed clone (its own log showed a blank serial_number
        for it, despite the kernel-level HIDIOCGRAWUNIQ reporting the
        correct value), so its device deduplication has nothing reliable
        to key on. Not something fixable from here - see the
        "Decky BT HID proxy dead end" memory note for the full writeup.
        This is why the feature stays desktop-only.

        Returns True if the engine was asked to stop while waiting, matching
        _stop_event.wait()."""
        proxy_cfg = self.config.get("bt_hid_proxy", {})
        want_attach = (proxy_cfg.get("enabled", False)
                       and time.monotonic() >= getattr(self, "_bt_proxy_retry_after", 0.0))
        if want_attach and self._bt_proxy_session is None:
            self._bt_proxy_session = bt_hid_proxy.BtHidProxySession()
        session = self._bt_proxy_session
        if session is None:
            return self._stop_event.wait(timeout)

        deadline = time.monotonic() + timeout
        last_heartbeat = 0.0
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return True
            if (want_attach and session.real_fd is None
                    and bt_hid_proxy.find_real_hid_sys_path(require_driver_bound=False)):
                try:
                    session.attach()
                except bt_hid_proxy.ProxyUnavailable:
                    backoff = getattr(self, "_bt_proxy_backoff", 5)
                    self._bt_proxy_retry_after = time.monotonic() + backoff
                    self._bt_proxy_backoff = min(backoff * 2, 300)
                return False
            now = time.monotonic()
            if session.real_fd is None and session.uhid_fd is not None and now - last_heartbeat > 0.15:
                session.heartbeat_input()
                last_heartbeat = now
            if session.uhid_fd is not None:
                readable, _, _ = select.select([session.uhid_fd], [], [], 0.1)
                # Drain what's queued (bounded - see UHID_MAX_DRAIN_PER_TICK)
                # rather than just one report - confirmed on real hardware
                # that Steam can burst writes against a detached clone it
                # still thinks is present faster than one-per-~100ms-poll
                # can keep up with, overflowing the kernel's bounded uhid
                # queue ("Output queue is full" in dmesg, continuously, for
                # as long as the burst lasts).
                for _ in range(UHID_MAX_DRAIN_PER_TICK):
                    if not readable:
                        break
                    session.relay_output_or_get_report()
                    readable, _, _ = select.select([session.uhid_fd], [], [], 0)
                else:
                    # Still backlogged after a full budget of real hardware
                    # work - see UHID_FAST_DRAIN_CAP.
                    for _ in range(UHID_FAST_DRAIN_CAP):
                        if not readable:
                            break
                        session.relay_output_or_get_report(fast=True)
                        readable, _, _ = select.select([session.uhid_fd], [], [], 0)
            else:
                self._stop_event.wait(0.1)
        return self._stop_event.is_set()

    def run(self):
        while not self._stop_event.is_set():
            dev = find_ff_device()
            if dev is None:
                session = self._bt_proxy_session
                if session is not None and session.real_fd is not None:
                    # The proxy session already attached the real device on
                    # its own (see _service_bt_proxy_idle's fast sysfs-based
                    # polling) - by now its evdev node is locked to 0600 and
                    # this process can't freshly open it either, only the fd
                    # attach() already has. Fall back to the clone's own
                    # evdev interface rather than getting stuck here
                    # indefinitely - see find_clone_ff_device()'s own
                    # comment for why that's a sound substitute.
                    dev = find_clone_ff_device()
            if dev is None:
                self._emit_status("searching")
                self._emit_connection(None)
                if self._service_bt_proxy_idle(2.0):
                    break
                continue
            try:
                self._emit_status("connected")
                self._emit_connection(connection_kind(dev))
                self._session(dev)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._emit_status(f"error: {e}")
                self._emit_connection(None)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            if self._stop_event.is_set():
                break
            self._service_bt_proxy_idle(1.0)
        self._teardown_bt_proxy_session()

    def _session(self, dev):
        """Dispatches to whichever haptics path applies to this connection.
        Direct audio over USB (see find_dualsense_sink()) is tried first
        there. Direct audio over Bluetooth is opt-in and needs the external
        `SAxense` tool (see find_dualsense_hidraw()). Anything else falls
        back to the synthesized-envelope/FF_RUMBLE path."""
        kind = connection_kind(dev)
        proxy_cfg = self.config.get("bt_hid_proxy", {})
        if not proxy_cfg.get("enabled", False):
            # Turning the feature off is the one case that should actually
            # remove the clone (see BtHidProxySession.destroy()) - unlike a
            # routine disconnect, there's no future reconnect coming that
            # would benefit from keeping it alive.
            self._teardown_bt_proxy_session()
        now = time.monotonic()
        if (kind == "bluetooth" and proxy_cfg.get("enabled", False)
                and now >= getattr(self, "_bt_proxy_retry_after", 0.0)):
            self._session_bt_proxy(dev)
            return
        self._session_fallback(dev, kind)

    def _bt_proxy_should_retry(self, kind):
        """True once it's worth breaking out of a fallback session (BT
        direct-audio/SAxense or plain FF_RUMBLE) to let _session() redispatch
        and try the Bluetooth HID proxy again - a failed proxy attempt
        otherwise means the fallback session (which has no reason on its own
        to ever re-check) sticks around for the entire rest of that
        connection. Uses the same exponential-backoff deadline
        _session_bt_proxy sets on failure, so a persistently broken install
        settles into long, infrequent retries instead of repeatedly forcing
        the controller's evdev handle to close/reopen (each retry attempt
        does that, however it turns out) - confirmed on real hardware that a
        fixed short cooldown against a genuinely persistent failure caused
        visible, repeated input drops, which is worse than just staying in
        the fallback session quietly."""
        return (kind == "bluetooth" and self.config.get("bt_hid_proxy", {}).get("enabled", False)
                and time.monotonic() >= getattr(self, "_bt_proxy_retry_after", 0.0))

    def _session_fallback(self, dev, kind):
        """Everything except the Bluetooth HID proxy: USB/BT direct-audio if
        applicable, else the synthesized-envelope/FF_RUMBLE path. Also used
        by _session_bt_proxy when the proxy itself can't be set up, so a
        failed proxy attempt degrades through the user's other preferences
        (e.g. BT direct-audio/SAxense) instead of jumping straight to plain
        FF_RUMBLE and silently ignoring them."""
        direct_cfg = self.config.get("direct_audio", {})
        if kind == "usb" and direct_cfg.get("enabled", True):
            sink = find_dualsense_sink()
            if sink:
                self._session_direct_audio(dev, sink)
                return
        elif kind == "bluetooth" and direct_cfg.get("enabled", True) and direct_cfg.get("bt_enabled", False):
            hidraw = find_dualsense_hidraw()
            if hidraw and shutil.which("SAxense"):
                self._session_bt_direct_audio(dev, hidraw)
                return
        self._session_ff(dev)

    def _session_direct_audio(self, dev, sink):
        """USB only: streams live system audio as literal PCM straight onto
        the two motors (see find_dualsense_sink()) instead of synthesizing an
        envelope for FF_RUMBLE - the same trick DSX uses on Windows and the
        PS5 itself uses internally. Deliberately sends zero FF traffic while
        this runs: a concurrent FF_RUMBLE write fights the kernel driver for
        control of the controller's audio-routing state and silences this
        path entirely (confirmed against real hardware), so button haptics
        are reproduced here as a synthesized click mixed into the outgoing
        PCM instead of a separate FF effect."""
        rate = RATE_DIRECT
        chunk_samples = CHUNK_SAMPLES_DIRECT
        stereo_bytes = chunk_samples * 2 * 2
        stereo_fmt = f"<{chunk_samples * 2}h"
        quad_fmt = f"<{chunk_samples * 4}h"

        audio_prefix = _audio_subprocess_prefix()
        parec = subprocess.Popen(
            audio_prefix + ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
                             f"--rate={rate}", "--channels=2", "--raw", "--latency-msec=20"],
            # bufsize=0: an io.BufferedReader on stdout would eagerly pull
            # ahead into its own userspace buffer on .read(), hiding stale
            # audio there where _drain_stale_audio()'s FIONREAD check (which
            # only sees the kernel pipe) can never find it. Unbuffered makes
            # every .read(n) a direct syscall for exactly n bytes, so
            # FIONREAD stays an accurate picture of what's actually backed up.
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        paplay = subprocess.Popen(
            audio_prefix + ["paplay", "--raw", f"--rate={rate}", "--format=s16le", "--channels=4",
                             "--channel-map=front-left,front-right,rear-left,rear-right", f"--device={sink}"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        left_y = right_y = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        analog_raw, analog_axis_info = _init_analog_raw(dev)
        strong_phase = weak_phase = 0.0

        try:
            while not self._stop_event.is_set():
                _drain_stale_audio(parec.stdout, stereo_bytes)
                data = parec.stdout.read(stereo_bytes)
                if len(data) < stereo_bytes:
                    if parec.poll() is not None:
                        raise RuntimeError("audio capture (parec) exited")
                    continue
                if paplay.poll() is not None:
                    raise RuntimeError("audio playback (paplay) exited")

                cfg = self.config
                direct_cfg = cfg.get("direct_audio", {})
                gain = direct_cfg.get("gain", 3.0)
                cutoff_hz = direct_cfg.get("cutoff_hz", 500)

                while True:
                    ev = dev.read_one()
                    if ev is None:
                        break
                    if ev.type == ecodes.EV_KEY:
                        held_keys[ev.code] = ev.value != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                        if ev.code == ecodes.ABS_HAT0X:
                            hat_x = ev.value
                        else:
                            hat_y = ev.value
                        held_keys[DPAD_VIRTUAL_CODE] = hat_x != 0 or hat_y != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in analog_raw:
                        analog_raw[ev.code] = ev.value

                analog_scale = _analog_held_scale(analog_raw, analog_axis_info)
                for _code, _mag in analog_scale.items():
                    held_keys[_code] = _mag > 0

                samples = struct.unpack(stereo_fmt, data)
                left_in = [s / 32768.0 for s in samples[0::2]]
                right_in = [s / 32768.0 for s in samples[1::2]]
                left_y, left = lowpass_block(left_in, left_y, cutoff_hz, rate)
                right_y, right = lowpass_block(right_in, right_y, cutoff_hz, rate)

                # Same per-side button feedback as the FF path (BUTTON_SIDE),
                # just mixed in as a short tone instead of an FF magnitude.
                button_strong_target, button_strong_hz, button_weak_target, button_weak_hz = \
                    _button_click_targets(cfg, held_keys, BUTTON_CLICK_HZ, analog_scale)
                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)
                strong_phase_step = 2 * math.pi * button_strong_hz / rate
                weak_phase_step = 2 * math.pi * button_weak_hz / rate

                frame = [0] * (chunk_samples * 4)
                peak_left = peak_right = 0.0
                for i in range(chunk_samples):
                    l = left[i] * gain
                    r = right[i] * gain
                    strong_click = math.sin(strong_phase)
                    weak_click = math.sin(weak_phase)
                    strong_phase += strong_phase_step
                    weak_phase += weak_phase_step
                    if button_strong_env > 0.001:
                        l += strong_click * button_strong_env
                    if button_weak_env > 0.001:
                        r += weak_click * button_weak_env
                    l = math.tanh(l)
                    r = math.tanh(r)
                    peak_left = max(peak_left, abs(l))
                    peak_right = max(peak_right, abs(r))
                    frame[i * 4 + 2] = int(l * 32767)
                    frame[i * 4 + 3] = int(r * 32767)
                strong_phase = math.fmod(strong_phase, 2 * math.pi)
                weak_phase = math.fmod(weak_phase, 2 * math.pi)

                paplay.stdin.write(struct.pack(quad_fmt, *frame))
                paplay.stdin.flush()
                self._emit_levels(peak_left, peak_right)
        finally:
            try:
                paplay.stdin.close()
            except Exception:
                pass
            for proc in (parec, paplay):
                try:
                    proc.terminate()
                except Exception:
                    pass
            for proc in (parec, paplay):
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass

    def _session_bt_direct_audio(self, dev, hidraw_path):
        """Bluetooth, opt-in (direct_audio.bt_enabled): the same idea as
        _session_direct_audio, but over a community-reverse-engineered BT
        HID haptics protocol instead of a USB Audio Class interface, via the
        external `SAxense` tool (https://github.com/egormanga/SAxense -
        research and protocol credit: egormanga/Sdore). Confirmed against
        real hardware to keep the same per-motor precision as the USB path
        despite the much lower bitrate (8-bit, combined 3kHz). SAxense paces
        and formats the actual HID reports itself; this just feeds it gain-
        staged PCM and points its output straight at the hidraw device."""
        rate = BT_RATE
        # Fixed for this session's lifetime (reread on the next reconnect,
        # like `rate` above) - the read buffer sizes/formats below are
        # derived from it once, not something to recompute mid-stream.
        chunk_ms = max(BT_CHUNK_MS_MIN, min(BT_CHUNK_MS_MAX,
                        self.config.get("direct_audio", {}).get("bt_chunk_ms", BT_CHUNK_MS)))
        chunk_samples = rate * chunk_ms // 1000
        stereo_bytes = chunk_samples * 2 * 2
        stereo_fmt = f"<{chunk_samples * 2}h"

        # os.open with plain O_WRONLY (not the "wb"-mode open(), which
        # implies O_CREAT) - never silently create a regular file if this
        # path doesn't exist yet, which would permanently shadow the real
        # hidraw device the kernel registers moments later. See
        # bt_hid_proxy.find_clone_hidraw_path()'s own comment on this race.
        hidraw_file = os.fdopen(os.open(hidraw_path, os.O_WRONLY), "wb", buffering=0)
        audio_prefix = _audio_subprocess_prefix()
        parec = _spawn_stereo_parec(audio_prefix, rate)
        saxense = subprocess.Popen(
            ["SAxense"], stdin=subprocess.PIPE, stdout=hidraw_file, stderr=subprocess.DEVNULL,
        )
        last_parec_restart = 0.0

        def _write_saxense_stdin(data):
            saxense.stdin.write(data)
            saxense.stdin.flush()
        saxense_writer = _AsyncStalePipeWriter(_write_saxense_stdin)

        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        analog_raw, analog_axis_info = _init_analog_raw(dev)
        strong_phase = weak_phase = 0.0
        # Immersive Lighting only - see _run_bt_proxy_saxense's identical
        # block for the full rationale (this path has no existing band-split
        # either, SAxense drives the motors from literal PCM). Uses the
        # sysfs LED path (find_led_paths()/write_led_sysfs()) rather than a
        # proxy session, same as _session_ff, since this session runs with
        # no Bluetooth HID Proxy in the picture at all.
        led_bass_y = led_treble_y = led_mid_y = 0.0
        led_bass_ceil = led_treble_ceil = led_mid_ceil = 0.0
        led_bass_env = led_treble_env = led_mid_env = 0.0
        led_bass_smooth = led_mid_smooth = led_treble_smooth = 0.0
        led_update_hz = 1000.0 / chunk_ms
        lightbar_path, player_led_paths = find_led_paths(dev)
        led_last_write = 0.0

        try:
            while not self._stop_event.is_set() and not self._bt_proxy_should_retry("bluetooth"):
                dropped = _drain_stale_audio(parec.stdout, stereo_bytes)
                now = time.monotonic()
                if (self.config.get("direct_audio", {}).get("parec_restart_on_stall", False)
                        and dropped >= PAREC_RESTART_STALL_CHUNKS * stereo_bytes
                        and now - last_parec_restart > PAREC_RESTART_COOLDOWN_S):
                    parec.terminate()
                    parec.wait()
                    parec = _spawn_stereo_parec(audio_prefix, rate)
                    last_parec_restart = now
                data = parec.stdout.read(stereo_bytes)
                if len(data) < stereo_bytes:
                    if parec.poll() is not None:
                        raise RuntimeError("audio capture (parec) exited")
                    continue
                if saxense.poll() is not None:
                    raise RuntimeError("SAxense exited")

                cfg = self.config
                gain = cfg.get("direct_audio", {}).get("gain", 5.0)

                while True:
                    ev = dev.read_one()
                    if ev is None:
                        break
                    if ev.type == ecodes.EV_KEY:
                        held_keys[ev.code] = ev.value != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                        if ev.code == ecodes.ABS_HAT0X:
                            hat_x = ev.value
                        else:
                            hat_y = ev.value
                        held_keys[DPAD_VIRTUAL_CODE] = hat_x != 0 or hat_y != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in analog_raw:
                        analog_raw[ev.code] = ev.value

                analog_scale = _analog_held_scale(analog_raw, analog_axis_info)
                for _code, _mag in analog_scale.items():
                    held_keys[_code] = _mag > 0

                samples = struct.unpack(stereo_fmt, data)
                left_in = samples[0::2]
                right_in = samples[1::2]

                led_on = cfg.get("led_visualizer", {}).get("enabled", False)
                led_bass_mag = led_mid_mag = led_treble_mag = 0.0
                if led_on:
                    # Raw int16-scale, not normalized - see
                    # _run_bt_proxy_saxense's identical block for why
                    # (lowpass_block()/peak() normalize internally; doing it
                    # here too would double-normalize and crush every band
                    # to ~0).
                    left_norm = [s * gain for s in left_in]
                    right_norm = [s * gain for s in right_in]
                    led_bass_y, led_bass_band = lowpass_block(left_norm, led_bass_y, cfg["bass_cutoff_hz"], rate)
                    led_treble_y, led_treble_ref = lowpass_block(right_norm, led_treble_y, cfg["treble_cutoff_hz"], rate)
                    led_treble_band = [r - t for r, t in zip(right_norm, led_treble_ref)]
                    led_mid_y, led_mid_lp = lowpass_block(right_norm, led_mid_y, cfg["bass_cutoff_hz"], rate)
                    led_mid_band = [t - m for t, m in zip(led_treble_ref, led_mid_lp)]

                    led_bass_ceil, led_bass_delta = ceiling_step(
                        peak(led_bass_band), led_bass_ceil,
                        cfg["bass_ceiling"]["attack_s"], cfg["bass_ceiling"]["release_s"], led_update_hz)
                    led_treble_ceil, led_treble_delta = ceiling_step(
                        peak(led_treble_band), led_treble_ceil,
                        cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], led_update_hz)
                    led_mid_ceil, led_mid_delta = ceiling_step(
                        peak(led_mid_band), led_mid_ceil,
                        cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], led_update_hz)

                    led_bass_env, led_bass_mag = shape(led_bass_delta, led_bass_env, cfg["bass"])
                    led_treble_env, led_treble_mag = shape(led_treble_delta, led_treble_env, cfg["treble"])
                    led_mid_env, led_mid_mag = shape(led_mid_delta, led_mid_env, cfg["treble"])
                    led_gain = cfg["master_gain"]
                    led_bass_mag = min(1.0, led_bass_mag * led_gain)
                    led_mid_mag = min(1.0, led_mid_mag * led_gain)
                    led_treble_mag = min(1.0, led_treble_mag * led_gain)

                button_strong_target, button_strong_hz, button_weak_target, button_weak_hz = \
                    _button_click_targets(cfg, held_keys, BT_BUTTON_CLICK_HZ, analog_scale)
                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)
                strong_phase_step = 2 * math.pi * button_strong_hz / rate
                weak_phase_step = 2 * math.pi * button_weak_hz / rate

                if led_on:
                    led_cfg = cfg.get("led_visualizer", {})
                    att, rel, gam = led_cfg.get("attack", 0.5), led_cfg.get("release", 0.08), led_cfg.get("gamma", 1.8)
                    led_bass_smooth, led_bass_out = _led_smooth(led_bass_mag, led_bass_smooth, att, rel, gam)
                    led_mid_smooth, led_mid_out = _led_smooth(led_mid_mag, led_mid_smooth, att, rel, gam)
                    led_treble_smooth, led_treble_out = _led_smooth(led_treble_mag, led_treble_smooth, att, rel, gam)
                    now = time.monotonic()
                    if now - led_last_write > LED_WRITE_INTERVAL_S:
                        led_last_write = now
                        write_led_sysfs(lightbar_path, player_led_paths,
                                         (led_bass_out, led_mid_out, led_treble_out, led_cfg.get("bass_priority", 0.6)))

                out = bytearray(chunk_samples * 2)
                peak_left = peak_right = 0.0
                for i in range(chunk_samples):
                    l = (left_in[i] / 32768.0) * gain
                    r = (right_in[i] / 32768.0) * gain
                    strong_click = math.sin(strong_phase)
                    weak_click = math.sin(weak_phase)
                    strong_phase += strong_phase_step
                    weak_phase += weak_phase_step
                    if button_strong_env > 0.001:
                        l += strong_click * button_strong_env
                    if button_weak_env > 0.001:
                        r += weak_click * button_weak_env
                    l = math.tanh(l)
                    r = math.tanh(r)
                    peak_left = max(peak_left, abs(l))
                    peak_right = max(peak_right, abs(r))
                    out[i * 2] = int(l * 127) & 0xFF
                    out[i * 2 + 1] = int(r * 127) & 0xFF
                strong_phase = math.fmod(strong_phase, 2 * math.pi)
                weak_phase = math.fmod(weak_phase, 2 * math.pi)

                saxense_writer.write(bytes(out))
                self._emit_levels(peak_left, peak_right)
        finally:
            saxense_writer.stop()
            try:
                saxense.stdin.close()
            except Exception:
                pass
            for proc in (parec, saxense):
                try:
                    proc.terminate()
                except Exception:
                    pass
            for proc in (parec, saxense):
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
            try:
                hidraw_file.close()
            except Exception:
                pass

    def _session_bt_proxy(self, dev):
        """Bluetooth only: clones the controller via /dev/uhid, hides the real
        device from everyone else (Steam included), relays its input/feature
        reports transparently, and keeps Steam's cached trigger/lightbar
        writes flowing to the real hardware while our own audio-reactive
        haptics run alongside instead of racing it for the wire - see
        bt_hid_proxy.py. Falls back through _session_fallback (BT direct-
        audio/SAxense if the user has that enabled too, else plain
        FF_RUMBLE) for this connection if the proxy can't be set up (missing
        helper/udev rule, /dev/uhid inaccessible), with an exponentially
        backed-off cooldown before retrying (5s, 10s, 20s, ... capped at 5
        minutes, reset to 5s on the next success): each retry attempt closes
        and reopens the controller's evdev handle regardless of outcome, and
        confirmed on real hardware that a fixed short cooldown against a
        genuinely persistent failure (as opposed to a brief one) caused
        visible, repeated input drops - worse than just settling into the
        fallback session quietly until something actually changes.

        The clone itself outlives any single call to this method - see
        self._bt_proxy_session/BtHidProxySession.attach()/detach(). Only
        the real-device side is torn down when this connection ends;
        Steam never sees the clone disappear and reappear on a routine
        reconnect."""
        if self._bt_proxy_session is None:
            self._bt_proxy_session = bt_hid_proxy.BtHidProxySession()
        session = self._bt_proxy_session
        try:
            session.attach()
        except bt_hid_proxy.ProxyUnavailable:
            self._emit_status("bt_proxy_unavailable")
            backoff = getattr(self, "_bt_proxy_backoff", 5)
            self._bt_proxy_retry_after = time.monotonic() + backoff
            self._bt_proxy_backoff = min(backoff * 2, 300)
            self._session_fallback(dev, "bluetooth")
            return
        self._bt_proxy_backoff = 5

        try:
            direct_cfg = self.config.get("direct_audio", {})
            clone_hidraw = None
            if direct_cfg.get("enabled", True) and direct_cfg.get("bt_enabled", False) and shutil.which("SAxense"):
                clone_hidraw = bt_hid_proxy.find_clone_hidraw_path()
            if clone_hidraw:
                self._run_bt_proxy_saxense(session, dev, clone_hidraw)
            else:
                self._run_bt_proxy_envelope(session, dev)
        finally:
            session.detach()

    def _run_bt_proxy_envelope(self, session, dev):
        """Synthesized-envelope rumble through the proxy - structurally a
        copy of _session_ff (same parec spawn, same bass/treble/button DSP),
        swapping the FF_RUMBLE write for the proxy's relay+merge each tick."""
        proc = subprocess.Popen(
            _audio_subprocess_prefix() +
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={RATE}", f"--channels={CHANNELS}", "--raw", "--latency-msec=20"],
            # bufsize=0 - see the other parec spawns' identical comment.
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )

        bass_y = treble_y = 0.0
        bass_ceil = treble_ceil = 0.0
        strong_env = weak_env = 0.0
        # Mid-band, for the Immersive Lighting visualizer only (see
        # bt_hid_proxy.apply_led_visualizer()) - no third motor exists to
        # drive with it. Isolated from the same right channel treble already
        # reads (mid_lp is a second, independent lowpass accumulator at
        # bass_cutoff_hz; subtracting it from the already-computed
        # treble_ref - itself a lowpass at treble_cutoff_hz - leaves exactly
        # the band between the two cutoffs, the classic difference-of-
        # lowpasses bandpass). Reuses the treble band's own shape/ceiling
        # tuning rather than exposing a whole separate set of sliders for a
        # cosmetic-only signal.
        mid_y = 0.0
        mid_ceil = 0.0
        mid_env = 0.0
        led_bass_smooth = led_mid_smooth = led_treble_smooth = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        analog_raw, analog_axis_info = _init_analog_raw(dev)
        update_hz = 1000.0 / CHUNK_MS
        fmt = f"<{CHUNK_SAMPLES * CHANNELS}h"
        last_status_emit = 0.0

        try:
            while not self._stop_event.is_set() and self.config.get("bt_hid_proxy", {}).get("enabled", False):
                readable, _, _ = select.select(
                    [session.real_fd, session.uhid_fd, proc.stdout], [], [], 0.02)

                if proc.stdout in readable:
                    _drain_stale_audio(proc.stdout, CHUNK_BYTES)
                    data = proc.stdout.read(CHUNK_BYTES)
                    if len(data) < CHUNK_BYTES:
                        if proc.poll() is not None:
                            raise RuntimeError("audio capture (parec) exited")
                    else:
                        cfg = self.config

                        while True:
                            ev = dev.read_one()
                            if ev is None:
                                break
                            if ev.type == ecodes.EV_KEY:
                                held_keys[ev.code] = ev.value != 0
                            elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                                if ev.code == ecodes.ABS_HAT0X:
                                    hat_x = ev.value
                                else:
                                    hat_y = ev.value
                                held_keys[DPAD_VIRTUAL_CODE] = hat_x != 0 or hat_y != 0
                            elif ev.type == ecodes.EV_ABS and ev.code in analog_raw:
                                analog_raw[ev.code] = ev.value

                        analog_scale = _analog_held_scale(analog_raw, analog_axis_info)
                        for _code, _mag in analog_scale.items():
                            held_keys[_code] = _mag > 0

                        samples = struct.unpack(fmt, data)
                        left = samples[0::2]
                        right = samples[1::2]

                        bass_y, bass_band = lowpass_block(left, bass_y, cfg["bass_cutoff_hz"], RATE)
                        treble_y, treble_ref = lowpass_block(right, treble_y, cfg["treble_cutoff_hz"], RATE)
                        treble_band = [r - t for r, t in zip(right, treble_ref)]

                        led_on = cfg.get("led_visualizer", {}).get("enabled", False)
                        mid_mag = 0.0
                        if led_on:
                            mid_y, mid_lp = lowpass_block(right, mid_y, cfg["bass_cutoff_hz"], RATE)
                            mid_band = [t - m for t, m in zip(treble_ref, mid_lp)]
                            mid_ceil, mid_delta = ceiling_step(
                                peak(mid_band), mid_ceil,
                                cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], update_hz)
                            mid_env, mid_mag = shape(mid_delta, mid_env, cfg["treble"])
                            mid_mag = min(1.0, mid_mag * cfg["master_gain"])

                        bass_ceil, bass_delta = ceiling_step(
                            peak(bass_band), bass_ceil,
                            cfg["bass_ceiling"]["attack_s"], cfg["bass_ceiling"]["release_s"], update_hz)
                        treble_ceil, treble_delta = ceiling_step(
                            peak(treble_band), treble_ceil,
                            cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], update_hz)

                        strong_env, strong_mag = shape(bass_delta, strong_env, cfg["bass"])
                        weak_env, weak_mag = shape(treble_delta, weak_env, cfg["treble"])

                        gain = cfg["master_gain"]
                        strong_mag = min(1.0, strong_mag * gain)
                        weak_mag = min(1.0, weak_mag * gain)

                        button_strong_target, _, button_weak_target, _ = \
                            _button_click_targets(cfg, held_keys, BUTTON_CLICK_HZ, analog_scale)

                        button_strong_env += (button_strong_target - button_strong_env) * (
                            BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                        button_weak_env += (button_weak_target - button_weak_env) * (
                            BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                        strong_mag = min(1.0, strong_mag + button_strong_env)
                        weak_mag = min(1.0, weak_mag + button_weak_env)

                        led = None
                        if led_on:
                            led_cfg = cfg.get("led_visualizer", {})
                            att, rel, gam = led_cfg.get("attack", 0.5), led_cfg.get("release", 0.08), led_cfg.get("gamma", 1.8)
                            led_bass_smooth, led_bass_out = _led_smooth(strong_mag, led_bass_smooth, att, rel, gam)
                            led_mid_smooth, led_mid_out = _led_smooth(mid_mag, led_mid_smooth, att, rel, gam)
                            led_treble_smooth, led_treble_out = _led_smooth(weak_mag, led_treble_smooth, att, rel, gam)
                            led = (led_bass_out, led_mid_out, led_treble_out, led_cfg.get("bass_priority", 0.6))
                        session.write_rumble(strong_mag, weak_mag, led)
                        self._emit_levels(strong_mag, weak_mag)

                if session.real_fd in readable:
                    session.relay_input()
                if session.uhid_fd in readable:
                    # Drain what's queued (bounded - see
                    # UHID_MAX_DRAIN_PER_TICK) rather than just this one
                    # readable notification - see _service_bt_proxy_idle's
                    # identical comment on why a burst can otherwise overflow
                    # the kernel's bounded uhid queue faster than one-per-
                    # tick keeps up with, and why draining unboundedly here
                    # specifically caused Steam-visible disconnects (starves
                    # relay_input() above under a sustained, not just
                    # bursty, write rate).
                    for _ in range(UHID_MAX_DRAIN_PER_TICK):
                        session.relay_output_or_get_report()
                        more, _, _ = select.select([session.uhid_fd], [], [], 0)
                        if not more:
                            break
                    else:
                        # Still backlogged after a full budget of real
                        # hardware work - see UHID_FAST_DRAIN_CAP.
                        for _ in range(UHID_FAST_DRAIN_CAP):
                            session.relay_output_or_get_report(fast=True)
                            more, _, _ = select.select([session.uhid_fd], [], [], 0)
                            if not more:
                                break

                now = time.monotonic()
                if now - last_status_emit > 1.5:
                    last_status_emit = now
                    self._emit_status("proxied")
        finally:
            proc.terminate()
            proc.wait()

    def _run_bt_proxy_saxense(self, session, dev, clone_hidraw):
        """Literal-PCM rumble through the proxy, same technique as
        _session_bt_direct_audio (see there for the DSP/protocol rationale),
        but pointed at the clone's hidraw instead of the real device's:
        SAxense writes a distinct HID report (id 0x32, 141 bytes - see
        SAxense.c) that never overlaps with the 0x31 report triggers/
        lightbar/rumble live on, so BtHidProxySession's relay passes it
        straight through to real hardware untouched once it arrives via the
        clone. Steam's cached trigger effect is kept alive separately via
        forward_trigger_only(), which - confirmed on real hardware - must
        NOT also re-broadcast the game's cached rumble/HAPTICS_SELECT state:
        doing so raced SAxense's own report for control of the motors and
        drowned it out, even though they're technically distinct report IDs."""
        rate = BT_RATE
        # See _session_bt_direct_audio's identical line for why this is
        # fixed for the session's lifetime rather than reread per tick.
        chunk_ms = max(BT_CHUNK_MS_MIN, min(BT_CHUNK_MS_MAX,
                        self.config.get("direct_audio", {}).get("bt_chunk_ms", BT_CHUNK_MS)))
        chunk_samples = rate * chunk_ms // 1000
        stereo_bytes = chunk_samples * 2 * 2
        stereo_fmt = f"<{chunk_samples * 2}h"

        hidraw_file = os.fdopen(os.open(clone_hidraw, os.O_WRONLY), "wb", buffering=0)
        audio_prefix = _audio_subprocess_prefix()
        parec = _spawn_stereo_parec(audio_prefix, rate)
        saxense = subprocess.Popen(
            ["SAxense"], stdin=subprocess.PIPE, stdout=hidraw_file, stderr=subprocess.DEVNULL,
        )
        last_parec_restart = 0.0

        def _write_saxense_stdin(data):
            saxense.stdin.write(data)
            saxense.stdin.flush()
        saxense_writer = _AsyncStalePipeWriter(_write_saxense_stdin)

        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        analog_raw, analog_axis_info = _init_analog_raw(dev)
        strong_phase = weak_phase = 0.0
        last_status_emit = 0.0
        # Immersive Lighting only - this path has no existing band-split
        # (SAxense drives the motors from literal PCM, not a synthesized
        # envelope), so this replicates _run_bt_proxy_envelope's own
        # bass/mid/treble split and shaping purely for the LED's sake, gated
        # behind led_on below so it costs nothing when the feature is off.
        led_bass_y = led_treble_y = led_mid_y = 0.0
        led_bass_ceil = led_treble_ceil = led_mid_ceil = 0.0
        led_bass_env = led_treble_env = led_mid_env = 0.0
        led_bass_smooth = led_mid_smooth = led_treble_smooth = 0.0
        led_update_hz = 1000.0 / chunk_ms
        led_last_write = 0.0

        try:
            while not self._stop_event.is_set() and self.config.get("bt_hid_proxy", {}).get("enabled", False):
                readable, _, _ = select.select(
                    [session.real_fd, session.uhid_fd, parec.stdout], [], [], 0.02)

                if parec.stdout in readable:
                    dropped = _drain_stale_audio(parec.stdout, stereo_bytes)
                    now = time.monotonic()
                    if (self.config.get("direct_audio", {}).get("parec_restart_on_stall", False)
                            and dropped >= PAREC_RESTART_STALL_CHUNKS * stereo_bytes
                            and now - last_parec_restart > PAREC_RESTART_COOLDOWN_S):
                        parec.terminate()
                        parec.wait()
                        parec = _spawn_stereo_parec(audio_prefix, rate)
                        last_parec_restart = now
                    data = parec.stdout.read(stereo_bytes)
                    if len(data) < stereo_bytes:
                        if parec.poll() is not None:
                            raise RuntimeError("audio capture (parec) exited")
                    else:
                        if saxense.poll() is not None:
                            raise RuntimeError("SAxense exited")

                        cfg = self.config
                        gain = cfg.get("direct_audio", {}).get("gain", 5.0)

                        while True:
                            ev = dev.read_one()
                            if ev is None:
                                break
                            if ev.type == ecodes.EV_KEY:
                                held_keys[ev.code] = ev.value != 0
                            elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                                if ev.code == ecodes.ABS_HAT0X:
                                    hat_x = ev.value
                                else:
                                    hat_y = ev.value
                                held_keys[DPAD_VIRTUAL_CODE] = hat_x != 0 or hat_y != 0
                            elif ev.type == ecodes.EV_ABS and ev.code in analog_raw:
                                analog_raw[ev.code] = ev.value

                        analog_scale = _analog_held_scale(analog_raw, analog_axis_info)
                        for _code, _mag in analog_scale.items():
                            held_keys[_code] = _mag > 0

                        samples = struct.unpack(stereo_fmt, data)
                        left_in = samples[0::2]
                        right_in = samples[1::2]

                        led_on = cfg.get("led_visualizer", {}).get("enabled", False)
                        led_bass_mag = led_mid_mag = led_treble_mag = 0.0
                        if led_on:
                            # Deliberately NOT normalized to -1..1 here -
                            # lowpass_block()/peak() (see _run_bt_proxy_
                            # envelope's identical bass/treble computation)
                            # expect raw int16-scale samples and normalize
                            # internally via peak()'s own /32768.0; doing it
                            # here too would double-normalize and crush
                            # every band to ~0. `gain` (direct_audio's own,
                            # already used below for the literal-PCM motor
                            # signal) is still applied directly to the raw
                            # samples so the LED reacts at a comparable
                            # loudness to what's actually driving the
                            # motors, instead of using _run_bt_proxy_
                            # envelope's un-gained raw scale as-is.
                            left_norm = [s * gain for s in left_in]
                            right_norm = [s * gain for s in right_in]
                            led_bass_y, led_bass_band = lowpass_block(left_norm, led_bass_y, cfg["bass_cutoff_hz"], rate)
                            led_treble_y, led_treble_ref = lowpass_block(right_norm, led_treble_y, cfg["treble_cutoff_hz"], rate)
                            led_treble_band = [r - t for r, t in zip(right_norm, led_treble_ref)]
                            led_mid_y, led_mid_lp = lowpass_block(right_norm, led_mid_y, cfg["bass_cutoff_hz"], rate)
                            led_mid_band = [t - m for t, m in zip(led_treble_ref, led_mid_lp)]

                            led_bass_ceil, led_bass_delta = ceiling_step(
                                peak(led_bass_band), led_bass_ceil,
                                cfg["bass_ceiling"]["attack_s"], cfg["bass_ceiling"]["release_s"], led_update_hz)
                            led_treble_ceil, led_treble_delta = ceiling_step(
                                peak(led_treble_band), led_treble_ceil,
                                cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], led_update_hz)
                            led_mid_ceil, led_mid_delta = ceiling_step(
                                peak(led_mid_band), led_mid_ceil,
                                cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], led_update_hz)

                            led_bass_env, led_bass_mag = shape(led_bass_delta, led_bass_env, cfg["bass"])
                            led_treble_env, led_treble_mag = shape(led_treble_delta, led_treble_env, cfg["treble"])
                            led_mid_env, led_mid_mag = shape(led_mid_delta, led_mid_env, cfg["treble"])
                            led_gain = cfg["master_gain"]
                            led_bass_mag = min(1.0, led_bass_mag * led_gain)
                            led_mid_mag = min(1.0, led_mid_mag * led_gain)
                            led_treble_mag = min(1.0, led_treble_mag * led_gain)

                        button_strong_target, button_strong_hz, button_weak_target, button_weak_hz = \
                            _button_click_targets(cfg, held_keys, BT_BUTTON_CLICK_HZ, analog_scale)
                        button_strong_env += (button_strong_target - button_strong_env) * (
                            BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                        button_weak_env += (button_weak_target - button_weak_env) * (
                            BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)
                        strong_phase_step = 2 * math.pi * button_strong_hz / rate
                        weak_phase_step = 2 * math.pi * button_weak_hz / rate

                        out = bytearray(chunk_samples * 2)
                        peak_left = peak_right = 0.0
                        for i in range(chunk_samples):
                            l = (left_in[i] / 32768.0) * gain
                            r = (right_in[i] / 32768.0) * gain
                            strong_click = math.sin(strong_phase)
                            weak_click = math.sin(weak_phase)
                            strong_phase += strong_phase_step
                            weak_phase += weak_phase_step
                            if button_strong_env > 0.001:
                                l += strong_click * button_strong_env
                            if button_weak_env > 0.001:
                                r += weak_click * button_weak_env
                            l = math.tanh(l)
                            r = math.tanh(r)
                            peak_left = max(peak_left, abs(l))
                            peak_right = max(peak_right, abs(r))
                            out[i * 2] = int(l * 127) & 0xFF
                            out[i * 2 + 1] = int(r * 127) & 0xFF
                        strong_phase = math.fmod(strong_phase, 2 * math.pi)
                        weak_phase = math.fmod(weak_phase, 2 * math.pi)

                        saxense_writer.write(bytes(out))
                        led = None
                        if led_on:
                            led_cfg = cfg.get("led_visualizer", {})
                            att, rel, gam = led_cfg.get("attack", 0.5), led_cfg.get("release", 0.08), led_cfg.get("gamma", 1.8)
                            led_bass_smooth, led_bass_out = _led_smooth(led_bass_mag, led_bass_smooth, att, rel, gam)
                            led_mid_smooth, led_mid_out = _led_smooth(led_mid_mag, led_mid_smooth, att, rel, gam)
                            led_treble_smooth, led_treble_out = _led_smooth(led_treble_mag, led_treble_smooth, att, rel, gam)
                            led = (led_bass_out, led_mid_out, led_treble_out, led_cfg.get("bass_priority", 0.6))
                            # forward_trigger_only()'s own dedup only helps
                            # once a color stops changing (silence, held
                            # notes) - while music is actively playing the
                            # LED output changes on nearly every tick, so it
                            # doesn't reduce the extra Bluetooth traffic this
                            # report rides on top of SAxense's own stream
                            # when it matters most. Same time throttle as
                            # write_led_sysfs() (see LED_WRITE_INTERVAL_S) -
                            # already confirmed imperceptible there since
                            # _led_smooth()'s own envelope is what produces
                            # the visible motion, not the raw write rate.
                            now = time.monotonic()
                            if now - led_last_write > LED_WRITE_INTERVAL_S:
                                led_last_write = now
                                session.forward_trigger_only(led)
                        else:
                            session.forward_trigger_only(led)
                        self._emit_levels(peak_left, peak_right)

                if session.real_fd in readable:
                    session.relay_input()
                if session.uhid_fd in readable:
                    # Drain what's queued (bounded - see
                    # UHID_MAX_DRAIN_PER_TICK) rather than just this one
                    # readable notification - see _service_bt_proxy_idle's
                    # identical comment on why a burst can otherwise overflow
                    # the kernel's bounded uhid queue faster than one-per-
                    # tick keeps up with, and why draining unboundedly here
                    # specifically caused Steam-visible disconnects (starves
                    # relay_input() above under a sustained, not just
                    # bursty, write rate).
                    for _ in range(UHID_MAX_DRAIN_PER_TICK):
                        session.relay_output_or_get_report()
                        more, _, _ = select.select([session.uhid_fd], [], [], 0)
                        if not more:
                            break
                    else:
                        # Still backlogged after a full budget of real
                        # hardware work - see UHID_FAST_DRAIN_CAP.
                        for _ in range(UHID_FAST_DRAIN_CAP):
                            session.relay_output_or_get_report(fast=True)
                            more, _, _ = select.select([session.uhid_fd], [], [], 0)
                            if not more:
                                break

                now = time.monotonic()
                if now - last_status_emit > 1.5:
                    last_status_emit = now
                    self._emit_status("proxied")
        finally:
            saxense_writer.stop()
            saxense.terminate()
            saxense.wait()
            parec.terminate()
            parec.wait()
            hidraw_file.close()

    def _session_ff(self, dev):
        effect = ff.Effect(
            ecodes.FF_RUMBLE, -1, 0,
            ff.Trigger(0, 0),
            ff.Replay(REPLAY_LEN_MS, 0),
            ff.EffectType(ff_rumble_effect=ff.Rumble(strong_magnitude=0, weak_magnitude=0)),
        )
        effect_id = dev.upload_effect(effect)
        effect.id = effect_id

        proc = subprocess.Popen(
            _audio_subprocess_prefix() +
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={RATE}", f"--channels={CHANNELS}", "--raw", "--latency-msec=20"],
            # bufsize=0 - see the other parec spawns' identical comment.
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )

        bass_y = treble_y = 0.0
        bass_ceil = treble_ceil = 0.0
        strong_env = weak_env = 0.0
        # Mid-band and LED smoothing state - see _run_bt_proxy_envelope's
        # own comment on the mid-band, this mirrors it exactly. This is the
        # sysfs-backed Immersive Lighting path (find_led_paths()/
        # write_led_sysfs()), used here since this session has no Bluetooth
        # HID Proxy to safely own report bytes with - notably including the
        # Decky plugin, which dropped that proxy entirely.
        mid_y = 0.0
        mid_ceil = 0.0
        mid_env = 0.0
        led_bass_smooth = led_mid_smooth = led_treble_smooth = 0.0
        lightbar_path, player_led_paths = find_led_paths(dev)
        led_last_write = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        analog_raw, analog_axis_info = _init_analog_raw(dev)
        update_hz = 1000.0 / CHUNK_MS
        fmt = f"<{CHUNK_SAMPLES * CHANNELS}h"

        # Steam grabs raw HID control of the controller for games with native
        # PS5 adaptive-trigger support, and keeps writing to it (at least for
        # the lightbar) for as long as Steam itself runs - our FF_RUMBLE
        # writes below still go out, but get overwritten by Steam's on the
        # wire, so nothing physically reaches the motors. There's no way to
        # win that write race (see the direct-audio sessions' own comments on
        # concurrent FF_RUMBLE writes fighting each other), so this doesn't
        # try - it just checks periodically (an fd/proc scan isn't cheap
        # enough to do every 20ms chunk) whether another process is holding
        # the device open, and reports it via status instead of silently
        # claiming "connected" while doing nothing.
        last_ownership_check = 0.0
        last_reported_overridden = False
        kind = connection_kind(dev)

        try:
            while not self._stop_event.is_set() and not self._bt_proxy_should_retry(kind):
                _drain_stale_audio(proc.stdout, CHUNK_BYTES)
                data = proc.stdout.read(CHUNK_BYTES)
                if len(data) < CHUNK_BYTES:
                    if proc.poll() is not None:
                        raise RuntimeError("audio capture (parec) exited")
                    continue

                cfg = self.config

                while True:
                    ev = dev.read_one()
                    if ev is None:
                        break
                    if ev.type == ecodes.EV_KEY:
                        held_keys[ev.code] = ev.value != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                        if ev.code == ecodes.ABS_HAT0X:
                            hat_x = ev.value
                        else:
                            hat_y = ev.value
                        held_keys[DPAD_VIRTUAL_CODE] = hat_x != 0 or hat_y != 0
                    elif ev.type == ecodes.EV_ABS and ev.code in analog_raw:
                        analog_raw[ev.code] = ev.value

                analog_scale = _analog_held_scale(analog_raw, analog_axis_info)
                for _code, _mag in analog_scale.items():
                    held_keys[_code] = _mag > 0

                samples = struct.unpack(fmt, data)
                left = samples[0::2]
                right = samples[1::2]

                bass_y, bass_band = lowpass_block(left, bass_y, cfg["bass_cutoff_hz"], RATE)
                treble_y, treble_ref = lowpass_block(right, treble_y, cfg["treble_cutoff_hz"], RATE)
                treble_band = [r - t for r, t in zip(right, treble_ref)]

                led_on = cfg.get("led_visualizer", {}).get("enabled", False)
                mid_mag = 0.0
                if led_on:
                    mid_y, mid_lp = lowpass_block(right, mid_y, cfg["bass_cutoff_hz"], RATE)
                    mid_band = [t - m for t, m in zip(treble_ref, mid_lp)]
                    mid_ceil, mid_delta = ceiling_step(
                        peak(mid_band), mid_ceil,
                        cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], update_hz)
                    mid_env, mid_mag = shape(mid_delta, mid_env, cfg["treble"])
                    mid_mag = min(1.0, mid_mag * cfg["master_gain"])

                bass_ceil, bass_delta = ceiling_step(
                    peak(bass_band), bass_ceil,
                    cfg["bass_ceiling"]["attack_s"], cfg["bass_ceiling"]["release_s"], update_hz)
                treble_ceil, treble_delta = ceiling_step(
                    peak(treble_band), treble_ceil,
                    cfg["treble_ceiling"]["attack_s"], cfg["treble_ceiling"]["release_s"], update_hz)

                strong_env, strong_mag = shape(bass_delta, strong_env, cfg["bass"])
                weak_env, weak_mag = shape(treble_delta, weak_env, cfg["treble"])

                gain = cfg["master_gain"]
                strong_mag = min(1.0, strong_mag * gain)
                weak_mag = min(1.0, weak_mag * gain)

                # Button-press feedback: each configured button feeds the
                # motor on its physical side (BUTTON_SIDE), at its own
                # strength - several held at once on the same side just take
                # the loudest rather than stacking past 1.0.
                button_strong_target, _, button_weak_target, _ = \
                    _button_click_targets(cfg, held_keys, BUTTON_CLICK_HZ, analog_scale)

                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                strong_mag = min(1.0, strong_mag + button_strong_env)
                weak_mag = min(1.0, weak_mag + button_weak_env)

                if led_on:
                    led_cfg = cfg.get("led_visualizer", {})
                    att, rel, gam = led_cfg.get("attack", 0.5), led_cfg.get("release", 0.08), led_cfg.get("gamma", 1.8)
                    led_bass_smooth, led_bass_out = _led_smooth(strong_mag, led_bass_smooth, att, rel, gam)
                    led_mid_smooth, led_mid_out = _led_smooth(mid_mag, led_mid_smooth, att, rel, gam)
                    led_treble_smooth, led_treble_out = _led_smooth(weak_mag, led_treble_smooth, att, rel, gam)
                    now = time.monotonic()
                    if now - led_last_write > LED_WRITE_INTERVAL_S:
                        led_last_write = now
                        write_led_sysfs(lightbar_path, player_led_paths,
                                         (led_bass_out, led_mid_out, led_treble_out, led_cfg.get("bass_priority", 0.6)))

                effect.u.ff_rumble_effect.strong_magnitude = int(strong_mag * 0xFFFF)
                effect.u.ff_rumble_effect.weak_magnitude = int(weak_mag * 0xFFFF)
                dev.upload_effect(effect)
                dev.write(ecodes.EV_FF, effect_id, 1)
                self._emit_levels(strong_mag, weak_mag)

                now = time.monotonic()
                if now - last_ownership_check > 1.5:
                    last_ownership_check = now
                    import triggers  # deferred: avoids a circular import at module load time
                    overridden = triggers.is_controller_owned_elsewhere()
                    if overridden != last_reported_overridden:
                        last_reported_overridden = overridden
                        self._emit_status("overridden" if overridden else "connected")
        finally:
            try:
                dev.erase_effect(effect_id)
            except OSError:
                pass
            proc.terminate()
            proc.wait()


def read_battery():
    """Returns (percent:int|None, status:str|None) for the first DualSense
    battery power_supply found in sysfs."""
    import glob
    for path in glob.glob("/sys/class/power_supply/ps-controller-battery-*"):
        try:
            with open(f"{path}/capacity") as f:
                percent = int(f.read().strip())
            with open(f"{path}/status") as f:
                status = f.read().strip()
            return percent, status
        except OSError:
            continue
    return None, None


if __name__ == "__main__":
    cfg = DEFAULT_CONFIG
    engine = HapticsEngine(cfg)
    engine.start()
    try:
        while True:
            print(engine.status_queue.get())
    except KeyboardInterrupt:
        engine.stop()
        engine.join()
