"""Unit tests for the pure DSP / feedback-shaping math in haptics_engine.py.

These pin the current, hardware-validated behavior so refactors can be
checked without a controller attached.
"""
import math

import pytest

import haptics_engine as he
from haptics_engine import (
    DPAD_VIRTUAL_CODE,
    LEFT_STICK_VIRTUAL_CODE,
    LEFT_TRIGGER_VIRTUAL_CODE,
    RIGHT_STICK_VIRTUAL_CODE,
    RIGHT_TRIGGER_VIRTUAL_CODE,
    STICK_DEADZONE,
    _analog_held_scale,
    _button_click_targets,
    _deadzone_rescale,
    _led_smooth,
    ceiling_step,
    lowpass_block,
    peak,
    shape,
)
from evdev import ecodes


class TestPeak:
    def test_empty_is_silence(self):
        assert peak([]) == 0.0

    def test_full_scale_negative(self):
        assert peak([0, -32768, 100]) == 1.0

    def test_half_scale(self):
        assert peak([16384]) == pytest.approx(0.5)

    def test_uses_absolute_maximum(self):
        assert peak([-30000, 10000]) == pytest.approx(30000 / 32768.0)


class TestLowpassBlock:
    def test_empty_block_passes_state_through(self):
        y, out = lowpass_block([], 0.25, 90, 8000)
        assert y == 0.25
        assert out == []

    def test_dc_input_converges_to_input(self):
        y, out = lowpass_block([1000.0] * 4000, 0.0, 500, 8000)
        assert out == sorted(out)  # monotonic rise, no overshoot
        assert out[-1] == y
        assert y == pytest.approx(1000.0, rel=1e-3)

    def test_lower_cutoff_responds_slower(self):
        _, slow = lowpass_block([1000.0] * 10, 0.0, 90, 8000)
        _, fast = lowpass_block([1000.0] * 10, 0.0, 500, 8000)
        assert slow[-1] < fast[-1]

    def test_zero_cutoff_is_clamped_not_division_error(self):
        y, out = lowpass_block([100.0], 0.0, 0, 8000)
        assert 0.0 < y < 100.0


class TestCeilingStep:
    def test_level_above_ceiling_yields_positive_delta(self):
        ceiling, delta = ceiling_step(0.8, 0.2, 0.08, 2.5, 50)
        assert delta == pytest.approx(0.6)
        assert 0.2 < ceiling < 0.8  # chased upward, not snapped

    def test_level_below_ceiling_decays_with_zero_delta(self):
        ceiling, delta = ceiling_step(0.1, 0.5, 0.08, 2.5, 50)
        assert delta == 0.0
        assert 0.1 < ceiling < 0.5

    def test_attack_and_release_rates_match_time_constants(self):
        rise, _ = ceiling_step(1.0, 0.0, 0.08, 2.5, 50)
        assert rise == pytest.approx(1 - math.exp(-1.0 / (0.08 * 50)))
        fall, _ = ceiling_step(0.0, 1.0, 0.08, 2.5, 50)
        assert fall == pytest.approx(math.exp(-1.0 / (2.5 * 50)))

    def test_tiny_time_constants_are_clamped(self):
        ceiling, _ = ceiling_step(1.0, 0.0, 0.0, 0.0, 50)
        assert 0.0 < ceiling <= 1.0


BASS_PARAMS = {"attack": 0.95, "release": 0.5, "lo": 0.010, "hi": 0.12, "gamma": 1.3}


class TestShape:
    def test_below_gate_outputs_zero(self):
        env, out = shape(0.005, 0.005, BASS_PARAMS)
        assert out == 0.0

    def test_above_hi_clamps_to_full(self):
        env, out = shape(0.5, 0.5, BASS_PARAMS)
        assert out == 1.0

    def test_rising_level_uses_attack_coefficient(self):
        env, _ = shape(1.0, 0.0, BASS_PARAMS)
        assert env == pytest.approx(0.95)

    def test_falling_level_uses_release_coefficient(self):
        env, _ = shape(0.0, 1.0, BASS_PARAMS)
        assert env == pytest.approx(0.5)

    def test_gamma_shapes_midrange(self):
        # halfway between lo and hi, held steady: x = 0.5 -> 0.5 ** gamma
        mid = (BASS_PARAMS["lo"] + BASS_PARAMS["hi"]) / 2
        _, out = shape(mid, mid, BASS_PARAMS)
        assert out == pytest.approx(0.5 ** BASS_PARAMS["gamma"])

    def test_degenerate_band_outputs_zero(self):
        params = dict(BASS_PARAMS, lo=0.1, hi=0.1)
        _, out = shape(0.5, 0.5, params)
        assert out == 0.0


class TestLedSmooth:
    def test_rising_uses_attack(self):
        env, shown = _led_smooth(1.0, 0.0, attack=0.5, release=0.08, gamma=1.0)
        assert env == pytest.approx(0.5)
        assert shown == pytest.approx(0.5)

    def test_falling_uses_release(self):
        env, _ = _led_smooth(0.0, 1.0, attack=0.5, release=0.08, gamma=1.0)
        assert env == pytest.approx(0.92)

    def test_gamma_mutes_low_levels(self):
        _, shown = _led_smooth(0.25, 0.25, attack=0.5, release=0.08, gamma=1.8)
        assert shown == pytest.approx(0.25 ** 1.8)
        assert shown < 0.25


class TestDeadzoneRescale:
    def test_inside_deadzone_is_zero(self):
        assert _deadzone_rescale(0.10, 0.15) == 0.0

    def test_at_deadzone_edge_starts_from_zero(self):
        assert _deadzone_rescale(0.15, 0.15) == 0.0

    def test_full_deflection_is_full(self):
        assert _deadzone_rescale(1.0, 0.15) == 1.0

    def test_ramps_from_edge_not_jumps(self):
        just_past = _deadzone_rescale(0.16, 0.15)
        assert 0.0 < just_past < 0.05

    def test_clamps_overrange(self):
        assert _deadzone_rescale(1.5, 0.15) == 1.0


def _synthetic_axes():
    """axis_info/raw as _init_analog_raw would build them for a 0..255
    controller: sticks rest centered at 128, triggers rest at 0."""
    axis_info = {}
    raw = {}
    for code in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY):
        axis_info[code] = (127.5, 127.5)
        raw[code] = 127.5
    for code in (ecodes.ABS_Z, ecodes.ABS_RZ):
        axis_info[code] = (0, 255)
        raw[code] = 0
    return raw, axis_info


class TestAnalogHeldScale:
    def test_all_at_rest_is_all_zero(self):
        raw, axis_info = _synthetic_axes()
        scale = _analog_held_scale(raw, axis_info)
        assert set(scale) == {
            LEFT_STICK_VIRTUAL_CODE, RIGHT_STICK_VIRTUAL_CODE,
            LEFT_TRIGGER_VIRTUAL_CODE, RIGHT_TRIGGER_VIRTUAL_CODE,
        }
        assert all(v == 0.0 for v in scale.values())

    def test_full_stick_deflection_is_full_scale(self):
        raw, axis_info = _synthetic_axes()
        raw[ecodes.ABS_X] = 255
        scale = _analog_held_scale(raw, axis_info)
        assert scale[LEFT_STICK_VIRTUAL_CODE] == 1.0
        assert scale[RIGHT_STICK_VIRTUAL_CODE] == 0.0

    def test_diagonal_uses_2d_magnitude(self):
        raw, axis_info = _synthetic_axes()
        # ~0.42 on each axis -> hypot ~0.6, past the deadzone
        raw[ecodes.ABS_RX] = 127.5 + 54
        raw[ecodes.ABS_RY] = 127.5 - 54
        scale = _analog_held_scale(raw, axis_info)
        norm = math.hypot(54 / 127.5, 54 / 127.5)
        expected = (norm - STICK_DEADZONE) / (1.0 - STICK_DEADZONE)
        assert scale[RIGHT_STICK_VIRTUAL_CODE] == pytest.approx(expected)

    def test_trigger_pull_is_unipolar(self):
        raw, axis_info = _synthetic_axes()
        raw[ecodes.ABS_RZ] = 255
        scale = _analog_held_scale(raw, axis_info)
        assert scale[RIGHT_TRIGGER_VIRTUAL_CODE] == 1.0
        assert scale[LEFT_TRIGGER_VIRTUAL_CODE] == 0.0


class TestButtonClickTargets:
    def _cfg(self, entries):
        return {"button_haptics": entries}

    def test_no_buttons_configured(self):
        result = _button_click_targets(self._cfg({}), {}, default_hz=150)
        assert result == (0.0, 150, 0.0, 150)

    def test_sides_route_to_their_own_motor(self):
        cfg = self._cfg({
            str(ecodes.BTN_TL): {"enabled": True, "strength": 0.5, "click_hz": 200},
            str(ecodes.BTN_SOUTH): {"enabled": True, "strength": 0.7, "click_hz": 90},
        })
        held = {ecodes.BTN_TL: True, ecodes.BTN_SOUTH: True}
        strong, strong_hz, weak, weak_hz = _button_click_targets(cfg, held, 150)
        assert (strong, strong_hz) == (0.5, 200)  # L1 -> left/strong motor
        assert (weak, weak_hz) == (0.7, 90)       # Cross -> right/weak motor

    def test_strongest_held_button_wins_per_side(self):
        cfg = self._cfg({
            str(ecodes.BTN_SOUTH): {"enabled": True, "strength": 0.3, "click_hz": 100},
            str(ecodes.BTN_EAST): {"enabled": True, "strength": 0.8, "click_hz": 300},
        })
        held = {ecodes.BTN_SOUTH: True, ecodes.BTN_EAST: True}
        _, _, weak, weak_hz = _button_click_targets(cfg, held, 150)
        assert (weak, weak_hz) == (0.8, 300)

    def test_disabled_and_unheld_are_ignored(self):
        cfg = self._cfg({
            str(ecodes.BTN_SOUTH): {"enabled": False, "strength": 0.9},
            str(ecodes.BTN_EAST): {"enabled": True, "strength": 0.9},
        })
        held = {ecodes.BTN_SOUTH: True}  # EAST enabled but not held
        assert _button_click_targets(cfg, held, 150) == (0.0, 150, 0.0, 150)

    def test_held_scale_makes_stick_feedback_proportional(self):
        cfg = self._cfg({
            str(LEFT_STICK_VIRTUAL_CODE): {"enabled": True, "strength": 0.8, "click_hz": 120},
        })
        held = {LEFT_STICK_VIRTUAL_CODE: True}
        strong, strong_hz, _, _ = _button_click_targets(
            cfg, held, 150, held_scale={LEFT_STICK_VIRTUAL_CODE: 0.5})
        assert strong == pytest.approx(0.4)
        assert strong_hz == 120

    def test_dpad_virtual_code_feeds_strong_motor(self):
        cfg = self._cfg({str(DPAD_VIRTUAL_CODE): {"enabled": True, "strength": 0.6}})
        strong, _, weak, _ = _button_click_targets(cfg, {DPAD_VIRTUAL_CODE: True}, 150)
        assert (strong, weak) == (0.6, 0.0)


class TestButtonSideTable:
    def test_every_virtual_code_has_a_side(self):
        for code in (DPAD_VIRTUAL_CODE, LEFT_STICK_VIRTUAL_CODE, RIGHT_STICK_VIRTUAL_CODE,
                     LEFT_TRIGGER_VIRTUAL_CODE, RIGHT_TRIGGER_VIRTUAL_CODE):
            assert code in he.BUTTON_SIDE

    def test_sides_are_only_strong_or_weak(self):
        assert set(he.BUTTON_SIDE.values()) <= {"strong", "weak"}

    def test_left_hand_side_is_strong_right_is_weak(self):
        assert he.BUTTON_SIDE[ecodes.BTN_TL] == "strong"
        assert he.BUTTON_SIDE[ecodes.BTN_THUMBL] == "strong"
        assert he.BUTTON_SIDE[ecodes.BTN_TR] == "weak"
        assert he.BUTTON_SIDE[ecodes.BTN_SOUTH] == "weak"
