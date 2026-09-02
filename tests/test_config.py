"""Tests for config.py: default state, save/load roundtrip, and - most
importantly - the legacy-format migrations, which only ever run on real
users' old config files and so are exactly the code nobody exercises when
developing against a fresh checkout."""
import json

import pytest

import config
from haptics_engine import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    return tmp_path


def _write_raw(data):
    config.CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False))


class TestMergeDefaults:
    def test_fills_missing_keys_with_deep_copies(self):
        cfg = {}
        config._merge_defaults(cfg, DEFAULT_CONFIG)
        assert cfg["bass"] == DEFAULT_CONFIG["bass"]
        cfg["bass"]["gamma"] = 999
        assert DEFAULT_CONFIG["bass"]["gamma"] != 999

    def test_keeps_existing_values(self):
        cfg = {"master_gain": 2.5, "bass": {"gamma": 3.0}}
        config._merge_defaults(cfg, DEFAULT_CONFIG)
        assert cfg["master_gain"] == 2.5
        assert cfg["bass"]["gamma"] == 3.0
        # sibling keys inside the nested dict still get filled in
        assert cfg["bass"]["attack"] == DEFAULT_CONFIG["bass"]["attack"]


class TestDefaultState:
    def test_no_file_yields_balanced_preset(self):
        state = config.load_state()
        assert state["active_ref"] == "preset:balanced"
        assert state["profiles"] == {}
        assert state["trigger_auto_reconnect"] is True
        assert state["theme"] == "system"

    def test_active_carries_full_engine_schema(self):
        # preset params only define DSP fields; the merge must add the rest
        # (button_haptics, direct_audio, ...) so the engine never KeyErrors
        state = config.load_state()
        assert set(DEFAULT_CONFIG) <= set(state["active"])

    def test_unreadable_json_falls_back_to_defaults(self):
        config.CONFIG_FILE.write_text("{not json")
        state = config.load_state()
        assert state["active_ref"] == "preset:balanced"


class TestRoundtrip:
    def test_save_then_load_preserves_state(self):
        state = config.load_state()
        state["active"]["master_gain"] = 1.7
        state["active_ref"] = "custom"
        state["profiles"]["Мой"] = dict(state["active"])
        state["trigger_preset_left"] = "bow"
        state["trigger_custom_right"] = {"mode": "vibration", "params": {"position": 1}}
        state["theme"] = "dark"
        state["language"] = "ru"
        config.save_state(state)

        loaded = config.load_state()
        assert loaded["active"]["master_gain"] == 1.7
        assert loaded["active_ref"] == "custom"
        assert "Мой" in loaded["profiles"]
        assert loaded["trigger_preset_left"] == "bow"
        assert loaded["trigger_preset_right"] is None
        assert loaded["trigger_custom_right"] == {"mode": "vibration", "params": {"position": 1}}
        assert loaded["theme"] == "dark"
        assert loaded["language"] == "ru"

    def test_loaded_profiles_get_missing_defaults_filled(self):
        state = config.load_state()
        state["profiles"]["old"] = {"master_gain": 0.5}  # pre-button_haptics profile
        config.save_state(state)
        loaded = config.load_state()
        assert loaded["profiles"]["old"]["master_gain"] == 0.5
        assert "button_haptics" in loaded["profiles"]["old"]


class TestLegacyMigrations:
    def test_flat_params_become_a_named_profile(self):
        # the original pre-presets format: engine params at the top level
        _write_raw({"master_gain": 1.4, "bass": {"gamma": 2.0}})
        state = config.load_state()
        assert state["active"]["master_gain"] == 1.4
        assert state["active_ref"] == "profile:Мои настройки"
        assert state["profiles"]["Мои настройки"]["master_gain"] == 1.4
        # and the migrated params still get the full schema merged in
        assert "direct_audio" in state["active"]

    def test_single_button_haptic_becomes_multi_button_entry(self):
        _write_raw({
            "active": {"button_haptic": {"button_code": 304, "enabled": True, "strength": 0.6}},
            "active_ref": "custom",
        })
        state = config.load_state()
        assert "button_haptic" not in state["active"]
        assert state["active"]["button_haptics"]["304"] == {"enabled": True, "strength": 0.6}

    def test_button_haptic_without_code_is_dropped(self):
        _write_raw({"active": {"button_haptic": {"button_code": None, "enabled": True}},
                    "active_ref": "custom"})
        state = config.load_state()
        assert state["active"]["button_haptics"] == {}

    def test_single_trigger_preset_applies_to_both_sides(self):
        _write_raw({"active": {}, "trigger_preset": "weapon"})
        state = config.load_state()
        assert state["trigger_preset_left"] == "weapon"
        assert state["trigger_preset_right"] == "weapon"

    def test_per_side_trigger_presets_pass_through(self):
        _write_raw({"active": {}, "trigger_preset_left": "soft", "trigger_preset_right": None})
        state = config.load_state()
        assert state["trigger_preset_left"] == "soft"
        assert state["trigger_preset_right"] is None
