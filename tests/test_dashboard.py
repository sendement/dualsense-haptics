"""Read-only telemetry and quick selection must not change controller semantics."""
import copy
import os
import time

import pytest

from config import _default_state
from haptics_engine import HapticsEngine, DPAD_VIRTUAL_CODE, LEFT_STICK_VIRTUAL_CODE
from evdev import ecodes as ec


def test_visual_snapshot_filters_disabled_buttons_and_preserves_config():
    state = _default_state()
    cfg = state['active']
    cfg['button_haptics'] = {
        str(ec.BTN_SOUTH): {'enabled': True, 'strength': .8},
        str(ec.BTN_EAST): {'enabled': False, 'strength': 1},
        str(LEFT_STICK_VIRTUAL_CODE): {'enabled': True, 'strength': .6},
    }
    before = copy.deepcopy(cfg)
    engine = HapticsEngine(cfg)
    held = {ec.BTN_SOUTH: True, ec.BTN_EAST: True, LEFT_STICK_VIRTUAL_CODE: True}
    led = ((128, 51, 179), (True, True, False, False, False))
    engine._emit_visuals(held, {LEFT_STICK_VIRTUAL_CODE: .5}, led)
    assert engine.visual_state is None  # Headless use does no telemetry work.
    engine.visual_feedback_enabled = True
    engine._emit_visuals(held, {LEFT_STICK_VIRTUAL_CODE: .5}, led)
    snapshot = engine.visual_state
    assert snapshot[1] == (128, 51, 179)
    assert snapshot[3] == {ec.BTN_SOUTH: .8, LEFT_STICK_VIRTUAL_CODE: .3}
    held.clear()
    assert snapshot[2][ec.BTN_SOUTH] == 1
    engine._emit_visuals({}, {}, None)
    assert engine.visual_state[1:] == (None, {}, {})
    assert cfg == before


@pytest.fixture
def dashboard(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    widgets = pytest.importorskip('PySide6.QtWidgets')
    import ui
    import theme
    app = widgets.QApplication.instance() or widgets.QApplication([])
    monkeypatch.setattr('config.is_autostart_enabled', lambda: False)
    from unittest.mock import Mock
    monkeypatch.setattr('config.set_autostart', Mock())
    monkeypatch.setattr('app_audio_binding.list_active_app_names', lambda: ['firefox'])
    state = _default_state()
    engine = HapticsEngine(state['active'])
    app.setStyleSheet(theme.manager.stylesheet())
    window = ui.MainWindow(state, lambda: engine, lambda: None, lambda: None, lambda: None)
    yield window, engine, app
    window.home_page.meter_timer.stop()
    window.led_page.preview_timer.stop()
    window.led_page.preview_scene.timer.stop()
    window.settings_page.connection_timer.stop()
    window.presets_page.connection_timer.stop()
    window.profiles_page.connection_timer.stop()
    window.triggers_page.connection_timer.stop()
    window.button_haptic_page.feedback_timer.stop()
    window.advanced_page.preview_timer.stop()
    window.app_audio_binding_page._combo_refresh_timer.stop()
    theme.manager.changed.disconnect(window._on_theme_changed)
    ui.i18n.manager.changed.disconnect(window._on_language_changed)
    window.hide()
    window.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_quick_trigger_routes_only_selected_side_and_saved_parameters(dashboard, monkeypatch):
    window, engine, app = dashboard
    calls = []
    window.state['trigger_preset_params_right']['hard_wall'] = {'strength': 4}
    window.state['trigger_snap_click_right']['hard_wall'] = False
    monkeypatch.setattr(window, '_apply_trigger_preset', lambda *args, **kwargs: calls.append((args, kwargs)))
    combo = window.home_page.trigger_panels['right'].mode_combo
    combo.activated.emit(combo.findData('hard_wall'))
    assert calls[0][0] == ('hard_wall', 'right')
    assert calls[0][1]['overrides'] == {'strength': 4}
    assert calls[0][1]['snap_click'] is False
    # Failed/no-op application leaves the selector at the previously applied state.
    assert combo.currentData() is None
    assert window.state['trigger_preset_left'] is None
    off = []
    monkeypatch.setattr(window, '_turn_off_triggers', off.append)
    combo.activated.emit(0)
    assert off == ['right']


def test_custom_title_bar_exposes_live_status_navigation_and_window_controls(dashboard):
    import re

    import ui
    from PySide6.QtCore import Qt

    window, engine, app = dashboard
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.title_bar.version_badge.text() == ui.APP_VERSION
    assert re.fullmatch(r'v\d+\.\d+\.\d+', ui.APP_VERSION)
    assert set(window._resize_handles) == {
        'top', 'bottom', 'left', 'right',
        'top_left', 'top_right', 'bottom_left', 'bottom_right',
    }

    window.set_status_text('Подключено', connected=True)
    window.set_battery_text('78% · разряжается')
    assert window.title_bar.status_label.text() == 'Подключено'
    assert window.title_bar.device_pill.property('connected') is True
    assert window.title_bar.battery_label.text() == '78%'

    window.title_bar.settings_btn.click()
    assert window.stack.currentWidget() is window.settings_page
    window.resize(920, 700)
    window.show()
    app.processEvents()
    assert window.title_bar.center_title.isHidden()
    assert window.title_bar.settings_btn.isVisible()


def test_custom_trigger_survives_dashboard_refresh(dashboard):
    window, engine, app = dashboard
    window.state['trigger_preset_left'] = 'custom'
    window.state['trigger_custom_left'] = {'mode': 'feedback', 'values': {'position': 3, 'strength': 4}}
    window.home_page.refresh_active()
    combo = window.home_page.trigger_panels['left'].mode_combo
    assert combo.currentData() == 'custom'
    count = combo.count()
    window.home_page.refresh_active()
    assert combo.count() == count


def test_upstream_app_sound_page_coexists_with_custom_dashboard(dashboard):
    window, engine, app = dashboard
    assert window.stack.count() == 10
    assert set(window.nav_buttons) == set(window.pages)
    window.show_page('app_audio')
    page = window.app_audio_binding_page
    assert window.stack.currentWidget() is page
    assert page.app_combo.findText('firefox') >= 0
    page.app_combo.setCurrentText('firefox')
    page._add_app()
    page._set_selected('firefox')
    assert window.state['app_audio_binding_selected'] == 'firefox'
    assert window.state['app_audio_binding_enabled'] is False
    page._remove_app('firefox')
    assert window.state['app_audio_binding_selected'] is None
    window.show_page('home')
    assert window.stack.currentWidget() is window.home_page
    assert window.home_page.trigger_panels['left'].mode_combo.count() > 1


def test_app_sound_redesign_distinguishes_selection_from_live_routing(dashboard):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QBoxLayout

    window, engine, app = dashboard
    page = window.app_audio_binding_page
    window.state['app_audio_binding_apps'] = ['firefox', 'vlc']
    window.state['app_audio_binding_selected'] = 'vlc'
    window.state['app_audio_binding_enabled'] = True
    page.live_apps = {'firefox'}
    page.refresh()

    assert set(page.app_rows) == {None, 'firefox', 'vlc'}
    assert page.app_rows[None].property('active') is True
    assert page.app_rows['vlc'].property('selected') is True
    assert page.app_rows['vlc'].property('waiting') is True

    page._set_selected('firefox')
    page.live_apps = {'firefox'}
    page.refresh()
    assert page.app_rows['firefox'].property('active') is True
    assert page.app_rows[None].property('active') is False

    window.resize(920, 900)
    window.show_page('app_audio')
    window.show()
    app.processEvents()
    assert page.workspace.direction() == QBoxLayout.Direction.TopToBottom
    assert page.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_profiles_redesign_keeps_search_selection_and_actions_working(dashboard, monkeypatch):
    import ui
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox, QBoxLayout, QAbstractItemView

    window, engine, app = dashboard
    page = window.profiles_page
    balanced = copy.deepcopy(window.state['active'])
    music = copy.deepcopy(window.state['active'])
    music['master_gain'] = 1.8
    music['led']['enabled'] = True
    music['led']['preset'] = 'rainbow'
    window.state['profiles'] = {'Сбалансированный': balanced, 'Музыка': music}
    window.state['active_ref'] = 'profile:Сбалансированный'
    page.refresh()

    assert page.list.dragDropMode() == QAbstractItemView.InternalMove
    assert list(page.profile_cards) == ['Сбалансированный', 'Музыка']
    assert page.selected_name == 'Сбалансированный'
    assert page.profile_cards['Сбалансированный'].property('selected') is True
    assert not page.detail_active.isHidden()

    page.search_edit.setText('муз')
    assert list(page.profile_cards) == ['Музыка']
    page.search_edit.clear()

    applied = []
    page.on_apply = applied.append
    page._select_profile('Музыка')
    page.apply_btn.click()
    assert applied == ['Музыка']
    assert page.metric_bars['vibration'][0].value() == 72
    assert any(label.text().endswith('72%')
               for label in page.profile_cards['Музыка'].findChildren(ui.QLabel))

    page.name_edit.setText('Новый профиль')
    page.save_btn.click()
    assert 'Новый профиль' in window.state['profiles']
    assert window.state['active_ref'] == 'profile:Новый профиль'

    page._select_profile('Новый профиль')
    monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('Переименован', True))
    page._rename_selected()
    assert 'Переименован' in window.state['profiles']
    assert 'Новый профиль' not in window.state['profiles']

    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    page._delete_selected()
    assert 'Переименован' not in window.state['profiles']

    window.resize(920, 900)
    window.show_page('profiles')
    window.show()
    app.processEvents()
    assert page.workspace.direction() == QBoxLayout.Direction.TopToBottom
    assert page.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_profiles_can_be_reordered_and_keep_order_through_other_actions(dashboard, monkeypatch):
    import ui

    window, engine, app = dashboard
    page = window.profiles_page
    params = copy.deepcopy(window.state['active'])
    window.state['profiles'] = {name: copy.deepcopy(params) for name in ('Alpha', 'Beta', 'Gamma')}
    page.refresh()

    page._store_visible_order(['Gamma', 'Alpha', 'Beta'])
    page.refresh()
    assert list(window.state['profiles']) == ['Gamma', 'Alpha', 'Beta']
    assert list(page.profile_cards) == ['Gamma', 'Alpha', 'Beta']

    page._select_profile('Alpha')
    monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('Renamed', True))
    page._rename_selected()
    assert list(window.state['profiles']) == ['Gamma', 'Renamed', 'Beta']

    page.name_edit.setText('Delta')
    page._save_current()
    assert list(window.state['profiles']) == ['Gamma', 'Renamed', 'Beta', 'Delta']


def test_profile_rename_cannot_overwrite_an_existing_profile(dashboard, monkeypatch):
    import ui

    window, engine, app = dashboard
    page = window.profiles_page
    params = copy.deepcopy(window.state['active'])
    window.state['profiles'] = {'Alpha': copy.deepcopy(params), 'Beta': copy.deepcopy(params)}
    page.refresh()
    page._select_profile('Alpha')
    warnings = []
    monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('Beta', True))
    monkeypatch.setattr(ui.QMessageBox, 'warning', lambda *args: warnings.append(args))

    page._rename_selected()

    assert list(window.state['profiles']) == ['Alpha', 'Beta']
    assert page.selected_name == 'Alpha'
    assert warnings

    page.name_edit.setText('Beta')
    page._save_current()
    assert list(window.state['profiles']) == ['Alpha', 'Beta']
    assert len(warnings) == 2


def test_led_parameter_edits_are_persisted(dashboard):
    from unittest.mock import Mock

    window, engine, app = dashboard
    page = window.led_page
    page.on_change = Mock()
    page._set_led_attack(.33)
    page._set_led_release(.44)
    page._set_led_gamma(1.7)
    page._set_led_bass_priority(.62)
    page._set_preset_value('static', 'brightness', .75)

    page.on_change.assert_called()
    assert page.on_change.call_count == 5
    assert window.state['active']['led']['immersive']['attack'] == .33
    assert window.state['active']['led']['static']['brightness'] == .75


def test_only_visible_page_timers_and_telemetry_are_active(dashboard):
    window, engine, app = dashboard
    window.show()
    app.processEvents()
    assert window.home_page.meter_timer.isActive()
    assert not window.button_haptic_page.feedback_timer.isActive()
    assert engine.visual_feedback_enabled is True

    window.show_page('profiles')
    app.processEvents()
    assert window.profiles_page.connection_timer.isActive()
    assert not window.home_page.meter_timer.isActive()
    assert engine.visual_feedback_enabled is False

    window.show_page('led')
    app.processEvents()
    assert window.led_page.preview_timer.isActive()
    assert window.led_page.preview_scene.timer.isActive()
    assert not window.profiles_page.connection_timer.isActive()
    assert engine.visual_feedback_enabled is True

    for key in ('triggers', 'advanced'):
        window.show_page(key)
        app.processEvents()
        assert engine.visual_feedback_enabled is True

    window.hide()
    app.processEvents()
    assert not any(timer.isActive() for timers in window._managed_page_timers.values()
                   for timer, _interval in timers)
    assert engine.visual_feedback_enabled is False


def test_visual_pages_tolerate_missing_engine(dashboard):
    window, engine, app = dashboard
    window.home_page.engine_holder = lambda: None
    window.triggers_page.engine_holder = lambda: None
    window.button_haptic_page.engine_holder = lambda: None
    window.advanced_page.engine_holder = lambda: None
    window.led_page.engine_holder = lambda: None

    window.home_page._poll_meter()
    window.triggers_page._refresh_connection()
    window.button_haptic_page._poll_feedback()
    window.advanced_page._poll_preview()
    window.led_page._poll_preview()

    assert window.home_page.gamepad.level == 0
    assert window.button_haptic_page.gamepad.feedback == {}


def test_stale_feedback_and_led_color_are_cleared(dashboard):
    window, engine, app = dashboard
    page = window.home_page
    window.state['active']['led']['enabled'] = True
    engine.visual_state = (time.monotonic(), (12, 80, 220), {ec.BTN_SOUTH: .8}, {ec.BTN_SOUTH: .8})
    page._poll_meter()
    assert page.lightbar_card.target == (12, 80, 220)
    assert page.gamepad.feedback == {ec.BTN_SOUTH: .8}
    engine.visual_state = (time.monotonic() - 1, (12, 80, 220), {}, {ec.BTN_SOUTH: .8})
    page._poll_meter()
    assert page.lightbar_card.target == (0, 0, 0)
    assert page.lightbar_dots.rgb is None
    assert page.gamepad.feedback == {}


def test_engaged_trigger_preset_shows_up_in_the_feedback_label(dashboard):
    """The controller graphic glows for a squeezed trigger via `held` even
    without a configured preset, but the feedback label's text only mirrors
    that squeeze when a preset is actually engaged on that side - matching
    the adaptive trigger's real behavior (unconfigured triggers do nothing,
    so a text mention would be misleading)."""
    from haptics_engine import LEFT_TRIGGER_VIRTUAL_CODE
    from ui import t

    window, engine, app = dashboard
    page = window.home_page
    held = {LEFT_TRIGGER_VIRTUAL_CODE: .8}
    engine.visual_state = (time.monotonic(), None, held, {})

    page._poll_meter()
    assert page.gamepad.feedback == held
    assert t('btn_left_trigger') not in page.feedback_label.text()

    window.state['trigger_preset_left'] = 'hard_wall'
    page._poll_meter()
    assert f"{t('btn_left_trigger')} 80%" in page.feedback_label.text()


def test_led_page_preview_uses_live_color_and_player_meter(dashboard):
    window, engine, app = dashboard
    page = window.led_page
    window.state['active']['led']['enabled'] = True
    page.refresh()
    engine.visual_state = (time.monotonic(), (40, 120, 220), {}, {})
    window.home_page.connection_indicator.set_connection('usb')
    page._poll_preview()
    assert page.preview_state.text() == 'ON'
    assert page.live_color.rgb == (40, 120, 220)
    assert page.preview_scene.target == (40, 120, 220)
    assert page.gamepad.light_rgb == (40, 120, 220)
    assert page.player_meter._lit == 4
    assert page.connection_indicator.kind == 'usb'

    engine.visual_state = (time.monotonic() - 1, (40, 120, 220), {}, {})
    page._poll_preview()
    assert page.live_color.rgb is None
    assert page.player_meter._lit == 1

    page.led_visualizer_check.setChecked(False)
    page._poll_preview()
    assert page.preview_state.text() == 'OFF'
    assert page.player_meter._lit == 0
    assert page.gamepad.light_rgb == (20, 34, 52)


def test_led_page_exposes_v110_presets_and_previews_static_color(dashboard):
    window, engine, app = dashboard
    page = window.led_page
    assert [page.preset_combo.itemData(i) for i in range(page.preset_combo.count())] == [
        'static', 'breathing', 'wave', 'immersive',
        'rainbow', 'heartbeat', 'battery', 'custom',
    ]
    window.state['active']['led']['enabled'] = True
    window.state['active']['led']['static']['color'] = [218, 36, 112]
    page.refresh()
    page.mode_buttons['static'].click()
    page._poll_preview()
    assert window.state['active']['led']['preset'] == 'static'
    assert page.mode_buttons['static'].isChecked()
    assert not page.brightness_slider.isHidden()
    assert page.live_color.rgb == (218, 36, 112)
    assert page.gamepad.light_rgb == (218, 36, 112)
    window.home_page._poll_meter()
    assert window.home_page.lightbar_rgb == (218, 36, 112)

    for preset_id in page._PRESET_ORDER:
        page.mode_buttons[preset_id].click()
        app.processEvents()
        assert window.state['active']['led']['preset'] == preset_id
        assert page.mode_buttons[preset_id].isChecked()


def test_live_led_color_is_shared_by_every_controller_preview(dashboard):
    window, engine, app = dashboard
    rgb = (218, 36, 112)
    window.state['active']['led']['enabled'] = True
    window.led_page.refresh()
    engine.visual_state = (time.monotonic(), rgb, {}, {})
    window.home_page._poll_meter()
    window.triggers_page._refresh_connection()
    window.button_haptic_page._poll_feedback()
    window.advanced_page._poll_preview()
    window.led_page._poll_preview()
    previews = (
        window.home_page.gamepad,
        window.triggers_page.hero_gamepad,
        window.button_haptic_page.gamepad,
        window.advanced_page.controller_outline,
        window.led_page.gamepad,
    )
    assert window.home_page.lightbar_rgb == rgb
    assert all(preview.light_rgb == rgb for preview in previews)


def test_gamepad_lightbar_recolor_uses_only_original_light_pixels(dashboard):
    from PySide6.QtCore import Qt
    window, engine, app = dashboard
    gamepad = window.home_page.gamepad
    gamepad.set_light_color((230, 35, 70))
    source = gamepad._finished_image().scaled(306, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    layer = gamepad._lightbar_layer(source).toImage()
    gamepad._ensure_light_mask(source)
    mask = gamepad._light_mask.toImage()
    lit = [layer.pixelColor(x, y) for y in range(layer.height()) for x in range(layer.width())
           if layer.pixelColor(x, y).alpha() > 0]
    assert lit
    assert all(color.red() > color.blue() for color in lit)
    assert all(layer.pixelColor(x, y).alpha() == 0
               for y in range(layer.height()) for x in range(layer.width())
               if mask.pixelColor(x, y).alpha() == 0)

    # Regression: a blue or purple selected shell must never become part of
    # the LED mask and get painted as one large dark patch when LEDs are off.
    for skin in ('blue', 'purple'):
        gamepad.set_skin(skin)
        gamepad._light_mask_key = None
        tinted = gamepad._finished_image().scaled(306, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        tinted_layer = gamepad._lightbar_layer(tinted).toImage()
        lit_count = sum(tinted_layer.pixelColor(x, y).alpha() > 0
                        for y in range(tinted_layer.height()) for x in range(tinted_layer.width()))
        assert 0 < lit_count < tinted_layer.width() * tinted_layer.height() * .02


@pytest.mark.parametrize('width', [920, 1400])
def test_led_page_redesign_remains_usable_at_supported_widths(dashboard, width):
    from PySide6.QtCore import Qt
    window, engine, app = dashboard
    window.resize(width, 900)
    window.show_page('led')
    window.show()
    app.processEvents()
    page = window.led_page
    assert page.gamepad.isVisible()
    assert page.led_visualizer_check.isVisible()
    assert page.gamepad.height() >= 250
    assert page.led_attack_slider.width() > 180
    assert page.led_gamma_slider.width() > 180
    assert page.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_settings_redesign_keeps_theme_and_language_controls_working(dashboard):
    import theme
    window, engine, app = dashboard
    page = window.settings_page
    assert set(page.theme_buttons) == {'dark', 'light', 'system'}
    assert page.theme_buttons['system'].isChecked()

    page.theme_buttons['dark'].click()
    app.processEvents()
    assert window.state['theme'] == 'dark'
    assert theme.manager.preference == 'dark'
    assert page.theme_buttons['dark'].isChecked()

    page.theme_buttons['system'].click()
    app.processEvents()
    assert window.state['theme'] == 'system'
    assert page.theme_buttons['system'].isChecked()

    page.lang_combo.setCurrentIndex(page.lang_combo.findData('ru'))
    app.processEvents()
    assert window.state['language'] == 'ru'
    assert window.settings_page.lang_combo.currentData() == 'ru'
    window.settings_page.lang_combo.setCurrentIndex(window.settings_page.lang_combo.findData('en'))
    app.processEvents()
    assert window.state['language'] == 'en'


@pytest.mark.parametrize('width', [920, 1400])
def test_settings_theme_cards_remain_visible_at_supported_widths(dashboard, width):
    window, engine, app = dashboard
    window.resize(width, 900)
    window.show_page('settings')
    window.show()
    app.processEvents()
    page = window.settings_page
    for button in page.theme_buttons.values():
        assert button.isVisible()
        assert button.width() >= 130
        assert button.height() >= 104
    window.home_page.connection_indicator.set_connection('bluetooth')
    page._refresh_connection()
    assert page.connection_indicator.kind == 'bluetooth'


def test_preset_filters_search_and_featured_apply_use_real_presets(dashboard):
    import ui
    window, engine, app = dashboard
    page = window.presets_page
    window.show_page('presets')
    window.show()
    app.processEvents()
    assert set(page.cards) == set(ui.PRESET_ORDER)
    assert set(page.filter_buttons) == set(page.FILTERS)

    page.filter_buttons['music'].click()
    assert not page.cards['music'].isHidden()
    assert all(card.isHidden() for pid, card in page.cards.items() if pid != 'music')
    assert page.featured.isHidden()

    page.filter_buttons['all'].click()
    page.search.setText(ui.t('preset_voice_label'))
    assert not page.cards['voice'].isHidden()
    assert all(card.isHidden() for pid, card in page.cards.items() if pid != 'voice')
    page.search.clear()

    page.featured.apply_btn.click()
    assert window.state['active_ref'] == 'preset:cinema'
    assert page.cards['cinema'].property('active') is True
    assert page.featured.property('active') is True


@pytest.mark.parametrize('width', [920, 1400])
def test_preset_redesign_is_two_column_and_usable_at_supported_widths(dashboard, width):
    window, engine, app = dashboard
    window.resize(width, 900)
    window.show_page('presets')
    window.show()
    app.processEvents()
    page = window.presets_page
    assert page.featured.isVisible()
    assert page.search.isVisible()
    assert all(button.isVisible() for button in page.filter_buttons.values())
    assert abs(page.cards['balanced'].width() - page.cards['cinema'].width()) <= 1
    assert page.cards['balanced'].x() < page.cards['cinema'].x()
    assert page.cards['music'].y() > page.cards['balanced'].y()
    assert page.scroll.horizontalScrollBar().maximum() == 0


def test_trigger_redesign_preserves_every_preset_and_quick_control(dashboard):
    import ui
    window, engine, app = dashboard
    page = window.triggers_page
    left = page.left_column
    assert set(left.cards) == set(ui.TRIGGER_PRESET_ORDER)

    window.state['trigger_preset_left'] = 'hard_wall'
    page.refresh()
    hard_wall = left.cards['hard_wall']
    assert hard_wall.property('active') is True
    assert len(hard_wall.quick_sliders) == 2
    hard_wall.quick_sliders[0][1].set_value(5)
    hard_wall.snap_click_check.setChecked(False)
    hard_wall.snap_strength_slider.set_value(4)
    calls = []
    left.on_apply = lambda *args: calls.append(args)
    hard_wall.apply_btn.click()
    assert calls == [('hard_wall', 'left', {'strength': 5, 'snap': 8}, False, 4)]


def test_custom_trigger_raw_controls_use_compact_two_column_grid(dashboard):
    window, engine, app = dashboard
    custom = window.triggers_page.right_column.custom_card
    custom.mode_combo.setCurrentIndex(custom.mode_combo.findData('feedback_raw'))
    app.processEvents()
    assert len(custom.slider_widgets) == 10
    positions = [custom.sliders_layout.getItemPosition(i)[:2]
                 for i in range(custom.sliders_layout.count())]
    assert positions[0] == (0, 0)
    assert positions[1] == (0, 1)
    assert positions[-1] == (4, 1)


@pytest.mark.parametrize('width, stacked', [(920, True), (1400, False)])
def test_trigger_columns_adapt_without_horizontal_scrolling(dashboard, width, stacked):
    from PySide6.QtWidgets import QBoxLayout
    window, engine, app = dashboard
    window.resize(width, 980)
    window.show_page('triggers')
    window.show()
    app.processEvents()
    page = window.triggers_page
    expected = (QBoxLayout.Direction.TopToBottom if stacked
                else QBoxLayout.Direction.LeftToRight)
    assert page.columns_layout.direction() == expected
    assert page.scroll.horizontalScrollBar().maximum() == 0
    window.home_page.connection_indicator.set_connection('usb')
    page._refresh_connection()
    assert page.connection_indicator.kind == 'usb'


def test_vibration_page_live_outline_uses_shared_motor_telemetry(dashboard):
    from PySide6.QtTest import QTest

    window, engine, app = dashboard
    page = window.advanced_page
    window.show()
    window.show_page('advanced')
    app.processEvents()
    engine.level_queue.put_nowait((.82, .31))
    window.home_page.connection_indicator.set_connection('bluetooth')
    QTest.qWait(90)
    assert page.controller_outline.strong == pytest.approx(.82)
    assert page.controller_outline.weak == pytest.approx(.31)
    assert page.live_wave.strong == pytest.approx(.82)
    assert page.live_wave.weak == pytest.approx(.31)
    assert page.hero_bass_bar.value() == 82
    assert page.hero_treble_bar.value() == 31
    assert page.connection_indicator.kind == 'bluetooth'

    page._motor_level_state = (time.monotonic() - 1, 1, 1)
    page._poll_preview()
    assert page.controller_outline.strong == 0
    assert page.controller_outline.weak == 0


def test_pressed_button_glow_is_live_on_every_controller_preview(dashboard):
    window, engine, app = dashboard
    held = {DPAD_VIRTUAL_CODE: 1.0, ec.BTN_SOUTH: .72}

    polls = (
        ('home', window.home_page._poll_meter, window.home_page.gamepad),
        ('triggers', window.triggers_page._refresh_connection, window.triggers_page.hero_gamepad),
        ('button_haptic', window.button_haptic_page._poll_feedback, window.button_haptic_page.gamepad),
        ('advanced', window.advanced_page._poll_preview, window.advanced_page.controller_outline),
        ('led', window.led_page._poll_preview, window.led_page.gamepad),
    )
    window.show()
    for key, poll, controller in polls:
        window.show_page(key)
        engine.visual_state = (time.monotonic(), None, held, {})
        poll()
        assert controller.feedback == held

    engine.visual_state = (time.monotonic() - 1, None, held, {})
    window.led_page._poll_preview()
    assert window.led_page.gamepad.feedback == {}


def test_restarted_engine_reenables_visible_page_telemetry(dashboard):
    window, old_engine, app = dashboard
    box = {'engine': old_engine}
    window.engine_holder = lambda: box['engine']
    window.stop_engine_cb = lambda: box.update(engine=None)
    window.start_engine_cb = lambda: box.update(engine=HapticsEngine(window.state['active']))
    window.show()
    window.show_page('home')
    app.processEvents()
    assert old_engine.visual_feedback_enabled is True

    window._toggle()
    window._toggle()

    assert box['engine'] is not old_engine
    assert box['engine'].visual_feedback_enabled is True


def test_connection_indicator_uses_one_rounded_pill_language(dashboard):
    import ui

    window, engine, app = dashboard
    indicator = window.home_page.connection_indicator
    indicator.set_connection('usb')
    assert indicator.status_label.text() == ui.t('status_connected')
    assert indicator.status_label.height() == indicator.usb_label.height() == indicator.bt_label.height()
    assert all('border-radius: 17px' in label.styleSheet()
               for label in (indicator.status_label, indicator.usb_label, indicator.bt_label))


def test_vibration_motor_pulses_stay_on_real_controller_surface(dashboard):
    from PySide6.QtCore import Qt
    from ui import GamepadWidget
    window, engine, app = dashboard
    controller = window.advanced_page.controller_outline
    assert isinstance(controller, GamepadWidget)
    left = controller.MOTOR_ANCHORS['left']
    right = controller.MOTOR_ANCHORS['right']
    assert set(left) == set(right) == {'upper', 'lower'}
    assert all(point[0] < .5 for point in left.values())
    assert all(point[0] > .5 for point in right.values())
    assert left['upper'][1] < left['lower'][1]
    assert right['upper'][1] < right['lower'][1]
    source = controller._finished_image().scaled(306, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    mask = source.toImage()
    points = {
        side: {
            zone: (round(source.width() * point[0]), round(source.height() * point[1]))
            for zone, point in zones.items()
        }
        for side, zones in controller.MOTOR_ANCHORS.items()
    }
    for levels, active, inactive in (((.8, 0), 'left', 'right'), ((0, .6), 'right', 'left')):
        controller.set_levels(*levels)
        layer = controller._motor_surface_layer(source).toImage()
        assert all(layer.pixelColor(*point).alpha() > 0 for point in points[active].values())
        assert all(layer.pixelColor(*point).alpha() == 0 for point in points[inactive].values())
        assert all(layer.pixelColor(x, y).alpha() == 0
                   for y in range(layer.height()) for x in range(layer.width())
                   if mask.pixelColor(x, y).alpha() == 0)

    assert controller.MOTOR_COLORS['upper'].name() == '#18b8ff'
    assert controller.MOTOR_COLORS['lower'].name() == '#955cff'


def test_profile_detail_metric_bars_share_one_start_column(dashboard):
    from PySide6.QtCore import QPoint

    window, engine, app = dashboard
    page = window.profiles_page
    window.state['profiles']['alignment'] = copy.deepcopy(window.state['active'])
    page.refresh()
    page._select_profile('alignment')
    window.show()
    window.show_page('profiles')
    app.processEvents()

    starts = {
        bar.mapTo(page.details_body, QPoint(0, 0)).x()
        for bar, _value in page.metric_bars.values()
    }
    assert len(starts) == 1


def test_button_page_glows_live_pressed_controls_and_clears_stale_state(dashboard):
    window, engine, app = dashboard
    page = window.button_haptic_page
    held = {DPAD_VIRTUAL_CODE: 1, ec.BTN_SOUTH: .75}
    feedback = {DPAD_VIRTUAL_CODE: .4, ec.BTN_SOUTH: .3}
    engine.visual_state = (time.monotonic(), None, held, feedback)
    window.home_page.connection_indicator.set_connection('usb')
    window.show()
    window.show_page('button_haptic')
    app.processEvents()
    page._poll_feedback()
    assert engine.visual_feedback_enabled is True
    assert page.gamepad.feedback == held
    assert page.rows[DPAD_VIRTUAL_CODE].property('pressed') is True
    assert page.rows[ec.BTN_SOUTH].property('pressed') is True
    assert page.left_wave._value == 40
    assert page.right_wave._value == 30
    assert page.connection_indicator.kind == 'usb'

    engine.visual_state = (time.monotonic() - 1, None, held, feedback)
    page._poll_feedback()
    assert page.gamepad.feedback == {}
    assert page.rows[DPAD_VIRTUAL_CODE].property('pressed') is False
    assert page.rows[ec.BTN_SOUTH].property('pressed') is False


def test_gamepad_button_glow_is_clipped_to_controller_alpha(dashboard):
    from PySide6.QtCore import Qt
    window, engine, app = dashboard
    gamepad = window.button_haptic_page.gamepad
    gamepad.set_feedback({DPAD_VIRTUAL_CODE: 1, ec.BTN_NORTH: .8})
    source = gamepad._finished_image().scaled(306, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    layer = gamepad._masked_feedback_layer(source).toImage()
    mask = source.toImage()
    assert any(layer.pixelColor(x, y).alpha() > 0
               for y in range(layer.height()) for x in range(layer.width()))
    assert all(layer.pixelColor(x, y).alpha() == 0
               for y in range(layer.height()) for x in range(layer.width())
               if mask.pixelColor(x, y).alpha() == 0)


def test_button_redesign_preserves_per_control_settings(dashboard):
    window, engine, app = dashboard
    page = window.button_haptic_page
    row = page.rows[ec.BTN_SOUTH]
    row.check.click()
    row.slider.setValue(675)
    row.hz_slider.setValue(210)
    entry = window.state['active']['button_haptics'][str(ec.BTN_SOUTH)]
    assert entry == {'enabled': True, 'strength': .675, 'click_hz': 210}


@pytest.mark.parametrize('width, stacked', [(920, True), (1400, False)])
def test_button_redesign_adapts_without_horizontal_scrolling(dashboard, width, stacked):
    from PySide6.QtWidgets import QBoxLayout
    window, engine, app = dashboard
    window.resize(width, 980)
    window.show_page('button_haptic')
    window.show()
    app.processEvents()
    page = window.button_haptic_page
    expected = (QBoxLayout.Direction.TopToBottom if stacked
                else QBoxLayout.Direction.LeftToRight)
    assert page.columns_layout.direction() == expected
    assert page.gamepad.isVisible()
    assert page.scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize('width, stacked', [(920, True), (1400, False)])
def test_vibration_redesign_adapts_without_horizontal_scrolling(dashboard, width, stacked):
    from PySide6.QtWidgets import QBoxLayout
    window, engine, app = dashboard
    window.resize(width, 980)
    window.show_page('advanced')
    window.show()
    app.processEvents()
    page = window.advanced_page
    expected = (QBoxLayout.Direction.TopToBottom if stacked
                else QBoxLayout.Direction.LeftToRight)
    assert page.summary_layout.direction() == expected
    assert page.bands_layout.direction() == expected
    assert page.controller_outline.isVisible()
    assert page.scroll.horizontalScrollBar().maximum() == 0


def test_collapsed_icon_size_survives_navigation(dashboard):
    from PySide6.QtTest import QTest
    window, engine, app = dashboard
    window.show()
    app.processEvents()
    window._toggle_sidebar_collapsed()
    window.show_page('triggers')
    QTest.qWait(500)
    assert window.nav_buttons['triggers'].iconSize().width() == 38
    assert window.nav_buttons['home'].iconSize().width() == 36
    window._toggle_sidebar_collapsed()
    QTest.qWait(500)
    assert window.nav_buttons['triggers'].iconSize().width() == 22


def test_autostart_has_own_card_beside_vibration(dashboard):
    import config
    window, engine, app = dashboard
    window.show()
    for collapsed in (False, True, False):
        if window._sidebar_collapsed != collapsed:
            window._toggle_sidebar_collapsed()
        app.processEvents()
        page = window.home_page
        checkbox = page.autostart_check
        card = page.autostart_card
        vibration_card = page.toggle_btn.parentWidget()
        assert checkbox.isVisible()
        assert page.isAncestorOf(checkbox)
        assert not window.sidebar.isAncestorOf(checkbox)
        assert card.y() == vibration_card.y()
        assert card.height() == vibration_card.height()
        assert card.x() > vibration_card.geometry().right()
        assert checkbox.toolTip()
        assert checkbox.text()
    config.set_autostart.assert_not_called()
    checkbox.click()
    config.set_autostart.assert_called_once_with(True)
    checkbox.click()
    assert config.set_autostart.call_args.args == (False,)


def test_autostart_card_reads_current_setting_after_page_rebuild(dashboard, monkeypatch):
    import config
    window, engine, app = dashboard
    monkeypatch.setattr(config, 'is_autostart_enabled', lambda: True)
    window._on_language_changed()
    assert window.home_page.autostart_check.isChecked()
    config.set_autostart.assert_not_called()


def test_controller_finish_is_visual_only_and_survives_page_rebuild(dashboard):
    from config import CONTROLLER_SKINS
    window, engine, app = dashboard
    before = copy.deepcopy(window.state)
    saves = []
    window.home_page.skin_cb = lambda: saves.append(window.state['controller_skin'])
    combo = window.home_page.skin_combo
    assert tuple(combo.itemData(i) for i in range(combo.count())) == CONTROLLER_SKINS
    for skin in CONTROLLER_SKINS:
        combo.activated.emit(combo.findData(skin))
        assert window.home_page.gamepad.skin == skin
        assert window.state == {**before, 'controller_skin': skin}
        rendered = window.home_page.gamepad._finished_image()
        assert not rendered.isNull()
        assert rendered.size() == window.home_page.gamepad._image.size()
    assert saves == list(CONTROLLER_SKINS)
    window._on_language_changed()
    assert window.home_page.skin_combo.currentData() == CONTROLLER_SKINS[-1]
    assert window.home_page.gamepad.skin == CONTROLLER_SKINS[-1]


def test_controller_finish_syncs_to_every_preview_immediately(dashboard):
    from unittest.mock import Mock
    from ui import GamepadWidget
    window, engine, app = dashboard
    window.save_cb = Mock()
    combo = window.home_page.skin_combo
    combo.activated.emit(combo.findData('black'))
    previews = window.findChildren(GamepadWidget)
    assert len(previews) >= 4
    assert len({id(preview._image) for preview in previews}) == 1
    assert all(preview.skin == 'black' for preview in previews)
    assert window.advanced_page.controller_outline.skin == 'black'
    window.save_cb.assert_called_once_with()

    window._on_language_changed()
    assert all(preview.skin == 'black' for preview in window.findChildren(GamepadWidget))
    assert window.advanced_page.controller_outline.skin == 'black'


def test_black_controller_detail_reflection_stays_inside_image(dashboard):
    from PySide6.QtCore import Qt
    window, engine, app = dashboard
    gamepad = window.home_page.gamepad
    gamepad.set_skin('black')
    source = gamepad._finished_image().scaled(306, 204, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    layer = gamepad._black_detail_layer(source).toImage()
    mask = source.toImage()
    assert any(layer.pixelColor(x, y).alpha() > 0
               for y in range(layer.height()) for x in range(layer.width()))
    assert all(layer.pixelColor(x, y).alpha() == 0
               for y in range(layer.height()) for x in range(layer.width())
               if mask.pixelColor(x, y).alpha() == 0)


@pytest.mark.parametrize('width', [920, 1400])
def test_trigger_panels_and_meter_columns_are_symmetric(dashboard, width):
    from PySide6.QtCore import QPoint
    from ui import TriggerSilhouette
    window, engine, app = dashboard
    window.state['trigger_preset_left'] = 'machine'
    window.state['trigger_preset_right'] = 'strong_click'
    window.home_page.refresh_active()
    window.resize(width, 980)
    window.show()
    app.processEvents()
    left, right = (window.home_page.trigger_panels[side] for side in ('left', 'right'))
    assert abs(left.width() - right.width()) <= 1
    for panel in (left, right):
        assert panel.start_bar.mapTo(panel, QPoint()).x() == panel.force_bar.mapTo(panel, QPoint()).x()
        assert panel.start_bar.width() == panel.force_bar.width()
    assert abs(left.mode_combo.width() - right.mode_combo.width()) <= 1
    left_art = left.findChild(TriggerSilhouette)
    right_art = right.findChild(TriggerSilhouette)
    left_details_x = left.mode_combo.mapTo(left, QPoint()).x()
    right_details_x = right.mode_combo.mapTo(right, QPoint()).x()
    assert left_art.geometry().right() < left_details_x
    assert right_details_x + right.mode_combo.width() < right_art.x()
    assert left_art.x() == right.width() - right_art.geometry().right() - 1
    assert abs(left.width() - left_details_x - left.mode_combo.width() - right_details_x) <= 1
