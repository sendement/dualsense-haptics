"""PySide6 UI: tray icon + main window (sidebar navigation, home/presets/
profiles/triggers/button-haptic/advanced/settings)."""
import copy
import queue
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QRectF, QPointF, QEvent, QObject, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QLinearGradient, QPainterPath,
)
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton, QProgressBar,
    QStackedWidget, QButtonGroup, QListWidget, QListWidgetItem, QLineEdit,
    QInputDialog, QMessageBox, QFrame, QScrollArea, QComboBox,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect, QGraphicsOpacityEffect,
)

from evdev import ecodes as ec

from presets import PRESETS, PRESET_ORDER, preset_params, TRIGGER_PRESETS, TRIGGER_PRESET_ORDER
from haptics_engine import DPAD_VIRTUAL_CODE
import triggers
import theme
import i18n
from i18n import LANGUAGES

t = i18n.manager.t

# Grouped by physical side of the controller, matching BUTTON_SIDE in
# haptics_engine.py: left-side buttons vibrate the strong/left motor
# (lightly, via their own strength slider), right-side buttons the
# weak/right motor - feedback comes from the side the button is on.
# Each entry is (i18n key, evdev code) so labels follow the active language.
LEFT_BUTTON_OPTIONS = [
    ("btn_dpad", DPAD_VIRTUAL_CODE),
    ("btn_l1", ec.BTN_TL),
    ("btn_l2_press", ec.BTN_TL2),
    ("btn_l3", ec.BTN_THUMBL),
    ("btn_share", ec.BTN_SELECT),
]
RIGHT_BUTTON_OPTIONS = [
    ("btn_cross", ec.BTN_SOUTH),
    ("btn_circle", ec.BTN_EAST),
    ("btn_triangle", ec.BTN_NORTH),
    ("btn_square", ec.BTN_WEST),
    ("btn_r1", ec.BTN_TR),
    ("btn_r2_press", ec.BTN_TR2),
    ("btn_r3", ec.BTN_THUMBR),
    ("btn_options", ec.BTN_START),
    ("btn_ps", ec.BTN_MODE),
]
BUTTON_OPTIONS = LEFT_BUTTON_OPTIONS + RIGHT_BUTTON_OPTIONS

NAV_ITEMS = [
    ("home", "nav_home"), ("presets", "nav_presets"), ("profiles", "nav_profiles"),
    ("triggers", "nav_triggers"), ("button_haptic", "nav_button_haptic"),
    ("advanced", "nav_advanced"), ("settings", "nav_settings"),
]


# ---------------------------------------------------------------- press animation

class _PressAnimator(QObject):
    """App-wide event filter that gives every QPushButton a quick opacity dip
    on press and a smooth return on release - QSS alone can't animate a
    transition, so this is done as a tiny QPropertyAnimation per press."""

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and obj.isEnabled():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                self._animate(obj, 0.55)
            elif etype in (QEvent.Type.MouseButtonRelease, QEvent.Type.Leave):
                self._animate(obj, 1.0)
        return False

    def _animate(self, widget, target):
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(1.0)
            widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(100)
        anim.setStartValue(effect.opacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        widget._press_anim_ref = anim  # keep alive until it finishes


def install_press_animations(app):
    animator = _PressAnimator(app)
    app.installEventFilter(animator)
    return animator


# ---------------------------------------------------------------- icons/art

def draw_gamepad_path(rect):
    """Top-down DualSense-ish silhouette: flared grips, waisted center,
    gently peaked top edge - as opposed to a generic oval+circles gamepad."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    def pt(fx, fy):
        return QPointF(x + fx * w, y + fy * h)

    path = QPainterPath()
    path.moveTo(pt(0.5, 0.10))
    path.cubicTo(pt(0.58, 0.02), pt(0.72, 0.0), pt(0.80, 0.06))
    path.cubicTo(pt(0.90, 0.14), pt(0.94, 0.28), pt(0.97, 0.40))
    path.cubicTo(pt(1.02, 0.55), pt(0.98, 0.80), pt(0.86, 0.93))
    path.cubicTo(pt(0.78, 1.02), pt(0.68, 0.95), pt(0.64, 0.80))
    path.cubicTo(pt(0.60, 0.68), pt(0.56, 0.58), pt(0.5, 0.55))
    path.cubicTo(pt(0.44, 0.58), pt(0.40, 0.68), pt(0.36, 0.80))
    path.cubicTo(pt(0.32, 0.95), pt(0.22, 1.02), pt(0.14, 0.93))
    path.cubicTo(pt(0.02, 0.80), pt(-0.02, 0.55), pt(0.03, 0.40))
    path.cubicTo(pt(0.06, 0.28), pt(0.10, 0.14), pt(0.20, 0.06))
    path.cubicTo(pt(0.28, 0.0), pt(0.42, 0.02), pt(0.5, 0.10))
    path.closeSubpath()
    return path


def make_app_icon(palette, status="ok"):
    color = {
        "ok": palette["good"], "searching": palette["warn"],
        "error": palette["bad"], "off": palette["fg_dim"],
    }.get(status, palette["fg_dim"])
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QColor(palette["bg_card"]))
    grad.setColorAt(1, QColor(palette["bg"]))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, size - 4, size - 4, 16, 16)

    p.setBrush(QColor(palette["accent"]))
    path = draw_gamepad_path(QRectF(size * 0.15, size * 0.22, size * 0.7, size * 0.4))
    p.drawPath(path)

    p.setBrush(QColor(color))
    p.setPen(QPen(QColor(palette["bg"]), 2))
    p.drawEllipse(QRectF(size - 20, size - 20, 16, 16))
    p.end()
    return QIcon(pm)


ASSET_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "dualsense.png"

# Graduated glow: each tier only fades in once the level passes its "lo"
# threshold, reaching full opacity at "hi" - so the halo visibly grows in
# stages with vibration strength instead of one glow that just dims/brightens.
GLOW_TIERS = [
    {"lo": 0.04, "hi": 0.28, "radius": 10, "padding": 16, "max_opacity": 0.85},
    {"lo": 0.28, "hi": 0.52, "radius": 20, "padding": 28, "max_opacity": 0.65},
    {"lo": 0.52, "hi": 0.76, "radius": 32, "padding": 42, "max_opacity": 0.50},
    {"lo": 0.76, "hi": 1.00, "radius": 46, "padding": 58, "max_opacity": 0.40},
]


def _recolor_silhouette(pixmap, color):
    """Replaces every visible pixel's color with `color`, keeping the
    original alpha - i.e. a solid-color cutout matching the image's shape."""
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.drawPixmap(0, 0, pixmap)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(result.rect(), color)
    p.end()
    return result


def _render_blurred(pixmap, radius, padding):
    """Renders `pixmap` through a QGraphicsBlurEffect onto a larger
    transparent canvas so the blur can bleed outward instead of being
    clipped to the original bounds - i.e. an actual outer glow."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pixmap)
    item.setPos(padding, padding)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    out_w = pixmap.width() + 2 * padding
    out_h = pixmap.height() + 2 * padding
    result = QPixmap(out_w, out_h)
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.setRenderHint(QPainter.Antialiasing)
    scene.render(p, QRectF(0, 0, out_w, out_h), QRectF(0, 0, out_w, out_h))
    p.end()
    return result


class GamepadWidget(QWidget):
    """Hero illustration on the home page. Pulses a soft accent glow with
    the live motor levels so the dashboard feels alive, not just decorative.

    Prefers a static image at assets/dualsense.png if present (checked by
    mtime so dropping/replacing the file works without restarting the app);
    falls back to a hand-drawn silhouette otherwise. Glow color follows the
    active theme's accent, cached per (image, size, theme)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.level = 0.0
        self._image = None
        self._image_mtime = None
        self._glow_key = None
        self._glow_layers = []  # list of (padding, QPixmap), outermost first
        self._reload_image()

    def set_level(self, level):
        self.level = level
        self.update()

    def _reload_image(self):
        try:
            mtime = ASSET_IMAGE_PATH.stat().st_mtime
        except OSError:
            self._image = None
            self._image_mtime = None
            return
        if mtime == self._image_mtime:
            return
        pixmap = QPixmap(str(ASSET_IMAGE_PATH))
        self._image = pixmap if not pixmap.isNull() else None
        self._image_mtime = mtime
        self._glow_key = None  # force glow layer rebuild for the new image

    def _ensure_glow_layers(self, scaled):
        key = (self._image_mtime, scaled.width(), scaled.height(), theme.manager.name)
        if key == self._glow_key:
            return
        silhouette = _recolor_silhouette(scaled, QColor(theme.manager.palette["accent"]))
        self._glow_layers = [
            (tier["padding"], _render_blurred(silhouette, tier["radius"], tier["padding"]))
            for tier in GLOW_TIERS
        ]
        self._glow_key = key

    def paintEvent(self, event):
        self._reload_image()
        if self._image is not None:
            self._paint_image(self._image)
        else:
            self._paint_vector()

    def _paint_image(self, pixmap):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        target_w, target_h = w * 0.7, h * 0.75
        scaled = pixmap.scaled(int(target_w), int(target_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (w - scaled.width()) / 2
        y = (h - scaled.height()) / 2

        self._ensure_glow_layers(scaled)
        # draw largest/faintest tier first, tightest/brightest last, so the
        # halo reads as one glow that grows outward rather than flat rings
        for tier, (padding, layer) in reversed(list(zip(GLOW_TIERS, self._glow_layers))):
            frac = (self.level - tier["lo"]) / (tier["hi"] - tier["lo"])
            frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
            if frac <= 0.0:
                continue
            p.setOpacity(frac * tier["max_opacity"])
            p.drawPixmap(int(x - padding), int(y - padding), layer)
        p.setOpacity(1.0)

        p.drawPixmap(int(x), int(y), scaled)
        p.end()

    def _paint_vector(self):
        pal = theme.manager.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        gw, gh = min(w * 0.55, 300), min(h * 0.6, 190)
        rect = QRectF(cx - gw / 2, cy - gh / 2, gw, gh)

        def fx(v):
            return rect.x() + v * rect.width()

        def fy(v):
            return rect.y() + v * rect.height()

        if self.level > 0.02:
            glow = QColor(pal["accent"])
            glow.setAlphaF(min(0.35, 0.1 + self.level * 0.4))
            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            pad = 14 + self.level * 18
            p.drawRoundedRect(rect.adjusted(-pad, -pad, pad, pad), gh * 0.4, gh * 0.4)

        path = draw_gamepad_path(rect)
        shell = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        shell.setColorAt(0, QColor("#eef0f4"))
        shell.setColorAt(1, QColor("#c9cdd8"))
        p.setBrush(shell)
        p.setPen(QPen(QColor("#9aa0ad"), 1.5))
        p.drawPath(path)

        dark = QColor("#20232c")
        accent = QColor(pal["accent"])
        lit_accent = QColor(pal["accent"])
        lit_accent.setAlphaF(min(1.0, 0.55 + self.level * 0.9))

        # touchpad, centered top
        p.setPen(Qt.NoPen)
        p.setBrush(dark)
        p.drawRoundedRect(QRectF(fx(0.32), fy(0.14), fx(0.68) - fx(0.32), fy(0.40) - fy(0.14)), 6, 6)

        # light strips flanking the touchpad - the DualSense's signature detail
        p.setBrush(lit_accent)
        p.drawRoundedRect(QRectF(fx(0.24), fy(0.17), fx(0.30) - fx(0.24), fy(0.37) - fy(0.17)), 3, 3)
        p.drawRoundedRect(QRectF(fx(0.70), fy(0.17), fx(0.76) - fx(0.70), fy(0.37) - fy(0.17)), 3, 3)

        # D-pad, above the left stick
        dpad_cx, dpad_cy, dpad_r = fx(0.20), fy(0.44), gh * 0.045
        p.setBrush(dark)
        p.drawRoundedRect(QRectF(dpad_cx - dpad_r, dpad_cy - dpad_r * 0.35, dpad_r * 2, dpad_r * 0.7), 1, 1)
        p.drawRoundedRect(QRectF(dpad_cx - dpad_r * 0.35, dpad_cy - dpad_r, dpad_r * 0.7, dpad_r * 2), 1, 1)

        # face buttons, above the right stick
        face_cx, face_cy, face_r = fx(0.80), fy(0.44), gh * 0.05
        for ddx, ddy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            p.drawEllipse(QPointF(face_cx + ddx * face_r * 1.4, face_cy + ddy * face_r * 1.4), face_r * 0.5, face_r * 0.5)

        # analog sticks - left sits higher than right, as on a real DualSense
        for scx, scy in ((fx(0.32), fy(0.62)), (fx(0.62), fy(0.74))):
            r_outer = gh * 0.10
            p.setBrush(dark)
            p.drawEllipse(QPointF(scx, scy), r_outer, r_outer)
            p.setBrush(accent)
            p.drawEllipse(QPointF(scx, scy), r_outer * 0.4, r_outer * 0.4)

        # PS/home button, between the sticks
        home_cx, home_cy, home_r = fx(0.5), fy(0.50), gh * 0.045
        p.setBrush(dark)
        p.drawEllipse(QPointF(home_cx, home_cy), home_r, home_r)
        p.setBrush(lit_accent)
        p.drawEllipse(QPointF(home_cx, home_cy), home_r * 0.45, home_r * 0.45)

        p.end()


class ConnectionIndicator(QWidget):
    """Two small pill badges - the transport actually in use (USB or
    Bluetooth) lights up in the accent color, the other stays dim. Both are
    dim while searching/disconnected."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.usb_label = QLabel("USB")
        self.bt_label = QLabel("Bluetooth")
        layout.addWidget(self.usb_label)
        layout.addWidget(self.bt_label)
        self.set_connection(None)

    def _pill_style(self, active):
        pal = theme.manager.palette
        if active:
            return (f"background: {pal['accent']}; color: {pal['accent_ink']}; "
                     "border-radius: 8px; padding: 2px 8px; font-size: 10px; font-weight: 700;")
        return (f"background: transparent; color: {pal['fg_dim']}; border: 1px solid {pal['border']}; "
                "border-radius: 8px; padding: 2px 8px; font-size: 10px;")

    def set_connection(self, kind):
        self.usb_label.setStyleSheet(self._pill_style(kind == "usb"))
        self.bt_label.setStyleSheet(self._pill_style(kind == "bluetooth"))


# ---------------------------------------------------------------- shared widgets

class ParamSlider(QWidget):
    def __init__(self, label, lo, hi, value, decimals=3, hint=None, on_change=None):
        super().__init__()
        self.lo, self.hi, self.decimals = lo, hi, decimals
        self.on_change = on_change
        self.steps = 1000

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        row = QHBoxLayout()
        name = QLabel(label)
        self.value_label = QLabel()
        self.value_label.setProperty("role", "value")
        self.value_label.setAlignment(Qt.AlignRight)
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(self.value_label)
        layout.addLayout(row)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.steps)
        self.slider.setValue(self._to_slider(value))
        self.slider.valueChanged.connect(self._changed)
        layout.addWidget(self.slider)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "hint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        self._update_label(value)

    def _to_slider(self, v):
        return int((v - self.lo) / (self.hi - self.lo) * self.steps)

    def _to_value(self, s):
        return self.lo + (s / self.steps) * (self.hi - self.lo)

    def _update_label(self, v):
        self.value_label.setText(f"{v:.{self.decimals}f}")

    def _changed(self, s):
        v = self._to_value(s)
        self._update_label(v)
        if self.on_change:
            self.on_change(v)

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.slider.blockSignals(False)
        self._update_label(v)


def band_group(title, cfg, ceil_cfg, on_change):
    box = QGroupBox(title)
    layout = QVBoxLayout(box)

    def bind(key):
        def setter(v):
            cfg[key] = v
            on_change()
        return setter

    def bind_ceil(key):
        def setter(v):
            ceil_cfg[key] = v
            on_change()
        return setter

    sliders = {}
    sliders["lo"] = ParamSlider(t("slider_lo"), 0.0, 0.05, cfg["lo"], 4, t("slider_lo_hint"), bind("lo"))
    sliders["hi"] = ParamSlider(t("slider_hi"), 0.01, 0.3, cfg["hi"], 3, t("slider_hi_hint"), bind("hi"))
    sliders["attack"] = ParamSlider(t("slider_attack"), 0.5, 0.99, cfg["attack"], 2, t("slider_attack_hint"), bind("attack"))
    sliders["release"] = ParamSlider(t("slider_release"), 0.1, 0.9, cfg["release"], 2, t("slider_release_hint"), bind("release"))
    sliders["gamma"] = ParamSlider(t("slider_gamma"), 0.4, 2.5, cfg["gamma"], 2, t("slider_gamma_hint"), bind("gamma"))
    sliders["ceil_attack"] = ParamSlider(t("slider_ceil_attack"), 0.02, 0.5, ceil_cfg["attack_s"], 2,
                                          t("slider_ceil_attack_hint"), bind_ceil("attack_s"))
    sliders["ceil_release"] = ParamSlider(t("slider_ceil_release"), 0.3, 5.0, ceil_cfg["release_s"], 1,
                                           t("slider_ceil_release_hint"), bind_ceil("release_s"))
    for s in sliders.values():
        layout.addWidget(s)

    def refresh():
        sliders["lo"].set_value(cfg["lo"])
        sliders["hi"].set_value(cfg["hi"])
        sliders["attack"].set_value(cfg["attack"])
        sliders["release"].set_value(cfg["release"])
        sliders["gamma"].set_value(cfg["gamma"])
        sliders["ceil_attack"].set_value(ceil_cfg["attack_s"])
        sliders["ceil_release"].set_value(ceil_cfg["release_s"])

    box.refresh = refresh
    return box


def ref_label(state):
    ref = state["active_ref"]
    if ref.startswith("preset:"):
        pid = ref[len("preset:"):]
        return t(f"preset_{pid}_label") if pid in PRESETS else t("label_preset_fallback")
    if ref.startswith("profile:"):
        name = ref[len("profile:"):]
        if name in state["profiles"]:
            return name
    return t("label_custom_settings")


def trigger_ref_label(state, side):
    pid = state.get(f"trigger_preset_{side}")
    if pid and pid in TRIGGER_PRESETS:
        return t(f"trigger_{pid}_label")
    return t("label_trigger_off")


# ---------------------------------------------------------------- pages

class HomePage(QWidget):
    def __init__(self, state, engine_holder, toggle_cb):
        super().__init__()
        self.state = state
        self.engine_holder = engine_holder

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(16)

        top = QHBoxLayout()
        title = QLabel("DualSense Haptics")
        title.setProperty("role", "h1")
        top.addWidget(title)
        top.addStretch(1)
        self.connection_indicator = ConnectionIndicator()
        top.addWidget(self.connection_indicator)
        self.status_label = QLabel("...")
        self.status_label.setProperty("role", "hint")
        top.addWidget(self.status_label)
        root.addLayout(top)

        self.gamepad = GamepadWidget()
        root.addWidget(self.gamepad)

        active_card = QFrame()
        active_card.setObjectName("card")
        ac_layout = QVBoxLayout(active_card)
        ac_hdr = QLabel(t("home_active_profile"))
        ac_hdr.setProperty("role", "h2")
        ac_layout.addWidget(ac_hdr)
        self.active_label = QLabel(ref_label(state))
        self.active_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        ac_layout.addWidget(self.active_label)
        root.addWidget(active_card)

        trigger_card = QFrame()
        trigger_card.setObjectName("card")
        tg_layout = QVBoxLayout(trigger_card)
        tg_hdr = QLabel(t("home_adaptive_triggers"))
        tg_hdr.setProperty("role", "h2")
        tg_layout.addWidget(tg_hdr)
        tg_row = QHBoxLayout()
        self.trigger_labels = {}
        for side, side_label in (("left", "L2"), ("right", "R2")):
            col = QVBoxLayout()
            l = QLabel(side_label)
            l.setProperty("role", "hint")
            col.addWidget(l)
            v = QLabel(trigger_ref_label(state, side))
            v.setStyleSheet("font-size: 15px; font-weight: 700;")
            col.addWidget(v)
            self.trigger_labels[side] = v
            tg_row.addLayout(col)
        tg_layout.addLayout(tg_row)
        root.addWidget(trigger_card)

        row = QHBoxLayout()
        battery_card = QFrame()
        battery_card.setObjectName("card")
        bc_layout = QVBoxLayout(battery_card)
        bc_hdr = QLabel(t("home_battery"))
        bc_hdr.setProperty("role", "h2")
        bc_layout.addWidget(bc_hdr)
        self.battery_label = QLabel(t("battery_unknown"))
        self.battery_label.setStyleSheet("font-size: 17px; font-weight: 700;")
        bc_layout.addWidget(self.battery_label)
        row.addWidget(battery_card)

        toggle_card = QFrame()
        toggle_card.setObjectName("card")
        tc_layout = QVBoxLayout(toggle_card)
        tc_hdr = QLabel(t("home_vibration"))
        tc_hdr.setProperty("role", "h2")
        tc_layout.addWidget(tc_hdr)
        self.toggle_btn = QPushButton(t("btn_disable"))
        self.toggle_btn.setObjectName("primary")
        self.toggle_btn.clicked.connect(toggle_cb)
        tc_layout.addWidget(self.toggle_btn)
        row.addWidget(toggle_card)
        root.addLayout(row)

        meter_card = QFrame()
        meter_card.setObjectName("card")
        m_layout = QVBoxLayout(meter_card)
        m_hdr = QLabel(t("home_motor_response"))
        m_hdr.setProperty("role", "h2")
        m_layout.addWidget(m_hdr)
        self.strong_bar = QProgressBar()
        self.weak_bar = QProgressBar()
        for label, bar in ((t("label_bass"), self.strong_bar), (t("label_treble"), self.weak_bar)):
            r = QHBoxLayout()
            l = QLabel(label)
            l.setMinimumWidth(60)
            r.addWidget(l)
            bar.setRange(0, 100)
            r.addWidget(bar)
            m_layout.addLayout(r)
        root.addWidget(meter_card)

        root.addStretch(1)

        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._poll_meter)
        self.meter_timer.start(60)

    def set_enabled_text(self, enabled):
        self.toggle_btn.setText(t("btn_disable") if enabled else t("btn_enable"))

    def set_status_text(self, text):
        self.status_label.setText(text)

    def refresh_active(self):
        self.active_label.setText(ref_label(self.state))
        for side, label in self.trigger_labels.items():
            label.setText(trigger_ref_label(self.state, side))

    def set_battery_text(self, text):
        self.battery_label.setText(text)

    def _poll_meter(self):
        engine = self.engine_holder()
        if engine is None:
            self.strong_bar.setValue(0)
            self.weak_bar.setValue(0)
            self.gamepad.set_level(0)
            self.connection_indicator.set_connection(None)
            return
        try:
            strong, weak = engine.level_queue.get_nowait()
            self.strong_bar.setValue(int(strong * 100))
            self.weak_bar.setValue(int(weak * 100))
            self.gamepad.set_level(max(strong, weak))
        except queue.Empty:
            pass
        try:
            kind = engine.connection_queue.get_nowait()
            self.connection_indicator.set_connection(kind)
        except queue.Empty:
            pass


class PresetsPage(QWidget):
    def __init__(self, state, on_apply):
        super().__init__()
        self.state = state
        self.on_apply = on_apply
        self.cards = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("presets_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("presets_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        for pid in PRESET_ORDER:
            card = QFrame()
            card.setObjectName("card")
            layout = QHBoxLayout(card)
            text_col = QVBoxLayout()
            name = QLabel(t(f"preset_{pid}_label"))
            name.setStyleSheet("font-size: 15px; font-weight: 700;")
            desc = QLabel(t(f"preset_{pid}_desc"))
            desc.setProperty("role", "hint")
            desc.setWordWrap(True)
            text_col.addWidget(name)
            text_col.addWidget(desc)
            layout.addLayout(text_col, 1)
            btn = QPushButton(t("btn_apply"))
            btn.clicked.connect(lambda _=False, p=pid: self.on_apply(p))
            layout.addWidget(btn)
            outer.addWidget(card)
            self.cards[pid] = card

        outer.addStretch(1)
        self.refresh()

    def refresh(self):
        active = self.state["active_ref"]
        for pid, card in self.cards.items():
            card.setObjectName("cardActive" if active == f"preset:{pid}" else "card")
            card.style().unpolish(card)
            card.style().polish(card)


class ProfilesPage(QWidget):
    def __init__(self, state, on_apply, on_change):
        super().__init__()
        self.state = state
        self.on_apply = on_apply
        self.on_change = on_change

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("profiles_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("profiles_hint"))
        hint.setProperty("role", "hint")
        outer.addWidget(hint)

        self.list = QListWidget()
        outer.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton(t("btn_apply"))
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply_selected)
        rename_btn = QPushButton(t("btn_rename"))
        rename_btn.clicked.connect(self._rename_selected)
        delete_btn = QPushButton(t("btn_delete"))
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(delete_btn)
        outer.addLayout(btn_row)

        save_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("profile_name_placeholder"))
        save_btn = QPushButton(t("btn_save_as_profile"))
        save_btn.clicked.connect(self._save_current)
        save_row.addWidget(self.name_edit, 1)
        save_row.addWidget(save_btn)
        outer.addLayout(save_row)

        self.refresh()

    def refresh(self):
        self.list.clear()
        for name in sorted(self.state["profiles"]):
            self.list.addItem(QListWidgetItem(name))

    def _selected_name(self):
        item = self.list.currentItem()
        return item.text() if item else None

    def _apply_selected(self):
        name = self._selected_name()
        if name:
            self.on_apply(name)

    def _rename_selected(self):
        name = self._selected_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(self, t("rename_profile_title"), t("rename_profile_label"), text=name)
        if ok and new_name and new_name != name:
            self.state["profiles"][new_name] = self.state["profiles"].pop(name)
            if self.state["active_ref"] == f"profile:{name}":
                self.state["active_ref"] = f"profile:{new_name}"
            self.on_change()
            self.refresh()

    def _delete_selected(self):
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(self, t("delete_profile_title"), t("delete_profile_confirm", name=name)) == QMessageBox.Yes:
            del self.state["profiles"][name]
            if self.state["active_ref"] == f"profile:{name}":
                self.state["active_ref"] = "custom"
            self.on_change()
            self.refresh()

    def _save_current(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        self.state["profiles"][name] = copy.deepcopy(self.state["active"])
        self.state["active_ref"] = f"profile:{name}"
        self.name_edit.clear()
        self.on_change()
        self.refresh()


class TriggerColumn(QWidget):
    """One trigger's (L2 or R2) preset list: independent from the other side."""

    def __init__(self, state, side, side_title, on_apply, on_off):
        super().__init__()
        self.state = state
        self.side = side
        self.on_apply = on_apply
        self.cards = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr_row = QHBoxLayout()
        hdr = QLabel(side_title)
        hdr.setStyleSheet("font-size: 15px; font-weight: 700;")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        off_btn = QPushButton(t("btn_off"))
        off_btn.setObjectName("danger")
        off_btn.clicked.connect(lambda: on_off(side))
        hdr_row.addWidget(off_btn)
        layout.addLayout(hdr_row)

        for pid in TRIGGER_PRESET_ORDER:
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            name = QLabel(t(f"trigger_{pid}_label"))
            name.setStyleSheet("font-size: 14px; font-weight: 700;")
            desc = QLabel(t(f"trigger_{pid}_desc"))
            desc.setProperty("role", "hint")
            desc.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(desc)
            btn = QPushButton(t("btn_apply"))
            btn.clicked.connect(lambda _=False, p=pid: self.on_apply(p, self.side))
            card_layout.addWidget(btn)
            layout.addWidget(card)
            self.cards[pid] = card

        layout.addStretch(1)
        self.refresh()

    def refresh(self):
        active = self.state.get(f"trigger_preset_{self.side}")
        for pid, card in self.cards.items():
            card.setObjectName("cardActive" if active == pid else "card")
            card.style().unpolish(card)
            card.style().polish(card)


class TriggersPage(QWidget):
    def __init__(self, state, on_apply, on_off):
        super().__init__()
        self.state = state

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("triggers_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("triggers_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        columns_widget = QWidget()
        columns = QHBoxLayout(columns_widget)
        self.left_column = TriggerColumn(state, "left", t("trigger_left_title"), on_apply, on_off)
        self.right_column = TriggerColumn(state, "right", t("trigger_right_title"), on_apply, on_off)
        columns.addWidget(self.left_column)
        columns.addWidget(self.right_column)
        scroll.setWidget(columns_widget)
        outer.addWidget(scroll, 1)

        self.auto_check = QCheckBox(t("auto_reconnect_checkbox"))
        self.auto_check.setChecked(state["trigger_auto_reconnect"])
        self.auto_check.toggled.connect(self._toggle_auto)
        outer.addWidget(self.auto_check)

    def _toggle_auto(self, checked):
        self.state["trigger_auto_reconnect"] = checked

    def refresh(self):
        self.left_column.refresh()
        self.right_column.refresh()


class ButtonHapticRow(QWidget):
    """One button: checkbox + inline strength slider, kept to a single
    compact row so a whole group of buttons reads as a list, not a stack of
    cards."""

    def __init__(self, label, code, entry):
        super().__init__()
        self.code = code

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.check = QCheckBox(label)
        self.check.setMinimumWidth(140)
        self.check.setChecked(entry.get("enabled", False))
        layout.addWidget(self.check)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(int(entry.get("strength", 0.4) * 1000))
        layout.addWidget(self.slider, 1)

        self.value_label = QLabel(f"{entry.get('strength', 0.4):.2f}")
        self.value_label.setProperty("role", "value")
        self.value_label.setFixedWidth(36)
        layout.addWidget(self.value_label)


class ButtonHapticPage(QWidget):
    def __init__(self, state, on_change):
        super().__init__()
        self.state = state
        self.on_change = on_change
        self.rows = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("button_haptic_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("button_haptic_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner_layout = QHBoxLayout(inner)

        inner_layout.addWidget(self._build_group(t("group_left_side"), LEFT_BUTTON_OPTIONS))
        inner_layout.addWidget(self._build_group(t("group_right_side"), RIGHT_BUTTON_OPTIONS))

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_group(self, title, options):
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        for label_key, code in options:
            entry = self.state["active"]["button_haptics"].setdefault(str(code), {"enabled": False, "strength": 0.4})
            row = ButtonHapticRow(t(label_key), code, entry)
            row.check.toggled.connect(lambda checked, c=code: self._set_enabled(c, checked))
            row.slider.valueChanged.connect(lambda v, c=code: self._set_strength(c, v / 1000))
            layout.addWidget(row)
            self.rows[code] = row
        layout.addStretch(1)
        return box

    def _entry(self, code):
        return self.state["active"]["button_haptics"].setdefault(str(code), {"enabled": False, "strength": 0.4})

    def _set_enabled(self, code, checked):
        self._entry(code)["enabled"] = checked
        self.on_change()

    def _set_strength(self, code, value):
        self._entry(code)["strength"] = value
        self.rows[code].value_label.setText(f"{value:.2f}")
        self.on_change()

    def refresh(self):
        for code, row in self.rows.items():
            entry = self._entry(code)
            row.check.blockSignals(True)
            row.check.setChecked(entry["enabled"])
            row.check.blockSignals(False)
            row.slider.blockSignals(True)
            row.slider.setValue(int(entry["strength"] * 1000))
            row.slider.blockSignals(False)
            row.value_label.setText(f"{entry['strength']:.2f}")


class AdvancedPage(QWidget):
    def __init__(self, state, on_change):
        super().__init__()
        self.state = state
        active = state["active"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("advanced_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("advanced_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        general_box = QGroupBox(t("group_general"))
        gl = QVBoxLayout(general_box)
        self.gain_slider = ParamSlider(t("label_master_gain"), 0.2, 2.5, active["master_gain"], 2,
                                        None, self._set_gain)
        gl.addWidget(self.gain_slider)
        inner_layout.addWidget(general_box)

        self.bass_box = band_group(t("group_bass"), active["bass"], active["bass_ceiling"], on_change)
        self.treble_box = band_group(t("group_treble"), active["treble"], active["treble_ceiling"], on_change)
        inner_layout.addWidget(self.bass_box)
        inner_layout.addWidget(self.treble_box)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _set_gain(self, v):
        self.state["active"]["master_gain"] = v

    def refresh(self):
        self.gain_slider.set_value(self.state["active"]["master_gain"])
        self.bass_box.refresh()
        self.treble_box.refresh()


class SettingsPage(QWidget):
    def __init__(self, state, on_theme_change, on_language_change):
        super().__init__()
        self.state = state

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("settings_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)

        theme_box = QGroupBox(t("group_theme"))
        theme_layout = QVBoxLayout(theme_box)
        theme_choices = [("system", t("theme_system")), ("light", t("theme_light")), ("dark", t("theme_dark"))]
        self.theme_combo = QComboBox()
        for value, label in theme_choices:
            self.theme_combo.addItem(label, value)
        current_theme = state.get("theme", "system")
        idx = next((i for i, (v, _) in enumerate(theme_choices) if v == current_theme), 0)
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(lambda i: on_theme_change(self.theme_combo.itemData(i)))
        theme_layout.addWidget(self.theme_combo)
        outer.addWidget(theme_box)

        lang_box = QGroupBox(t("group_language"))
        lang_layout = QVBoxLayout(lang_box)
        self.lang_combo = QComboBox()
        for code, native_name in LANGUAGES:
            self.lang_combo.addItem(native_name, code)
        current_lang = state.get("language", "en")
        idx = next((i for i, (code, _) in enumerate(LANGUAGES) if code == current_lang), 0)
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(lambda i: on_language_change(self.lang_combo.itemData(i)))
        lang_layout.addWidget(self.lang_combo)
        outer.addWidget(lang_box)

        outer.addStretch(1)


# ---------------------------------------------------------------- main window

class MainWindow(QWidget):
    def __init__(self, state, engine_holder, start_engine_cb, stop_engine_cb, save_cb):
        super().__init__()
        self.state = state
        self.engine_holder = engine_holder
        self.start_engine_cb = start_engine_cb
        self.stop_engine_cb = stop_engine_cb
        self.save_cb = save_cb
        self.enabled = True
        self._current_page_key = "home"

        self.setWindowTitle("DualSense Haptics")
        self._apply_window_icon()
        self.resize(760, 620)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet(f"background: {theme.manager.palette['bg_sidebar']};")
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(12, 20, 12, 20)
        sb_layout.setSpacing(4)

        brand = QLabel("🎮 DS Haptics")
        brand.setStyleSheet("font-size: 15px; font-weight: 700; padding: 0 8px 16px 8px;")
        sb_layout.addWidget(brand)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, _label_key in NAV_ITEMS:
            btn = QPushButton()
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            sb_layout.addWidget(btn)
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
        sb_layout.addStretch(1)

        from config import is_autostart_enabled, set_autostart
        self.autostart_check = QCheckBox()
        self.autostart_check.setChecked(is_autostart_enabled())
        self.autostart_check.toggled.connect(set_autostart)
        sb_layout.addWidget(self.autostart_check)

        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_pages()
        self._retranslate_sidebar()
        self.show_page("home")

        theme.manager.changed.connect(self._on_theme_changed)
        i18n.manager.changed.connect(self._on_language_changed)

    def _build_pages(self):
        self.home_page = HomePage(self.state, self.engine_holder, self._toggle)
        self.presets_page = PresetsPage(self.state, self._apply_preset)
        self.profiles_page = ProfilesPage(self.state, self._apply_profile, self._on_state_changed)
        self.triggers_page = TriggersPage(self.state, self._apply_trigger_preset, self._turn_off_triggers)
        self.button_haptic_page = ButtonHapticPage(self.state, self.save_cb)
        self.advanced_page = AdvancedPage(self.state, self._on_advanced_change)
        self.settings_page = SettingsPage(self.state, self._on_theme_pref_change, self._on_language_pref_change)

        self.pages = {
            "home": self.home_page,
            "presets": self.presets_page,
            "profiles": self.profiles_page,
            "triggers": self.triggers_page,
            "button_haptic": self.button_haptic_page,
            "advanced": self.advanced_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.home_page.set_enabled_text(self.enabled)

    def _retranslate_sidebar(self):
        for key, label_key in NAV_ITEMS:
            self.nav_buttons[key].setText(t(label_key))
        self.autostart_check.setText(t("autostart_checkbox"))

    def _apply_window_icon(self):
        self.setWindowIcon(make_app_icon(theme.manager.palette))

    def show_page(self, key):
        self._current_page_key = key
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)

    def _apply_params(self, new_params, ref):
        active = self.state["active"]
        active["master_gain"] = new_params["master_gain"]
        active["bass_cutoff_hz"] = new_params["bass_cutoff_hz"]
        active["treble_cutoff_hz"] = new_params["treble_cutoff_hz"]
        for band in ("bass", "treble", "bass_ceiling", "treble_ceiling"):
            active[band].clear()
            active[band].update(copy.deepcopy(new_params[band]))
        self.state["active_ref"] = ref
        self._on_state_changed()

    def _apply_preset(self, preset_id):
        self._apply_params(preset_params(preset_id), f"preset:{preset_id}")

    def _apply_profile(self, name):
        self._apply_params(self.state["profiles"][name], f"profile:{name}")

    def _apply_trigger_preset(self, preset_id, side, silent=False):
        ok, err = triggers.apply_trigger_preset(preset_id, side)
        if ok:
            self.state[f"trigger_preset_{side}"] = preset_id
            self._on_state_changed()
        elif not silent:
            QMessageBox.warning(self, t("trigger_apply_fail_title"), err)

    def _turn_off_triggers(self, side):
        ok, err = triggers.turn_off_triggers(side)
        if ok:
            self.state[f"trigger_preset_{side}"] = None
            self._on_state_changed()
        else:
            QMessageBox.warning(self, t("trigger_off_fail_title"), err)

    def reapply_triggers_on_reconnect(self):
        """Called when the controller transitions to "connected". Re-sends the
        last chosen trigger presets unless another process already has the
        controller open (a game reading input, most likely) - see triggers.py."""
        if not self.state.get("trigger_auto_reconnect", True):
            return
        left = self.state.get("trigger_preset_left")
        right = self.state.get("trigger_preset_right")
        if not left and not right:
            return
        if triggers.is_controller_owned_elsewhere():
            return
        if left:
            self._apply_trigger_preset(left, "left", silent=True)
        if right:
            self._apply_trigger_preset(right, "right", silent=True)

    def _on_advanced_change(self):
        self.state["active_ref"] = "custom"
        self._on_state_changed()

    def _on_state_changed(self):
        self.save_cb()
        self.home_page.refresh_active()
        self.presets_page.refresh()
        self.profiles_page.refresh()
        self.triggers_page.refresh()
        self.advanced_page.refresh()

    def _toggle(self):
        if self.enabled:
            self.stop_engine_cb()
            self.enabled = False
        else:
            self.start_engine_cb()
            self.enabled = True
        self.home_page.set_enabled_text(self.enabled)
        if hasattr(self, "on_toggle"):
            self.on_toggle(self.enabled)

    def _on_theme_pref_change(self, preference):
        self.state["theme"] = preference
        self.save_cb()
        theme.manager.set_preference(preference)

    def _on_language_pref_change(self, lang):
        self.state["language"] = lang
        self.save_cb()
        i18n.manager.set_language(lang)

    def _on_theme_changed(self):
        QApplication.instance().setStyleSheet(theme.manager.stylesheet())
        self._apply_window_icon()
        self.sidebar.setStyleSheet(f"background: {theme.manager.palette['bg_sidebar']};")
        self.home_page.gamepad.update()
        if hasattr(self, "on_theme_applied"):
            self.on_theme_applied()

    def _on_language_changed(self):
        key = self._current_page_key
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self._build_pages()
        self._retranslate_sidebar()
        self.show_page(key)
        if hasattr(self, "on_language_applied"):
            self.on_language_applied()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class TrayApp:
    def __init__(self, app, main_window, start_engine_cb, stop_engine_cb, engine_holder):
        self.app = app
        self.main_window = main_window
        self.start_engine_cb = start_engine_cb
        self.stop_engine_cb = stop_engine_cb
        self.engine_holder = engine_holder

        self._status_kind = "searching"  # "searching" | "connected" | "error"
        self._error_msg = ""
        self._disabled = False
        self._icon_status = "searching"
        self._battery_percent = None
        self._battery_raw_status = None
        self._last_status = None

        main_window.on_toggle = self._on_toggle
        main_window.on_theme_applied = self._refresh_icon
        main_window.on_language_applied = self._retranslate

        self.tray = QSystemTrayIcon(make_app_icon(theme.manager.palette, "searching"))

        self.menu = QMenu()
        self.status_action = self.menu.addAction(t("status_searching"))
        self.status_action.setEnabled(False)
        self.battery_action = self.menu.addAction(t("tray_battery_initial"))
        self.battery_action.setEnabled(False)
        self.menu.addSeparator()
        self.toggle_action = self.menu.addAction(t("tray_disable_vibration"))
        self.toggle_action.triggered.connect(self._toggle_from_tray)
        self.open_action = self.menu.addAction(t("tray_open"))
        self.open_action.triggered.connect(self._open_window)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction(t("tray_quit"))
        self.quit_action.triggered.connect(self._quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self._update_tooltip()
        self.tray.show()

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._poll_status)
        self.status_timer.start(300)

        self.battery_timer = QTimer()
        self.battery_timer.timeout.connect(self._poll_battery)
        self.battery_timer.start(30_000)
        self._poll_battery()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._open_window()

    def _open_window(self):
        self.main_window.show_page("home")
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _toggle_from_tray(self):
        self.main_window._toggle()

    def _status_display_text(self):
        if self._disabled:
            return t("status_disabled")
        if self._status_kind == "connected":
            return t("status_connected")
        if self._status_kind == "searching":
            return t("status_searching")
        return t("status_error", msg=self._error_msg)

    def _battery_status_localized(self):
        key = {"Discharging": "battery_discharging", "Charging": "battery_charging",
               "Full": "battery_full"}.get(self._battery_raw_status)
        return t(key) if key else (self._battery_raw_status or "")

    def _battery_display_text(self):
        if self._battery_percent is None:
            return t("tray_battery_missing")
        return t("tray_battery_label", percent=self._battery_percent, status=self._battery_status_localized())

    def _update_tooltip(self):
        self.tray.setToolTip(t("tray_tooltip", status=self._status_display_text()))

    def _refresh_icon(self):
        self.tray.setIcon(make_app_icon(theme.manager.palette, self._icon_status))

    def _retranslate(self):
        self.status_action.setText(self._status_display_text())
        self.battery_action.setText(self._battery_display_text())
        self.toggle_action.setText(t("tray_disable_vibration") if not self._disabled else t("tray_enable_vibration"))
        self.open_action.setText(t("tray_open"))
        self.quit_action.setText(t("tray_quit"))
        self._update_tooltip()

    def _on_toggle(self, enabled):
        self._disabled = not enabled
        self.toggle_action.setText(t("tray_disable_vibration") if enabled else t("tray_enable_vibration"))
        self._icon_status = "off" if not enabled else {
            "connected": "ok", "searching": "searching", "error": "error",
        }.get(self._status_kind, "searching")
        self._refresh_icon()
        self.status_action.setText(self._status_display_text())
        self._update_tooltip()

    def _poll_status(self):
        engine = self.engine_holder()
        if engine is None:
            return
        try:
            while True:
                status = engine.status_queue.get_nowait()
                self._apply_status(status)
        except queue.Empty:
            pass

    def _apply_status(self, status):
        if status == "connected":
            self._status_kind = "connected"
        elif status == "searching":
            self._status_kind = "searching"
        else:
            self._status_kind = "error"
            self._error_msg = status[len("error: "):] if status.startswith("error: ") else status

        if not self._disabled:
            self._icon_status = {"connected": "ok", "searching": "searching", "error": "error"}[self._status_kind]
            self._refresh_icon()

        text = self._status_display_text()
        self.status_action.setText(text)
        self.main_window.home_page.set_status_text(text)
        self._update_tooltip()

        if status == "connected" and self._last_status != "connected":
            QTimer.singleShot(300, self.main_window.reapply_triggers_on_reconnect)
        self._last_status = status

    def _poll_battery(self):
        from haptics_engine import read_battery
        percent, status = read_battery()
        self._battery_percent = percent
        self._battery_raw_status = status
        if percent is None:
            self.battery_action.setText(t("tray_battery_missing"))
            self.main_window.home_page.set_battery_text(t("battery_unknown"))
            return
        self.battery_action.setText(self._battery_display_text())
        self.main_window.home_page.set_battery_text(f"{percent}% · {self._battery_status_localized()}")

    def _quit(self):
        self.stop_engine_cb()
        self.app.quit()
