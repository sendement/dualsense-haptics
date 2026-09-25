"""Tests for app_audio_binding.py's pure decision logic - purely audio-
source narrowing, with no notion of presets/profiles at all, and at most
one selected app ever (mixing multiple sources is never possible). Anything
that actually shells out to pactl needs a real PipeWire/Pulse system and
isn't exercised here - the watcher's tap lifecycle decisions (grace period,
teardown safety) are instead driven through a fake pactl and a fake clock."""
import types

import pytest

import app_audio_binding as aab


class TestDecide:
    def test_nothing_selected_is_global(self):
        assert aab._decide(None, set()) is False

    def test_selected_app_open_narrows_to_it(self):
        assert aab._decide("mpv", {"mpv"}) is True

    def test_selected_app_not_open_is_global(self):
        assert aab._decide("mpv", set()) is False


class TestBinaryName:
    def test_prefers_process_binary_over_application_name(self):
        si = {"properties": {"application.process.binary": "mpv", "application.name": "mpv media player"}}
        assert aab._binary_name(si) == "mpv"

    def test_falls_back_to_application_name(self):
        si = {"properties": {"application.name": "Firefox"}}
        assert aab._binary_name(si) == "Firefox"

    def test_no_properties_yields_none(self):
        assert aab._binary_name({}) is None


class _Harness:
    """A watcher whose pactl-facing helpers and clock are faked out, so the
    tap lifecycle can be stepped through deterministically."""

    def __init__(self, monkeypatch, selected="game"):
        self.now = 100.0
        self.open_apps = set()
        self.created = 0
        self.reverted = 0
        self.state = {"app_audio_binding_selected": selected}
        self.box = {"source": None}
        monkeypatch.setattr(aab, "time", types.SimpleNamespace(
            monotonic=lambda: self.now, sleep=lambda s: None))
        monkeypatch.setattr(aab, "_snapshot_open_apps",
                            lambda names: (set(names) & self.open_apps, {}))
        monkeypatch.setattr(aab, "_create_tap_modules", self._create)
        monkeypatch.setattr(aab, "_revert_any_stray_routing_and_teardown", self._revert)
        monkeypatch.setattr(aab, "_all_tap_sink_indices", lambda: [])
        self.watcher = aab._AppAudioBindingThread(self.state, self.box)

    def _create(self):
        self.created += 1

    def _revert(self):
        self.reverted += 1

    def tick(self, advance=0.0):
        self.now += advance
        self.watcher._recompute()


class TestTapGracePeriod:
    def test_a_flapping_stream_does_not_rebuild_the_tap(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game"}
        h.tick()
        assert h.created == 1
        assert h.box["source"] == f"{aab._NULL_SINK_NAME}.monitor"

        for _ in range(6):  # stream closes and reopens well inside the grace period
            h.open_apps = set()
            h.tick(advance=0.5)
            h.open_apps = {"game"}
            h.tick(advance=0.5)

        assert h.created == 1
        assert h.reverted == 0
        assert h.box["source"] == f"{aab._NULL_SINK_NAME}.monitor"

    def test_tap_is_held_through_the_grace_period_then_torn_down(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game"}
        h.tick()
        h.open_apps = set()

        h.tick(advance=1.0)
        h.tick(advance=aab._TEARDOWN_GRACE_S - 1.5)
        assert h.reverted == 0
        assert h.box["source"] is not None

        h.tick(advance=2.0)
        assert h.reverted == 1
        assert h.box["source"] is None

    def test_grace_timer_restarts_after_the_stream_comes_back(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game"}
        h.tick()
        h.open_apps = set()
        h.tick(advance=aab._TEARDOWN_GRACE_S - 0.5)
        h.open_apps = {"game"}
        h.tick(advance=0.2)
        h.open_apps = set()
        h.tick(advance=0.2)
        h.tick(advance=aab._TEARDOWN_GRACE_S - 1.0)
        assert h.reverted == 0  # counted from the second disappearance, not the first

    def test_switching_selection_to_global_reverts_immediately(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game"}
        h.tick()
        h.state["app_audio_binding_selected"] = None
        h.tick(advance=0.1)
        assert h.reverted == 1
        assert h.box["source"] is None

    def test_switching_to_an_app_that_is_not_open_reverts_immediately(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game"}
        h.tick()
        h.state["app_audio_binding_selected"] = "browser"
        h.tick(advance=0.1)
        assert h.reverted == 1

    def test_switching_between_two_open_apps_reuses_the_tap(self, monkeypatch):
        h = _Harness(monkeypatch)
        h.open_apps = {"game", "browser"}
        h.tick()
        h.state["app_audio_binding_selected"] = "browser"
        h.tick(advance=0.1)
        assert h.created == 1
        assert h.reverted == 0
        assert h.watcher._narrowed_app == "browser"


class TestIdleWhenGlobal:
    def test_nothing_selected_and_nothing_narrowed_never_touches_pactl(self, monkeypatch):
        h = _Harness(monkeypatch, selected=None)
        monkeypatch.setattr(aab, "_snapshot_open_apps",
                            lambda names: pytest.fail("pactl was queried while idle on Global"))
        h.tick()
        h.tick(advance=5)
        assert h.created == 0
        assert h.box["source"] is None


class TestTeardownSafety:
    def _fake_pactl(self, monkeypatch, stragglers_per_check):
        calls = []
        checks = iter(stragglers_per_check)
        monkeypatch.setattr(aab, "time", types.SimpleNamespace(
            monotonic=lambda: 0.0, sleep=lambda s: None))
        monkeypatch.setattr(aab, "_all_tap_sink_indices", lambda: [7])
        monkeypatch.setattr(aab, "_list_json", lambda *a: [
            {"index": i, "sink": 7} for i in next(checks, [])])
        monkeypatch.setattr(aab, "_run_pactl", lambda *a, **k: calls.append(("pactl", *a)) or (True, ""))
        monkeypatch.setattr(aab, "_teardown_tap_modules", lambda: calls.append(("teardown",)))
        return calls

    def test_streams_on_the_tap_are_moved_off_before_unloading(self, monkeypatch):
        calls = self._fake_pactl(monkeypatch, [[11, 12], []])
        aab._revert_any_stray_routing_and_teardown()
        assert calls == [
            ("pactl", "move-sink-input", "11", "@DEFAULT_SINK@"),
            ("pactl", "move-sink-input", "12", "@DEFAULT_SINK@"),
            ("teardown",),
        ]

    def test_a_stream_that_lands_on_the_tap_mid_teardown_is_caught_by_the_recheck(self, monkeypatch):
        calls = self._fake_pactl(monkeypatch, [[11], [21], []])
        aab._revert_any_stray_routing_and_teardown()
        moves = [c[2] for c in calls if c[0] == "pactl"]
        assert moves == ["11", "21"]
        assert calls[-1] == ("teardown",)

    def test_recheck_budget_is_bounded_and_teardown_still_happens(self, monkeypatch):
        calls = self._fake_pactl(monkeypatch, [[1]] * 50)
        aab._revert_any_stray_routing_and_teardown()
        assert len([c for c in calls if c[0] == "pactl"]) == aab._TEARDOWN_RECHECKS
        assert calls[-1] == ("teardown",)
