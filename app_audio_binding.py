"""
Desktop-only per-application audio binding. The user adds apps (identified
by their audio stream's application.process.binary property, e.g.
"firefox") on the "App Sound" page and picks at most one of them (radio-
button style - mixing multiple sources is never allowed) as the current
selection; while that app's stream is open, capture narrows to just its
audio (via a temporary PipeWire null-sink + loopback "tap"). Nothing
selected, or the selected app not currently producing sound, falls back to
Global (full-system capture).

Deliberately has no notion of DSP presets/profiles at all - this only ever
narrows *which audio the engine listens to*, never which haptic settings
apply. state["profiles"] is a different, unrelated page's concept and is
never read here.

Not vendored to the Decky plugin (see tests/test_vendored_sync.py's list) -
Steam already has its own separate, unrelated game-profile-linking mechanism
there.

The watcher thread (_AppAudioBindingThread) owns all PipeWire/Pulse state.
It re-derives tap membership from live pactl state on every tick rather
than trusting bookkeeping from the last check - matching sink-inputs by
name alone can't tell a stream closing and a brand new one from the same
app opening apart (confirmed live: a game's audio device reset created a
fresh stream that a change-detection shortcut here once let slip through
unnoticed, leaving the engine capturing a silent tap indefinitely).
"""
import json
import select
import subprocess
import threading
import time

_NULL_SINK_NAME = "dualsense_haptics_app_tap"
_SUBSCRIBE_POLL_S = 0.2
_FALLBACK_RECOMPUTE_S = 2.0
_JOIN_TIMEOUT_S = 2.0

# How long the tap outlives the selected app's last stream before it's torn
# down. Games and browsers routinely close and reopen their stream within a
# second or two (device reset, loading screen, tab switch); tearing the tap
# down and rebuilding it each time churned a null-sink + loopback pair per
# flap (confirmed with a synthetic flapping stream: 14 load/unload calls for
# 6 flaps) and flipped the engine's capture source with each one, restarting
# its audio session every time.
_TEARDOWN_GRACE_S = 4.0

# Bursts of sink-input events (a game starting opens several streams at
# once) are coalesced: at most one recompute per this interval.
_MIN_RECOMPUTE_INTERVAL_S = 0.15

# How many times teardown re-checks the tap for streams that landed on it
# (e.g. stream-restore placing a fresh stream there) before unloading.
_TEARDOWN_RECHECKS = 3


def _log(message):
    print(f"[app_audio_binding] {message}", flush=True)

_THREAD = None
_LOCK = threading.Lock()


def _run_cmd(cmd, timeout=3):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, result.stdout


def _run_pactl(*args, timeout=3):
    return _run_cmd(["pactl", *args], timeout=timeout)


def _list_json(*args):
    """pactl -f json list <args> - [] on any failure, so callers can treat
    "couldn't tell" the same as "nothing there" rather than crashing."""
    ok, out = _run_pactl("-f", "json", "list", *args)
    if not ok:
        return []
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return []


# pactl reports a missing string property as the literal "(null)".
_MISSING = (None, "", "(null)")

# PipeWire client.id -> ((binary, application name), monotonic time looked
# up). A found binary never changes for the life of the client; a miss is
# retried after a while (the client may not have published its properties
# yet).
_CLIENT_INFO_CACHE = {}
_CLIENT_MISS_TTL_S = 5.0
_CLIENT_CACHE_MAX = 256

# Names that say nothing about *which* game a Wine stream belongs to.
_GENERIC_NAMES = {"wine", "wine64", "wine-preloader", "wine64-preloader",
                  "playback", "audio stream", "pipewire", "pulseaudio"}


def _binary_name(sink_input):
    """The name a stream's own properties give it - process binary, else
    application name - or None if neither is usable."""
    props = sink_input.get("properties", {})
    for key in ("application.process.binary", "application.name"):
        value = props.get(key)
        if value not in _MISSING:
            return value
    return None


def _is_wine_binary(name):
    return bool(name) and name.startswith("wine") and (
        name.endswith("-preloader") or name in ("wine", "wine64"))


def _game_name(name, binary):
    """`name` if it actually names something (a game), else None."""
    if name in _MISSING:
        return None
    name = name.strip()
    low = name.lower()
    if not low or low == (binary or "").lower() or low in _GENERIC_NAMES:
        return None
    if low.startswith("alsa plug-in"):
        return None
    return name


def _client_info(client_id):
    """(application.process.binary, application.name) of the PipeWire
    *client* behind a stream.

    Native PipeWire streams - what Proton/Wine games create through the ALSA
    plugin - show up in pactl with no process binary and "(null)" names (a
    "TM" in a game's title is enough), so the stream itself can't say which
    app it is; its client object still can, and for a Wine game its name is
    the game's title. `pw-dump <id>` returns just that object (a full dump
    is ~300KB), cached per client."""
    if client_id in _MISSING:
        return None, None
    key = str(client_id)
    now = time.monotonic()
    cached = _CLIENT_INFO_CACHE.get(key)
    if cached is not None:
        info, looked_up = cached
        if info[0] or now - looked_up < _CLIENT_MISS_TTL_S:
            return info
    info = (None, None)
    ok, out = _run_cmd(["pw-dump", key])
    if ok:
        try:
            for obj in json.loads(out):
                if str(obj.get("id")) == key:
                    props = obj.get("info", {}).get("props", {})
                    binary = props.get("application.process.binary")
                    name = props.get("application.name")
                    info = (None if binary in _MISSING else binary,
                            None if name in _MISSING else name)
                    break
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    if len(_CLIENT_INFO_CACHE) >= _CLIENT_CACHE_MAX:
        _CLIENT_INFO_CACHE.clear()
    _CLIENT_INFO_CACHE[key] = (info, now)
    return info


def _client_binary(client_id):
    return _client_info(client_id)[0]


def _is_loopback_stream(props):
    """The output side of a module-loopback - ours (the per-app tap's) is
    always up while narrowed. Plumbing, not an app anyone would pin. Matched
    by its node name (output.loopback-<pid>-<id>): the stream carries no
    process binary of its own, only its client's."""
    name = props.get("node.name") or props.get("media.name") or ""
    return name.startswith(("output.loopback-", "loopback-"))


def _stream_identities(sink_input):
    """Every name a stream can be pinned under, best first. A Wine game's
    title comes first (so pins are per game, not "any Wine program"), then
    its process binary - so a pin made before titles were shown, like
    wine64-preloader, keeps matching. Anything else is just its binary or
    application name."""
    props = sink_input.get("properties", {})
    if _is_loopback_stream(props):
        return []
    binary = props.get("application.process.binary")
    binary = None if binary in _MISSING else binary
    own_name = props.get("application.name")
    client_binary = client_name = None
    if binary is None or (_is_wine_binary(binary) and _game_name(own_name, binary) is None):
        client_binary, client_name = _client_info(props.get("client.id"))
    binary = binary or client_binary

    identities = []
    if _is_wine_binary(binary):
        game = _game_name(own_name, binary) or _game_name(client_name, binary)
        if game:
            identities.append(game)
    if binary:
        identities.append(binary)
    else:
        fallback = _binary_name(sink_input)
        if fallback:
            identities.append(fallback)
    return identities


def _app_name(sink_input):
    """The name shown for a stream: its first (best) identity."""
    identities = _stream_identities(sink_input)
    return identities[0] if identities else None


def list_active_app_names():
    """Distinct names of every app currently producing sound - feeds the
    "App Sound" page's add-app picker (Wine games listed by title)."""
    names = {_app_name(si) for si in _list_json("sink-inputs")}
    names.discard(None)
    return sorted(names)


def list_active_apps_snapshot():
    """(picker names, every identity in play) from ONE sink-input listing.
    The names are what the add-app picker offers (a Wine game by title); the
    identities also include fallbacks like wine64-preloader, so a pin made
    on those is still recognised as live by the page's status badges."""
    names, identities = set(), set()
    for si in _list_json("sink-inputs"):
        ids = _stream_identities(si)
        if ids:
            names.add(ids[0])
            identities.update(ids)
    return sorted(names), identities


def _snapshot_open_apps(names_of_interest):
    """One sink-inputs snapshot, restricted to names_of_interest. Returns
    (open_set, {app_name: [sink_input_index, ...]})."""
    open_set = set()
    indices = {}
    for si in _list_json("sink-inputs"):
        for name in _stream_identities(si):
            if name in names_of_interest:
                open_set.add(name)
                indices.setdefault(name, []).append(si.get("index"))
    return open_set, indices


def _decide(selected, open_apps):
    """Pure decision logic (no I/O) - table-tested in tests/. Only one app
    can ever be selected at a time (enforced by the UI, not here) - mixing
    multiple sources is never possible by construction. True narrows
    capture to `selected`; False means Global (full-system capture)."""
    return bool(selected) and selected in open_apps


def _all_tap_sink_indices():
    """Every sink currently named _NULL_SINK_NAME - normally at most one,
    but an unclean process kill (SIGKILL/SIGTERM bypasses stop_watching()'s
    cleanup entirely) can leave a stale duplicate behind before the next
    watcher startup gets a chance to run crash-recovery. Confirmed live
    that duplicates can coexist under the same name, so anything moving
    sink-inputs back to @DEFAULT_SINK@ before a teardown must check every
    one of them - checking only the first (whichever pactl happens to list
    first) can silently miss a real app's audio sitting on a different
    duplicate, orphaning it silent when _teardown_tap_modules() then
    unloads every matching module regardless."""
    return [sink.get("index") for sink in _list_json("sinks") if sink.get("name") == _NULL_SINK_NAME]


def _teardown_tap_modules():
    """Unloads any loopback/null-sink modules for the fixed-name tap, found
    by querying pactl fresh rather than tracking module ids locally - reused
    both for a normal revert-to-baseline and for crash-recovery at watcher
    startup (a previous hard-kill can leave these loaded).

    Deliberately uses `list short modules` (tab-separated: id, name,
    argument), not `-f json list modules` - confirmed live that PipeWire's
    pactl compat layer omits the module id entirely from the JSON form
    (unlike sinks/sink-inputs, which do carry "index"), so JSON parsing here
    would silently never find anything to unload."""
    ok, out = _run_pactl("list", "short", "modules")
    if not ok:
        return
    loopback_ids = []
    null_sink_ids = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or _NULL_SINK_NAME not in parts[2]:
            continue
        mod_id, name = parts[0], parts[1]
        if name == "module-loopback":
            loopback_ids.append(mod_id)
        elif name == "module-null-sink":
            null_sink_ids.append(mod_id)
    # Loopback first - unloading the null-sink out from under a still-loaded
    # loopback reading its monitor is more likely to surface as an error.
    for mod_id in loopback_ids + null_sink_ids:
        _run_pactl("unload-module", mod_id)


def _create_tap_modules():
    _run_pactl("load-module", "module-null-sink", f"sink_name={_NULL_SINK_NAME}",
               "sink_properties=device.description=DualSense-Haptics-App-Tap")
    _run_pactl("load-module", "module-loopback", f"source={_NULL_SINK_NAME}.monitor",
               "sink=@DEFAULT_SINK@", "latency_msec=1")


def _revert_any_stray_routing_and_teardown():
    """Moves everything off the tap and unloads it. Re-checks after moving:
    unloading a sink that still has a stream attached makes PipeWire kill
    that stream, which some clients (Chromium-based apps especially) handle
    badly - and a fresh stream can land on the tap between the move and the
    unload (module-stream-restore re-places a stream where it last was), so
    one pass isn't enough. Only unloads once a check finds the tap empty (or
    the re-check budget is spent)."""
    clean = False
    for _ in range(_TEARDOWN_RECHECKS):
        tap_indices = set(_all_tap_sink_indices())
        stragglers = ([si for si in _list_json("sink-inputs") if si.get("sink") in tap_indices]
                      if tap_indices else [])
        if not stragglers:
            clean = True
            break
        for si in stragglers:
            idx = si.get("index")
            if idx is not None:
                _run_pactl("move-sink-input", str(idx), "@DEFAULT_SINK@")
        time.sleep(0.05)
    if not clean:
        _log("tap still had streams after re-checks - unloading anyway")
    _teardown_tap_modules()


def clear_narrowing(capture_source_box):
    """Synchronous, idempotent - called when the feature is turned off so a
    narrowed capture source doesn't linger. Safe even if nothing is
    narrowed: the watcher's own bookkeeping self-heals on its next
    recompute regardless (see _AppAudioBindingThread._recompute)."""
    _revert_any_stray_routing_and_teardown()
    capture_source_box["source"] = None


class _AppAudioBindingThread(threading.Thread):
    def __init__(self, state, capture_source_box):
        super().__init__(daemon=True, name="AppAudioBinding")
        self.state = state
        self.capture_source_box = capture_source_box
        self._stop = threading.Event()
        self._narrowed_app = None
        # monotonic time the narrowed app's last stream disappeared (None
        # while it has one) - see _TEARDOWN_GRACE_S.
        self._gone_since = None

    def stop(self):
        self._stop.set()

    def run(self):
        # Crash recovery: a previous hard-kill can leave a real app's audio
        # still routed through a leftover tap from before - move it back
        # before unloading, exactly like a normal clear_narrowing() would,
        # so recovery never silently orphans someone's audio.
        _revert_any_stray_routing_and_teardown()
        try:
            proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            proc = None
        try:
            self._recompute()
            last_recompute = time.monotonic()
            next_fallback = last_recompute + _FALLBACK_RECOMPUTE_S
            dirty = False
            while not self._stop.is_set():
                if proc is not None and proc.stdout is not None:
                    ready, _, _ = select.select([proc.stdout], [], [], _SUBSCRIBE_POLL_S)
                    if ready:
                        line = proc.stdout.readline()
                        if not line:
                            # subscribe died - the ~2s fallback below keeps
                            # things working without it, just less snappy.
                            proc = None
                        elif "sink-input" in line:
                            dirty = True
                else:
                    self._stop.wait(_SUBSCRIBE_POLL_S)
                now = time.monotonic()
                # A burst of events (a game opening several streams at once)
                # collapses into one recompute; the poll timeout above
                # guarantees the loop comes back to service a deferred one.
                if (dirty and now - last_recompute >= _MIN_RECOMPUTE_INTERVAL_S) or now >= next_fallback:
                    self._recompute()
                    dirty = False
                    last_recompute = time.monotonic()
                    next_fallback = last_recompute + _FALLBACK_RECOMPUTE_S
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            if self._narrowed_app is not None:
                self._revert_to_baseline_routing()

    def _recompute(self):
        selected = self.state.get("app_audio_binding_selected")
        if not selected and self._narrowed_app is None:
            # Global and nothing narrowed: there is nothing to watch, so
            # don't spawn pactl (each one opens a fresh connection to the
            # audio server) just to learn that.
            return
        names_of_interest = {selected} if selected else set()
        open_apps, _ = _snapshot_open_apps(names_of_interest)
        should_narrow = _decide(selected, open_apps)

        if should_narrow:
            self._gone_since = None
            if self._narrowed_app != selected:
                if self._narrowed_app is None:
                    _create_tap_modules()
                _log(f"narrowing capture to {selected}")
                self._narrowed_app = selected
        elif self._narrowed_app is not None:
            # The selected app has no live stream right now. If the user
            # switched the selection away (Global, or an app that isn't
            # open), fall back immediately; if it's the same app whose
            # stream just vanished, hold the tap for a grace period first -
            # it very often comes straight back (see _TEARDOWN_GRACE_S).
            now = time.monotonic()
            if selected != self._narrowed_app:
                self._revert_to_baseline_routing()
            else:
                if self._gone_since is None:
                    self._gone_since = now
                if now - self._gone_since >= _TEARDOWN_GRACE_S:
                    self._revert_to_baseline_routing()

        if self._narrowed_app is not None:
            # Every tick, regardless of whether the open-set of *names*
            # changed since last time - matching by name alone can't tell
            # a stream closing and a brand new one from the very same app
            # opening apart (e.g. a game momentarily resetting its audio
            # device on a loading screen), so tap membership is re-derived
            # from live pactl state each time rather than trusted from
            # stale bookkeeping. Confirmed live: without this, a recreated
            # stream that PipeWire placed back on the default sink (not the
            # tap) went completely unnoticed - the name-based open-set
            # looked unchanged, so nothing ever moved it in, leaving the
            # engine capturing a silent tap indefinitely.
            self._sync_tap_membership(self._narrowed_app)
            self.capture_source_box["source"] = f"{_NULL_SINK_NAME}.monitor"

    def _sync_tap_membership(self, app_name):
        """Makes the tap sink contain exactly app_name's current sink-
        inputs and nothing else - handles both a stray other app landing
        there (PipeWire's module-stream-restore "remembering" a past
        placement) and app_name itself opening a fresh stream that was
        never explicitly moved in."""
        tap_indices = set(_all_tap_sink_indices())
        if not tap_indices:
            return
        for si in _list_json("sink-inputs"):
            idx = si.get("index")
            if idx is None:
                continue
            on_tap = si.get("sink") in tap_indices
            matches = app_name in _stream_identities(si)
            if matches and not on_tap:
                _log(f"moving {app_name} stream {idx} onto the tap")
                _run_pactl("move-sink-input", str(idx), _NULL_SINK_NAME)
            elif not matches and on_tap:
                _log(f"moving {_app_name(si)} stream {idx} off the tap")
                _run_pactl("move-sink-input", str(idx), "@DEFAULT_SINK@")

    def _revert_to_baseline_routing(self):
        if self._narrowed_app is None:
            return
        _log(f"reverting to global capture (was narrowed to {self._narrowed_app})")
        _revert_any_stray_routing_and_teardown()
        self._narrowed_app = None
        self._gone_since = None
        self.capture_source_box["source"] = None


def start_watching(state, capture_source_box):
    global _THREAD
    with _LOCK:
        if _THREAD is not None:
            return
        _THREAD = _AppAudioBindingThread(state, capture_source_box)
        _THREAD.start()


def stop_watching():
    global _THREAD
    with _LOCK:
        thread, _THREAD = _THREAD, None
    if thread is not None:
        thread.stop()
        # Longer than triggers.py's snap-click 0.3s join - this one may wait
        # through a real move-sink-input + unload-module sequence, not just
        # an event wait.
        thread.join(timeout=_JOIN_TIMEOUT_S)
