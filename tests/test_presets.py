"""Data-integrity tests for presets.py: every preset stays consistent with
DEFAULT_CONFIG's schema, and every trigger preset stays inside dualsensectl's
own documented validation ranges (main.c), so adding/tuning a preset can't
silently produce a config the engine or dualsensectl rejects."""
import pytest

from haptics_engine import DEFAULT_CONFIG
from presets import (
    PRESET_ORDER,
    PRESETS,
    TRIGGER_EFFECT_ORDER,
    TRIGGER_EFFECT_PARAMS,
    TRIGGER_PRESET_ORDER,
    TRIGGER_PRESETS,
    TRIGGER_RAW_CLI_NAME,
    preset_params,
)


class TestPresets:
    def test_order_covers_exactly_the_defined_presets(self):
        assert sorted(PRESET_ORDER) == sorted(PRESETS)
        assert len(set(PRESET_ORDER)) == len(PRESET_ORDER)

    def test_preset_params_returns_an_independent_copy(self):
        params = preset_params("balanced")
        params["bass"]["gamma"] = 999
        assert PRESETS["balanced"]["params"]["bass"]["gamma"] != 999

    @pytest.mark.parametrize("preset_id", sorted(PRESETS))
    def test_params_are_a_subset_of_the_engine_schema(self, preset_id):
        params = PRESETS[preset_id]["params"]
        assert set(params) <= set(DEFAULT_CONFIG)
        for key in ("bass", "treble", "bass_ceiling", "treble_ceiling"):
            assert set(params[key]) == set(DEFAULT_CONFIG[key])

    @pytest.mark.parametrize("preset_id", sorted(PRESETS))
    def test_band_shapes_are_sane(self, preset_id):
        params = PRESETS[preset_id]["params"]
        for band in ("bass", "treble"):
            b = params[band]
            assert 0.0 < b["attack"] <= 1.0
            assert 0.0 < b["release"] <= 1.0
            assert 0.0 <= b["lo"] < b["hi"], f"{band} gate must sit below its ceiling"
            assert b["gamma"] > 0
        assert params["master_gain"] > 0
        assert params["bass_cutoff_hz"] < params["treble_cutoff_hz"]


# dualsensectl main.c validation, quoted in presets.py's own comment.
def _check_feedback(a):
    position, strength = map(int, a)
    assert 0 <= position <= 9 and 1 <= strength <= 8


def _check_weapon(a):
    start, end, strength = map(int, a)
    assert 2 <= start <= 7 and start < end <= 8 and 1 <= strength <= 8


def _check_bow(a):
    start, end, strength, snap = map(int, a)
    assert 1 <= start <= 8 and start < end <= 8
    assert 1 <= strength <= 8 and 1 <= snap <= 8


def _check_machine(a):
    start, end, str_a, str_b, freq, period = map(int, a)
    assert 1 <= start <= 8 and start < end <= 9
    assert 0 <= str_a <= 7 and 0 <= str_b <= 7 and freq > 0


def _check_galloping(a):
    start, end, first, second, freq = map(int, a)
    assert 0 <= start <= 8 and start < end <= 9
    assert 0 <= first <= 6 and first < second <= 7 and freq > 0


def _check_vibration(a):
    position, amplitude, freq = map(int, a)
    assert 0 <= position <= 9 and 1 <= amplitude <= 8 and freq > 0


_MODE_CHECKS = {
    "feedback": _check_feedback,
    "weapon": _check_weapon,
    "bow": _check_bow,
    "machine": _check_machine,
    "galloping": _check_galloping,
    "vibration": _check_vibration,
}


class TestTriggerPresets:
    def test_order_covers_exactly_the_defined_presets(self):
        assert sorted(TRIGGER_PRESET_ORDER) == sorted(TRIGGER_PRESETS)
        assert len(set(TRIGGER_PRESET_ORDER)) == len(TRIGGER_PRESET_ORDER)

    @pytest.mark.parametrize("preset_id", sorted(TRIGGER_PRESETS))
    def test_args_pass_dualsensectl_validation(self, preset_id):
        mode, *args = TRIGGER_PRESETS[preset_id]["args"]
        assert mode in _MODE_CHECKS, f"unknown dualsensectl mode {mode!r}"
        _MODE_CHECKS[mode](args)


class TestTriggerEffectBuilder:
    def test_order_covers_exactly_the_defined_modes(self):
        assert sorted(TRIGGER_EFFECT_ORDER) == sorted(TRIGGER_EFFECT_PARAMS)

    @pytest.mark.parametrize("mode", sorted(TRIGGER_EFFECT_PARAMS))
    def test_defaults_sit_inside_their_own_slider_range(self, mode):
        for key, lo, hi, default in TRIGGER_EFFECT_PARAMS[mode]:
            assert lo <= default <= hi, f"{mode}.{key}"
            assert lo < hi or (lo == hi == default)

    @pytest.mark.parametrize("mode", sorted(TRIGGER_EFFECT_PARAMS))
    def test_param_keys_are_unique(self, mode):
        keys = [key for key, *_ in TRIGGER_EFFECT_PARAMS[mode]]
        assert len(keys) == len(set(keys))

    def test_raw_modes_have_cli_spellings(self):
        assert set(TRIGGER_RAW_CLI_NAME) == {"feedback_raw", "vibration_raw"}
        for internal, cli in TRIGGER_RAW_CLI_NAME.items():
            assert internal in TRIGGER_EFFECT_PARAMS
            assert cli == internal.replace("_", "-")
