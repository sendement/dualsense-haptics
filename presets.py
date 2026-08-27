"""Built-in presets: ready-made parameter sets for the haptics engine.

Display text (label/description) lives in i18n.py, keyed off each preset id
as `preset_<id>_label` / `preset_<id>_desc` (and `trigger_<id>_label` /
`trigger_<id>_desc` for trigger presets) - this module only holds data.
"""
import copy

PRESETS = {
    "balanced": {
        "params": {
            "master_gain": 1.0,
            "bass_cutoff_hz": 90, "treble_cutoff_hz": 500,
            "bass": {"attack": 0.95, "release": 0.5, "lo": 0.010, "hi": 0.12, "gamma": 1.3},
            "treble": {"attack": 0.95, "release": 0.55, "lo": 0.003, "hi": 0.045, "gamma": 0.7},
            "bass_ceiling": {"attack_s": 0.08, "release_s": 2.5},
            "treble_ceiling": {"attack_s": 0.05, "release_s": 2.0},
        },
    },
    "cinema": {
        "params": {
            "master_gain": 1.1,
            "bass_cutoff_hz": 90, "treble_cutoff_hz": 500,
            "bass": {"attack": 0.95, "release": 0.45, "lo": 0.020, "hi": 0.16, "gamma": 1.6},
            "treble": {"attack": 0.9, "release": 0.5, "lo": 0.006, "hi": 0.08, "gamma": 1.0},
            "bass_ceiling": {"attack_s": 0.10, "release_s": 3.0},
            "treble_ceiling": {"attack_s": 0.08, "release_s": 2.5},
        },
    },
    "music": {
        "params": {
            "master_gain": 1.2,
            "bass_cutoff_hz": 90, "treble_cutoff_hz": 500,
            "bass": {"attack": 0.97, "release": 0.6, "lo": 0.008, "hi": 0.10, "gamma": 1.1},
            "treble": {"attack": 0.97, "release": 0.6, "lo": 0.0025, "hi": 0.04, "gamma": 0.8},
            "bass_ceiling": {"attack_s": 0.06, "release_s": 1.5},
            "treble_ceiling": {"attack_s": 0.04, "release_s": 1.2},
        },
    },
    "voice": {
        "params": {
            "master_gain": 1.0,
            "bass_cutoff_hz": 90, "treble_cutoff_hz": 500,
            "bass": {"attack": 0.95, "release": 0.5, "lo": 0.025, "hi": 0.22, "gamma": 1.8},
            "treble": {"attack": 0.95, "release": 0.55, "lo": 0.003, "hi": 0.045, "gamma": 0.7},
            "bass_ceiling": {"attack_s": 0.08, "release_s": 2.5},
            "treble_ceiling": {"attack_s": 0.05, "release_s": 2.0},
        },
    },
    "max": {
        "params": {
            "master_gain": 1.3,
            "bass_cutoff_hz": 90, "treble_cutoff_hz": 500,
            "bass": {"attack": 0.97, "release": 0.6, "lo": 0.004, "hi": 0.05, "gamma": 0.8},
            "treble": {"attack": 0.97, "release": 0.65, "lo": 0.0015, "hi": 0.02, "gamma": 0.6},
            "bass_ceiling": {"attack_s": 0.3, "release_s": 1.0},
            "treble_ceiling": {"attack_s": 0.3, "release_s": 1.0},
        },
    },
}

PRESET_ORDER = ["balanced", "cinema", "music", "voice", "max"]


def preset_params(preset_id):
    return copy.deepcopy(PRESETS[preset_id]["params"])


# Adaptive trigger presets. "args" are passed straight to
# `dualsensectl trigger <left|right|both> <args...>` - see triggers.py.
# Parameter ranges come from dualsensectl's own validation (main.c):
#   feedback POSITION(0-9) STRENGTH(1-8)
#   weapon START(2-7) END(start+1..8) STRENGTH(1-8)
#   bow START(1-8) END(start+1..8) STRENGTH(1-8) SNAP(1-8)
#   machine START(1-8) END(start+1..9) STRENGTH_A(0-7) STRENGTH_B(0-7) FREQ(>0) PERIOD
#   galloping START(0-8) END(start+1..9) FIRST_FOOT(0-6) SECOND_FOOT(first+1..7) FREQ(>0, best <8)
#   vibration POSITION(0-9) AMPLITUDE(1-8) FREQUENCY(>0)
TRIGGER_PRESETS = {
    "soft": {"args": ["feedback", "2", "3"]},
    "hard_wall": {"args": ["feedback", "7", "8"]},
    "weapon": {"args": ["weapon", "3", "6", "6"]},
    "bow": {"args": ["bow", "2", "7", "6", "8"]},
    "machine": {"args": ["machine", "2", "8", "1", "7", "4", "2"]},
    "clicker": {"args": ["vibration", "1", "6", "3"]},
    "gallop": {"args": ["galloping", "1", "8", "3", "5", "5"]},
}

TRIGGER_PRESET_ORDER = ["soft", "hard_wall", "weapon", "bow", "machine", "clicker", "gallop"]
