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

from presets import TRIGGER_PRESETS
from haptics_engine import SONY_VENDOR_ID, DUALSENSE_PRODUCT_IDS


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
    args = ["dualsensectl", "trigger", trigger] + TRIGGER_PRESETS[preset_id]["args"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, result.stderr.strip() or "dualsensectl failed"
    return True, ""


def turn_off_triggers(trigger="both"):
    try:
        result = subprocess.run(["dualsensectl", "trigger", trigger, "off"],
                                 capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, result.stderr.strip() or "dualsensectl failed"
    return True, ""
