"""Adaptive trigger control, backed by the `dualsensectl` CLI.

Trigger effects are "set and forget": unlike the rumble motors, there's no
continuous stream, so this module never fights a game for the device in a
loop - it just sends one HID output report when asked to. HID has no notion
of "who owns the device", so the only way to be polite to a game that's
already driving the triggers itself is a heuristic: if another process has
the controller's hidraw/evdev node open (a game reading input keeps it open
for the whole session), assume it's in control and skip *automatic*
re-application on reconnect. An explicit user action always applies.
"""
import glob
import os
import subprocess

import evdev
from evdev import ecodes

from presets import TRIGGER_PRESETS, TRIGGER_EFFECT_PARAMS, TRIGGER_RAW_CLI_NAME
from haptics_engine import SONY_VENDOR_ID, DUALSENSE_PRODUCT_IDS


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


def apply_trigger_preset(preset_id, trigger="both"):
    if preset_id not in TRIGGER_PRESETS:
        return False, f"unknown preset {preset_id}"
    args = ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", trigger] + TRIGGER_PRESETS[preset_id]["args"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, result.stderr.strip() or "dualsensectl failed"
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
    if result.returncode != 0:
        return False, result.stderr.strip() or "dualsensectl failed"
    return True, ""


def turn_off_triggers(trigger="both"):
    try:
        result = subprocess.run(
            ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", trigger, "off"],
            capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, result.stderr.strip() or "dualsensectl failed"
    return True, ""
