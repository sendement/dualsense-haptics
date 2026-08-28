"""
Core audio-to-haptics engine for the DualSense, decoupled from any GUI.

Captures the system's default audio output and drives the DualSense's two
rumble motors (FF_RUMBLE strong=bass, weak=treble) through the standard
Linux force-feedback (evdev) API. See README.md for the DSP rationale.

Runs in its own thread; `config` is a plain nested dict that the GUI can
mutate directly for live tuning (each analysis chunk re-reads it, so no
locking is needed - worst case one 20ms frame uses a slightly stale value).
"""
import glob
import math
import queue
import re
import select
import shutil
import struct
import subprocess
import sys
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

# Direct-audio (Bluetooth) path: same idea, over a community-reverse-
# engineered BT HID haptics protocol (github.com/egormanga/SAxense) rather
# than the USB Audio Class interface - opt-in and far lower fidelity (8-bit,
# combined 3kHz for both channels) but still literal PCM, not a synthesized
# envelope. See find_dualsense_hidraw() and HapticsEngine._session_bt_direct_audio.
BT_RATE = 3000
BT_CHUNK_MS = 20
BT_CHUNK_SAMPLES = BT_RATE * BT_CHUNK_MS // 1000
BT_BUTTON_CLICK_HZ = 150

DEFAULT_CONFIG = {
    "master_gain": 1.0,
    "bass_cutoff_hz": 90,
    "treble_cutoff_hz": 500,
    "bass": {"attack": 0.95, "release": 0.5, "lo": 0.010, "hi": 0.12, "gamma": 1.3},
    "treble": {"attack": 0.95, "release": 0.55, "lo": 0.003, "hi": 0.045, "gamma": 0.7},
    "bass_ceiling": {"attack_s": 0.08, "release_s": 2.5},
    "treble_ceiling": {"attack_s": 0.05, "release_s": 2.0},
    # button code (str, JSON-friendly) -> {"enabled": bool, "strength": float}.
    # Empty by default - no button feedback until the user picks one.
    "button_haptics": {},
    # USB only - see find_dualsense_sink() and HapticsEngine._session_direct_audio.
    # bt_enabled is separate and opt-in (default off) - see BT_RATE above.
    "direct_audio": {"enabled": True, "gain": 5.0, "cutoff_hz": 500, "bt_enabled": False},
    # Bluetooth only, opt-in - see bt_hid_proxy.py and HapticsEngine._session_bt_proxy.
    "bt_hid_proxy": {"enabled": False},
}

BUTTON_ATTACK = 0.7
BUTTON_RELEASE = 0.5

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


# Sony's USB vendor/product ID for the DualSense - matched instead of the
# device name, since the kernel reports a different name per transport
# ("DualSense Wireless Controller" over Bluetooth vs. "Sony Interactive
# Entertainment DualSense Wireless Controller" over USB). Both the regular
# DualSense and the Edge report the same evdev FF_RUMBLE interface, just
# under a different product ID (confirmed against dualsensectl's own
# device table, which recognizes the same two IDs).
SONY_VENDOR_ID = 0x054C
DUALSENSE_PRODUCT_IDS = {0x0CE6, 0x0DF2}  # DualSense, DualSense Edge


def find_ff_device():
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if (ecodes.EV_FF in d.capabilities()
                and d.info.vendor == SONY_VENDOR_ID
                and d.info.product in DUALSENSE_PRODUCT_IDS):
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

    def stop(self):
        self._stop_event.set()

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

    def run(self):
        while not self._stop_event.is_set():
            dev = find_ff_device()
            if dev is None:
                self._emit_status("searching")
                self._emit_connection(None)
                if self._stop_event.wait(2.0):
                    return
                continue
            try:
                self._emit_status("connected")
                self._emit_connection(connection_kind(dev))
                self._session(dev)
            except Exception as e:
                self._emit_status(f"error: {e}")
                self._emit_connection(None)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
            if self._stop_event.is_set():
                return
            self._stop_event.wait(1.0)

    def _session(self, dev):
        """Dispatches to whichever haptics path applies to this connection.
        Direct audio over USB (see find_dualsense_sink()) is tried first
        there. Direct audio over Bluetooth is opt-in and needs the external
        `SAxense` tool (see find_dualsense_hidraw()). Anything else falls
        back to the synthesized-envelope/FF_RUMBLE path."""
        kind = connection_kind(dev)
        proxy_cfg = self.config.get("bt_hid_proxy", {})
        now = time.monotonic()
        if (kind == "bluetooth" and proxy_cfg.get("enabled", False)
                and now >= getattr(self, "_bt_proxy_retry_after", 0.0)):
            self._session_bt_proxy(dev)
            return
        self._session_fallback(dev, kind)

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
        phase_step = 2 * math.pi * BUTTON_CLICK_HZ / rate

        parec = subprocess.Popen(
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={rate}", "--channels=2", "--raw", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        paplay = subprocess.Popen(
            ["paplay", "--raw", f"--rate={rate}", "--format=s16le", "--channels=4",
             "--channel-map=front-left,front-right,rear-left,rear-right", f"--device={sink}"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        left_y = right_y = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        phase = 0.0

        try:
            while not self._stop_event.is_set():
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

                samples = struct.unpack(stereo_fmt, data)
                left_in = [s / 32768.0 for s in samples[0::2]]
                right_in = [s / 32768.0 for s in samples[1::2]]
                left_y, left = lowpass_block(left_in, left_y, cutoff_hz, rate)
                right_y, right = lowpass_block(right_in, right_y, cutoff_hz, rate)

                # Same per-side button feedback as the FF path (BUTTON_SIDE),
                # just mixed in as a short tone instead of an FF magnitude.
                button_strong_target = 0.0
                button_weak_target = 0.0
                for code_str, entry in cfg["button_haptics"].items():
                    if not entry.get("enabled") or not held_keys.get(int(code_str), False):
                        continue
                    side = BUTTON_SIDE.get(int(code_str), "weak")
                    strength = entry.get("strength", 0.4)
                    if side == "strong":
                        button_strong_target = max(button_strong_target, strength)
                    else:
                        button_weak_target = max(button_weak_target, strength)
                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                frame = [0] * (chunk_samples * 4)
                peak_left = peak_right = 0.0
                for i in range(chunk_samples):
                    l = left[i] * gain
                    r = right[i] * gain
                    click = math.sin(phase)
                    phase += phase_step
                    if button_strong_env > 0.001:
                        l += click * button_strong_env
                    if button_weak_env > 0.001:
                        r += click * button_weak_env
                    l = math.tanh(l)
                    r = math.tanh(r)
                    peak_left = max(peak_left, abs(l))
                    peak_right = max(peak_right, abs(r))
                    frame[i * 4 + 2] = int(l * 32767)
                    frame[i * 4 + 3] = int(r * 32767)
                phase = math.fmod(phase, 2 * math.pi)

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
        chunk_samples = BT_CHUNK_SAMPLES
        stereo_bytes = chunk_samples * 2 * 2
        stereo_fmt = f"<{chunk_samples * 2}h"
        phase_step = 2 * math.pi * BT_BUTTON_CLICK_HZ / rate

        hidraw_file = open(hidraw_path, "wb", buffering=0)
        parec = subprocess.Popen(
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={rate}", "--channels=2", "--raw", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        saxense = subprocess.Popen(
            ["SAxense"], stdin=subprocess.PIPE, stdout=hidraw_file, stderr=subprocess.DEVNULL,
        )

        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        phase = 0.0

        try:
            while not self._stop_event.is_set():
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

                samples = struct.unpack(stereo_fmt, data)
                left_in = samples[0::2]
                right_in = samples[1::2]

                button_strong_target = 0.0
                button_weak_target = 0.0
                for code_str, entry in cfg["button_haptics"].items():
                    if not entry.get("enabled") or not held_keys.get(int(code_str), False):
                        continue
                    side = BUTTON_SIDE.get(int(code_str), "weak")
                    strength = entry.get("strength", 0.4)
                    if side == "strong":
                        button_strong_target = max(button_strong_target, strength)
                    else:
                        button_weak_target = max(button_weak_target, strength)
                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                out = bytearray(chunk_samples * 2)
                peak_left = peak_right = 0.0
                for i in range(chunk_samples):
                    l = (left_in[i] / 32768.0) * gain
                    r = (right_in[i] / 32768.0) * gain
                    click = math.sin(phase)
                    phase += phase_step
                    if button_strong_env > 0.001:
                        l += click * button_strong_env
                    if button_weak_env > 0.001:
                        r += click * button_weak_env
                    l = math.tanh(l)
                    r = math.tanh(r)
                    peak_left = max(peak_left, abs(l))
                    peak_right = max(peak_right, abs(r))
                    out[i * 2] = int(l * 127) & 0xFF
                    out[i * 2 + 1] = int(r * 127) & 0xFF
                phase = math.fmod(phase, 2 * math.pi)

                saxense.stdin.write(bytes(out))
                saxense.stdin.flush()
                self._emit_levels(peak_left, peak_right)
        finally:
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
        helper/udev rule, /dev/uhid inaccessible), with a 30s cooldown before
        retrying so a persistently broken install doesn't respawn the helper
        every 2s reconnect poll."""
        session = bt_hid_proxy.BtHidProxySession()
        try:
            session.open()
        except bt_hid_proxy.ProxyUnavailable:
            self._emit_status("bt_proxy_unavailable")
            self._bt_proxy_retry_after = time.monotonic() + 30
            self._session_fallback(dev, "bluetooth")
            return

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
            while True:
                try:
                    session.close()
                    break
                except KeyboardInterrupt:
                    continue

    def _run_bt_proxy_envelope(self, session, dev):
        """Synthesized-envelope rumble through the proxy - structurally a
        copy of _session_ff (same parec spawn, same bass/treble/button DSP),
        swapping the FF_RUMBLE write for the proxy's relay+merge each tick."""
        proc = subprocess.Popen(
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={RATE}", f"--channels={CHANNELS}", "--raw", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        bass_y = treble_y = 0.0
        bass_ceil = treble_ceil = 0.0
        strong_env = weak_env = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        update_hz = 1000.0 / CHUNK_MS
        fmt = f"<{CHUNK_SAMPLES * CHANNELS}h"
        last_status_emit = 0.0

        try:
            while not self._stop_event.is_set() and self.config.get("bt_hid_proxy", {}).get("enabled", False):
                readable, _, _ = select.select(
                    [session.real_fd, session.uhid_fd, proc.stdout], [], [], 0.02)

                if proc.stdout in readable:
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

                        samples = struct.unpack(fmt, data)
                        left = samples[0::2]
                        right = samples[1::2]

                        bass_y, bass_band = lowpass_block(left, bass_y, cfg["bass_cutoff_hz"], RATE)
                        treble_y, treble_ref = lowpass_block(right, treble_y, cfg["treble_cutoff_hz"], RATE)
                        treble_band = [r - t for r, t in zip(right, treble_ref)]

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

                        button_strong_target = 0.0
                        button_weak_target = 0.0
                        for code_str, entry in cfg["button_haptics"].items():
                            if not entry.get("enabled") or not held_keys.get(int(code_str), False):
                                continue
                            side = BUTTON_SIDE.get(int(code_str), "weak")
                            strength = entry.get("strength", 0.4)
                            if side == "strong":
                                button_strong_target = max(button_strong_target, strength)
                            else:
                                button_weak_target = max(button_weak_target, strength)

                        button_strong_env += (button_strong_target - button_strong_env) * (
                            BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                        button_weak_env += (button_weak_target - button_weak_env) * (
                            BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                        strong_mag = min(1.0, strong_mag + button_strong_env)
                        weak_mag = min(1.0, weak_mag + button_weak_env)

                        session.write_rumble(strong_mag, weak_mag)
                        self._emit_levels(strong_mag, weak_mag)

                if session.real_fd in readable:
                    session.relay_input()
                if session.uhid_fd in readable:
                    session.relay_output_or_get_report()

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
        forward_cached_report(), since write_rumble()'s own motor-byte
        override doesn't apply here - SAxense owns the motors instead."""
        rate = BT_RATE
        chunk_samples = BT_CHUNK_SAMPLES
        stereo_bytes = chunk_samples * 2 * 2
        stereo_fmt = f"<{chunk_samples * 2}h"
        phase_step = 2 * math.pi * BT_BUTTON_CLICK_HZ / rate

        hidraw_file = open(clone_hidraw, "wb", buffering=0)
        parec = subprocess.Popen(
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={rate}", "--channels=2", "--raw", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        saxense = subprocess.Popen(
            ["SAxense"], stdin=subprocess.PIPE, stdout=hidraw_file, stderr=subprocess.DEVNULL,
        )

        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
        phase = 0.0
        last_status_emit = 0.0

        try:
            while not self._stop_event.is_set() and self.config.get("bt_hid_proxy", {}).get("enabled", False):
                readable, _, _ = select.select(
                    [session.real_fd, session.uhid_fd, parec.stdout], [], [], 0.02)

                if parec.stdout in readable:
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

                        samples = struct.unpack(stereo_fmt, data)
                        left_in = samples[0::2]
                        right_in = samples[1::2]

                        button_strong_target = 0.0
                        button_weak_target = 0.0
                        for code_str, entry in cfg["button_haptics"].items():
                            if not entry.get("enabled") or not held_keys.get(int(code_str), False):
                                continue
                            side = BUTTON_SIDE.get(int(code_str), "weak")
                            strength = entry.get("strength", 0.4)
                            if side == "strong":
                                button_strong_target = max(button_strong_target, strength)
                            else:
                                button_weak_target = max(button_weak_target, strength)
                        button_strong_env += (button_strong_target - button_strong_env) * (
                            BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                        button_weak_env += (button_weak_target - button_weak_env) * (
                            BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                        out = bytearray(chunk_samples * 2)
                        peak_left = peak_right = 0.0
                        for i in range(chunk_samples):
                            l = (left_in[i] / 32768.0) * gain
                            r = (right_in[i] / 32768.0) * gain
                            click = math.sin(phase)
                            phase += phase_step
                            if button_strong_env > 0.001:
                                l += click * button_strong_env
                            if button_weak_env > 0.001:
                                r += click * button_weak_env
                            l = math.tanh(l)
                            r = math.tanh(r)
                            peak_left = max(peak_left, abs(l))
                            peak_right = max(peak_right, abs(r))
                            out[i * 2] = int(l * 127) & 0xFF
                            out[i * 2 + 1] = int(r * 127) & 0xFF
                        phase = math.fmod(phase, 2 * math.pi)

                        saxense.stdin.write(bytes(out))
                        saxense.stdin.flush()
                        session.forward_cached_report()
                        self._emit_levels(peak_left, peak_right)

                if session.real_fd in readable:
                    session.relay_input()
                if session.uhid_fd in readable:
                    session.relay_output_or_get_report()

                now = time.monotonic()
                if now - last_status_emit > 1.5:
                    last_status_emit = now
                    self._emit_status("proxied")
        finally:
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
            ["parec", "-d", "@DEFAULT_SINK@.monitor", "--format=s16le",
             f"--rate={RATE}", f"--channels={CHANNELS}", "--raw", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        bass_y = treble_y = 0.0
        bass_ceil = treble_ceil = 0.0
        strong_env = weak_env = 0.0
        button_strong_env = button_weak_env = 0.0
        held_keys = {}
        hat_x = hat_y = 0
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

        try:
            while not self._stop_event.is_set():
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

                samples = struct.unpack(fmt, data)
                left = samples[0::2]
                right = samples[1::2]

                bass_y, bass_band = lowpass_block(left, bass_y, cfg["bass_cutoff_hz"], RATE)
                treble_y, treble_ref = lowpass_block(right, treble_y, cfg["treble_cutoff_hz"], RATE)
                treble_band = [r - t for r, t in zip(right, treble_ref)]

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
                button_strong_target = 0.0
                button_weak_target = 0.0
                for code_str, entry in cfg["button_haptics"].items():
                    if not entry.get("enabled") or not held_keys.get(int(code_str), False):
                        continue
                    side = BUTTON_SIDE.get(int(code_str), "weak")
                    strength = entry.get("strength", 0.4)
                    if side == "strong":
                        button_strong_target = max(button_strong_target, strength)
                    else:
                        button_weak_target = max(button_weak_target, strength)

                button_strong_env += (button_strong_target - button_strong_env) * (
                    BUTTON_ATTACK if button_strong_target > button_strong_env else BUTTON_RELEASE)
                button_weak_env += (button_weak_target - button_weak_env) * (
                    BUTTON_ATTACK if button_weak_target > button_weak_env else BUTTON_RELEASE)

                strong_mag = min(1.0, strong_mag + button_strong_env)
                weak_mag = min(1.0, weak_mag + button_weak_env)

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
