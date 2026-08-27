"""Config persistence (presets/profiles/active state) and XDG autostart handling."""
import copy
import json
import os
from pathlib import Path

from haptics_engine import DEFAULT_CONFIG
from presets import preset_params
from i18n import detect_system_language

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "dualsense-haptics"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "dualsense-haptics.desktop"

APP_DIR = Path(__file__).resolve().parent


def _merge_defaults(cfg, defaults):
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
            _merge_defaults(cfg[k], v)
    return cfg


def _default_state():
    return {
        "active": preset_params("balanced"),
        "active_ref": "preset:balanced",
        "profiles": {},
        "trigger_preset_left": None,
        "trigger_preset_right": None,
        "trigger_custom_left": None,
        "trigger_custom_right": None,
        "trigger_auto_reconnect": True,
        "theme": "system",
        "language": detect_system_language(),
    }


def load_state():
    """Returns {"active": {...engine params...}, "active_ref": str, "profiles": {name: params}}."""
    if not CONFIG_FILE.exists():
        return _default_state()
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return _default_state()

    if "active" not in raw:
        # Old flat-params format from before presets/profiles existed - keep it
        # as a user profile so nothing from prior tuning gets lost.
        old_params = _merge_defaults(raw, DEFAULT_CONFIG)
        state = _default_state()
        state["active"] = old_params
        state["active_ref"] = "profile:Мои настройки"
        state["profiles"] = {"Мои настройки": copy.deepcopy(old_params)}
        return state

    state = _default_state()
    state["active"] = _merge_defaults(raw.get("active", {}), DEFAULT_CONFIG)

    old_bh = state["active"].pop("button_haptic", None)
    if old_bh and old_bh.get("button_code") is not None:
        # Old single-button format - carry it over as one entry in the new
        # multi-button dict.
        state["active"]["button_haptics"][str(old_bh["button_code"])] = {
            "enabled": old_bh.get("enabled", False),
            "strength": old_bh.get("strength", 0.4),
        }

    state["active_ref"] = raw.get("active_ref", "custom")
    state["profiles"] = raw.get("profiles", {})
    if "trigger_preset" in raw:
        # Old single-preset-for-both-sides format - carry it over to both.
        state["trigger_preset_left"] = raw["trigger_preset"]
        state["trigger_preset_right"] = raw["trigger_preset"]
    else:
        state["trigger_preset_left"] = raw.get("trigger_preset_left")
        state["trigger_preset_right"] = raw.get("trigger_preset_right")
    state["trigger_custom_left"] = raw.get("trigger_custom_left")
    state["trigger_custom_right"] = raw.get("trigger_custom_right")
    state["trigger_auto_reconnect"] = raw.get("trigger_auto_reconnect", True)
    state["theme"] = raw.get("theme", "system")
    state["language"] = raw.get("language", detect_system_language())
    for name, params in state["profiles"].items():
        _merge_defaults(params, DEFAULT_CONFIG)
    return state


def save_state(state):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def is_autostart_enabled():
    return AUTOSTART_FILE.exists()


def set_autostart(enabled):
    if enabled:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        installed_bin = Path("/usr/bin/dualsense-haptics")
        exec_line = "dualsense-haptics --tray" if installed_bin.exists() else f'python3 "{APP_DIR / "main.py"}" --tray'
        entry = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=DualSense Haptics\n"
            f"Exec={exec_line}\n"
            "Icon=input-gaming\n"
            "X-GNOME-Autostart-enabled=true\n"
            "NoDisplay=false\n"
            "Terminal=false\n"
        )
        AUTOSTART_FILE.write_text(entry)
    else:
        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
