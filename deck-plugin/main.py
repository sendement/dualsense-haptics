"""Decky Loader plugin backend.

Deliberately does NOT import haptics_engine.py or config.py here (both pull
in python-evdev, which has a compiled C extension - importing that inside
Decky's PyInstaller-frozen PluginLoader process reliably fails with a
"partially initialized module" error). Instead this process only manages a
plain `python3 headless_runner.py` child process (a normal, unfrozen
interpreter where evdev imports fine) and talks to it via the filesystem:
this file reads/writes config.json directly (mirroring config.py's own
format closely enough that the runner's config.load_state() - which does
the real default-merging - reads it back correctly) and polls status.json
that the runner writes. presets.py has no evdev dependency, so it's
imported directly and safely.
"""
import json
import os
import pwd
import signal
import subprocess
import sys
import time

import decky

os.environ.setdefault("XDG_CONFIG_HOME", decky.DECKY_PLUGIN_SETTINGS_DIR)

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PY_MODULES_DIR = os.path.join(PLUGIN_DIR, "py_modules")
RUNNER_PATH = os.path.join(PY_MODULES_DIR, "headless_runner.py")
# Matches config.py's own CONFIG_DIR computation (XDG_CONFIG_HOME/dualsense-haptics).
CONFIG_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "dualsense-haptics", "config.json")

sys.path.insert(0, PY_MODULES_DIR)
import presets  # noqa: E402 - pure Python, no evdev dependency, safe here
import bt_hid_proxy  # noqa: E402 - pure Python (no evdev dependency), safe here too


def _kill_stale_headless_runner():
    """Decky can stop/restart plugin_loader, or reload just this plugin,
    without ever SIGTERM-ing an already-spawned headless_runner.py child -
    confirmed on real hardware that the orphan survives indefinitely,
    reparented to init, still holding the controller (locked real device,
    live uhid clone) and fighting any fresh session for it. Called at
    plugin load and before every start_engine(), since a fresh main.py
    process's own self.proc is always None regardless of what an earlier
    incarnation left running. Verifies the PID via /proc/<pid>/cmdline
    before touching it, in case the PID has since been reused by something
    unrelated."""
    pid_file = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "headless_runner.pid")
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read()
    except OSError:
        cmdline = b""
    if b"headless_runner.py" in cmdline:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        else:
            for _ in range(20):
                time.sleep(0.1)
                if not os.path.exists(f"/proc/{pid}"):
                    break
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    try:
        os.remove(pid_file)
    except OSError:
        pass


def _dualsensectl_prefix():
    """Mirrors triggers.py's own helper (not importable here - see module
    docstring, triggers.py pulls in evdev via haptics_engine). Targets the
    proxy clone explicitly once one is active - see bt_hid_proxy.py."""
    uniq = bt_hid_proxy.is_proxy_active()
    return ["-d", uniq] if uniq else []


def _read_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_config(raw):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)


# Mirrors haptics_engine.py's DEFAULT_CONFIG bass/treble(_ceiling) entries -
# not imported directly (see this file's own module docstring), so kept in
# sync by hand like the rest of this file's config fallbacks.
_DEFAULT_BAND = {
    "bass": {"attack": 0.95, "release": 0.5, "lo": 0.010, "hi": 0.12, "gamma": 1.3},
    "treble": {"attack": 0.95, "release": 0.55, "lo": 0.003, "hi": 0.045, "gamma": 0.7},
}
_DEFAULT_CEILING = {
    "bass": {"attack_s": 0.08, "release_s": 2.5},
    "treble": {"attack_s": 0.05, "release_s": 2.0},
}


def _build_custom_args(mode, values):
    """Duplicated from triggers.py (not importable here - see module
    docstring): "end"-style params must exceed their paired "start" param or
    dualsensectl rejects the whole command, so bump it up (clamped to its
    own max) rather than constrain the sliders live."""
    if mode == "off":
        return ["off"]
    spec = presets.TRIGGER_EFFECT_PARAMS[mode]
    bounds = {key: (lo, hi) for key, lo, hi, _default in spec}
    values = dict(values)
    for start_key, end_key in (("start", "end"), ("first_foot", "second_foot")):
        if start_key in values and end_key in values and values[end_key] <= values[start_key]:
            _lo, hi = bounds[end_key]
            values[end_key] = min(values[start_key] + 1, hi)
    cli_mode = presets.TRIGGER_RAW_CLI_NAME.get(mode, mode)
    return [cli_mode] + [str(int(values[key])) for key, _lo, _hi, _default in spec]


class Plugin:
    async def _main(self):
        self.proc = None
        _kill_stale_headless_runner()
        bt_hid_proxy.recover_stale_lock()
        decky.logger.info("DualSense Haptics (Deck) loaded")

    async def _unload(self):
        await self.stop_engine()
        decky.logger.info("DualSense Haptics (Deck) unloaded")

    async def start_engine(self) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            _kill_stale_headless_runner()
            os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
            env = dict(os.environ)
            # Decky's plugin process doesn't inherit a desktop session
            # environment, so parec/paplay/pactl (PipeWire/PulseAudio
            # clients) can't otherwise find the user's audio server socket.
            # With the "root" manifest flag (needed for /dev/uhid access -
            # see bt_hid_proxy.py) this process's own os.getuid() is 0, not
            # the desktop user's - decky.DECKY_USER is the actual logged-in
            # user regardless of which UID we're running as. Passed through
            # so haptics_engine.py's own parec/paplay calls (run from the
            # headless_runner.py child spawned below) know who to run as
            # too - PipeWire refuses a root client outright.
            try:
                target_uid = pwd.getpwnam(decky.DECKY_USER).pw_uid
            except KeyError:
                target_uid = os.getuid()
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{target_uid}")
            env["DUALSENSE_AUDIO_USER"] = decky.DECKY_USER
            self.proc = subprocess.Popen(
                ["/usr/bin/python3", RUNNER_PATH, decky.DECKY_PLUGIN_RUNTIME_DIR],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            )
        return True

    async def stop_engine(self) -> bool:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        return True

    async def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def get_status(self) -> dict:
        result = {
            "running": self.proc is not None and self.proc.poll() is None,
            "status": None, "connection": None,
            "battery_percent": None, "battery_status": None,
        }
        status_file = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "status.json")
        try:
            with open(status_file) as f:
                result.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
        result["running"] = self.proc is not None and self.proc.poll() is None
        return result

    async def list_presets(self) -> list:
        return presets.PRESET_ORDER

    async def get_active_preset(self):
        raw = _read_config() or {}
        ref = raw.get("active_ref", "")
        if ref.startswith("preset:"):
            return ref.split(":", 1)[1]
        return None

    async def apply_preset(self, preset_id: str) -> bool:
        raw = _read_config() or {}
        params = presets.preset_params(preset_id)
        active = raw.setdefault("active", {})
        for key in ("master_gain", "bass_cutoff_hz", "treble_cutoff_hz"):
            active[key] = params[key]
        for band in ("bass", "treble", "bass_ceiling", "treble_ceiling"):
            active[band] = params[band]
        raw["active_ref"] = f"preset:{preset_id}"
        _write_config(raw)
        return True

    async def get_gain(self) -> float:
        raw = _read_config() or {}
        return raw.get("active", {}).get("master_gain", 1.0)

    async def set_gain(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {})["master_gain"] = value
        raw["active_ref"] = "custom"
        _write_config(raw)
        return True

    async def list_profiles(self) -> list:
        raw = _read_config() or {}
        return list(raw.get("profiles", {}).keys())

    async def get_active_profile(self):
        raw = _read_config() or {}
        ref = raw.get("active_ref", "")
        if ref.startswith("profile:"):
            return ref.split(":", 1)[1]
        return None

    async def apply_profile(self, name: str) -> bool:
        raw = _read_config() or {}
        profile = raw.get("profiles", {}).get(name)
        if profile is None:
            return False
        active = raw.setdefault("active", {})
        for key in ("master_gain", "bass_cutoff_hz", "treble_cutoff_hz"):
            if key in profile:
                active[key] = profile[key]
        for band in ("bass", "treble", "bass_ceiling", "treble_ceiling"):
            if band in profile:
                active[band] = profile[band]
        raw["active_ref"] = f"profile:{name}"
        _write_config(raw)
        return True

    async def get_active_ref(self) -> str:
        raw = _read_config() or {}
        return raw.get("active_ref", "custom")

    async def apply_ref(self, ref: str) -> bool:
        """Dispatches a raw active_ref string ("preset:x" / "profile:x") to
        the matching apply_* method - used by the frontend's Steam
        GameSessions hook (see game_profiles below) so it doesn't need to
        parse the ref format itself."""
        if ref.startswith("preset:"):
            return await self.apply_preset(ref.split(":", 1)[1])
        if ref.startswith("profile:"):
            return await self.apply_profile(ref.split(":", 1)[1])
        return False

    async def get_game_profiles(self) -> dict:
        """{app_id (str): {"name": display name, "ref": active_ref string}} -
        which saved settings to auto-apply when a given Steam game launches.
        Deck-only: there's normally exactly one foreground app on a Deck, so
        this doesn't need the desktop's per-audio-source disambiguation."""
        raw = _read_config() or {}
        return raw.get("game_profiles", {})

    async def set_game_profile(self, app_id: str, name: str, ref: str) -> bool:
        raw = _read_config() or {}
        raw.setdefault("game_profiles", {})[app_id] = {"name": name, "ref": ref}
        _write_config(raw)
        return True

    async def get_game_profiles_enabled(self) -> bool:
        """Gates whether a launching game's linked profile (see
        get_game_profiles above) actually gets auto-applied - default True to
        match this feature's original always-on behavior. False means stay on
        whatever preset/profile is manually selected, ignoring any links."""
        raw = _read_config() or {}
        return raw.get("game_profiles_enabled", True)

    async def set_game_profiles_enabled(self, value: bool) -> bool:
        raw = _read_config() or {}
        raw["game_profiles_enabled"] = value
        _write_config(raw)
        return True

    async def list_trigger_presets(self) -> list:
        return presets.TRIGGER_PRESET_ORDER

    async def get_trigger_preset(self, side: str):
        raw = _read_config() or {}
        return raw.get(f"trigger_preset_{side}")

    async def apply_trigger_preset(self, preset_id: str, side: str) -> bool:
        if preset_id not in presets.TRIGGER_PRESETS:
            return False
        args = ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", side] + presets.TRIGGER_PRESETS[preset_id]["args"]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
        raw = _read_config() or {}
        raw[f"trigger_preset_{side}"] = preset_id
        _write_config(raw)
        return True

    async def turn_off_trigger(self, side: str) -> bool:
        try:
            result = subprocess.run(
                ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", side, "off"],
                capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
        raw = _read_config() or {}
        raw[f"trigger_preset_{side}"] = None
        _write_config(raw)
        return True

    async def get_direct_audio(self) -> dict:
        raw = _read_config() or {}
        return raw.get("active", {}).get(
            "direct_audio", {"enabled": True, "gain": 5.0, "bt_enabled": False, "bt_chunk_ms": 20})

    async def set_direct_audio_enabled(self, value: bool) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("direct_audio", {})["enabled"] = value
        _write_config(raw)
        return True

    async def set_direct_audio_bt_enabled(self, value: bool) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("direct_audio", {})["bt_enabled"] = value
        _write_config(raw)
        return True

    async def set_bt_chunk_ms(self, value: int) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("direct_audio", {})["bt_chunk_ms"] = value
        _write_config(raw)
        return True

    async def set_direct_audio_gain(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("direct_audio", {})["gain"] = value
        _write_config(raw)
        return True

    async def get_led_visualizer(self) -> dict:
        raw = _read_config() or {}
        return raw.get("active", {}).get(
            "led_visualizer", {"enabled": False, "attack": 0.5, "release": 0.08, "gamma": 1.8, "bass_priority": 0.6})

    async def set_led_visualizer_enabled(self, value: bool) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("led_visualizer", {})["enabled"] = value
        _write_config(raw)
        return True

    async def set_led_attack(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("led_visualizer", {})["attack"] = value
        _write_config(raw)
        return True

    async def set_led_release(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("led_visualizer", {})["release"] = value
        _write_config(raw)
        return True

    async def set_led_gamma(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("led_visualizer", {})["gamma"] = value
        _write_config(raw)
        return True

    async def set_led_bass_priority(self, value: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("led_visualizer", {})["bass_priority"] = value
        _write_config(raw)
        return True

    async def get_band_settings(self, band: str) -> dict:
        """band is "bass" or "treble" - merges active[band] (lo/hi/attack/
        release/gamma) with active[f"{band}_ceiling"] (attack_s/release_s)
        into one flat dict, matching ui.py's band_group() grouping. Defaults
        match haptics_engine.py's DEFAULT_CONFIG (not imported directly -
        see this file's own module docstring on why evdev-importing modules
        stay out of this process)."""
        raw = _read_config() or {}
        active = raw.get("active", {})
        return {**_DEFAULT_BAND[band], **_DEFAULT_CEILING[band],
                **active.get(band, {}), **active.get(f"{band}_ceiling", {})}

    async def set_band_param(self, band: str, key: str, value: float) -> bool:
        raw = _read_config() or {}
        active = raw.setdefault("active", {})
        target = f"{band}_ceiling" if key in ("attack_s", "release_s") else band
        active.setdefault(target, {})[key] = value
        _write_config(raw)
        return True

    async def get_button_haptics(self) -> dict:
        raw = _read_config() or {}
        return raw.get("active", {}).get("button_haptics", {})

    async def set_button_haptic(self, code: str, enabled: bool, strength: float) -> bool:
        raw = _read_config() or {}
        raw.setdefault("active", {}).setdefault("button_haptics", {})[code] = \
            {"enabled": enabled, "strength": strength}
        _write_config(raw)
        return True

    async def get_custom_trigger(self, side: str):
        raw = _read_config() or {}
        return raw.get(f"trigger_custom_{side}")

    async def apply_custom_trigger(self, mode: str, values: dict, side: str) -> bool:
        args = _build_custom_args(mode, values)
        try:
            result = subprocess.run(
                ["dualsensectl"] + _dualsensectl_prefix() + ["trigger", side] + args,
                capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
        raw = _read_config() or {}
        raw[f"trigger_preset_{side}"] = "custom" if mode != "off" else None
        raw[f"trigger_custom_{side}"] = {"mode": mode, "values": values}
        _write_config(raw)
        return True

    async def get_language(self) -> str:
        raw = _read_config() or {}
        return raw.get("language", "en")

    async def set_language(self, code: str) -> bool:
        raw = _read_config() or {}
        raw["language"] = code
        _write_config(raw)
        return True
