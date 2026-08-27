"""
Core audio-to-haptics engine for the DualSense, decoupled from any GUI.

Captures the system's default audio output and drives the DualSense's two
rumble motors (FF_RUMBLE strong=bass, weak=treble) through the standard
Linux force-feedback (evdev) API. See README.md for the DSP rationale.

Runs in its own thread; `config` is a plain nested dict that the GUI can
mutate directly for live tuning (each analysis chunk re-reads it, so no
locking is needed - worst case one 20ms frame uses a slightly stale value).
"""
import math
import queue
import struct
import subprocess
import sys
import threading
import time

import evdev
from evdev import ecodes, ff

RATE = 8000
CHANNELS = 2
CHUNK_MS = 20
CHUNK_SAMPLES = RATE * CHUNK_MS // 1000
CHUNK_BYTES = CHUNK_SAMPLES * CHANNELS * 2  # s16le
REPLAY_LEN_MS = 60

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
