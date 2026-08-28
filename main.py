#!/usr/bin/env python3
import argparse
import sys

from PySide6.QtWidgets import QApplication

from haptics_engine import HapticsEngine
from config import load_state, save_state
from ui import MainWindow, TrayApp, install_press_animations
import bt_hid_proxy
import theme
import i18n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true", help="start minimized to tray (used by autostart)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    bt_hid_proxy.recover_stale_lock()

    state = load_state()
    theme.manager.set_preference(state.get("theme", "system"))
    i18n.manager.set_language(state.get("language", i18n.manager.lang))
    app.setStyleSheet(theme.manager.stylesheet())
    install_press_animations(app)

    engine_box = {"engine": None}

    def start_engine():
        if engine_box["engine"] is not None:
            return
        engine = HapticsEngine(state["active"])
        engine.start()
        engine_box["engine"] = engine

    def stop_engine():
        engine = engine_box["engine"]
        if engine is not None:
            engine.stop()
            engine.join(timeout=2)
            engine_box["engine"] = None

    def save():
        save_state(state)

    start_engine()

    main_window = MainWindow(
        state,
        engine_holder=lambda: engine_box["engine"],
        start_engine_cb=start_engine,
        stop_engine_cb=stop_engine,
        save_cb=save,
    )

    tray = TrayApp(
        app, main_window,
        start_engine_cb=start_engine,
        stop_engine_cb=stop_engine,
        engine_holder=lambda: engine_box["engine"],
    )

    if not args.tray:
        tray._open_window()

    exit_code = app.exec()
    stop_engine()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
