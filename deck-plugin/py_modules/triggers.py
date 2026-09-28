"""Adaptive trigger control, backed by the `dualsensectl` CLI.

Trigger effects are "set and forget": unlike the rumble motors, there's no
continuous stream, so this module never fights a game for the device in a
loop - it just sends one HID output report when asked to. HID has no notion
of "who owns the device", so the only way to be polite to a game that's
already driving the triggers itself is a heuristic: if another process has
the controller's hidraw/evdev node open (a game reading input keeps it open
for the whole session), assume it's in control and skip *automatic*
re-application on reconnect. An explicit user action always applies.

The one exception is the optional "snap click" (see start_snap_click below):
a background thread that watches the trigger's live position and briefly
overrides the base effect with a vibration burst the instant it crosses into
a hard-stop zone, faking a combination the firmware's report format can't
express directly.
"""
import glob
import os
import select
import subprocess
import threading
import time

import evdev
from evdev import ecodes

from presets import TRIGGER_PRESETS, TRIGGER_EFFECT_PARAMS, TRIGGER_RAW_CLI_NAME
from haptics_engine import SONY_VENDOR_ID, DUALSENSE_PRODUCT_IDS

_TRIGGER_AXIS = {"left": ecodes.ABS_Z, "right": ecodes.ABS_RZ}


def _dualsensectl_prefix():
    """When a Bluetooth HID proxy session is active, the real device's hidraw
    node is hidden (see bt_hid_proxy.py) and dualsensectl's own device
    enumeration would otherwise pick it first and fail with a permission
    error before ever trying the clone - so target the clone explicitly by
    its fixed fake serial in that case."""
    import bt_hid_proxy  # deferred: avoids a needless import when never used
    uniq = bt_hid_proxy.is_proxy_active()
    return ["-d", uniq] if uniq else []


def find_hidraw_paths():
    """All /dev/hidrawN nodes belonging to a Sony DualSense (any transport)."""
    paths = []
    for sys_path in glob.glob("/sys/bus/hid/devices/*:054C:*/hidraw/hidraw*") + \
            glob.glob("/sys/bus/hid/devices/*:054c:*/hidraw/hidraw*"):
        name = os.path.basename(sys_path)
        paths.append(f"/dev/{name}")
    return paths


def find_evdev_path():
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if (ecodes.EV_FF in d.capabilities()
                and d.info.vendor == SONY_VENDOR_ID
                and d.info.product in DUALSENSE_PRODUCT_IDS):
            return d.path
    return None


def other_process_has_device_open(paths):
    """True if some process other than us holds an fd on any of `paths`."""
    targets = {p for p in paths if p}
    if not targets:
        return False
    my_pid = os.getpid()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == my_pid:
            continue
        try:
            for fd_entry in os.scandir(f"/proc/{entry.name}/fd"):
                try:
                    target = os.readlink(fd_entry.path)
                except OSError:
                    continue
                if target in targets:
                    return True
        except OSError:
            continue
    return False


def is_controller_owned_elsewhere():
    return other_process_has_device_open(find_hidraw_paths() + [find_evdev_path()])


def dualsensectl_error(result):
    """Error text if a dualsensectl run did not reach the controller, else
    None. dualsensectl 0.7.0 logs a failed hid_write to stderr but still
    exits 0, so the exit status alone can report success (and get a preset
    remembered) for a command that was never delivered."""
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        return stderr or "dualsensectl failed"
    if "hid_write" in stderr.lower():
        return stderr
    return None


def apply_trigger_preset(preset_id, trigger="both"):
    if preset_id not in TRIGGER_PRESETS:
        return False, f"unknown preset {preset_id}"
    preset = TRIGGER_PRESETS[preset_id]
    args = (["dualsensectl"] + _dualsensectl_prefix() + ["trigger", trigger]
            + build_custom_args(preset["mode"], preset["values"]))
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    error = dualsensectl_error(result)
    if error:
        return False, error
    return True, ""


def build_custom_args(mode, values):
    """Builds the dualsensectl arg list for a custom effect. "end"-style
    params must exceed their paired "start" param or dualsensectl rejects
    the whole command - rather than constrain the sliders live, just bump
    the value up (clamped to its own max) here on apply."""
    if mode == "off":
        return ["off"]
    spec = TRIGGER_EFFECT_PARAMS[mode]
    bounds = {key: (lo, hi) for key, lo, hi, _default in spec}
    values = dict(values)
    for start_key, end_key in (("start", "end"), ("first_foot", "second_foot")):
        if start_key in values and end_key in values and values[end_key] <= values[start_key]:
            _lo, hi = bounds[end_key]
            values[end_key] = min(values[start_key] + 1, hi)
    cli_mode = TRIGGER_RAW_CLI_NAME.get(mode, mode)
    return [cli_mode] + [str(values[key]) for key, _lo, _hi, _default in spec]


def apply_custom_trigger(mode, values, trigger="both"):
    args = build_custom_args(mode, values)
    try:
        result = subprocess.run(
            ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", trigger] + args,
            capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    error = dualsensectl_error(result)
    if error:
        return False, error
    return True, ""


def turn_off_triggers(trigger="both"):
    try:
        result = subprocess.run(
            ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", trigger, "off"],
            capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    error = dualsensectl_error(result)
    if error:
        return False, error
    return True, ""


# One-shot "snap click": the firmware can't combine a static resistance/snap
# effect (bow, feedback-raw) with a vibration pulse in a single HID report -
# only one effect mode is ever active per trigger - so a real physical click
# layered on top of a hardware snap has to be faked in software: watch the
# trigger's live analog position and, the instant it crosses into a "wall"
# zone, briefly override the effect with a sharp vibration burst before
# restoring the base effect underneath it.
_SNAP_CLICK_THREADS = {}  # side -> _SnapClickThread
_SNAP_CLICK_LOCK = threading.Lock()


class _SnapClickThread(threading.Thread):
    def __init__(self, side, evdev_path, wall_zones, base_mode, base_values,
                 click_amplitude=8, click_frequency=15, click_duration_s=0.09,
                 click_cooldown_s=0.35):
        super().__init__(daemon=True)
        self.side = side
        self.evdev_path = evdev_path
        self.wall_zones = wall_zones
        self.base_mode = base_mode
        self.base_values = base_values
        self.click_amplitude = click_amplitude
        self.click_frequency = click_frequency
        self.click_duration_s = click_duration_s
        # The click's own vibration burst physically jostles the trigger
        # arm, which briefly kicks the analog reading back out of the wall
        # zone and re-arms the naive armed/disarmed check below - without a
        # cooldown, one real press reliably re-fires 2-3 times in a row as
        # that echo settles. Comfortably covers click_duration_s plus
        # mechanical settling time, well under a real second press's cadence.
        self.click_cooldown_s = click_cooldown_s
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            dev = evdev.InputDevice(self.evdev_path)
        except OSError:
            return
        try:
            axis_code = _TRIGGER_AXIS[self.side]
            absinfo = dev.absinfo(axis_code)
            span = max(1, absinfo.max - absinfo.min)
            # Seed from the trigger's actual current position, not a blind
            # True - switching presets/profiles (or a reconnect) restarts
            # this thread from scratch, and if the finger is already resting
            # past the wall at that moment (e.g. flipping through preset
            # cards while still holding it down for comparison), starting
            # "armed" would read that as a fresh press and fire immediately -
            # stacking into a spurious double/triple click across a few
            # quick switches even though nothing new was actually pressed.
            start_zone = int((absinfo.value - absinfo.min) / span * 9)
            armed = start_zone not in self.wall_zones
            last_fire = 0.0
            while not self._stop.is_set():
                ready, _, _ = select.select([dev.fd], [], [], 0.1)
                if not ready:
                    continue
                for ev in dev.read():
                    if ev.type != ecodes.EV_ABS or ev.code != axis_code:
                        continue
                    zone = int((ev.value - absinfo.min) / span * 9)
                    in_wall = zone in self.wall_zones
                    now = time.monotonic()
                    if in_wall and armed and now - last_fire >= self.click_cooldown_s:
                        armed = False
                        last_fire = now
                        self._fire_click()
                    elif not in_wall:
                        armed = True
        except OSError:
            pass
        finally:
            dev.close()

    def _fire_click(self):
        # The lowest wall zone is where the trigger actually crossed into
        # the wall (e.g. bow's "end") - buzz there, not at the far end of
        # wall_zones (which can now extend all the way to 9, see
        # start_snap_click's caller), so the click feels anchored to the
        # snap itself rather than to full travel.
        apply_custom_trigger("vibration",
            {"position": min(self.wall_zones, default=9), "amplitude": self.click_amplitude,
             "frequency": self.click_frequency}, self.side)
        if self._stop.wait(self.click_duration_s):
            return
        apply_custom_trigger(self.base_mode, self.base_values, self.side)


def start_snap_click(side, base_mode, base_values, wall_zones, **click_kwargs):
    """(Re)starts the snap-click watcher for one side. `wall_zones` is the
    set of 0-9 zone indices that should fire the click when entered - for a
    single bow-style snap that's just {end}; for a multi-stage feedback-raw
    shape it's presets.wall_zones_from_feedback_raw(values)."""
    stop_snap_click(side)
    if not wall_zones:
        return
    evdev_path = find_evdev_path()
    if not evdev_path:
        return
    thread = _SnapClickThread(side, evdev_path, set(wall_zones), base_mode, base_values, **click_kwargs)
    with _SNAP_CLICK_LOCK:
        _SNAP_CLICK_THREADS[side] = thread
    thread.start()


def stop_snap_click(side):
    with _SNAP_CLICK_LOCK:
        thread = _SNAP_CLICK_THREADS.pop(side, None)
    if thread:
        thread.stop()
        # start_snap_click() calls this right before spawning a replacement
        # thread for the same side - without waiting here, the old thread
        # can keep reading the trigger for a little while after that (it
        # only notices _stop between select() timeouts) and independently
        # fire its own click during the overlap, on top of whatever the new
        # thread does.
        thread.join(timeout=0.3)
