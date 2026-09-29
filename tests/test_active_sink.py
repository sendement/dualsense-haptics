"""Tests for _active_sink_monitor() and HapticsEngine._capture_source()'s
"auto" mode (see haptics_engine.py) - the deck-plugin's stand-in for the
desktop app's own App Audio Binding, following whichever sink pactl reports
as actually RUNNING instead of blindly trusting @DEFAULT_SINK@. Only the
pure decision logic is covered here; pactl itself is always faked."""
import types

import haptics_engine as he


def _fake_run(stdout, returncode=0):
    return lambda *a, **k: types.SimpleNamespace(returncode=returncode, stdout=stdout)


class TestActiveSinkMonitor:
    def test_picks_the_running_sink(self, monkeypatch):
        monkeypatch.setattr(he.subprocess, "run", _fake_run(
            "63\talsa_output.foo\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        ))
        assert he._active_sink_monitor([]) == "alsa_output.foo.monitor"

    def test_no_running_sink_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(he.subprocess, "run", _fake_run(
            "63\talsa_output.foo\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
            "64\talsa_output.bar\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
        ))
        assert he._active_sink_monitor([]) == "@DEFAULT_SINK@.monitor"

    def test_pactl_failure_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(he.subprocess, "run", _fake_run("", returncode=1))
        assert he._active_sink_monitor([]) == "@DEFAULT_SINK@.monitor"

    def test_pactl_launch_failure_falls_back_to_default(self, monkeypatch):
        def raise_it(*a, **k):
            raise OSError("no pactl")
        monkeypatch.setattr(he.subprocess, "run", raise_it)
        assert he._active_sink_monitor([]) == "@DEFAULT_SINK@.monitor"

    def test_prefers_current_over_switching_sinks(self, monkeypatch):
        """Two sinks legitimately RUNNING at once (e.g. a game plus a
        notification sound) shouldn't fight over which one gets captured on
        every refresh - keep the one already in use if it's still valid."""
        monkeypatch.setattr(he.subprocess, "run", _fake_run(
            "63\talsa_output.foo\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
            "64\talsa_output.bar\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        ))
        assert he._active_sink_monitor([], current="alsa_output.bar.monitor") == "alsa_output.bar.monitor"

    def test_switches_away_once_current_sink_stops_running(self, monkeypatch):
        monkeypatch.setattr(he.subprocess, "run", _fake_run(
            "63\talsa_output.foo\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        ))
        assert he._active_sink_monitor([], current="alsa_output.bar.monitor") == "alsa_output.foo.monitor"

    def test_no_current_falls_back_to_default_with_no_running_sink(self, monkeypatch):
        monkeypatch.setattr(he.subprocess, "run", _fake_run(""))
        assert he._active_sink_monitor([], current=None) == "@DEFAULT_SINK@.monitor"


class TestCaptureSourceAutoMode:
    def test_non_auto_source_never_calls_pactl(self, monkeypatch):
        calls = []
        monkeypatch.setattr(he.subprocess, "run", lambda *a, **k: calls.append(a))
        engine = he.HapticsEngine.__new__(he.HapticsEngine)
        engine.capture_source = {"source": "some.specific.monitor"}
        assert engine._capture_source() == "some.specific.monitor"
        assert calls == []

    def test_unset_source_is_plain_default(self):
        engine = he.HapticsEngine.__new__(he.HapticsEngine)
        engine.capture_source = {"source": None}
        assert engine._capture_source() == "@DEFAULT_SINK@.monitor"

    def test_auto_mode_polls_pactl_and_caches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(he.subprocess, "run", lambda *a, **k: (
            calls.append(1) or types.SimpleNamespace(
                returncode=0,
                stdout="63\talsa_output.foo\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n",
            )
        ))
        now = [1000.0]
        monkeypatch.setattr(he.time, "monotonic", lambda: now[0])
        engine = he.HapticsEngine.__new__(he.HapticsEngine)
        engine.capture_source = {"source": "auto"}
        engine._auto_sink_cache = [None, 0.0]

        assert engine._capture_source() == "alsa_output.foo.monitor"
        assert len(calls) == 1

        # Well within AUTO_SINK_REFRESH_S - must not re-poll.
        now[0] += 0.1
        assert engine._capture_source() == "alsa_output.foo.monitor"
        assert len(calls) == 1

        # Past the refresh window - polls again.
        now[0] += he.AUTO_SINK_REFRESH_S + 0.1
        assert engine._capture_source() == "alsa_output.foo.monitor"
        assert len(calls) == 2
