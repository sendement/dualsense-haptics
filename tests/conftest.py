"""Shared test setup: import path + stand-ins for Linux-only dependencies.

The app itself is Linux-only (evdev, fcntl, uhid, parec), but everything
these tests cover is pure computation - DSP math, HID report/CRC building,
preset data, config migration, i18n tables. To let the suite run anywhere
(CI containers without hardware, or a Windows/macOS checkout), any of the
platform modules that are missing get replaced with minimal stand-ins
*before* the app modules import them. On a real Linux box with the real
libraries installed, the real ones are used untouched.

Nothing here fakes device behavior - functions that genuinely need hardware
(session loops, device discovery) are simply not exercised by this suite.
"""
import sys
import types
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _install(name, module):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            sys.modules[name] = module


# --- evdev ------------------------------------------------------------------
# haptics_engine builds BUTTON_SIDE and the analog-axis tables from ecodes
# constants at import time, so the stand-in carries the real Linux
# input-event-codes values for everything referenced there (tests assert
# against these same constants). Anything else resolves to a deterministic
# synthetic value so future module-level references never break the import.
_ECODES = {
    "ABS_X": 0x00, "ABS_Y": 0x01, "ABS_Z": 0x02,
    "ABS_RX": 0x03, "ABS_RY": 0x04, "ABS_RZ": 0x05,
    "ABS_HAT0X": 0x10, "ABS_HAT0Y": 0x11,
    "BTN_SOUTH": 0x130, "BTN_EAST": 0x131, "BTN_NORTH": 0x133, "BTN_WEST": 0x134,
    "BTN_TL": 0x136, "BTN_TR": 0x137, "BTN_TL2": 0x138, "BTN_TR2": 0x139,
    "BTN_SELECT": 0x13A, "BTN_START": 0x13B, "BTN_MODE": 0x13C,
    "BTN_THUMBL": 0x13D, "BTN_THUMBR": 0x13E,
    "EV_KEY": 0x01, "EV_ABS": 0x03, "EV_FF": 0x15,
    "FF_RUMBLE": 0x50,
}


class _EcodesModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = _ECODES.get(name)
        if value is None:
            value = 0x10000 + (zlib.crc32(name.encode()) & 0xFFFF)
        setattr(self, name, value)
        return value


def _make_evdev_stub():
    evdev = types.ModuleType("evdev")
    ecodes = _EcodesModule("evdev.ecodes")
    ff = types.ModuleType("evdev.ff")
    evdev.ecodes = ecodes
    evdev.ff = ff
    sys.modules["evdev.ecodes"] = ecodes
    sys.modules["evdev.ff"] = ff
    return evdev


_install("evdev", _make_evdev_stub())


# --- Linux-only stdlib (fcntl / pwd / termios) ------------------------------
# Imported at module top by haptics_engine/bt_hid_proxy but only *called* on
# device/session paths this suite never touches. Attribute access yields a
# loud failure if a test wanders onto such a path by accident.
class _LoudModule(types.ModuleType):
    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        name = self.__name__

        def _fail(*args, **kwargs):
            raise RuntimeError(
                f"{name}.{attr} is a test stand-in - this code path needs real Linux"
            )
        return _fail


for _name in ("fcntl", "pwd", "termios"):
    _install(_name, _LoudModule(_name))


# --- PySide6.QtCore ---------------------------------------------------------
# i18n.py needs QObject/Signal/QLocale at import time (it instantiates its
# global `manager`). The Signal stand-in is functional enough for tests to
# assert that `changed` really fires on language switches.
class _BoundSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._slots.clear()
        else:
            self._slots.remove(slot)

    def emit(self, *args, **kwargs):
        for slot in list(self._slots):
            slot(*args, **kwargs)


class _Signal:
    def __init__(self, *args, **kwargs):
        pass

    def __set_name__(self, owner, name):
        self._attr = f"__stub_signal_{name}"

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        bound = obj.__dict__.get(self._attr)
        if bound is None:
            bound = _BoundSignal()
            obj.__dict__[self._attr] = bound
        return bound


class _QObject:
    def __init__(self, *args, **kwargs):
        pass


class _QLocaleResult:
    @staticmethod
    def name():
        return "en_US"


class _QLocale:
    @staticmethod
    def system():
        return _QLocaleResult()


def _make_pyside_stub():
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = _QObject
    qtcore.Signal = _Signal
    qtcore.QLocale = _QLocale
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = qtcore
    sys.modules["PySide6.QtCore"] = qtcore
    return pyside


_install("PySide6", _make_pyside_stub())
