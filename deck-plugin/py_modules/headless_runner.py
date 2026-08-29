#!/usr/bin/env python3
"""Standalone runner for the Decky plugin: hosts a HapticsEngine in a normal
(non-frozen) Python process. Importing python-evdev's compiled _input
extension from inside Decky's PyInstaller-frozen PluginLoader process
reliably fails with "partially initialized module" errors, so this whole
evdev-dependent chain (haptics_engine -> config -> evdev) runs here instead,
outside that frozen process. Talks to main.py purely through the
filesystem: hot-reloads config.json for live parameter updates (the same
file main.py writes to for preset/gain changes) and writes status.json for
main.py to read back (connection/status/battery).
"""
import json
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from haptics_engine import HapticsEngine, read_battery  # noqa: E402
from config import load_state, CONFIG_FILE  # noqa: E402
import bt_hid_proxy  # noqa: E402


def main():
    runtime_dir = sys.argv[1]
    status_file = os.path.join(runtime_dir, "status.json")
    pid_file = os.path.join(runtime_dir, "headless_runner.pid")

    bt_hid_proxy.recover_stale_lock()

    # Decky's plugin_loader can be stopped/restarted (or the plugin
    # reloaded) without ever SIGTERM-ing this already-spawned child -
    # confirmed on real hardware that the orphan survives indefinitely,
    # reparented to init, still holding the controller. main.py checks this
    # same PID file at every plugin load and start_engine() call and kills
    # whatever it finds there before spawning a fresh instance (see
    # _kill_stale_headless_runner() there); this just keeps it current.
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    state = load_state()
    engine = HapticsEngine(state["active"])
    engine.start()

    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    last_mtime = None
    last_status = None
    last_connection = None

    try:
        while not stop_event.is_set():
            try:
                mtime = os.path.getmtime(CONFIG_FILE)
                if mtime != last_mtime:
                    last_mtime = mtime
                    fresh = load_state()
                    # HapticsEngine holds a reference to this exact dict
                    # object (not a copy), and its own thread reads from it
                    # concurrently on every audio tick - update() first so
                    # the dict is never momentarily missing a key (e.g.
                    # bt_hid_proxy), which a concurrent read could otherwise
                    # catch mid-reload and misread as "disabled", aborting a
                    # live proxy session. clear()-then-update() had exactly
                    # that window; confirmed on real hardware that applying a
                    # game profile mid-session could trip it.
                    stale_keys = state["active"].keys() - fresh["active"].keys()
                    state["active"].update(fresh["active"])
                    for key in stale_keys:
                        del state["active"][key]
            except OSError:
                pass

            try:
                while True:
                    last_status = engine.status_queue.get_nowait()
            except Exception:
                pass
            try:
                last_connection = engine.connection_queue.get_nowait()
            except Exception:
                pass

            percent, batt_status = read_battery()
            try:
                with open(status_file, "w") as f:
                    json.dump({
                        "status": last_status,
                        "connection": last_connection,
                        "battery_percent": percent,
                        "battery_status": batt_status,
                    }, f)
            except OSError:
                pass

            stop_event.wait(0.5)
    finally:
        engine.stop()
        engine.join(timeout=2)
        try:
            os.remove(pid_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()
