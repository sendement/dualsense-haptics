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


class TestNullNamesAreMissing:
    def test_pactl_null_placeholder_is_not_a_name(self):
        si = {"properties": {"application.name": "(null)", "node.name": "(null)"}}
        assert aab._binary_name(si) is None

    def test_null_binary_falls_through_to_application_name(self):
        si = {"properties": {"application.process.binary": "(null)", "application.name": "mpv"}}
        assert aab._binary_name(si) == "mpv"


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


class TestAppNameResolution:
    """A native PipeWire stream (Proton/Wine via the ALSA plugin) has no
    binary and (null) names in pactl, but its PipeWire client knows the app
    - and, for a Wine game, its title."""

    GAME_STREAM = {"index": 3698, "properties": {
        "application.name": "(null)", "node.name": "(null)", "client.id": "66"}}

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        aab._CLIENT_INFO_CACHE.clear()
        yield
        aab._CLIENT_INFO_CACHE.clear()

    def _pw_dump(self, monkeypatch, binary, calls, name="ELDEN RING\u2122"):
        props = {"application.process.binary": binary}
        if name is not None:
            props["application.name"] = name
        payload = [
            {"id": 61, "type": "PipeWire:Interface:Device", "info": {"props": {}}},
            {"id": 66, "type": "PipeWire:Interface:Client", "info": {"props": props}},
        ]
        def run(cmd, timeout=3):
            calls.append(cmd)
            return True, aab.json.dumps(payload)
        monkeypatch.setattr(aab, "_run_cmd", run)

    def test_wine_game_is_named_by_its_title(self, monkeypatch):
        calls = []
        self._pw_dump(monkeypatch, "wine64-preloader", calls)
        assert aab._app_name(self.GAME_STREAM) == "ELDEN RING\u2122"
        assert aab._stream_identities(self.GAME_STREAM) == ["ELDEN RING\u2122", "wine64-preloader"]
        assert calls == [["pw-dump", "66"]]

    def test_a_pin_made_on_the_binary_still_matches_the_game(self, monkeypatch):
        self._pw_dump(monkeypatch, "wine64-preloader", [])
        monkeypatch.setattr(aab, "_list_json", lambda *a: [self.GAME_STREAM])
        assert aab._snapshot_open_apps({"wine64-preloader"})[0] == {"wine64-preloader"}
        assert aab._snapshot_open_apps({"ELDEN RING\u2122"})[0] == {"ELDEN RING\u2122"}
        assert aab._snapshot_open_apps({"firefox"})[0] == set()

    def test_pinning_one_game_does_not_match_another_wine_game(self, monkeypatch):
        other = {"index": 9, "properties": {
            "application.process.binary": "wine64-preloader", "application.name": "Townfall.exe"}}
        self._pw_dump(monkeypatch, "wine64-preloader", [])
        monkeypatch.setattr(aab, "_list_json", lambda *a: [self.GAME_STREAM, other])
        _, indices = aab._snapshot_open_apps({"ELDEN RING\u2122"})
        assert indices == {"ELDEN RING\u2122": [3698]}

    def test_a_stream_that_already_has_a_usable_name_needs_no_lookup(self, monkeypatch):
        calls = []
        self._pw_dump(monkeypatch, "wine64-preloader", calls)
        si = {"properties": {"application.process.binary": "wine64-preloader",
                             "application.name": "Townfall.exe", "client.id": "66"}}
        assert aab._app_name(si) == "Townfall.exe"
        assert calls == []

    @pytest.mark.parametrize("useless", [None, "wine64-preloader", "ALSA plug-in [wine64-preloader]", "(null)", " "])
    def test_a_useless_client_name_falls_back_to_the_binary(self, monkeypatch, useless):
        self._pw_dump(monkeypatch, "wine64-preloader", [], name=useless)
        assert aab._app_name(self.GAME_STREAM) == "wine64-preloader"

    def test_non_wine_apps_are_named_by_binary_not_title(self, monkeypatch):
        calls = []
        self._pw_dump(monkeypatch, "vivaldi-bin", calls, name="Vivaldi")
        si = {"properties": {"application.name": "(null)", "client.id": "66"}}
        assert aab._app_name(si) == "vivaldi-bin"

    def test_only_the_client_object_is_read_not_other_objects_in_the_reply(self, monkeypatch):
        self._pw_dump(monkeypatch, "wine64-preloader", [])
        assert aab._client_binary("61") is None  # id 61 is a Device, not the requested client

    def test_a_streams_own_binary_wins_and_no_lookup_happens(self, monkeypatch):
        calls = []
        self._pw_dump(monkeypatch, "wine64-preloader", calls)
        si = {"properties": {"application.process.binary": "firefox", "client.id": "66"}}
        assert aab._app_name(si) == "firefox"
        assert calls == []

    def test_a_found_client_is_cached(self, monkeypatch):
        calls = []
        self._pw_dump(monkeypatch, "wine64-preloader", calls)
        aab._app_name(self.GAME_STREAM)
        aab._app_name(self.GAME_STREAM)
        assert len(calls) == 1

    def test_a_miss_is_retried_only_after_the_ttl(self, monkeypatch):
        calls = []
        clock = {"t": 100.0}
        monkeypatch.setattr(aab, "time", types.SimpleNamespace(monotonic=lambda: clock["t"], sleep=lambda s: None))
        self._pw_dump(monkeypatch, "(null)", calls, name=None)
        assert aab._app_name(self.GAME_STREAM) is None
        clock["t"] += 1.0
        aab._app_name(self.GAME_STREAM)
        assert len(calls) == 1
        clock["t"] += aab._CLIENT_MISS_TTL_S
        aab._app_name(self.GAME_STREAM)
        assert len(calls) == 2

    def test_pw_dump_failure_falls_back_to_the_stream_name(self, monkeypatch):
        monkeypatch.setattr(aab, "_run_cmd", lambda cmd, timeout=3: (False, "no pw-dump"))
        si = {"properties": {"application.name": "SomeApp", "client.id": "66"}}
        assert aab._app_name(si) == "SomeApp"
        assert aab._app_name(self.GAME_STREAM) is None

    def test_picker_lists_the_game_title_not_null_or_the_binary(self, monkeypatch):
        self._pw_dump(monkeypatch, "wine64-preloader", [])
        monkeypatch.setattr(aab, "_list_json", lambda *a: [
            {"properties": {"application.process.binary": "vivaldi-bin"}}, self.GAME_STREAM])
        assert aab.list_active_app_names() == ["ELDEN RING\u2122", "vivaldi-bin"]

    def test_the_taps_own_loopback_stream_is_not_an_app(self, monkeypatch):
        loopback = {"index": 4068, "properties": {
            "client.id": "70", "node.name": "output.loopback-361988-13",
            "media.name": "loopback-361988-13 output"}}
        assert aab._stream_identities(loopback) == []
        monkeypatch.setattr(aab, "_list_json", lambda *a: [
            {"properties": {"application.process.binary": "vivaldi-bin"}}, loopback])
        assert aab.list_active_app_names() == ["vivaldi-bin"]

    def test_a_real_app_is_not_mistaken_for_the_loopback(self):
        si = {"properties": {"application.process.binary": "pw-play", "node.name": "pw-play"}}
        assert aab._stream_identities(si) == ["pw-play"]

    def test_snapshot_gives_picker_names_and_every_identity_from_one_listing(self, monkeypatch):
        self._pw_dump(monkeypatch, "wine64-preloader", [])
        listings = []
        monkeypatch.setattr(aab, "_list_json", lambda *a: listings.append(a) or [
            {"properties": {"application.process.binary": "vivaldi-bin"}}, self.GAME_STREAM])
        names, identities = aab.list_active_apps_snapshot()
        assert names == ["ELDEN RING\u2122", "vivaldi-bin"]
        assert identities == {"ELDEN RING\u2122", "wine64-preloader", "vivaldi-bin"}
        assert len(listings) == 1
