"""dualsensectl reports a failed hid_write on stderr but still exits 0 (0.7.0),
so a trigger command can look successful without ever reaching the
controller. The Deck backend (deck-plugin/main.py) keeps its own copy of the
check - it can't import triggers/evdev - so a test pins the two together."""
import ast
import types
from pathlib import Path

import pytest

import triggers

REPO_ROOT = Path(__file__).resolve().parent.parent


def result(returncode=0, stderr=""):
    return types.SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")


CASES = [
    (result(0, ""), None),
    (result(0, "   \n"), None),
    (result(0, "some harmless notice"), None),
    (result(1, ""), "dualsensectl failed"),
    (result(1, "No device found"), "No device found"),
    (result(0, "hid_write() failed: Input/output error"), "hid_write() failed: Input/output error"),
    (result(0, "HID_WRITE error -1"), "HID_WRITE error -1"),
]


@pytest.mark.parametrize("res,expected", CASES)
def test_dualsensectl_error(res, expected):
    assert triggers.dualsensectl_error(res) == expected


def _deck_helper():
    source = (REPO_ROOT / "deck-plugin" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_dualsensectl_error")
    namespace = {}
    exec(compile(ast.Module(body=[func], type_ignores=[]), "deck-plugin/main.py", "exec"), namespace)
    return namespace["_dualsensectl_error"]


@pytest.mark.parametrize("res,expected", CASES)
def test_deck_backend_copy_agrees_with_triggers(res, expected):
    assert _deck_helper()(res) == expected


class TestApplyFunctionsReportUndeliveredCommands:
    @pytest.fixture(autouse=True)
    def _no_proxy(self, monkeypatch):
        monkeypatch.setattr(triggers, "_dualsensectl_prefix", lambda: [])

    def _run_returns(self, monkeypatch, res):
        monkeypatch.setattr(triggers.subprocess, "run", lambda *a, **k: res)

    def test_preset_with_a_logged_write_failure_is_not_success(self, monkeypatch):
        self._run_returns(monkeypatch, result(0, "hid_write() failed: Input/output error"))
        ok, err = triggers.apply_trigger_preset("hard_wall", "left")
        assert ok is False and "hid_write" in err

    def test_custom_effect_with_a_logged_write_failure_is_not_success(self, monkeypatch):
        self._run_returns(monkeypatch, result(0, "hid_write() failed"))
        ok, err = triggers.apply_custom_trigger("off", {}, "right")
        assert ok is False and "hid_write" in err

    def test_turning_off_with_a_logged_write_failure_is_not_success(self, monkeypatch):
        self._run_returns(monkeypatch, result(0, "hid_write() failed"))
        ok, err = triggers.turn_off_triggers("left")
        assert ok is False and "hid_write" in err

    def test_clean_run_is_still_success(self, monkeypatch):
        self._run_returns(monkeypatch, result(0, ""))
        assert triggers.apply_trigger_preset("hard_wall", "left") == (True, "")
        assert triggers.turn_off_triggers("left") == (True, "")
