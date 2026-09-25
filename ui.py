"""PySide6 UI: tray icon + main window (sidebar navigation, home/presets/
profiles/triggers/button-haptic/advanced/settings)."""
import copy
import math
import queue
import re
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QRectF, QPointF, QSize, QEvent, QObject, QPropertyAnimation, QEasingCurve,
    Property, Signal,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QImage, QPainter, QColor, QPen, QLinearGradient, QPainterPath, QFont,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout,
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton, QProgressBar, QGridLayout,
    QStackedWidget, QButtonGroup, QRadioButton, QListWidget, QListWidgetItem, QLineEdit,
    QInputDialog, QMessageBox, QFrame, QScrollArea, QComboBox, QSizePolicy, QColorDialog,
    QToolButton, QAbstractItemView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect, QGraphicsOpacityEffect,
)

from evdev import ecodes as ec

from presets import (
    PRESETS, PRESET_ORDER, preset_params, TRIGGER_PRESETS, TRIGGER_PRESET_ORDER,
    TRIGGER_EFFECT_ORDER, TRIGGER_EFFECT_PARAMS, TRIGGER_PRESET_QUICK_PARAMS,
    TRIGGER_PRESET_SNAP_CLICK, wall_zones_from_feedback_raw,
)
from haptics_engine import (
    DPAD_VIRTUAL_CODE, LEFT_STICK_VIRTUAL_CODE, RIGHT_STICK_VIRTUAL_CODE,
    LEFT_TRIGGER_VIRTUAL_CODE, RIGHT_TRIGGER_VIRTUAL_CODE,
    BT_CHUNK_MS, BT_CHUNK_MS_CHOICES,
    BUTTON_CLICK_HZ, BUTTON_CLICK_HZ_MIN, BUTTON_CLICK_HZ_MAX, DEFAULT_CONFIG,
)
import app_audio_binding
import bt_hid_proxy
import triggers
import theme
import i18n
from config import CONTROLLER_SKINS
from i18n import LANGUAGES

t = i18n.manager.t


def _read_app_version():
    """Single source of truth: the repo-root VERSION file, also read by
    packaging/PKGBUILD for pkgver - keeps the title-bar badge from drifting
    out of sync with the actual shipped version."""
    try:
        return "v" + (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return "v0.0.0"


APP_VERSION = _read_app_version()

# Grouped by physical side of the controller, matching BUTTON_SIDE in
# haptics_engine.py: left-side buttons vibrate the strong/left motor
# (lightly, via their own strength slider), right-side buttons the
# weak/right motor - feedback comes from the side the button is on.
# Each entry is (i18n key, evdev code) so labels follow the active language.
LEFT_BUTTON_OPTIONS = [
    ("btn_dpad", DPAD_VIRTUAL_CODE),
    ("btn_l1", ec.BTN_TL),
    ("btn_l2_press", ec.BTN_TL2),
    ("btn_left_trigger", LEFT_TRIGGER_VIRTUAL_CODE),
    ("btn_l3", ec.BTN_THUMBL),
    ("btn_left_stick", LEFT_STICK_VIRTUAL_CODE),
    ("btn_share", ec.BTN_SELECT),
]
RIGHT_BUTTON_OPTIONS = [
    ("btn_cross", ec.BTN_SOUTH),
    ("btn_circle", ec.BTN_EAST),
    ("btn_triangle", ec.BTN_NORTH),
    ("btn_square", ec.BTN_WEST),
    ("btn_r1", ec.BTN_TR),
    ("btn_r2_press", ec.BTN_TR2),
    ("btn_right_trigger", RIGHT_TRIGGER_VIRTUAL_CODE),
    ("btn_r3", ec.BTN_THUMBR),
    ("btn_right_stick", RIGHT_STICK_VIRTUAL_CODE),
    ("btn_options", ec.BTN_START),
    ("btn_ps", ec.BTN_MODE),
]
BUTTON_OPTIONS = LEFT_BUTTON_OPTIONS + RIGHT_BUTTON_OPTIONS

NAV_ITEMS = [
    ("home", "nav_home", "⌂"), ("presets", "nav_presets", "◇"),
    ("profiles", "nav_profiles", "○"), ("app_audio", "nav_app_audio", "♪"),
    ("triggers", "nav_triggers", "L2"),
    ("button_haptic", "nav_button_haptic", "≋"), ("advanced", "nav_advanced", "☷"),
    ("led", "nav_led", "☼"), ("experimental", "nav_experimental", "✦"),
    ("settings", "nav_settings", "⚙"),
]


# ---------------------------------------------------------------- press animation

# Icon-bearing buttons (sidebar nav items + the sidebar collapse toggle) get an
# animated iconSize on top of the opacity dip below - a checked nav item (the
# active page) rests slightly larger than the rest, hovering grows it further,
# and pressing briefly shrinks it. Keyed by objectName since that's already
# how these buttons are told apart from plain QPushButtons everywhere else in
# the app (which have no icon and so no-op through _resting_icon_size below).
ICON_SIZE_BASE = {"navItem": 20, "sidebarToggle": 30}
ICON_SIZE_CHECKED_BONUS = 2
ICON_SIZE_HOVER_BONUS = 3
ICON_SIZE_PRESS_PENALTY = 3


def _resting_icon_size(btn):
    """None for buttons this effect doesn't apply to (no known base size)."""
    base = ICON_SIZE_BASE.get(btn.objectName())
    if base is None:
        return None
    if btn.objectName() == 'navItem' and btn.property('collapsed'):
        base = 36
    if btn.isCheckable() and btn.isChecked():
        base += ICON_SIZE_CHECKED_BONUS
    return base


def _animate_icon_size(btn, target_px, duration=120):
    if btn.icon().isNull():
        return
    old = getattr(btn, "_icon_size_anim_ref", None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass  # already finished and self-deleted (DeleteWhenStopped) - nothing to stop
    anim = QPropertyAnimation(btn, b"iconSize", btn)
    anim.setDuration(duration)
    anim.setStartValue(btn.iconSize())
    anim.setEndValue(QSize(target_px, target_px))
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    btn._icon_size_anim_ref = anim  # keep alive until it finishes


def settle_icon_size(btn):
    """Animates (or, first time, just sets) `btn`'s icon back to its resting
    size - i.e. the checked-bonus size if it's the active nav item, else the
    plain base size. Called after any checked-state change and as the
    hover/press effect's "return to normal" step."""
    target = _resting_icon_size(btn)
    if target is not None:
        _animate_icon_size(btn, target)


class _PressAnimator(QObject):
    """App-wide event filter that gives every QPushButton a quick opacity dip
    on press and a smooth return on release - QSS alone can't animate a
    transition, so this is done as a tiny QPropertyAnimation per press. Also
    drives the icon-grow/shrink effect above for icon-bearing nav-style
    buttons (a no-op for every other QPushButton in the app)."""

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and obj.isEnabled():
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                self._animate(obj, 0.55)
                base = _resting_icon_size(obj)
                if base is not None:
                    _animate_icon_size(obj, max(10, base - ICON_SIZE_PRESS_PENALTY), duration=70)
            elif etype in (QEvent.Type.MouseButtonRelease, QEvent.Type.Leave):
                self._animate(obj, 1.0)
                settle_icon_size(obj)
            elif etype == QEvent.Type.Enter:
                base = _resting_icon_size(obj)
                if base is not None:
                    _animate_icon_size(obj, base + ICON_SIZE_HOVER_BONUS, duration=120)
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


_EMOJI_ICON_CACHE = {}


def render_emoji_icon(glyph, render_px=64):
    """Renders a monochrome navigation glyph with normal and selected colors."""
    cache_key = (glyph, theme.manager.name)
    cached = _EMOJI_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    def pixmap(color):
        pm = QPixmap(render_px, render_px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont("DejaVu Sans")
        font.setPixelSize(int(render_px * (0.60 if len(glyph) > 1 else 0.85)))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(pm.rect(), Qt.AlignCenter, glyph)
        p.end()
        return pm

    pal = theme.manager.palette
    icon = QIcon()
    icon.addPixmap(pixmap(pal["fg_dim"]), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pixmap(pal["accent_hover"]), QIcon.Mode.Normal, QIcon.State.On)
    _EMOJI_ICON_CACHE[cache_key] = icon
    return icon


def draw_sidebar_toggle_icon(color, render_px=64):
    """Small gamepad mark used as the brand and sidebar-collapse control."""
    pm = QPixmap(render_px, render_px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    rect = QRectF(render_px * 0.10, render_px * 0.23, render_px * 0.80, render_px * 0.50)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(draw_gamepad_path(rect))
    p.setBrush(QColor(theme.manager.palette["bg_sidebar"]))
    p.drawEllipse(QPointF(render_px * 0.34, render_px * 0.47), render_px * 0.055, render_px * 0.055)
    p.drawEllipse(QPointF(render_px * 0.68, render_px * 0.47), render_px * 0.045, render_px * 0.045)
    p.end()
    return QIcon(pm)


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
DEFAULT_GAMEPAD_LIGHT = (22, 140, 255)
OFF_GAMEPAD_LIGHT = (20, 34, 52)

# Display-only shell finishes; no controller LED or haptic setting is changed.
CONTROLLER_FINISHES = {
    'white': '#e0e6f5', 'black': '#343841', 'pink': '#ec82b2',
    'blue': '#438edb', 'purple': '#a086db', 'red': '#c74b65',
}

# Graduated glow: each tier only fades in once the level passes its "lo"
# threshold, reaching full opacity at "hi" - so the halo visibly grows in
# stages with vibration strength instead of one glow that just dims/brightens.
GLOW_TIERS = [
    {"lo": 0.04, "hi": 0.28, "radius": 10, "padding": 16, "max_opacity": 0.85},
    {"lo": 0.28, "hi": 0.52, "radius": 20, "padding": 28, "max_opacity": 0.65},
    {"lo": 0.52, "hi": 0.76, "radius": 32, "padding": 42, "max_opacity": 0.50},
    {"lo": 0.76, "hi": 1.00, "radius": 46, "padding": 58, "max_opacity": 0.40},
]

# Normalized to the full 612x408 bundled image, including its transparent
# padding. Keeping the map in one place also guarantees every page using a
# GamepadWidget highlights exactly the same physical control.
GAMEPAD_FEEDBACK_ANCHORS = {
    ec.BTN_SOUTH: (.688, .434, .025), ec.BTN_EAST: (.732, .370, .025),
    ec.BTN_NORTH: (.689, .303, .025), ec.BTN_WEST: (.644, .368, .025),
    DPAD_VIRTUAL_CODE: (.312, .366, .050),
    LEFT_STICK_VIRTUAL_CODE: (.404, .491, .046), ec.BTN_THUMBL: (.404, .491, .046),
    RIGHT_STICK_VIRTUAL_CODE: (.596, .491, .046), ec.BTN_THUMBR: (.596, .491, .046),
    ec.BTN_TL: (.312, .239, .038), ec.BTN_TR: (.688, .239, .038),
    ec.BTN_TL2: (.312, .208, .038), LEFT_TRIGGER_VIRTUAL_CODE: (.312, .208, .038),
    ec.BTN_TR2: (.688, .208, .038), RIGHT_TRIGGER_VIRTUAL_CODE: (.688, .208, .038),
    ec.BTN_SELECT: (.360, .269, .018), ec.BTN_START: (.642, .269, .018),
    ec.BTN_MODE: (.501, .479, .023),
}


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


def set_responsive_direction(width, *layouts, breakpoint=900):
    """Keep the repeated desktop/narrow layout switch consistent."""
    direction = (QBoxLayout.Direction.TopToBottom
                 if width < breakpoint else QBoxLayout.Direction.LeftToRight)
    for layout in layouts:
        if layout.direction() != direction:
            layout.setDirection(direction)


def fresh_visual_snapshot(engine_holder, max_age=.5):
    """Return one recent controller-input snapshot, or None when unavailable."""
    engine = engine_holder() if engine_holder is not None else None
    snapshot = getattr(engine, "visual_state", None) if engine is not None else None
    if snapshot is None or time.monotonic() - snapshot[0] >= max_age:
        return None
    return snapshot


def make_section_card(layout_cls=QVBoxLayout, margins=(16, 13, 16, 15), spacing=None):
    """Shared 'sectionCard' QFrame shell every dashboard/settings panel built
    by hand (QFrame + objectName + layout + margins); only the inner content
    differs per caller."""
    card = QFrame()
    card.setObjectName("sectionCard")
    layout = layout_cls(card)
    layout.setContentsMargins(*margins)
    if spacing is not None:
        layout.setSpacing(spacing)
    return card, layout


class GamepadWidget(QWidget):
    """Hero illustration on the home page. Pulses a soft accent glow with
    the live motor levels so the dashboard feels alive, not just decorative.

    Prefers a static image at assets/dualsense.png and falls back to a
    hand-drawn silhouette. Expensive image transforms are shared by every
    preview instead of being rebuilt independently on each paint."""

    _SOURCE_CACHE = {}
    _FINISH_CACHE = {}
    _SCALED_CACHE = {}
    _GLOW_CACHE = {}
    _LIGHT_MASK_CACHE = {}
    _LIGHTBAR_CACHE = {}
    _FEEDBACK_CACHE = {}
    _BLACK_DETAIL_CACHE = {}

    @staticmethod
    def _remember(cache, key, value, limit=48):
        cache[key] = value
        while len(cache) > limit:
            cache.pop(next(iter(cache)))
        return value

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.level = 0.0
        self.feedback = {}
        self._parallax = QPointF()
        self.setMouseTracking(True)
        self._image = None
        self._image_mtime = None
        self.skin = 'white'
        self.light_rgb = DEFAULT_GAMEPAD_LIGHT
        self._glow_key = None
        self._glow_layers = []  # list of (padding, QPixmap), outermost first
        self._light_mask_key = None
        self._light_mask = None
        self._reload_image()

    def set_level(self, level):
        level = max(0.0, min(1.0, float(level)))
        changed = abs(level - self.level) >= .002
        self.level = level
        if changed:
            self.update()

    def set_feedback(self, feedback):
        feedback = dict(feedback)
        if feedback != self.feedback:
            self.feedback = feedback
            self.update()

    def set_skin(self, skin):
        skin = skin if skin in CONTROLLER_FINISHES else 'white'
        if skin != self.skin:
            self.skin = skin
            self.update()

    def set_light_color(self, rgb):
        if rgb is None:
            rgb = DEFAULT_GAMEPAD_LIGHT
        try:
            color = tuple(max(0, min(255, round(float(value)))) for value in rgb[:3])
        except (TypeError, ValueError):
            color = DEFAULT_GAMEPAD_LIGHT
        if len(color) != 3:
            color = DEFAULT_GAMEPAD_LIGHT
        if color != self.light_rgb:
            self.light_rgb = color
            self.update()

    def _finished_image(self):
        """Shade neutral shell pixels at render time; retain alpha and details.

        This cache is independent of the live glow/feedback. In particular,
        saturated blue light strips and the dark sticks keep their colors.
        The original PNG is never modified.
        """
        if self.skin == 'white':
            return self._image
        key = (self._image_mtime, self.skin)
        if key in self._FINISH_CACHE:
            return self._FINISH_CACHE[key]
        img = self._image.toImage()
        target = QColor(CONTROLLER_FINISHES[self.skin])
        tint = (target.red(), target.green(), target.blue())
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixelColor(x, y)
                if not pixel.alpha():
                    continue
                channels = (pixel.red(), pixel.green(), pixel.blue())
                luminance = sum(channels) / 3
                if luminance <= 85 or max(channels) - min(channels) > 65:
                    continue
                weight = min(1.0, (luminance - 85) / 65)
                weight = weight * weight * (3 - 2 * weight)
                shade = luminance / 220
                rgb = [round(original * (1 - weight) + min(255, base * shade) * weight)
                       for original, base in zip(channels, tint)]
                img.setPixelColor(x, y, QColor(*rgb, pixel.alpha()))
        finished = QPixmap.fromImage(img)
        return self._remember(self._FINISH_CACHE, key, finished, 16)

    def mouseMoveEvent(self, event):
        self._parallax = QPointF((event.position().x() / max(1, self.width()) - 0.5) * 10,
                                 (event.position().y() / max(1, self.height()) - 0.5) * 6)
        self.update()

    def leaveEvent(self, event):
        self._parallax = QPointF()
        self.update()

    def _reload_image(self):
        path = str(ASSET_IMAGE_PATH)
        cached = self._SOURCE_CACHE.get(path)
        if cached is None:
            try:
                mtime = ASSET_IMAGE_PATH.stat().st_mtime
            except OSError:
                mtime, pixmap = None, None
            else:
                loaded = QPixmap(path)
                pixmap = loaded if not loaded.isNull() else None
            cached = (mtime, pixmap)
            self._SOURCE_CACHE[path] = cached
        self._image_mtime, self._image = cached
        self._glow_key = None  # force glow layer rebuild for the new image
        self._light_mask_key = None
        self._light_mask = None

    def _ensure_glow_layers(self, scaled):
        key = (self._image_mtime, scaled.width(), scaled.height(), theme.manager.name)
        if key == self._glow_key:
            return
        layers = self._GLOW_CACHE.get(key)
        if layers is None:
            silhouette = _recolor_silhouette(scaled, QColor(theme.manager.palette["accent"]))
            layers = [(tier["padding"], _render_blurred(
                silhouette, tier["radius"], tier["padding"])) for tier in GLOW_TIERS]
            self._remember(self._GLOW_CACHE, key, layers, 24)
        self._glow_layers = layers
        self._glow_key = key

    def _ensure_light_mask(self, scaled):
        """Cache the original asset's blue light-strip pixels as an alpha mask."""
        key = (self._image_mtime, scaled.width(), scaled.height())
        if key == self._light_mask_key:
            return
        cached = self._LIGHT_MASK_CACHE.get(key)
        if cached is not None:
            self._light_mask = cached
            self._light_mask_key = key
            return
        # Never derive this mask from the selected finish: a blue/purple
        # shell would otherwise be mistaken for one enormous LED surface.
        # The physical light strips are stable in the untouched source art.
        mask_source = (self._image.scaled(scaled.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                       if self._image is not None else scaled)
        source = mask_source.toImage()
        mask = QImage(source.size(), QImage.Format.Format_ARGB32)
        mask.fill(QColor(0, 0, 0, 0))
        for y in range(source.height()):
            for x in range(source.width()):
                pixel = source.pixelColor(x, y)
                blue_dominance = pixel.blue() - max(pixel.red(), pixel.green())
                if pixel.alpha() and pixel.blue() > 105 and blue_dominance > 28:
                    mask.setPixelColor(x, y, QColor(255, 255, 255, pixel.alpha()))
        self._light_mask = QPixmap.fromImage(mask)
        self._remember(self._LIGHT_MASK_CACHE, key, self._light_mask, 24)
        self._light_mask_key = key

    def _lightbar_layer(self, scaled):
        self._ensure_light_mask(scaled)
        key = (scaled.cacheKey(), self.light_rgb)
        cached = self._LIGHTBAR_CACHE.get(key)
        if cached is not None:
            return cached
        layer = QPixmap(scaled.size())
        layer.fill(Qt.transparent)
        painter = QPainter(layer)
        painter.fillRect(layer.rect(), QColor(*self.light_rgb))
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, self._light_mask)
        painter.end()
        return self._remember(self._LIGHTBAR_CACHE, key, layer, 48)

    def _masked_feedback_layer(self, scaled):
        """Paint control highlights through the controller's alpha mask.

        A radial bloom is useful on the shell, but without this final mask a
        D-pad/trigger near an edge produces a detached circle in empty space.
        The mask keeps the light on the physical surface while retaining its
        soft falloff and the separate ambient silhouette glow behind it.
        """
        feedback_key = tuple(sorted(
            (int(code), round(float(strength), 3))
            for code, strength in self.feedback.items() if strength > 0))
        key = (scaled.cacheKey(), feedback_key)
        cached = self._FEEDBACK_CACHE.get(key)
        if cached is not None:
            return cached
        layer = QPixmap(scaled.size())
        layer.fill(Qt.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.Antialiasing)
        for code, raw_strength in self.feedback.items():
            if code not in GAMEPAD_FEEDBACK_ANCHORS or raw_strength <= 0:
                continue
            strength = max(0.0, min(1.0, float(raw_strength)))
            ax, ay, radius = GAMEPAD_FEEDBACK_ANCHORS[code]
            center = QPointF(ax * scaled.width(), ay * scaled.height())
            radius *= scaled.width()
            glow = QRadialGradient(center, radius * 1.55)
            glow.setColorAt(0, QColor(105, 211, 255, int(100 + strength * 125)))
            glow.setColorAt(.62, QColor(38, 151, 255, int(45 + strength * 70)))
            glow.setColorAt(1, QColor(20, 125, 255, 0))
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center, radius * 1.55, radius * 1.55)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(165, 233, 255, int(115 + strength * 140)), 1.5))
            painter.drawEllipse(center, radius, radius)

        # DestinationIn multiplies the highlight alpha by the exact alpha of
        # the rendered controller, including its anti-aliased outer edge.
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return self._remember(self._FEEDBACK_CACHE, key, layer, 64)

    def _black_detail_layer(self, scaled):
        """Soft button lift for black plastic, without artificial outlines."""
        key = scaled.cacheKey()
        cached = self._BLACK_DETAIL_CACHE.get(key)
        if cached is not None:
            return cached
        layer = QPixmap(scaled.size())
        layer.fill(Qt.transparent)
        p = QPainter(layer)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = scaled.width(), scaled.height()

        # A broad reflection gives the charcoal shell volume without drawing
        # a line around either the body or its controls.
        sheen = QLinearGradient(w * .18, h * .15, w * .78, h * .72)
        sheen.setColorAt(0, QColor(190, 211, 235, 22))
        sheen.setColorAt(.42, QColor(112, 139, 172, 9))
        sheen.setColorAt(1, QColor(15, 39, 70, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(sheen)
        p.drawRect(layer.rect())

        # Controls are lifted by a faint diffuse fill. There is deliberately
        # no pen here: the original image supplies the physical edges and the
        # overlay only separates one dark material from another.
        touch = QLinearGradient(0, h * .205, 0, h * .407)
        touch.setColorAt(0, QColor(171, 184, 201, 20))
        touch.setColorAt(1, QColor(65, 76, 92, 7))
        p.setBrush(touch)
        p.drawRoundedRect(QRectF(w * .383, h * .205, w * .238, h * .202), 8, 8)

        for ax, ay, radius in ((.404, .491, .046), (.596, .491, .046)):
            center = QPointF(w * ax, h * ay)
            r = w * radius
            stick = QRadialGradient(QPointF(center.x() - r * .22, center.y() - r * .25), r * 1.25)
            stick.setColorAt(0, QColor(185, 198, 214, 40))
            stick.setColorAt(.55, QColor(105, 118, 137, 20))
            stick.setColorAt(1, QColor(45, 52, 65, 0))
            p.setBrush(stick)
            p.drawEllipse(center, r, r)

        # Face buttons retain their printed symbols from the source image;
        # only their caps become a touch lighter.
        for code in (ec.BTN_NORTH, ec.BTN_EAST, ec.BTN_SOUTH, ec.BTN_WEST):
            ax, ay, radius = GAMEPAD_FEEDBACK_ANCHORS[code]
            center = QPointF(w * ax, h * ay)
            r = w * radius
            button = QRadialGradient(QPointF(center.x() - r * .25, center.y() - r * .28), r * 1.35)
            button.setColorAt(0, QColor(205, 213, 225, 45))
            button.setColorAt(.65, QColor(116, 128, 146, 24))
            button.setColorAt(1, QColor(55, 64, 79, 0))
            p.setBrush(button)
            p.drawEllipse(center, r, r)

        # The D-pad uses the same diffuse material treatment as the caps.
        ax, ay, radius = GAMEPAD_FEEDBACK_ANCHORS[DPAD_VIRTUAL_CODE]
        cx, cy, r = w * ax, h * ay, w * radius
        cross = QPainterPath()
        cross.moveTo(cx - r * .28, cy - r)
        cross.lineTo(cx + r * .28, cy - r)
        cross.lineTo(cx + r * .28, cy - r * .30)
        cross.lineTo(cx + r, cy - r * .30)
        cross.lineTo(cx + r, cy + r * .30)
        cross.lineTo(cx + r * .28, cy + r * .30)
        cross.lineTo(cx + r * .28, cy + r)
        cross.lineTo(cx - r * .28, cy + r)
        cross.lineTo(cx - r * .28, cy + r * .30)
        cross.lineTo(cx - r, cy + r * .30)
        cross.lineTo(cx - r, cy - r * .30)
        cross.lineTo(cx - r * .28, cy - r * .30)
        cross.closeSubpath()
        dpad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        dpad.setColorAt(0, QColor(200, 210, 224, 42))
        dpad.setColorAt(1, QColor(78, 89, 106, 15))
        p.setBrush(dpad)
        p.drawPath(cross)

        # Keep every reflection inside the actual anti-aliased controller.
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawPixmap(0, 0, scaled)
        p.end()
        return self._remember(self._BLACK_DETAIL_CACHE, key, layer, 24)

    def paintEvent(self, event):
        if self._image is not None:
            self._paint_image(self._finished_image())
        else:
            self._paint_vector()

    def _paint_image(self, pixmap):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        # The bundled PNG deliberately carries generous transparent margins.
        # Oversizing the full canvas makes the visible controller fill the
        # hero area, as it does in the design reference.
        target_w, target_h = w * 1.30, h * 1.42
        scaled_key = (pixmap.cacheKey(), int(target_w), int(target_h))
        scaled = self._SCALED_CACHE.get(scaled_key)
        if scaled is None:
            scaled = pixmap.scaled(
                int(target_w), int(target_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._remember(self._SCALED_CACHE, scaled_key, scaled, 32)
        x = (w - scaled.width()) / 2 + self._parallax.x()
        y = (h - scaled.height()) / 2 + self._parallax.y()

        # Ground plane and compressed reflection sit behind the raised shell.
        floor = h * 0.90
        p.save()
        p.translate(w / 2, floor)
        p.scale(1, 0.10)
        shadow = QRadialGradient(QPointF(0, 0), w * 0.48)
        shadow.setColorAt(0, QColor(40, 125, 255, 150))
        shadow.setColorAt(0.45, QColor(0, 10, 26, 180))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(QPointF(0, 0), w * 0.48, w * 0.48)
        p.restore()
        p.save()
        p.setOpacity(0.10)
        p.translate(x, floor + 6)
        p.scale(1, -0.20)
        p.drawPixmap(0, -int(scaled.height() * 0.80), scaled)
        p.restore()

        self._ensure_glow_layers(scaled)
        # A low, constant blue halo keeps the controller grounded even while
        # the motors are idle; live vibration still expands it in tiers.
        if self._glow_layers:
            padding, layer = self._glow_layers[-1]
            p.setOpacity(0.12)
            p.drawPixmap(int(x - padding), int(y - padding), layer)
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
        if self.skin == 'black':
            p.drawPixmap(int(x), int(y), self._black_detail_layer(scaled))
        p.drawPixmap(int(x), int(y), self._lightbar_layer(scaled))
        if self.feedback:
            p.drawPixmap(int(x), int(y), self._masked_feedback_layer(scaled))
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
        finish = QColor(CONTROLLER_FINISHES[self.skin])
        shell.setColorAt(0, finish.lighter(110))
        shell.setColorAt(1, finish.darker(115))
        p.setBrush(shell)
        p.setPen(QPen(QColor("#9aa0ad"), 1.5))
        p.drawPath(path)

        dark = QColor("#20232c")
        accent = QColor(pal["accent"])
        lit_accent = QColor(*self.light_rgb)
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

        vector_anchors = {
            DPAD_VIRTUAL_CODE: (.20, .44, .10),
            ec.BTN_NORTH: (.80, .34, .045), ec.BTN_EAST: (.89, .44, .045),
            ec.BTN_SOUTH: (.80, .54, .045), ec.BTN_WEST: (.71, .44, .045),
            LEFT_STICK_VIRTUAL_CODE: (.32, .62, .11), ec.BTN_THUMBL: (.32, .62, .11),
            RIGHT_STICK_VIRTUAL_CODE: (.62, .74, .11), ec.BTN_THUMBR: (.62, .74, .11),
            ec.BTN_TL: (.22, .17, .08), ec.BTN_TL2: (.22, .11, .08),
            LEFT_TRIGGER_VIRTUAL_CODE: (.22, .11, .08), ec.BTN_TR: (.78, .17, .08),
            ec.BTN_TR2: (.78, .11, .08), RIGHT_TRIGGER_VIRTUAL_CODE: (.78, .11, .08),
            ec.BTN_SELECT: (.39, .32, .04), ec.BTN_START: (.61, .32, .04),
            ec.BTN_MODE: (.50, .50, .05),
        }
        p.save()
        p.setClipPath(path)
        for code, raw_strength in self.feedback.items():
            if code not in vector_anchors or raw_strength <= 0:
                continue
            strength = max(0.0, min(1.0, float(raw_strength)))
            ax, ay, radius = vector_anchors[code]
            center = QPointF(fx(ax), fy(ay))
            radius *= rect.width()
            glow = QRadialGradient(center, radius * 1.45)
            glow.setColorAt(0, QColor(105, 211, 255, int(100 + strength * 125)))
            glow.setColorAt(1, QColor(20, 125, 255, 0))
            p.setPen(QPen(QColor(165, 233, 255, int(115 + strength * 140)), 1.5))
            p.setBrush(glow)
            p.drawEllipse(center, radius * 1.45, radius * 1.45)
        p.restore()

        p.end()


class ConnectionIndicator(QWidget):
    """Uniform rounded status/transport pills used by every page header."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.status_label = QLabel(t("status_searching"))
        self.usb_label = QLabel("USB")
        self.bt_label = QLabel("Bluetooth")
        for label in (self.status_label, self.usb_label, self.bt_label):
            label.setAlignment(Qt.AlignCenter)
            label.setFixedHeight(36)
        self.status_label.setMinimumWidth(92)
        layout.addWidget(self.status_label)
        layout.addWidget(self.usb_label)
        layout.addWidget(self.bt_label)
        self.kind = None
        self._styled = False
        self.set_connection(None)

    def _pill_style(self, active=False, connected_status=False):
        pal = theme.manager.palette
        if active:
            color, border, background, weight = (
                pal["fg"], pal["accent"], pal["pressed"], 700)
        elif connected_status:
            color, border, background, weight = (
                pal["good"], pal["border"], pal["hero_end"], 700)
        else:
            color, border, background, weight = (
                pal["fg_dim"], pal["border"], pal["hero_end"], 500)
        return (f"background: {background}; color: {color}; border: 1px solid {border}; "
                f"border-radius: 17px; padding: 0 10px; font-size: 10px; font-weight: {weight};")

    def set_connection(self, kind, force=False):
        if self._styled and kind == self.kind and not force:
            return
        self.kind = kind
        self._styled = True
        connected = kind in ("usb", "bluetooth")
        self.status_label.setText(t("status_connected") if connected else t("status_searching"))
        self.status_label.setStyleSheet(self._pill_style(connected_status=connected))
        self.usb_label.setStyleSheet(self._pill_style(kind == "usb"))
        self.bt_label.setStyleSheet(self._pill_style(kind == "bluetooth"))


class BatteryGauge(QWidget):
    """Compact painted battery used by the dashboard summary card."""

    def __init__(self):
        super().__init__()
        self._value = 0
        self.setFixedSize(82, 42)

    def set_text(self, text):
        match = re.search(r"(\d{1,3})\s*%", text)
        self.set_value(int(match.group(1)) if match else 0)

    def set_value(self, value):
        value = max(0, min(100, int(value))) if value is not None else 0
        if value != self._value:
            self._value = value
            self.update()

    def paintEvent(self, event):
        pal = theme.manager.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(2, 5, 70, 32)
        p.setPen(QPen(QColor(pal["fg_dim"]), 2))
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(body, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal["fg_dim"]))
        p.drawRoundedRect(QRectF(74, 13, 6, 16), 2, 2)
        if self._value:
            fill = body.adjusted(5, 5, -5, -5)
            fill.setWidth(fill.width() * self._value / 100)
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0, QColor("#22d95b"))
            grad.setColorAt(1, QColor("#70ef83"))
            p.setBrush(grad)
            p.drawRoundedRect(fill, 3, 3)
        p.end()


class HeroScene(QFrame):
    """Layered lighting behind the controller, clipped to the hero card."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 15, 15)
        p.setClipPath(clip)
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w * .56, h * .2), w * .4)
        glow.setColorAt(0, QColor(61, 106, 206, 90))
        glow.setColorAt(1, QColor(35, 65, 130, 0))
        p.fillRect(self.rect(), glow)
        for offset, alpha in ((0, 105), (.16, 50), (-.13, 30)):
            path = QPainterPath()
            path.moveTo(w * .48, h * (.92 + offset))
            path.cubicTo(w * .70, h * (1.2 + offset), w * .76, h * (.04 + offset), w, h * (.18 + offset))
            p.setPen(QPen(QColor(37, 111, 242, alpha), 1.3))
            p.drawPath(path)
        p.end()


class LedAmbientCard(QFrame):
    """Smoothly fades the actual emitted RGB into the card background."""

    def __init__(self):
        super().__init__()
        self.setObjectName('componentCard')
        self.rgb = [0.0, 0.0, 0.0]
        self.target = (0, 0, 0)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(33)

    def set_color(self, rgb):
        self.target = tuple(rgb) if rgb is not None else (0, 0, 0)

    def _animate(self):
        if not self.isVisible():
            return
        self.phase += .018
        self.rgb = [v + (target - v) * .16 for v, target in zip(self.rgb, self.target)]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
        p.setClipPath(clip)
        rgb = tuple(round(v) for v in self.rgb)
        for x, alpha in ((.3 + .13 * math.sin(self.phase), 135), (.8, 70)):
            gradient = QRadialGradient(QPointF(self.width() * x, self.height()), self.width() * .8)
            gradient.setColorAt(0, QColor(*rgb, alpha))
            gradient.setColorAt(1, QColor(*rgb, 0))
            p.fillRect(self.rect(), gradient)
        p.end()


class LightbarDots(QWidget):
    """Current emitted RGB swatch; unavailable data never implies a color."""

    def __init__(self):
        super().__init__()
        self._enabled = False
        self.rgb = None
        self.setMinimumHeight(42)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self.update()

    def set_color(self, rgb):
        self.rgb = rgb
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(*self.rgb) if self.rgb is not None else QColor(theme.manager.palette['border'])
        p.setPen(QPen(QColor(theme.manager.palette['fg_dim']), 1))
        p.setBrush(color)
        p.drawEllipse(QPointF(17, self.height() / 2), 12, 12)
        p.setPen(QColor(theme.manager.palette['fg']))
        text = color.name().upper() if self.rgb is not None else t('dashboard_no_data')
        p.drawText(QRectF(40, 0, self.width() - 40, self.height()), Qt.AlignVCenter, text)
        p.end()


class PlayerLedMeter(QWidget):
    """Five-dot preview matching the controller's player LED strength bar."""

    def __init__(self):
        super().__init__()
        self._lit = 0
        self.setFixedHeight(28)

    def set_level(self, level):
        self._lit = round(max(0.0, min(1.0, level)) * 5)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.manager.palette
        for i in range(5):
            color = QColor(pal['accent_hover'] if i < self._lit else pal['border'])
            if i < self._lit:
                glow = QRadialGradient(QPointF(10 + i * 22, 14), 11)
                halo = QColor(color)
                halo.setAlpha(105)
                glow.setColorAt(0, halo)
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QPointF(10 + i * 22, 14), 11, 11)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(7 + i * 22, 9, 6, 10), 3, 3)
        p.end()


class LedPreviewScene(QFrame):
    """Depth-lit preview surface whose ambient color follows live LED RGB."""

    def __init__(self):
        super().__init__()
        self.setObjectName('ledPreview')
        self.rgb = [22.0, 140.0, 255.0]
        self.target = (22, 140, 255)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(33)

    def set_color(self, rgb):
        self.target = tuple(rgb) if rgb is not None else (22, 140, 255)

    def _animate(self):
        if not self.isVisible():
            return
        self.phase += .02
        self.rgb = [value + (target - value) * .12 for value, target in zip(self.rgb, self.target)]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)
        p.setClipPath(clip)
        rgb = tuple(round(value) for value in self.rgb)
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w * (.48 + math.sin(self.phase) * .03), h * .62), w * .48)
        glow.setColorAt(0, QColor(*rgb, 120))
        glow.setColorAt(.52, QColor(*rgb, 35))
        glow.setColorAt(1, QColor(*rgb, 0))
        p.fillRect(self.rect(), glow)
        floor = QLinearGradient(0, h * .72, 0, h)
        floor.setColorAt(0, QColor(*rgb, 0))
        floor.setColorAt(1, QColor(*rgb, 45))
        p.fillRect(self.rect(), floor)
        p.end()


class MotorWaveWidget(QWidget):
    """Live bar-wave view over the same bass/treble levels as the old meter."""

    def __init__(self, variant):
        super().__init__()
        self.variant = variant
        self._value = 0
        self._phase = 0.0
        self.setMinimumHeight(58)

    def setRange(self, lo, hi):
        pass

    def setValue(self, value):
        self._value = max(0, min(100, int(value)))
        self._phase = (self._phase + 0.22) % (math.pi * 2)
        self.update()

    def paintEvent(self, event):
        pal = theme.manager.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        well = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor(pal["border"]), 1))
        p.setBrush(QColor(pal["hero_end"]))
        p.drawRoundedRect(well, 9, 9)

        count = max(18, int((self.width() - 24) / 9))
        usable_w = self.width() - 24
        step = usable_w / count
        energy = 0.12 + self._value / 100 * 0.88
        start = QColor(pal["accent"])
        end = QColor("#7d4dff" if self.variant == "treble" else "#35b7ff")
        center_y = self.height() / 2
        for i in range(count):
            wave = abs(math.sin(i * 0.43 + self._phase))
            envelope = 0.45 + 0.55 * abs(math.sin(i * 0.17 + (1.2 if self.variant == "treble" else 0.0)))
            bar_h = max(3.0, (5 + wave * (self.height() - 18) * envelope) * energy)
            mix = i / max(1, count - 1)
            color = QColor(
                int(start.red() + (end.red() - start.red()) * mix),
                int(start.green() + (end.green() - start.green()) * mix),
                int(start.blue() + (end.blue() - start.blue()) * mix),
            )
            color.setAlpha(125 if self._value == 0 else 235)
            p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
            x = 12 + i * step + step / 2
            p.drawLine(QPointF(x, center_y - bar_h / 2), QPointF(x, center_y + bar_h / 2))
        p.end()


class DualMotorWaveWidget(QWidget):
    """Compact two-channel waveform used by the vibration profile banner."""

    def __init__(self):
        super().__init__()
        self.strong = 0.0
        self.weak = 0.0
        self.phase = 0.0
        self.setMinimumHeight(78)

    def set_levels(self, strong, weak):
        self.strong = max(0.0, min(1.0, float(strong)))
        self.weak = max(0.0, min(1.0, float(weak)))
        self.phase = (self.phase + .23) % (math.pi * 2)
        self.update()

    def _wave_path(self, level, phase_shift, frequency):
        path = QPainterPath()
        left, right = 8.0, max(9.0, self.width() - 8.0)
        center = self.height() / 2
        amplitude = (4.0 + level * max(8.0, self.height() * .34))
        samples = max(36, int(right - left))
        for i in range(samples + 1):
            ratio = i / samples
            x = left + (right - left) * ratio
            envelope = math.sin(math.pi * ratio) ** .72
            detail = .64 + .36 * math.sin(ratio * 31 + self.phase * .7)
            y = center + math.sin(ratio * frequency + self.phase + phase_shift) * amplitude * envelope * detail
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = self.height() / 2
        p.setPen(QPen(QColor(theme.manager.palette['border']), 1))
        p.drawLine(QPointF(7, center), QPointF(self.width() - 7, center))
        waves = (
            (self.strong, 0.0, 43, QColor('#8b5cff')),
            (self.weak, 1.3, 59, QColor('#20adff')),
        )
        for level, shift, frequency, color in waves:
            path = self._wave_path(level, shift, frequency)
            halo = QColor(color)
            halo.setAlpha(70 + int(level * 65))
            p.setPen(QPen(halo, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            color.setAlpha(155 + int(level * 100))
            p.setPen(QPen(color, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.end()


class ReactiveControllerOutline(GamepadWidget):
    """Real controller render with independent surface pulses per motor."""

    MOTOR_ANCHORS = {
        # Each physical motor owns both visual zones on its side. The upper
        # point is cyan and the lower point purple, while their shared level
        # still comes from the real left/right output channel.
        'left': {
            'upper': (.265, .355),
            'lower': (.285, .675),
        },
        'right': {
            'upper': (.735, .355),
            'lower': (.715, .675),
        },
    }
    MOTOR_COLORS = {
        'upper': QColor('#18b8ff'),
        'lower': QColor('#955cff'),
    }
    MOTOR_RADII = {
        'upper': .056,
        'lower': .068,
    }

    def __init__(self):
        super().__init__()
        self.strong = 0.0
        self.weak = 0.0
        self.phase = 0.0
        self.setMinimumSize(280, 154)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_levels(self, strong, weak):
        self.strong = max(0.0, min(1.0, float(strong)))
        self.weak = max(0.0, min(1.0, float(weak)))
        self.level = max(self.strong, self.weak)
        self.phase = (self.phase + .18) % (math.pi * 2)
        self.update()

    def _motor_surface_layer(self, scaled):
        layer = QPixmap(scaled.size())
        layer.fill(Qt.transparent)
        p = QPainter(layer)
        p.setRenderHint(QPainter.Antialiasing)
        pulse = .90 + .10 * math.sin(self.phase * 1.8)
        motors = (
            (self.strong, self.MOTOR_ANCHORS['left']),
            (self.weak, self.MOTOR_ANCHORS['right']),
        )
        for level, zones in motors:
            energy = level * pulse
            if energy <= .005:
                continue
            for zone, (anchor_x, anchor_y) in zones.items():
                color = self.MOTOR_COLORS[zone]
                radius = scaled.width() * (self.MOTOR_RADII[zone] + energy * .030)
                center = QPointF(scaled.width() * anchor_x, scaled.height() * anchor_y)
                glow = QRadialGradient(center, radius * 1.85)
                glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 45 + int(energy * 190)))
                glow.setColorAt(.34, QColor(color.red(), color.green(), color.blue(), 24 + int(energy * 120)))
                glow.setColorAt(.72, QColor(color.red(), color.green(), color.blue(), 8 + int(energy * 35)))
                glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(center, radius * 1.85, radius * 1.85)

        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawPixmap(0, 0, scaled)
        p.end()
        return layer

    def _paint_image(self, pixmap):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        target_w, target_h = w * 1.18, h * 1.58
        scaled = pixmap.scaled(int(target_w), int(target_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (w - scaled.width()) / 2 + self._parallax.x()
        y = (h - scaled.height()) / 2 - h * .025 + self._parallax.y()

        # Each reflection follows its own motor as well. At zero there is
        # no coloured residue that could look like activity on another side.
        floor_y = h * .86
        floor_specs = (
            (self.strong, w * .40, QColor('#8655ff')),
            (self.weak, w * .60, QColor('#8655ff')),
        )
        for level, cx, color in floor_specs:
            if level <= .005:
                continue
            floor = QRadialGradient(QPointF(cx, floor_y), w * .28)
            alpha = 12 + int(level * 103)
            floor.setColorAt(0, QColor(color.red(), color.green(), color.blue(), alpha))
            floor.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(floor)
            p.drawEllipse(QPointF(cx, floor_y), w * .28, h * .12)

        self._ensure_glow_layers(scaled)
        if self._glow_layers:
            padding, layer = self._glow_layers[-1]
            # A quiet, constant silhouette gives the controller depth; live
            # energy is deliberately confined to the matching motor zones.
            p.setOpacity(.07)
            p.drawPixmap(int(x - padding), int(y - padding), layer)
        p.setOpacity(1.0)
        p.drawPixmap(int(x), int(y), scaled)
        if self.skin == 'black':
            p.drawPixmap(int(x), int(y), self._black_detail_layer(scaled))
        p.drawPixmap(int(x), int(y), self._lightbar_layer(scaled))
        p.drawPixmap(int(x), int(y), self._motor_surface_layer(scaled))
        if self.feedback:
            p.drawPixmap(int(x), int(y), self._masked_feedback_layer(scaled))
        p.end()


class TriggerSilhouette(QWidget):
    """Small L2/R2 hardware illustration drawn entirely with Qt."""

    def __init__(self, side_label):
        super().__init__()
        self.side_label = side_label
        self.setFixedSize(94, 108)

    def paintEvent(self, event):
        pal = theme.manager.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.save()
        if self.side_label == 'R2':
            p.translate(self.width(), 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(24, 12)
        path.cubicTo(35, 7, 64, 7, 70, 14)
        path.cubicTo(76, 28, 78, 70, 69, 92)
        path.cubicTo(61, 102, 34, 102, 28, 92)
        path.cubicTo(19, 72, 15, 28, 24, 12)
        grad = QLinearGradient(22, 10, 74, 100)
        grad.setColorAt(0, QColor("#2b3c55"))
        grad.setColorAt(0.55, QColor("#101a29"))
        grad.setColorAt(1, QColor("#53657c"))
        p.setPen(QPen(QColor(pal["border"]), 2))
        p.setBrush(grad)
        p.drawPath(path)
        p.restore()
        p.setPen(QColor("#f3f6ff"))
        font = QFont("DejaVu Sans")
        font.setPixelSize(18)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, self.side_label)
        p.end()


def trigger_dashboard_values(state, side):
    """Returns display-only start/force percentages for the applied effect."""
    preset_id = state.get(f"trigger_preset_{side}")
    if preset_id == "custom":
        custom = state.get(f"trigger_custom_{side}") or {}
        values = dict(custom.get("values") or {})
    elif preset_id in TRIGGER_PRESETS:
        values = dict(TRIGGER_PRESETS[preset_id]["values"])
        values.update(state.get(f"trigger_preset_params_{side}", {}).get(preset_id, {}))
    else:
        return 0, 0

    start = values.get("start", values.get("position", 0))
    if "strength" in values:
        force, force_max = values["strength"], 8
    elif "amplitude" in values:
        force, force_max = values["amplitude"], 8
    elif "strength_b" in values:
        force, force_max = values["strength_b"], 7
    else:
        raw = [value for key, value in values.items() if key.startswith(("s", "a")) and key[1:].isdigit()]
        force, force_max = (max(raw), 8) if raw else (0, 8)
    return round(max(0, min(9, start)) / 9 * 100), round(max(0, min(force_max, force)) / force_max * 100)


class TriggerDashboardPanel(QFrame):
    """Quick preset selection using the same apply handlers as Triggers."""

    def __init__(self, state, side, side_label, select_cb=None):
        super().__init__()
        self.side = side
        self.state = state
        self.select_cb = select_cb
        self.setObjectName("triggerPanel")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        silhouette = TriggerSilhouette(side_label)
        if side == 'left':
            layout.addWidget(silhouette, 0, Qt.AlignVCenter)

        details = QVBoxLayout()
        details.setSpacing(5)
        mode_caption = QLabel(t("home_mode"))
        mode_caption.setProperty("role", "hint")
        details.addWidget(mode_caption)
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(120)
        self.mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode_combo.setMinimumContentsLength(10)
        self.mode_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.mode_combo.addItem(t('label_trigger_off'), None)
        for preset_id in TRIGGER_PRESET_ORDER:
            self.mode_combo.addItem(t(f'trigger_{preset_id}_label'), preset_id)
        self.mode_combo.activated.connect(self._select)
        details.addWidget(self.mode_combo)
        self.start_bar, self.start_value = self._add_meter(details, t("trig_param_start"))
        self.force_bar, self.force_value = self._add_meter(details, t("trig_param_strength"))
        layout.addLayout(details, 1)
        if side == 'right':
            layout.addWidget(silhouette, 0, Qt.AlignVCenter)
        self.refresh(state)

    def _select(self, index):
        preset_id = self.mode_combo.itemData(index)
        if preset_id != 'custom' and self.select_cb:
            self.select_cb(preset_id, self.side)
        # On hardware failure the applied state remains authoritative.
        self.refresh(self.state)

    def _add_meter(self, layout, caption):
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(caption)
        label.setProperty("role", "hint")
        label.setFixedWidth(max(62, max(label.fontMetrics().horizontalAdvance(t(key))
                                       for key in ('trig_param_start', 'trig_param_strength')) + 4))
        row.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setFixedHeight(7)
        row.addWidget(bar, 1)
        value = QLabel("0%")
        value.setProperty("role", "hint")
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setFixedWidth(34)
        row.addWidget(value)
        layout.addLayout(row)
        return bar, value

    def refresh(self, state):
        start, force = trigger_dashboard_values(state, self.side)
        self.mode_combo.blockSignals(True)
        custom_index = self.mode_combo.findData('custom')
        if custom_index >= 0:
            self.mode_combo.removeItem(custom_index)
        preset_id = state.get(f'trigger_preset_{self.side}')
        if preset_id == 'custom':
            self.mode_combo.addItem(trigger_ref_label(state, self.side), 'custom')
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(preset_id)))
        self.mode_combo.blockSignals(False)
        self.start_bar.setValue(start)
        self.force_bar.setValue(force)
        self.start_value.setText(f"{start}%")
        self.force_value.setText(f"{force}%")


# ---------------------------------------------------------------- shared widgets

class HoverGrowWrapper(QWidget):
    """Transparent wrapper that reserves `grow_px` of space around its single
    child on every side and, on hover, smoothly grows the child edge-to-edge
    into that reserved space and back - a real size change (not a cosmetic
    highlight), but one the surrounding layout never sees: this wrapper's
    own sizeHint already includes the reserved margin (constant regardless
    of hover state), and the child has no QLayout of its own managing it in
    here (parented directly, positioned via setGeometry in resizeEvent),
    so nothing else on the page ever has to move.

    Works for both a fixed-size child (a button) and one that stretches to
    fill its row/column (a slider, a settings card) - this wrapper copies
    the child's own size policy, so adding the wrapper to a layout the same
    way the child used to be added (same stretch factor/alignment) keeps
    that behavior; resizeEvent() keeps the child filling whatever space the
    wrapper is actually given, minus the current (animated) inset."""

    def __init__(self, child, grow_px=4, parent=None):
        super().__init__(parent)
        self._child = child
        self._grow_px = grow_px
        self._inset = float(grow_px)
        child.setParent(self)
        child.installEventFilter(self)
        self.setSizePolicy(child.sizePolicy())
        self._anim = QPropertyAnimation(self, b"inset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._layout_child()

    def sizeHint(self):
        h = self._child.sizeHint()
        return QSize(h.width() + 2 * self._grow_px, h.height() + 2 * self._grow_px)

    def minimumSizeHint(self):
        h = self._child.minimumSizeHint()
        return QSize(h.width() + 2 * self._grow_px, h.height() + 2 * self._grow_px)

    def hasHeightForWidth(self):
        return self._child.hasHeightForWidth()

    def heightForWidth(self, width):
        # A card's word-wrapped hint text genuinely needs more height at a
        # narrower width - without forwarding this, Qt's constrained-width
        # layout pass (any QVBoxLayout column, this one included) falls back
        # to the width-independent sizeHint() above, which silently
        # undershoots once the wrapper is actually laid out narrower than
        # that assumption - e.g. two side-by-side trigger columns where one
        # ends up a few px narrower than the other, wrapping its text onto
        # an extra line that this wrapper then doesn't leave room for,
        # visibly squashing that column's cards relative to its sibling's.
        inner = max(0, width - 2 * self._grow_px)
        return self._child.heightForWidth(inner) + 2 * self._grow_px

    def resizeEvent(self, event):
        self._layout_child()
        super().resizeEvent(event)

    def event(self, event):
        # The child isn't inside a QLayout (its geometry is set by hand in
        # _layout_child, so hover-growing doesn't fight Qt's layout engine),
        # so when its own content changes size (e.g. CustomTriggerCard
        # rebuilding its sliders for a different mode) Qt has nowhere to
        # deliver that "I need more room" signal except a LayoutRequest
        # event posted straight to us. Forward it as our own updateGeometry()
        # so it keeps bubbling up to whatever real layout manages *this*
        # widget - without this, the wrapper stays stuck at its original
        # size and new content gets clipped/squished inside it.
        if event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return super().event(event)

    def _layout_child(self):
        inset = int(round(self._inset))
        w = max(0, self.width() - 2 * inset)
        h = max(0, self.height() - 2 * inset)
        self._child.setGeometry(inset, inset, w, h)

    def getInset(self):
        return self._inset

    def setInset(self, value):
        self._inset = value
        self._layout_child()

    inset = Property(float, getInset, setInset)

    def _animate_to(self, target):
        try:
            self._anim.stop()
        except RuntimeError:
            pass  # already finished and self-deleted - nothing to stop
        self._anim.setStartValue(self._inset)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        self._animate_to(0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_to(self._grow_px)
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        if obj is self._child:
            if event.type() == QEvent.Type.Enter:
                self._animate_to(0)
            elif event.type() == QEvent.Type.Leave:
                self._animate_to(self._grow_px)
        return False


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
        layout.addWidget(HoverGrowWrapper(self.slider, grow_px=3))

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


class IntSlider(QWidget):
    """Plain integer slider (no float remapping) for the small raw ranges
    dualsensectl's custom trigger parameters use, e.g. 0-9."""

    def __init__(self, label, lo, hi, value, on_change=None):
        super().__init__()
        self.on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        row = QHBoxLayout()
        name = QLabel(label)
        self.value_label = QLabel(str(value))
        self.value_label.setProperty("role", "value")
        self.value_label.setAlignment(Qt.AlignRight)
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(self.value_label)
        layout.addLayout(row)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._changed)
        layout.addWidget(HoverGrowWrapper(self.slider, grow_px=3))

    def _changed(self, v):
        self.value_label.setText(str(v))
        if self.on_change:
            self.on_change(v)

    def value(self):
        return self.slider.value()

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.value_label.setText(str(v))


def band_group(title, cfg, ceil_cfg, on_change, variant="bass"):
    box = QFrame()
    box.setObjectName('sectionCard')
    layout = QVBoxLayout(box)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(4)

    header = QHBoxLayout()
    icon = QLabel('◎' if variant == 'bass' else '〰')
    icon.setObjectName('vibrationBandIcon')
    icon.setProperty('variant', variant)
    icon.setAlignment(Qt.AlignCenter)
    icon.setFixedSize(44, 44)
    header.addWidget(icon)
    heading = QVBoxLayout()
    heading.setSpacing(1)
    title_label = QLabel(title)
    title_label.setProperty('role', 'h2')
    heading.addWidget(title_label)
    subtitle = QLabel(t('slider_lo_hint'))
    subtitle.setProperty('role', 'hint')
    subtitle.setWordWrap(True)
    heading.addWidget(subtitle)
    header.addLayout(heading, 1)
    layout.addLayout(header)

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
    if pid == "custom":
        custom = state.get(f"trigger_custom_{side}") or {}
        mode = custom.get("mode", "off")
        return f"{t('label_trigger_custom')}: {t(f'trig_mode_{mode}')}"
    if pid and pid in TRIGGER_PRESETS:
        return t(f"trigger_{pid}_label")
    return t("label_trigger_off")


# ---------------------------------------------------------------- pages

class HomePage(QWidget):
    def __init__(self, state, engine_holder, toggle_cb, trigger_cb=None, skin_cb=None):
        super().__init__()
        self.state = state
        self.engine_holder = engine_holder
        self.skin_cb = skin_cb
        self.lightbar_rgb = self._configured_led_color()

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("DualSense Haptics")
        title.setProperty("role", "h1")
        heading.addWidget(title)
        subtitle = QLabel(t("home_subtitle"))
        subtitle.setProperty("role", "hint")
        heading.addWidget(subtitle)
        top.addLayout(heading)
        top.addStretch(1)
        self.status_label = QLabel("...")
        self.status_label.setProperty("role", "status")
        top.addWidget(self.status_label)
        self.connection_indicator = ConnectionIndicator()
        top.addWidget(self.connection_indicator)
        root.addLayout(top)

        hero_card = HeroScene()
        hero_card.setObjectName("heroCard")
        hero_card.setMinimumHeight(250)
        hero_layout = QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(26, 14, 20, 14)
        hero_layout.setSpacing(16)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(7)
        hero_text.addStretch(1)
        controller_name = QLabel("DualSense Wireless Controller")
        controller_name.setWordWrap(True)
        controller_name.setStyleSheet("font-size: 17px; font-weight: 750;")
        hero_text.addWidget(controller_name)
        manufacturer = QLabel("SONY INTERACTIVE ENTERTAINMENT")
        manufacturer.setProperty("role", "eyebrow")
        hero_text.addWidget(manufacturer)
        hero_text.addSpacing(13)
        battery_caption = QLabel(t("home_battery"))
        battery_caption.setProperty("role", "hint")
        hero_text.addWidget(battery_caption)
        self.hero_battery_label = QLabel(t("battery_unknown"))
        self.hero_battery_label.setProperty("role", "heroValue")
        hero_text.addWidget(self.hero_battery_label)
        skin_label = QLabel(t('controller_skin'))
        skin_label.setProperty('role', 'hint')
        hero_text.addWidget(skin_label)
        self.skin_combo = QComboBox()
        self.skin_combo.setMaximumWidth(220)
        for skin in CONTROLLER_SKINS:
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(CONTROLLER_FINISHES[skin]))
            self.skin_combo.addItem(QIcon(swatch), t(f'controller_skin_{skin}'), skin)
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(state.get('controller_skin', 'white'))))
        self.skin_combo.activated.connect(self._select_skin)
        hero_text.addWidget(self.skin_combo)
        hero_text.addStretch(1)
        hero_layout.addLayout(hero_text, 3)

        self.gamepad = GamepadWidget()
        self.gamepad.set_skin(state.get('controller_skin', 'white'))
        self.gamepad.set_light_color(self.lightbar_rgb)
        self.gamepad.setObjectName("gamepadArt")
        self.gamepad.setMinimumHeight(220)
        hero_layout.addWidget(self.gamepad, 5)
        motto = QLabel('S A M E\nG A M E S\n\nD E E P E R\nF E E L I N G S')
        motto.setProperty('role', 'hint')
        motto.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        hero_layout.addWidget(motto, 2)
        root.addWidget(hero_card)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        active_card, ac_layout = make_section_card(QHBoxLayout, margins=(18, 14, 18, 14))
        profile_icon = QLabel("◈")
        profile_icon.setObjectName("dashboardIcon")
        profile_icon.setAlignment(Qt.AlignCenter)
        profile_icon.setFixedSize(42, 42)
        ac_layout.addWidget(profile_icon)
        profile_text = QVBoxLayout()
        profile_text.setSpacing(5)
        ac_hdr = QLabel(t("home_active_profile"))
        ac_hdr.setProperty("role", "h2")
        profile_text.addWidget(ac_hdr)
        self.active_label = QLabel(ref_label(state))
        self.active_label.setProperty("role", "activeField")
        profile_text.addWidget(self.active_label)
        ac_layout.addLayout(profile_text, 1)
        summary_row.addWidget(active_card, 2)

        toggle_card, tc_layout = make_section_card(QHBoxLayout, margins=(18, 14, 18, 14))
        action_icon = QLabel("≋")
        action_icon.setObjectName("dashboardIcon")
        action_icon.setAlignment(Qt.AlignCenter)
        action_icon.setFixedSize(42, 42)
        tc_layout.addWidget(action_icon)
        toggle_text = QVBoxLayout()
        tc_hdr = QLabel(t("home_vibration"))
        tc_hdr.setProperty("role", "h2")
        toggle_text.addWidget(tc_hdr)
        toggle_hint = QLabel(t("label_custom_settings"))
        toggle_hint.setProperty("role", "hint")
        toggle_text.addWidget(toggle_hint)
        tc_layout.addLayout(toggle_text, 1)
        self.toggle_btn = QPushButton(t("btn_disable"))
        self.toggle_btn.setObjectName("primary")
        self.toggle_btn.clicked.connect(toggle_cb)
        self.toggle_btn.setMinimumWidth(120)
        tc_layout.addWidget(self.toggle_btn)
        summary_row.addWidget(toggle_card, 3)

        self.autostart_card, startup_layout = make_section_card(margins=(18, 14, 18, 14), spacing=5)
        startup_heading = QLabel(t("autostart_checkbox"))
        startup_heading.setProperty("role", "h2")
        startup_heading.setWordWrap(True)
        startup_layout.addWidget(startup_heading)
        from config import is_autostart_enabled, set_autostart
        self.autostart_check = QCheckBox(t("btn_enable"))
        self.autostart_check.setMinimumHeight(32)
        self.autostart_check.setAccessibleName(t("autostart_checkbox"))
        self.autostart_check.setToolTip(t("autostart_checkbox"))
        self.autostart_check.setChecked(is_autostart_enabled())
        self.autostart_check.toggled.connect(set_autostart)
        startup_layout.addWidget(self.autostart_check)
        summary_row.addWidget(self.autostart_card, 1)
        root.addLayout(summary_row)

        trigger_card, tg_layout = make_section_card()
        trigger_header = QHBoxLayout()
        tg_hdr = QLabel(t("home_adaptive_triggers"))
        tg_hdr.setProperty("role", "h2")
        trigger_header.addWidget(tg_hdr)
        trigger_header.addStretch(1)
        trigger_hint = QLabel(t("home_trigger_tagline"))
        trigger_hint.setProperty("role", "hint")
        trigger_hint.setMaximumWidth(520)
        trigger_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        trigger_header.addWidget(trigger_hint)
        tg_layout.addLayout(trigger_header)
        tg_row = QHBoxLayout()
        tg_row.setSpacing(10)
        self.trigger_panels = {}
        for side, side_label in (("left", "L2"), ("right", "R2")):
            panel = TriggerDashboardPanel(state, side, side_label, trigger_cb)
            self.trigger_panels[side] = panel
            tg_row.addWidget(panel, 1)
        tg_layout.addLayout(tg_row)
        root.addWidget(trigger_card)

        components_row = QHBoxLayout()
        components_row.setSpacing(10)
        battery_card = QFrame()
        battery_card.setObjectName("componentCard")
        bc_layout = QVBoxLayout(battery_card)
        bc_layout.setContentsMargins(17, 13, 17, 14)
        bc_hdr = QLabel(t("home_battery"))
        bc_hdr.setProperty("role", "h2")
        bc_layout.addWidget(bc_hdr)
        battery_row = QHBoxLayout()
        self.battery_gauge = BatteryGauge()
        battery_row.addWidget(self.battery_gauge)
        self.battery_label = QLabel(t("battery_unknown"))
        self.battery_label.setProperty("role", "componentValue")
        self.battery_label.setWordWrap(True)
        battery_row.addWidget(self.battery_label, 1)
        bc_layout.addLayout(battery_row)
        components_row.addWidget(battery_card, 1)

        vibration_card = QFrame()
        vibration_card.setObjectName("componentCard")
        vb_layout = QVBoxLayout(vibration_card)
        vb_layout.setContentsMargins(17, 13, 17, 14)
        vb_hdr = QLabel(t("home_vibration"))
        vb_hdr.setProperty("role", "h2")
        vb_layout.addWidget(vb_hdr)
        gain_row = QHBoxLayout()
        gain_caption = QLabel(t("label_master_gain"))
        gain_caption.setProperty("role", "hint")
        gain_row.addWidget(gain_caption)
        gain_row.addStretch(1)
        self.vibration_strength_value = QLabel()
        self.vibration_strength_value.setProperty("role", "value")
        gain_row.addWidget(self.vibration_strength_value)
        vb_layout.addLayout(gain_row)
        self.vibration_strength_bar = QProgressBar()
        self.vibration_strength_bar.setRange(0, 100)
        self.vibration_strength_bar.setFixedHeight(8)
        vb_layout.addWidget(self.vibration_strength_bar)
        components_row.addWidget(vibration_card, 1)

        self.lightbar_card = LedAmbientCard()
        lightbar_card = self.lightbar_card
        lb_layout = QVBoxLayout(lightbar_card)
        lb_layout.setContentsMargins(17, 13, 17, 14)
        lightbar_header = QHBoxLayout()
        lightbar_title = QLabel(t("led_title"))
        lightbar_title.setProperty("role", "h2")
        lightbar_header.addWidget(lightbar_title)
        lightbar_header.addStretch(1)
        self.lightbar_state_label = QLabel()
        self.lightbar_state_label.setProperty("role", "value")
        lightbar_header.addWidget(self.lightbar_state_label)
        lb_layout.addLayout(lightbar_header)
        self.lightbar_dots = LightbarDots()
        lb_layout.addWidget(self.lightbar_dots)
        components_row.addWidget(lightbar_card, 1)
        root.addLayout(components_row)

        self.feedback_label = QLabel(t('dashboard_feedback_idle'))
        self.feedback_label.setProperty('role', 'hint')
        self.feedback_label.setWordWrap(True)
        root.addWidget(self.feedback_label)

        meter_card = QFrame()
        meter_card.setObjectName("motorCard")
        m_layout = QVBoxLayout(meter_card)
        m_layout.setContentsMargins(17, 13, 17, 15)
        motor_header = QHBoxLayout()
        m_hdr = QLabel(t("home_motor_response"))
        m_hdr.setProperty("role", "h2")
        motor_header.addWidget(m_hdr)
        motor_header.addStretch(1)
        live_label = QLabel(t("home_realtime"))
        live_label.setProperty("role", "hint")
        motor_header.addWidget(live_label)
        m_layout.addLayout(motor_header)
        waves = QHBoxLayout()
        waves.setSpacing(10)
        self.strong_bar = MotorWaveWidget("bass")
        self.weak_bar = MotorWaveWidget("treble")
        for label, bar in ((t("label_bass"), self.strong_bar), (t("label_treble"), self.weak_bar)):
            wave_col = QVBoxLayout()
            wave_col.setSpacing(5)
            l = QLabel(label)
            l.setStyleSheet("font-weight: 700;")
            wave_col.addWidget(l)
            bar.setRange(0, 100)
            wave_col.addWidget(bar)
            waves.addLayout(wave_col, 1)
        m_layout.addLayout(waves)
        root.addWidget(meter_card)

        root.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._poll_meter)
        self.meter_timer.start(60)
        self.refresh_active()

    def _select_skin(self, index):
        skin = self.skin_combo.itemData(index)
        self.gamepad.set_skin(skin)
        self.state['controller_skin'] = self.gamepad.skin
        if self.skin_cb:
            self.skin_cb()

    def set_enabled_text(self, enabled):
        self.toggle_btn.setText(t("btn_disable") if enabled else t("btn_enable"))

    def set_status_text(self, text):
        self.status_label.setText(text)

    def _configured_led_color(self):
        led_cfg = self.state['active'].get('led', {})
        if not led_cfg.get('enabled', False):
            return OFF_GAMEPAD_LIGHT
        preset_id = led_cfg.get('preset', 'immersive')
        if preset_id != 'immersive':
            return bt_hid_proxy.compute_led_output(led_cfg, time.monotonic())[0]
        return tuple(led_cfg.get('immersive', {}).get('bass_color', DEFAULT_GAMEPAD_LIGHT))

    def refresh_active(self):
        self.active_label.setText(ref_label(self.state))
        for panel in self.trigger_panels.values():
            panel.refresh(self.state)
        gain = self.state["active"].get("master_gain", 1.0)
        self.vibration_strength_bar.setValue(round(max(0.0, min(2.5, gain)) / 2.5 * 100))
        self.vibration_strength_value.setText(f"{gain:.2f}×")
        lightbar_enabled = self.state["active"].get("led", {}).get("enabled", False)
        self.lightbar_state_label.setText("ON" if lightbar_enabled else "OFF")
        self.lightbar_dots.set_enabled(lightbar_enabled)
        if lightbar_enabled and self.lightbar_rgb == OFF_GAMEPAD_LIGHT:
            self.lightbar_rgb = self._configured_led_color()
            self.gamepad.set_light_color(self.lightbar_rgb)
        elif not lightbar_enabled:
            self.lightbar_card.set_color(None)
            self.lightbar_dots.set_color(None)
            self.lightbar_rgb = OFF_GAMEPAD_LIGHT
            self.gamepad.set_light_color(self.lightbar_rgb)

    def set_battery_text(self, text, percent=None):
        self.battery_label.setText(text)
        self.hero_battery_label.setText(text)
        if percent is None:
            self.battery_gauge.set_text(text)
        else:
            self.battery_gauge.set_value(percent)

    def _poll_meter(self):
        engine = self.engine_holder()
        held = {}
        feedback = {}
        rgb = None
        fresh = False
        if engine is not None:
            snapshot = fresh_visual_snapshot(self.engine_holder)
            fresh = snapshot is not None
            if snapshot is not None:
                _, rgb, held, feedback = snapshot
                held = dict(held)
                feedback = dict(feedback)
                # Trigger squeeze never lands in button_haptics config, so
                # the engine's own `feedback` never carries it - merge the
                # held pressure in here so the feedback label mentions an
                # engaged trigger preset the same way the glow already does.
                for side, code in (('left', LEFT_TRIGGER_VIRTUAL_CODE), ('right', RIGHT_TRIGGER_VIRTUAL_CODE)):
                    if self.state.get(f'trigger_preset_{side}') and held.get(code, 0) > 0:
                        feedback[code] = max(feedback.get(code, 0), held[code])
        led_enabled = self.state['active'].get('led', {}).get('enabled', False)
        if not led_enabled:
            rgb = None
        elif rgb is None and self.state['active']['led'].get('preset', 'immersive') != 'immersive':
            rgb = self._configured_led_color()
        display_rgb = rgb if rgb is not None else self._configured_led_color()
        self.lightbar_rgb = display_rgb
        self.gamepad.set_light_color(display_rgb)
        self.lightbar_state_label.setText(('ON' if fresh and rgb is not None else 'ON · —') if led_enabled else 'OFF')
        self.lightbar_card.set_color(rgb)
        self.lightbar_dots.set_color(rgb)
        self.gamepad.set_feedback(held)
        names = [f'{t(key)} {round(feedback[code] * 100)}%' for key, code in BUTTON_OPTIONS if feedback.get(code, 0) > 0]
        self.feedback_label.setText(' · '.join(names) if names else t('dashboard_feedback_idle'))
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


PRESET_ICONS = {
    'balanced': ('⚖', '#25b9ff'), 'cinema': ('●', '#8b62ff'),
    'music': ('♫', '#1fd4ed'), 'voice': ('◉', '#ed72b7'), 'max': ('ϟ', '#796aff'),
}


def preset_card_metrics(preset_id):
    """Four compact, comparable UI indicators derived from actual params."""
    params = PRESETS[preset_id]['params']
    gain = round(max(0, min(100, (params['master_gain'] - .8) / .5 * 100)))
    bass = round(max(0, min(100, (.24 - params['bass']['hi']) / .20 * 100)))
    treble = round(max(0, min(100, (.09 - params['treble']['hi']) / .075 * 100)))
    response = round((params['bass']['attack'] + params['treble']['attack']) / 2 * 100)
    return (
        (t('label_bass'), bass, '#a98aff'),
        (t('label_treble'), treble, '#79b8ff'),
        (t('presets_metric_power'), gain, '#50c7ed'),
        (t('presets_metric_response'), response, '#62e1d1'),
    )


class PresetIcon(QWidget):
    def __init__(self, preset_id, size=58):
        super().__init__()
        self.preset_id = preset_id
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glyph, color_name = PRESET_ICONS[self.preset_id]
        color = QColor(color_name)
        bg = QColor(color)
        bg.setAlpha(32)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 125), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        p.setPen(color)
        center = QPointF(self.width() / 2, self.height() / 2)
        if self.preset_id == 'cinema':
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(color, 3))
            p.drawEllipse(center, self.width() * .22, self.height() * .22)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            radius = self.width() * .045
            distance = self.width() * .115
            for dx, dy in ((0, -distance), (distance, 0), (0, distance), (-distance, 0)):
                p.drawEllipse(QPointF(center.x() + dx, center.y() + dy), radius, radius)
            p.end()
            return
        if self.preset_id == 'voice':
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(color, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawRoundedRect(QRectF(center.x() - 6, center.y() - 13, 12, 21), 6, 6)
            p.drawArc(QRectF(center.x() - 11, center.y() - 7, 22, 22), 180 * 16, 180 * 16)
            p.drawLine(QPointF(center.x(), center.y() + 8), QPointF(center.x(), center.y() + 15))
            p.drawLine(QPointF(center.x() - 7, center.y() + 15), QPointF(center.x() + 7, center.y() + 15))
            p.end()
            return
        font = QFont('DejaVu Sans')
        font.setPixelSize(round(self.height() * .43))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, glyph)
        p.end()


class PresetMetrics(QWidget):
    def __init__(self, preset_id, compact=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3 if compact else 4)
        self.bars = []
        for label_text, value, color in preset_card_metrics(preset_id):
            row = QHBoxLayout()
            row.setSpacing(6)
            label = QLabel(label_text)
            label.setProperty('role', 'hint')
            label.setFixedWidth(72 if compact else 88)
            row.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(value)
            bar.setFixedHeight(7)
            bar.setStyleSheet(
                f'QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}')
            row.addWidget(bar, 1)
            percent = QLabel(f'{value}%')
            percent.setProperty('role', 'hint')
            percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            percent.setFixedWidth(32)
            row.addWidget(percent)
            layout.addLayout(row)
            self.bars.append(bar)


class PresetCard(QFrame):
    def __init__(self, preset_id, on_apply):
        super().__init__()
        self.preset_id = preset_id
        self.setObjectName('presetCard')
        self.setProperty('active', False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(PresetIcon(preset_id))
        text = QVBoxLayout()
        name = QLabel(t(f'preset_{preset_id}_label'))
        name.setStyleSheet('font-size: 15px; font-weight: 750;')
        text.addWidget(name)
        desc = QLabel(t(f'preset_{preset_id}_desc'))
        desc.setProperty('role', 'hint')
        desc.setWordWrap(True)
        desc.setMinimumHeight(34)
        text.addWidget(desc)
        header.addLayout(text, 1)
        layout.addLayout(header)
        self.metrics = PresetMetrics(preset_id, compact=True)
        layout.addWidget(self.metrics)
        self.apply_btn = QPushButton('▶  ' + t('btn_apply'))
        self.apply_btn.setObjectName('primary')
        self.apply_btn.clicked.connect(lambda _checked=False: on_apply(preset_id))
        layout.addWidget(self.apply_btn)

    def set_active(self, active):
        self.setProperty('active', bool(active))
        self.style().unpolish(self)
        self.style().polish(self)


class FeaturedPresetCard(QFrame):
    def __init__(self, preset_id, on_apply):
        super().__init__()
        self.preset_id = preset_id
        self.setObjectName('featuredPreset')
        self.setProperty('active', False)
        self.setMinimumHeight(152)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        layout.addWidget(PresetIcon(preset_id, 64))
        text = QVBoxLayout()
        badge = QLabel('★  ' + t('presets_recommended'))
        badge.setProperty('role', 'presetBadge')
        text.addWidget(badge, 0, Qt.AlignLeft)
        name = QLabel(t(f'preset_{preset_id}_label'))
        name.setStyleSheet('font-size: 21px; font-weight: 800;')
        text.addWidget(name)
        desc = QLabel(t(f'preset_{preset_id}_desc'))
        desc.setProperty('role', 'hint')
        desc.setWordWrap(True)
        text.addWidget(desc)
        text.addStretch(1)
        layout.addLayout(text, 3)
        self.metrics = PresetMetrics(preset_id)
        self.metrics.setMinimumWidth(180)
        self.metrics.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.metrics, 2)
        action = QVBoxLayout()
        action.addStretch(1)
        self.apply_btn = QPushButton('▶  ' + t('btn_apply'))
        self.apply_btn.setObjectName('primary')
        self.apply_btn.setMinimumWidth(110)
        self.apply_btn.clicked.connect(lambda _checked=False: on_apply(preset_id))
        action.addWidget(self.apply_btn)
        action.addStretch(1)
        layout.addLayout(action)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipRect(self.rect().adjusted(1, 1, -1, -1))
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w * .58, h * .3), w * .38)
        glow.setColorAt(0, QColor(76, 85, 210, 70))
        glow.setColorAt(1, QColor(30, 45, 120, 0))
        p.fillRect(self.rect(), glow)
        for offset, alpha in ((0, 80), (18, 35)):
            wave = QPainterPath()
            wave.moveTo(w * .38, h - 12 + offset)
            wave.cubicTo(w * .54, h * .1 + offset, w * .73, h * 1.1 + offset, w, h * .22 + offset)
            p.setPen(QPen(QColor(91, 91, 255, alpha), 1.2))
            p.drawPath(wave)
        p.end()

    def set_active(self, active):
        self.setProperty('active', bool(active))
        self.style().unpolish(self)
        self.style().polish(self)


class PresetsPage(QWidget):
    FILTERS = {
        'all': set(PRESET_ORDER), 'general': {'balanced'}, 'games': {'max'},
        'music': {'music'}, 'cinema': {'cinema'}, 'voice': {'voice'},
    }

    def __init__(self, state, on_apply, connection_getter=None):
        super().__init__()
        self.state = state
        self.on_apply = on_apply
        self.connection_getter = connection_getter or (lambda: None)
        self.cards = {}

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel(t('presets_title'))
        title.setProperty('role', 'h1')
        heading.addWidget(title)
        hint = QLabel(t('presets_hint'))
        hint.setProperty('role', 'hint')
        hint.setWordWrap(True)
        heading.addWidget(hint)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        tools = QVBoxLayout()
        tools.setSpacing(7)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons = {}
        filter_labels = (
            ('all', t('presets_filter_all')), ('general', t('presets_filter_general')),
            ('games', t('presets_filter_games')), ('music', t('preset_music_label')),
            ('cinema', t('preset_cinema_label')), ('voice', t('preset_voice_label')),
        )
        for key, label in filter_labels:
            button = QPushButton(label)
            button.setObjectName('filterChip')
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, k=key: self._filter(k))
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filter_row.addWidget(button)
        self.filter_buttons['all'].setChecked(True)
        filter_row.addStretch(1)
        tools.addLayout(filter_row)
        search_row = QHBoxLayout()
        search_row.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('presets_search_placeholder'))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(lambda _text: self._filter())
        search_row.addWidget(self.search)
        tools.addLayout(search_row)
        outer.addLayout(tools)

        self.featured = FeaturedPresetCard('cinema', self.on_apply)
        outer.addWidget(self.featured)

        ready_header = QHBoxLayout()
        ready = QLabel(t('presets_ready'))
        ready.setProperty('role', 'h2')
        ready_header.addWidget(ready)
        ready_header.addStretch(1)
        count = QLabel(str(len(PRESET_ORDER)))
        count.setProperty('role', 'hint')
        ready_header.addWidget(count)
        outer.addLayout(ready_header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, pid in enumerate(PRESET_ORDER):
            card = PresetCard(pid, self.on_apply)
            self.cards[pid] = card
            grid.addWidget(card, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        outer.addStretch(1)
        scroll.setWidget(content)
        self.scroll = scroll
        page_layout.addWidget(scroll)

        self._active_filter = 'all'
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self._refresh_connection)
        self.connection_timer.start(250)
        self.refresh()

    def _refresh_connection(self):
        self.connection_indicator.set_connection(self.connection_getter())

    def _filter(self, category=None):
        if category is not None:
            self._active_filter = category
        allowed = self.FILTERS[self._active_filter]
        query = self.search.text().strip().casefold()
        for pid, card in self.cards.items():
            haystack = f"{t(f'preset_{pid}_label')} {t(f'preset_{pid}_desc')}".casefold()
            card.setVisible(pid in allowed and (not query or query in haystack))
        cinema_text = f"{t('preset_cinema_label')} {t('preset_cinema_desc')}".casefold()
        self.featured.setVisible('cinema' in allowed and (not query or query in cinema_text))

    def refresh(self):
        active = self.state['active_ref']
        for pid, card in self.cards.items():
            card.set_active(active == f'preset:{pid}')
        self.featured.set_active(active == 'preset:cinema')
        self._refresh_connection()


def profile_metrics(params):
    """Compact profile strengths derived from the profile's actual values."""
    vibration = round(max(0.0, min(1.0, params.get("master_gain", 1.0) / 2.5)) * 100)
    bass_hi = params.get("bass", {}).get("hi", 0.22)
    treble_hi = params.get("treble", {}).get("hi", 0.045)
    bass = round(max(0.0, min(1.0, (0.3 - bass_hi) / 0.29)) * 100)
    treble = round(max(0.0, min(1.0, (0.3 - treble_hi) / 0.29)) * 100)
    return {"vibration": vibration, "bass": bass, "treble": treble}


class ProfileCard(QFrame):
    def __init__(self, name, params, active=False):
        super().__init__()
        self.name = name
        self.setObjectName("profileCard")
        self.setProperty("selected", False)
        self.setProperty("active", active)
        # QListWidget owns selection and native InternalMove gestures.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(13)
        icon = QLabel("⚙")
        icon.setObjectName("profileGlyph")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(54, 54)
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(4)
        title_row = QHBoxLayout()
        title = QLabel(name)
        title.setProperty("role", "profileName")
        title_row.addWidget(title)
        title_row.addStretch(1)
        if active:
            badge = QLabel("●  " + t("home_active_profile"))
            badge.setProperty("role", "accentLabel")
            title_row.addWidget(badge)
        text.addLayout(title_row)
        subtitle = QLabel(t("label_custom_settings"))
        subtitle.setProperty("role", "hint")
        text.addWidget(subtitle)

        tags = QHBoxLayout()
        tags.setSpacing(6)
        for label in self._tags(params):
            chip = QLabel(label)
            chip.setProperty("role", "profileTag")
            tags.addWidget(chip)
        tags.addStretch(1)
        text.addLayout(tags)
        layout.addLayout(text, 1)

        arrow = QLabel("›")
        arrow.setProperty("role", "profileArrow")
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setFixedWidth(22)
        layout.addWidget(arrow)

        handle = QLabel("⣿")
        handle.setObjectName("profileDragHandle")
        handle.setAlignment(Qt.AlignCenter)
        handle.setFixedWidth(22)
        layout.addWidget(handle)

    @staticmethod
    def _tags(params):
        metrics = profile_metrics(params)
        return [
            f'{t("home_vibration")} {metrics["vibration"]}%',
            f'{t("label_bass")} {metrics["bass"]}%',
            f'{t("label_treble")} {metrics["treble"]}%',
        ]

    def set_selected(self, selected):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

class ProfileListWidget(QListWidget):
    """Native Qt profile list; the view supplies drag/drop and its indicator."""

    order_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("profileList")
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDropIndicatorShown(True)
        self.setSpacing(9)
        self.setMinimumHeight(360)

    def dropEvent(self, event):
        before = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        super().dropEvent(event)
        after = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if after != before:
            self.order_changed.emit(after)


class ProfilesPage(QWidget):
    def __init__(self, state, on_apply, on_change, connection_getter=None):
        super().__init__()
        self.state = state
        self.on_apply = on_apply
        self.on_change = on_change
        self.connection_getter = connection_getter or (lambda: None)
        self.selected_name = None
        self.profile_cards = {}

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel(t("profiles_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("profiles_hint"))
        hint.setProperty("role", "hint")
        heading.addWidget(hint)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        toolbar, toolbar_layout = make_section_card(QHBoxLayout, margins=(13, 10, 13, 10))
        toolbar_title = QLabel("◈  " + t("profiles_title"))
        toolbar_title.setProperty("role", "h2")
        toolbar_layout.addWidget(toolbar_title)
        toolbar_layout.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("⌕  " + t("profiles_title") + "…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(260)
        self.search_edit.textChanged.connect(lambda _text: self.refresh())
        toolbar_layout.addWidget(self.search_edit)
        outer.addWidget(toolbar)

        workspace_widget = QWidget()
        self.workspace = QBoxLayout(QBoxLayout.Direction.LeftToRight, workspace_widget)
        self.workspace.setContentsMargins(0, 0, 0, 0)
        self.workspace.setSpacing(12)

        list_panel, list_layout = make_section_card(margins=(14, 13, 14, 14), spacing=9)
        list_header = QHBoxLayout()
        mine = QLabel(t("profiles_title"))
        mine.setProperty("role", "h2")
        list_header.addWidget(mine)
        list_header.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setProperty("role", "hint")
        list_header.addWidget(self.count_label)
        list_layout.addLayout(list_header)
        self.list = ProfileListWidget()
        self.list.order_changed.connect(self._store_visible_order)
        self.list.currentItemChanged.connect(self._on_list_selection_changed)
        list_layout.addWidget(self.list)
        self.empty_label = QLabel(t("profiles_hint"))
        self.empty_label.setProperty("role", "emptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(130)
        list_layout.addWidget(self.empty_label)
        list_layout.addStretch(1)
        self.workspace.addWidget(list_panel, 3)

        self.details_panel = QFrame()
        self.details_panel.setObjectName("profileDetailCard")
        self.details_panel.setMinimumWidth(340)
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(16, 15, 16, 15)
        details_layout.setSpacing(10)
        details_heading = QLabel(t("profile_details_title"))
        details_heading.setProperty("role", "h2")
        details_layout.addWidget(details_heading)
        self.details_empty = QLabel(t("profiles_hint"))
        self.details_empty.setProperty("role", "emptyState")
        self.details_empty.setAlignment(Qt.AlignCenter)
        self.details_empty.setWordWrap(True)
        details_layout.addWidget(self.details_empty, 1)

        self.details_body = QWidget()
        body = QVBoxLayout(self.details_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        profile_header = QHBoxLayout()
        detail_icon = QLabel("⚙")
        detail_icon.setObjectName("profileGlyph")
        detail_icon.setAlignment(Qt.AlignCenter)
        detail_icon.setFixedSize(64, 64)
        profile_header.addWidget(detail_icon)
        profile_text = QVBoxLayout()
        self.detail_name = QLabel()
        self.detail_name.setProperty("role", "componentValue")
        profile_text.addWidget(self.detail_name)
        detail_type = QLabel(t("label_custom_settings"))
        detail_type.setProperty("role", "hint")
        profile_text.addWidget(detail_type)
        profile_header.addLayout(profile_text, 1)
        self.detail_active = QLabel("★")
        self.detail_active.setProperty("role", "profileStar")
        profile_header.addWidget(self.detail_active)
        body.addLayout(profile_header)

        divider = QFrame()
        divider.setObjectName("cardDivider")
        divider.setFrameShape(QFrame.HLine)
        body.addWidget(divider)
        self.metric_bars = {}
        self.metric_grid = QGridLayout()
        self.metric_grid.setContentsMargins(0, 0, 0, 0)
        self.metric_grid.setHorizontalSpacing(12)
        self.metric_grid.setVerticalSpacing(8)
        for row_index, (key, label) in enumerate((
            ("vibration", t("home_vibration")),
            ("bass", t("label_bass")),
            ("treble", t("label_treble")),
        )):
            metric_label = QLabel(label)
            self.metric_grid.addWidget(metric_label, row_index, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            self.metric_grid.addWidget(bar, row_index, 1)
            value = QLabel()
            value.setProperty("role", "value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setMinimumWidth(38)
            self.metric_grid.addWidget(value, row_index, 2)
            self.metric_bars[key] = (bar, value)
        self.metric_grid.setColumnStretch(1, 1)
        body.addLayout(self.metric_grid)

        body.addStretch(1)
        self.apply_btn = QPushButton("▶  " + t("btn_apply"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._apply_selected)
        body.addWidget(self.apply_btn)
        actions = QGridLayout()
        self.rename_btn = QPushButton("✎  " + t("btn_rename"))
        self.rename_btn.clicked.connect(self._rename_selected)
        self.delete_btn = QPushButton("♲  " + t("btn_delete"))
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(self.rename_btn, 0, 0)
        actions.addWidget(self.delete_btn, 0, 1)
        body.addLayout(actions)
        details_layout.addWidget(self.details_body, 1)
        self.workspace.addWidget(self.details_panel, 2)
        outer.addWidget(workspace_widget)

        create_card, create_layout = make_section_card(margins=(15, 13, 15, 13), spacing=9)
        create_intro = QHBoxLayout()
        create_icon = QLabel("＋")
        create_icon.setObjectName("profileGlyph")
        create_icon.setAlignment(Qt.AlignCenter)
        create_icon.setFixedSize(48, 48)
        create_intro.addWidget(create_icon)
        create_text = QVBoxLayout()
        create_title = QLabel(t("btn_save_as_profile"))
        create_title.setProperty("role", "h2")
        create_text.addWidget(create_title)
        create_hint = QLabel(t("profiles_hint"))
        create_hint.setProperty("role", "hint")
        create_text.addWidget(create_hint)
        create_intro.addLayout(create_text, 1)
        create_layout.addLayout(create_intro)
        create_form = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("profile_name_placeholder"))
        self.name_edit.returnPressed.connect(self._save_current)
        create_form.addWidget(self.name_edit, 2)
        self.save_btn = QPushButton(t("btn_save_as_profile"))
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save_current)
        create_form.addWidget(self.save_btn)
        create_layout.addLayout(create_form)
        outer.addWidget(create_card)
        outer.addStretch(1)

        self.scroll.setWidget(content)
        page_layout.addWidget(self.scroll)
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self._refresh_connection)
        self.connection_timer.start(250)
        self.refresh()

    def resizeEvent(self, event):
        set_responsive_direction(event.size().width(), self.workspace)
        super().resizeEvent(event)

    def _clear_cards(self):
        self.list.clear()
        self.profile_cards.clear()

    def refresh(self):
        previous = self.selected_name
        active_ref = self.state["active_ref"]
        query = self.search_edit.text().strip().casefold()
        active_name = active_ref[len("profile:"):] if active_ref.startswith("profile:") else None
        ordered_names = list(self.state["profiles"])
        names = [name for name in ordered_names
                 if not query or query in name.casefold()]
        self.list.blockSignals(True)
        self._clear_cards()
        for name in names:
            active = active_ref == f"profile:{name}"
            card = ProfileCard(name, self.state["profiles"][name], active)
            self.profile_cards[name] = card
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(0, max(82, card.sizeHint().height())))
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
        self.list.blockSignals(False)
        self.count_label.setText(str(len(names)))
        self.empty_label.setVisible(not names)
        if previous not in self.profile_cards:
            previous = active_name if active_name in self.profile_cards else (names[0] if names else None)
        self._select_profile(previous)
        self._refresh_connection()

    def _store_visible_order(self, visible_order):
        """Merge a filtered view order back into the insertion-ordered dict."""
        profiles = self.state["profiles"]
        visible_set = set(visible_order)
        replacements = iter(visible_order)
        full_order = [next(replacements) if name in visible_set else name for name in profiles]
        if full_order == list(profiles):
            return
        self.state["profiles"] = {name: profiles[name] for name in full_order}
        self.selected_name = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.on_change()

    def _on_list_selection_changed(self, current, previous):
        self._select_profile(current.data(Qt.UserRole) if current is not None else None)

    def _refresh_connection(self):
        self.connection_indicator.set_connection(self.connection_getter())

    def _select_profile(self, name):
        self.selected_name = name if name in self.state["profiles"] else None
        for card_name, card in self.profile_cards.items():
            card.set_selected(card_name == self.selected_name)
        self.list.blockSignals(True)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == self.selected_name:
                self.list.setCurrentRow(row)
                break
        if self.selected_name is None:
            self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        self._refresh_details()

    def _refresh_details(self):
        name = self.selected_name
        available = name in self.state["profiles"]
        self.details_empty.setVisible(not available)
        self.details_body.setVisible(available)
        if not available:
            return
        params = self.state["profiles"][name]
        self.detail_name.setText(name)
        self.detail_active.setVisible(self.state["active_ref"] == f"profile:{name}")
        for key, value in profile_metrics(params).items():
            bar, label = self.metric_bars[key]
            bar.setValue(value)
            label.setText(f"{value}%")

    def _selected_name(self):
        return self.selected_name

    def _apply_selected(self):
        name = self._selected_name()
        if name:
            self.on_apply(name)

    def _rename_selected(self):
        name = self._selected_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(
            self, t("rename_profile_title"), t("rename_profile_label"), text=name)
        new_name = new_name.strip() if ok else ""
        if new_name and new_name != name:
            if new_name in self.state["profiles"]:
                QMessageBox.warning(
                    self, t("rename_profile_title"),
                    t("profile_name_exists", name=new_name))
                return
            profiles = self.state["profiles"]
            self.state["profiles"] = {
                new_name if item == name else item: params
                for item, params in profiles.items()
            }
            if self.state["active_ref"] == f"profile:{name}":
                self.state["active_ref"] = f"profile:{new_name}"
            self.selected_name = new_name
            self.on_change()
            self.refresh()

    def _delete_selected(self):
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(
                self, t("delete_profile_title"),
                t("delete_profile_confirm", name=name)) == QMessageBox.Yes:
            del self.state["profiles"][name]
            if self.state["active_ref"] == f"profile:{name}":
                self.state["active_ref"] = "custom"
            self.selected_name = None
            self.on_change()
            self.refresh()

    def _save_current(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if name in self.state["profiles"]:
            QMessageBox.warning(
                self, t("rename_profile_title"),
                t("profile_name_exists", name=name))
            return
        self.state["profiles"][name] = copy.deepcopy(self.state["active"])
        self.state["active_ref"] = f"profile:{name}"
        self.selected_name = name
        self.name_edit.clear()
        self.on_change()
        self.refresh()


def _trigger_param_label(key):
    """feedback_raw/vibration_raw params are per-zone arrays (s0..s9 / a0..a9)
    rather than named fields - reuse the existing strength/amplitude wording
    with the zone index appended instead of adding 20 more translation keys."""
    if key[0] in ("s", "a") and key[1:].isdigit():
        base = "trig_param_strength" if key[0] == "s" else "trig_param_amplitude"
        return f"{t(base)} {key[1:]}"
    return t(f"trig_param_{key}")


TRIGGER_PRESET_ICONS = {
    'soft': ('≋', '#8068ff'), 'hard_wall': ('▦', '#9f74ff'),
    'weapon': ('⊕', '#816dff'), 'bow': ('⌁', '#d06fff'),
    'machine': ('╫', '#ff6d8f'), 'clicker': ('⋮', '#f6a553'),
    'gallop': ('♞', '#45cbe8'), 'strong_click': ('✦', '#ff647a'),
    'engine_hum': ('≈', '#5bc8ff'),
}


class TriggerPresetIcon(QWidget):
    def __init__(self, preset_id):
        super().__init__()
        self.preset_id = preset_id
        self.setFixedSize(54, 54)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glyph, color_name = TRIGGER_PRESET_ICONS[self.preset_id]
        color = QColor(color_name)
        fill = QColor(color)
        fill.setAlpha(30)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 145), 1))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 11, 11)
        p.setPen(color)
        font = QFont('DejaVu Sans')
        font.setPixelSize(26)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, glyph)
        p.end()


class CustomTriggerCard(QFrame):
    """Lets the user build a raw dualsensectl trigger effect by hand - pick
    an effect mode, dial in its parameters, apply. Restores whatever was
    last applied on this side (if anything), so reopening the app or
    switching pages doesn't lose what was already dialed in."""

    def __init__(self, state, side, on_apply, on_off):
        super().__init__()
        self.setObjectName("triggerCustomCard")
        self.setProperty('active', False)
        self.side = side
        self.on_apply = on_apply
        self.on_off = on_off
        self.slider_widgets = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(8)
        header = QHBoxLayout()
        custom_icon = QLabel('✣')
        custom_icon.setObjectName('triggerCustomIcon')
        custom_icon.setAlignment(Qt.AlignCenter)
        custom_icon.setFixedSize(42, 42)
        header.addWidget(custom_icon)
        title = QLabel(t("trigger_custom_title"))
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        header.addWidget(title, 1)
        layout.addLayout(header)
        hint = QLabel(t("trigger_custom_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        saved = state.get(f"trigger_custom_{side}") or {}
        initial_mode = saved.get("mode")
        if initial_mode not in TRIGGER_EFFECT_PARAMS:
            initial_mode = "feedback"

        self.mode_combo = QComboBox()
        for mode in TRIGGER_EFFECT_ORDER:
            self.mode_combo.addItem(t(f"trig_mode_{mode}"), mode)
        idx = self.mode_combo.findData(initial_mode)
        if idx != -1:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(lambda _=0: self._rebuild_sliders())
        layout.addWidget(self.mode_combo)

        self.sliders_layout = QGridLayout()
        self.sliders_layout.setHorizontalSpacing(14)
        self.sliders_layout.setVerticalSpacing(3)
        layout.addLayout(self.sliders_layout)

        # Only feedback-raw's per-zone resistance shape can carry a snap
        # click (it's the only custom mode able to define more than one
        # hard-wall zone) - see presets.wall_zones_from_feedback_raw.
        self.wall_click_check = QCheckBox(t("trigger_snap_click_wall_checkbox"))
        self.wall_click_check.setToolTip(t("trigger_snap_click_hint"))
        self.wall_click_check.setChecked(bool(state.get(f"trigger_custom_snap_click_{side}", False)))
        layout.addWidget(self.wall_click_check)

        apply_btn = QPushButton(t("btn_apply"))
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)

        initial_values = saved.get("values") if saved.get("mode") == initial_mode else None
        self._rebuild_sliders(initial_values)

    def _rebuild_sliders(self, initial_values=None):
        while self.sliders_layout.count():
            item = self.sliders_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()
        self.slider_widgets = []
        mode = self.mode_combo.currentData()
        for index, (key, lo, hi, default) in enumerate(TRIGGER_EFFECT_PARAMS.get(mode, [])):
            value = default
            if initial_values and key in initial_values:
                value = max(lo, min(hi, initial_values[key]))
            s = IntSlider(_trigger_param_label(key), lo, hi, value)
            self.sliders_layout.addWidget(s, index // 2, index % 2)
            self.slider_widgets.append((key, s))
        self.wall_click_check.setVisible(mode == "feedback_raw")

    def _apply(self):
        mode = self.mode_combo.currentData()
        if mode == "off":
            self.on_off(self.side)
            return
        values = {key: s.value() for key, s in self.slider_widgets}
        wall_click = self.wall_click_check.isChecked() if mode == "feedback_raw" else False
        self.on_apply(mode, values, self.side, wall_click)

    def refresh(self, active_ref):
        self.setProperty('active', active_ref == 'custom')
        self.style().unpolish(self)
        self.style().polish(self)


class TriggerColumn(QWidget):
    """One trigger's (L2 or R2) preset list: independent from the other side."""

    def __init__(self, state, side, side_title, on_apply, on_off, on_apply_custom):
        super().__init__()
        self.state = state
        self.side = side
        self.on_apply = on_apply
        self.cards = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName('triggerColumnHeader')
        hdr_row = QHBoxLayout(header_card)
        hdr_row.setContentsMargins(14, 11, 14, 11)
        badge = QLabel('L2' if side == 'left' else 'R2')
        badge.setObjectName('triggerSideBadge')
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(50, 50)
        hdr_row.addWidget(badge)
        heading = QVBoxLayout()
        hdr = QLabel(side_title)
        hdr.setStyleSheet("font-size: 16px; font-weight: 750;")
        heading.addWidget(hdr)
        side_hint = QLabel(t('trigger_side_hint'))
        side_hint.setProperty('role', 'hint')
        side_hint.setWordWrap(True)
        heading.addWidget(side_hint)
        hdr_row.addLayout(heading, 1)
        hdr_row.addStretch(1)
        self.state_label = QLabel()
        self.state_label.setProperty('role', 'accentLabel')
        hdr_row.addWidget(self.state_label)
        off_btn = QPushButton(t("btn_off"))
        off_btn.setObjectName("danger")
        off_btn.clicked.connect(lambda: on_off(side))
        hdr_row.addWidget(off_btn)
        layout.addWidget(header_card)

        for pid in TRIGGER_PRESET_ORDER:
            card = QFrame()
            card.setObjectName("triggerPresetCard")
            card.setProperty('active', False)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(13, 11, 13, 12)
            card_layout.setSpacing(7)
            card_header = QHBoxLayout()
            card_header.setSpacing(11)
            card_header.addWidget(TriggerPresetIcon(pid))
            text = QVBoxLayout()
            title_row = QHBoxLayout()
            name = QLabel(t(f"trigger_{pid}_label"))
            name.setStyleSheet("font-size: 14px; font-weight: 700;")
            title_row.addWidget(name)
            if pid == 'soft':
                recommended = QLabel('★ ' + t('presets_recommended'))
                recommended.setProperty('role', 'presetBadge')
                title_row.addWidget(recommended)
            title_row.addStretch(1)
            text.addLayout(title_row)
            desc = QLabel(t(f"trigger_{pid}_desc"))
            desc.setProperty("role", "hint")
            desc.setWordWrap(True)
            text.addWidget(desc)
            card_header.addLayout(text, 1)
            btn = QPushButton('▶  ' + t("btn_apply"))
            btn.setObjectName('primary')
            btn.setMinimumWidth(118)
            card_header.addWidget(btn, 0, Qt.AlignTop)
            card_layout.addLayout(card_header)

            quick_sliders = []
            quick_keys = TRIGGER_PRESET_QUICK_PARAMS.get(pid)
            if quick_keys:
                mode = TRIGGER_PRESETS[pid]["mode"]
                spec = {key: (lo, hi, default) for key, lo, hi, default in TRIGGER_EFFECT_PARAMS[mode]}
                defaults = TRIGGER_PRESETS[pid]["values"]
                saved = state.get(f"trigger_preset_params_{side}", {}).get(pid, {})
                for key in quick_keys:
                    lo, hi, default = spec[key]
                    value = max(lo, min(hi, saved.get(key, defaults.get(key, default))))
                    s = IntSlider(_trigger_param_label(key), lo, hi, value)
                    card_layout.addWidget(s)
                    quick_sliders.append((key, s))

            snap_click_check = None
            snap_strength_slider = None
            if pid in TRIGGER_PRESET_SNAP_CLICK:
                default_on = TRIGGER_PRESET_SNAP_CLICK[pid]
                saved_click = state.get(f"trigger_snap_click_{side}", {}).get(pid, default_on)
                snap_click_check = QCheckBox(t("trigger_snap_click_checkbox"))
                snap_click_check.setToolTip(t("trigger_snap_click_hint"))
                snap_click_check.setChecked(saved_click)
                card_layout.addWidget(snap_click_check)

                saved_strength = state.get(f"trigger_snap_click_strength_{side}", {}).get(pid, 8)
                snap_strength_slider = IntSlider(t("trig_param_snap_click_strength"), 1, 8, saved_strength)
                card_layout.addWidget(snap_strength_slider)

            btn.clicked.connect(lambda _=False, p=pid, qs=quick_sliders, cc=snap_click_check, ss=snap_strength_slider:
                                 self.on_apply(p, self.side,
                                               {key: s.value() for key, s in qs} if qs else None,
                                               cc.isChecked() if cc else None,
                                               ss.value() if ss else None))
            card.apply_btn = btn
            card.quick_sliders = quick_sliders
            card.snap_click_check = snap_click_check
            card.snap_strength_slider = snap_strength_slider
            layout.addWidget(card)
            self.cards[pid] = card

        self.custom_card = CustomTriggerCard(state, side, on_apply_custom, on_off)
        layout.addWidget(self.custom_card)

        layout.addStretch(1)
        self.refresh()

    def refresh(self):
        active = self.state.get(f"trigger_preset_{self.side}")
        self.state_label.setText('ON' if active else 'OFF')
        for pid, card in self.cards.items():
            card.setProperty('active', active == pid)
            card.style().unpolish(card)
            card.style().polish(card)
        self.custom_card.refresh(active)


class TriggersPage(QWidget):
    def __init__(self, state, on_apply, on_off, on_apply_custom, connection_getter=None,
                 light_color_getter=None, engine_holder=None):
        super().__init__()
        self.state = state
        self.connection_getter = connection_getter or (lambda: None)
        self.light_color_getter = light_color_getter or (lambda: DEFAULT_GAMEPAD_LIGHT)
        self.engine_holder = engine_holder or (lambda: None)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        hero = HeroScene()
        hero.setObjectName('heroCard')
        hero.setMinimumHeight(178)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 15, 20, 15)
        hero_layout.setSpacing(14)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        title = QLabel(t("triggers_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("triggers_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        heading.addWidget(hint)
        heading.addStretch(1)
        self.connection_indicator = ConnectionIndicator()
        heading.addWidget(self.connection_indicator, 0, Qt.AlignLeft)
        hero_layout.addLayout(heading, 4)

        art = QHBoxLayout()
        art.setSpacing(5)
        left_badge = QLabel('L2')
        left_badge.setObjectName('triggerHeroBadge')
        left_badge.setAlignment(Qt.AlignCenter)
        left_badge.setFixedSize(44, 50)
        art.addWidget(left_badge, 0, Qt.AlignVCenter)
        self.hero_gamepad = GamepadWidget()
        self.hero_gamepad.set_skin(state.get('controller_skin', 'white'))
        self.hero_gamepad.set_light_color(self.light_color_getter())
        self.hero_gamepad.setMinimumHeight(145)
        art.addWidget(self.hero_gamepad, 1)
        right_badge = QLabel('R2')
        right_badge.setObjectName('triggerHeroBadge')
        right_badge.setAlignment(Qt.AlignCenter)
        right_badge.setFixedSize(44, 50)
        art.addWidget(right_badge, 0, Qt.AlignVCenter)
        hero_layout.addLayout(art, 5)
        outer.addWidget(hero)

        columns_widget = QWidget()
        self.columns_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, columns_widget)
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(10)
        self.left_column = TriggerColumn(state, "left", t("trigger_left_title"), on_apply, on_off, on_apply_custom)
        self.right_column = TriggerColumn(state, "right", t("trigger_right_title"), on_apply, on_off, on_apply_custom)
        self.columns_layout.addWidget(self.left_column, 1)
        self.columns_layout.addWidget(self.right_column, 1)
        outer.addWidget(columns_widget)

        extras = QFrame()
        extras.setObjectName('sectionCard')
        extras_layout = QHBoxLayout(extras)
        extras_layout.setContentsMargins(16, 12, 16, 12)
        self.auto_check = QCheckBox(t("auto_reconnect_checkbox"))
        self.auto_check.setChecked(state["trigger_auto_reconnect"])
        self.auto_check.toggled.connect(self._toggle_auto)
        extras_layout.addWidget(self.auto_check)
        extras_layout.addStretch(1)
        outer.addWidget(extras)
        outer.addStretch(1)
        scroll.setWidget(content)
        self.scroll = scroll
        page_layout.addWidget(scroll)

        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self._refresh_connection)
        self.connection_timer.start(60)
        self._refresh_connection()

    def resizeEvent(self, event):
        set_responsive_direction(event.size().width(), self.columns_layout)
        super().resizeEvent(event)

    def _refresh_connection(self):
        self.connection_indicator.set_connection(self.connection_getter())
        self.hero_gamepad.set_light_color(self.light_color_getter())
        snapshot = fresh_visual_snapshot(self.engine_holder)
        self.hero_gamepad.set_feedback(dict(snapshot[2]) if snapshot is not None else {})

    def _toggle_auto(self, checked):
        self.state["trigger_auto_reconnect"] = checked

    def refresh(self):
        self.left_column.refresh()
        self.right_column.refresh()
        self.hero_gamepad.set_skin(self.state.get('controller_skin', 'white'))
        self._refresh_connection()


class ToggleSwitch(QCheckBox):
    """Small painted switch used where the reference calls for a toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 24)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.manager.palette
        track = QRectF(1, 3, 38, 18)
        if self.isChecked():
            glow = QColor(pal['accent'])
            glow.setAlpha(75)
            p.setPen(QPen(glow, 3))
            p.setBrush(QColor(pal['accent']))
        else:
            p.setPen(QPen(QColor(pal['border']), 1))
            p.setBrush(QColor(pal['pressed']))
        p.drawRoundedRect(track, 9, 9)
        knob_x = 30 if self.isChecked() else 10
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#e9f5ff' if self.isChecked() else pal['fg_dim']))
        p.drawEllipse(QPointF(knob_x, 12), 7, 7)
        p.end()


class ButtonHapticRow(QWidget):
    """Compact controller-button row with live pressed-state highlighting."""

    def __init__(self, label, code, entry):
        super().__init__()
        self.code = code
        self._pressed = False
        self.setObjectName('buttonHapticRow')
        self.setProperty('pressed', False)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(3)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(7)
        self.icon_label = QLabel(self._glyph(code))
        self.icon_label.setObjectName('buttonHapticIcon')
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(32, 32)
        primary_row.addWidget(self.icon_label)
        self.name_label = QLabel(label)
        self.name_label.setWordWrap(True)
        primary_row.addWidget(self.name_label, 2)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(int(entry.get("strength", 0.4) * 1000))
        primary_row.addWidget(HoverGrowWrapper(self.slider, grow_px=3), 2)
        self.value_label = QLabel(f"{entry.get('strength', 0.4):.2f}")
        self.value_label.setProperty("role", "value")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedWidth(42)
        primary_row.addWidget(self.value_label)
        self.check = ToggleSwitch()
        self.check.setToolTip(label)
        self.check.setChecked(entry.get("enabled", False))
        primary_row.addWidget(self.check)
        layout.addLayout(primary_row)

        hz_row = QHBoxLayout()
        hz_row.setSpacing(7)
        hz_row.addSpacing(39)
        hz_label = QLabel(t("trig_param_frequency"))
        hz_label.setProperty('role', 'hint')
        hz_label.setFixedWidth(62)
        hz_row.addWidget(hz_label)
        self.hz_slider = QSlider(Qt.Horizontal)
        self.hz_slider.setRange(BUTTON_CLICK_HZ_MIN, BUTTON_CLICK_HZ_MAX)
        self.hz_slider.setValue(int(entry.get("click_hz", BUTTON_CLICK_HZ)))
        hz_row.addWidget(HoverGrowWrapper(self.hz_slider, grow_px=3), 1)
        self.hz_value_label = QLabel(f"{int(entry.get('click_hz', BUTTON_CLICK_HZ))} Hz")
        self.hz_value_label.setProperty("role", "value")
        self.hz_value_label.setFixedWidth(50)
        hz_row.addWidget(self.hz_value_label)
        hz_row.addSpacing(40)
        layout.addLayout(hz_row)

    @staticmethod
    def _glyph(code):
        return {
            DPAD_VIRTUAL_CODE: '✚', ec.BTN_TL: 'L1', ec.BTN_TL2: 'L2',
            LEFT_TRIGGER_VIRTUAL_CODE: 'L2', ec.BTN_THUMBL: 'L3',
            LEFT_STICK_VIRTUAL_CODE: '◉', ec.BTN_SELECT: '↗',
            ec.BTN_TR: 'R1', ec.BTN_TR2: 'R2', RIGHT_TRIGGER_VIRTUAL_CODE: 'R2',
            ec.BTN_THUMBR: 'R3', RIGHT_STICK_VIRTUAL_CODE: '◉',
            ec.BTN_NORTH: '△', ec.BTN_EAST: '○', ec.BTN_SOUTH: '✕',
            ec.BTN_WEST: '□', ec.BTN_START: '≡', ec.BTN_MODE: 'PS',
        }.get(code, '●')

    def set_pressed(self, strength):
        pressed = float(strength) > 0
        if pressed != self._pressed:
            self._pressed = pressed
            self.setProperty('pressed', pressed)
            self.icon_label.setProperty('pressed', pressed)
            for widget in (self, self.icon_label):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        self.icon_label.setToolTip(f'{round(float(strength) * 100)}%' if pressed else '')
        self.update()


class ButtonHapticPage(QWidget):
    def __init__(self, state, on_change, engine_holder=None, connection_getter=None,
                 light_color_getter=None):
        super().__init__()
        self.state = state
        self.on_change = on_change
        self.engine_holder = engine_holder or (lambda: None)
        self.connection_getter = connection_getter or (lambda: None)
        self.light_color_getter = light_color_getter or (lambda: DEFAULT_GAMEPAD_LIGHT)
        self.rows = {}

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel(t("button_haptic_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("button_haptic_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        heading.addWidget(hint)
        header.addLayout(heading, 1)

        profile_card = QFrame()
        profile_card.setObjectName('buttonProfileCard')
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(13, 8, 13, 8)
        profile_layout.setSpacing(1)
        profile_caption = QLabel(t('home_active_profile'))
        profile_caption.setProperty('role', 'hint')
        profile_layout.addWidget(profile_caption)
        self.profile_label = QLabel(ref_label(state))
        self.profile_label.setProperty('role', 'h2')
        self.profile_label.setWordWrap(True)
        profile_layout.addWidget(self.profile_label)
        header.addWidget(profile_card)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator)
        outer.addLayout(header)

        columns = QWidget()
        self.columns_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, columns)
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(10)

        self.left_box = self._build_group(t("group_left_side"), LEFT_BUTTON_OPTIONS)
        self.columns_layout.addWidget(self.left_box, 4)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)
        preview = HeroScene()
        preview.setObjectName('buttonPreviewCard')
        preview.setMinimumHeight(340)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(14, 11, 14, 12)
        preview_header = QHBoxLayout()
        preview_title = QLabel(t('led_preview_title'))
        preview_title.setProperty('role', 'h2')
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        live_label = QLabel('●  ' + t('home_realtime'))
        live_label.setProperty('role', 'accentLabel')
        preview_header.addWidget(live_label)
        preview_layout.addLayout(preview_header)
        self.gamepad = GamepadWidget()
        self.gamepad.set_skin(state.get('controller_skin', 'white'))
        self.gamepad.set_light_color(self.light_color_getter())
        self.gamepad.setMinimumHeight(255)
        preview_layout.addWidget(self.gamepad, 1)
        self.feedback_label = QLabel(t('dashboard_feedback_idle'))
        self.feedback_label.setProperty('role', 'hint')
        self.feedback_label.setAlignment(Qt.AlignCenter)
        self.feedback_label.setWordWrap(True)
        preview_layout.addWidget(self.feedback_label)
        center_layout.addWidget(preview)

        response_card = QFrame()
        response_card.setObjectName('sectionCard')
        response_layout = QVBoxLayout(response_card)
        response_layout.setContentsMargins(14, 12, 14, 14)
        response_title = QLabel(t('home_motor_response'))
        response_title.setProperty('role', 'h2')
        response_layout.addWidget(response_title)
        waves = QHBoxLayout()
        waves.setSpacing(8)
        self.left_wave = MotorWaveWidget('bass')
        self.right_wave = MotorWaveWidget('treble')
        for label_text, wave in ((t('group_left_side'), self.left_wave),
                                 (t('group_right_side'), self.right_wave)):
            col = QVBoxLayout()
            label = QLabel(label_text)
            label.setProperty('role', 'hint')
            col.addWidget(label)
            wave.setRange(0, 100)
            col.addWidget(wave)
            waves.addLayout(col, 1)
        response_layout.addLayout(waves)
        center_layout.addWidget(response_card)
        center_layout.addStretch(1)
        self.columns_layout.addWidget(center, 4)

        self.right_box = self._build_group(t("group_right_side"), RIGHT_BUTTON_OPTIONS)
        self.columns_layout.addWidget(self.right_box, 4)
        outer.addWidget(columns)
        outer.addStretch(1)

        scroll.setWidget(content)
        self.scroll = scroll
        page_layout.addWidget(scroll)

        self.feedback_timer = QTimer(self)
        self.feedback_timer.timeout.connect(self._poll_feedback)
        self.feedback_timer.start(60)
        self._poll_feedback()

    def resizeEvent(self, event):
        set_responsive_direction(event.size().width(), self.columns_layout)
        super().resizeEvent(event)

    def _build_group(self, title, options):
        box = QFrame()
        box.setObjectName('buttonSideCard')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setProperty('role', 'h2')
        layout.addWidget(title_label)
        side_hint = QLabel(t('button_haptic_hint'))
        side_hint.setProperty('role', 'hint')
        side_hint.setWordWrap(True)
        layout.addWidget(side_hint)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName('cardDivider')
        layout.addWidget(line)
        for label_key, code in options:
            entry = self.state["active"]["button_haptics"].setdefault(str(code), {"enabled": False, "strength": 0.4, "click_hz": BUTTON_CLICK_HZ})
            row = ButtonHapticRow(t(label_key), code, entry)
            row.check.toggled.connect(lambda checked, c=code: self._set_enabled(c, checked))
            row.slider.valueChanged.connect(lambda v, c=code: self._set_strength(c, v / 1000))
            row.hz_slider.valueChanged.connect(lambda v, c=code: self._set_click_hz(c, v))
            layout.addWidget(row)
            self.rows[code] = row
        layout.addStretch(1)
        return box

    def _poll_feedback(self):
        held, feedback = {}, {}
        snapshot = fresh_visual_snapshot(self.engine_holder)
        if snapshot is not None:
            held = dict(snapshot[2])
            feedback = dict(snapshot[3])
        visible_codes = set(self.rows)
        pressed = {code: max(0.0, min(1.0, float(value)))
                   for code, value in held.items() if code in visible_codes and value > 0}
        self.gamepad.set_feedback(pressed)
        self.gamepad.set_level(max(feedback.values(), default=0.0))
        for code, row in self.rows.items():
            row.set_pressed(pressed.get(code, 0.0))
        names = [f"{t(key)} {round(pressed[code] * 100)}%"
                 for key, code in BUTTON_OPTIONS if code in pressed]
        self.feedback_label.setText(' · '.join(names) if names else t('dashboard_feedback_idle'))
        left_level = max((feedback.get(code, 0.0) for _, code in LEFT_BUTTON_OPTIONS), default=0.0)
        right_level = max((feedback.get(code, 0.0) for _, code in RIGHT_BUTTON_OPTIONS), default=0.0)
        self.left_wave.setValue(round(left_level * 100))
        self.right_wave.setValue(round(right_level * 100))
        self.gamepad.set_light_color(self.light_color_getter())
        self.connection_indicator.set_connection(self.connection_getter())

    def _entry(self, code):
        return self.state["active"]["button_haptics"].setdefault(str(code), {"enabled": False, "strength": 0.4, "click_hz": BUTTON_CLICK_HZ})

    def _set_enabled(self, code, checked):
        self._entry(code)["enabled"] = checked
        self.on_change()

    def _set_strength(self, code, value):
        self._entry(code)["strength"] = value
        self.rows[code].value_label.setText(f"{value:.2f}")
        self.on_change()

    def _set_click_hz(self, code, value):
        self._entry(code)["click_hz"] = value
        self.rows[code].hz_value_label.setText(f"{value} Hz")
        self.on_change()

    def refresh(self):
        self.profile_label.setText(ref_label(self.state))
        self.gamepad.set_skin(self.state.get('controller_skin', 'white'))
        for code, row in self.rows.items():
            entry = self._entry(code)
            row.check.blockSignals(True)
            row.check.setChecked(entry["enabled"])
            row.check.blockSignals(False)
            row.slider.blockSignals(True)
            row.slider.setValue(int(entry["strength"] * 1000))
            row.slider.blockSignals(False)
            row.value_label.setText(f"{entry['strength']:.2f}")
            row.hz_slider.blockSignals(True)
            row.hz_slider.setValue(int(entry.get("click_hz", BUTTON_CLICK_HZ)))
            row.hz_slider.blockSignals(False)
            row.hz_value_label.setText(f"{int(entry.get('click_hz', BUTTON_CLICK_HZ))} Hz")


class AdvancedPage(QWidget):
    def __init__(self, state, on_change, motor_level_getter=None, connection_getter=None,
                 light_color_getter=None, engine_holder=None):
        super().__init__()
        self.state = state
        self.on_change = on_change
        self.motor_level_getter = motor_level_getter or (lambda: (0.0, 0.0, 0.0))
        self.engine_holder = engine_holder or (lambda: None)
        self._motor_engine = None
        self._motor_level_state = (0.0, 0.0, 0.0)
        self.connection_getter = connection_getter or (lambda: None)
        self.light_color_getter = light_color_getter or (lambda: DEFAULT_GAMEPAD_LIGHT)
        active = state["active"]

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel(t("advanced_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("advanced_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        heading.addWidget(hint)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        hero = QFrame()
        hero.setObjectName('vibrationHero')
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(18)
        profile_icon = QLabel('〰')
        profile_icon.setObjectName('vibrationProfileIcon')
        profile_icon.setAlignment(Qt.AlignCenter)
        profile_icon.setFixedSize(70, 70)
        hero_layout.addWidget(profile_icon)
        profile_text = QVBoxLayout()
        profile_text.setSpacing(2)
        profile_caption = QLabel(t('home_active_profile'))
        profile_caption.setProperty('role', 'hint')
        profile_text.addWidget(profile_caption)
        self.profile_label = QLabel(ref_label(state))
        self.profile_label.setProperty('role', 'componentValue')
        self.profile_label.setWordWrap(True)
        profile_text.addWidget(self.profile_label)
        live_badge = QLabel('●  ' + t('home_realtime'))
        live_badge.setProperty('role', 'accentLabel')
        profile_text.addWidget(live_badge)
        profile_text.addStretch(1)
        hero_layout.addLayout(profile_text, 3)

        waveform_column = QVBoxLayout()
        waveform_column.setSpacing(2)
        waveform_label = QLabel(t('home_motor_response'))
        waveform_label.setProperty('role', 'eyebrow')
        waveform_column.addWidget(waveform_label)
        self.live_wave = DualMotorWaveWidget()
        waveform_column.addWidget(self.live_wave, 1)
        hero_layout.addLayout(waveform_column, 4)

        hero_levels = QVBoxLayout()
        hero_levels.setSpacing(6)
        self.hero_bass_label = QLabel()
        self.hero_treble_label = QLabel()
        for variant, label in (('bass', self.hero_bass_label), ('treble', self.hero_treble_label)):
            label.setProperty('role', 'value')
            hero_levels.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setProperty('variant', variant)
            setattr(self, f'hero_{variant}_bar', bar)
            hero_levels.addWidget(bar)
        hero_levels.addStretch(1)
        hero_layout.addLayout(hero_levels, 2)
        outer.addWidget(hero)

        summary_widget = QWidget()
        self.summary_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, summary_widget)
        self.summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_layout.setSpacing(10)

        general_box = QFrame()
        general_box.setObjectName('sectionCard')
        gl = QVBoxLayout(general_box)
        gl.setContentsMargins(16, 14, 16, 16)
        general_header = QHBoxLayout()
        general_icon = QLabel('⚙')
        general_icon.setObjectName('vibrationGeneralIcon')
        general_icon.setAlignment(Qt.AlignCenter)
        general_icon.setFixedSize(44, 44)
        general_header.addWidget(general_icon)
        general_heading = QVBoxLayout()
        general_title = QLabel(t('group_general'))
        general_title.setProperty('role', 'h2')
        general_heading.addWidget(general_title)
        general_hint = QLabel(t('advanced_hint'))
        general_hint.setProperty('role', 'hint')
        general_hint.setWordWrap(True)
        general_heading.addWidget(general_hint)
        general_header.addLayout(general_heading, 1)
        gl.addLayout(general_header)
        self.gain_slider = ParamSlider(t("label_master_gain"), 0.2, 2.5, active["master_gain"], 2,
                                        None, self._set_gain)
        gl.addWidget(self.gain_slider)
        gl.addStretch(1)
        self.summary_layout.addWidget(general_box, 4)

        balance_box = QFrame()
        balance_box.setObjectName('motorBalanceCard')
        balance_layout = QVBoxLayout(balance_box)
        balance_layout.setContentsMargins(16, 12, 16, 10)
        balance_header = QHBoxLayout()
        balance_title = QLabel(t('home_motor_response'))
        balance_title.setProperty('role', 'h2')
        balance_header.addWidget(balance_title)
        balance_header.addStretch(1)
        self.balance_status = QLabel(t('home_realtime'))
        self.balance_status.setProperty('role', 'accentLabel')
        balance_header.addWidget(self.balance_status)
        balance_layout.addLayout(balance_header)
        self.controller_outline = ReactiveControllerOutline()
        self.controller_outline.set_skin(state.get('controller_skin', 'white'))
        self.controller_outline.set_light_color(self.light_color_getter())
        balance_layout.addWidget(self.controller_outline, 1)
        balance_labels = QHBoxLayout()
        self.bass_value = QLabel()
        self.treble_value = QLabel()
        self.bass_value.setProperty('role', 'value')
        self.treble_value.setProperty('role', 'value')
        balance_labels.addWidget(self.bass_value)
        balance_labels.addStretch(1)
        balance_labels.addWidget(self.treble_value)
        balance_layout.addLayout(balance_labels)
        self.summary_layout.addWidget(balance_box, 5)
        outer.addWidget(summary_widget)

        bands_widget = QWidget()
        self.bands_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, bands_widget)
        self.bands_layout.setContentsMargins(0, 0, 0, 0)
        self.bands_layout.setSpacing(10)
        self.bass_box = band_group(t("group_bass"), active["bass"], active["bass_ceiling"], on_change, 'bass')
        self.treble_box = band_group(t("group_treble"), active["treble"], active["treble_ceiling"], on_change, 'treble')
        self.bands_layout.addWidget(self.bass_box, 1)
        self.bands_layout.addWidget(self.treble_box, 1)
        outer.addWidget(bands_widget)
        outer.addStretch(1)

        scroll.setWidget(content)
        self.scroll = scroll
        page_layout.addWidget(scroll)

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._poll_preview)
        self.preview_timer.start(60)
        self._poll_preview()

    def resizeEvent(self, event):
        set_responsive_direction(
            event.size().width(), self.summary_layout, self.bands_layout)
        super().resizeEvent(event)

    def _poll_preview(self):
        stamp, strong, weak = self._read_motor_levels()
        if not stamp or time.monotonic() - stamp > .5:
            strong, weak = 0.0, 0.0
        strong = max(0.0, min(1.0, float(strong)))
        weak = max(0.0, min(1.0, float(weak)))
        self.controller_outline.set_levels(strong, weak)
        snapshot = fresh_visual_snapshot(self.engine_holder)
        self.controller_outline.set_feedback(
            dict(snapshot[2]) if snapshot is not None else {})
        self.live_wave.set_levels(strong, weak)
        bass_percent, treble_percent = round(strong * 100), round(weak * 100)
        self.hero_bass_bar.setValue(bass_percent)
        self.hero_treble_bar.setValue(treble_percent)
        self.hero_bass_label.setText(f"{t('label_bass')}  {bass_percent}%")
        self.hero_treble_label.setText(f"{t('label_treble')}  {treble_percent}%")
        self.bass_value.setText(f"{t('label_bass')}  {bass_percent}%")
        self.treble_value.setText(f"{t('label_treble')}  {treble_percent}%")
        self.controller_outline.set_light_color(self.light_color_getter())
        self.connection_indicator.set_connection(self.connection_getter())

    def _read_motor_levels(self):
        """Consume the latest motor sample on this active page directly."""
        engine = self.engine_holder()
        if engine is None:
            try:
                return self.motor_level_getter()
            except (TypeError, ValueError):
                return 0.0, 0.0, 0.0
        if engine is not self._motor_engine:
            self._motor_engine = engine
            self._motor_level_state = (0.0, 0.0, 0.0)
        try:
            while True:
                strong, weak = engine.level_queue.get_nowait()
                self._motor_level_state = (time.monotonic(), strong, weak)
        except queue.Empty:
            pass
        return self._motor_level_state

    def _set_gain(self, v):
        self.state["active"]["master_gain"] = v

    def refresh(self):
        self.profile_label.setText(ref_label(self.state))
        self.controller_outline.set_skin(self.state.get('controller_skin', 'white'))
        self.gain_slider.set_value(self.state["active"]["master_gain"])
        self.bass_box.refresh()
        self.treble_box.refresh()
        self._poll_preview()


class ColorSwatchButton(QPushButton):
    """Compact color picker used by the LED preset editor."""

    def __init__(self, rgb, on_change):
        super().__init__()
        self.rgb = tuple(rgb)
        self.on_change = on_change
        self.setFixedSize(46, 28)
        self.setToolTip(t("label_led_color"))
        self._apply_style()
        self.clicked.connect(self._pick)

    def _apply_style(self):
        r, g, b = self.rgb
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); "
            "border: 1px solid rgba(128,128,128,120); border-radius: 8px;")

    def _pick(self):
        color = QColorDialog.getColor(QColor(*self.rgb), self.window(), t("label_led_color"))
        if color.isValid():
            self.rgb = (color.red(), color.green(), color.blue())
            self._apply_style()
            self.on_change(list(self.rgb))


class LedModeButton(QToolButton):
    """Large, scan-friendly preset tile used instead of a dropdown."""

    def __init__(self, glyph, title, preset_id):
        super().__init__()
        self.preset_id = preset_id
        self.setObjectName("ledModeButton")
        self.setText(title)
        self.setIcon(render_emoji_icon(glyph, 72))
        self.setIconSize(QSize(29, 29))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class LedPage(QWidget):
    _PRESET_ORDER = [
        "static", "breathing", "wave", "immersive",
        "rainbow", "heartbeat", "battery", "custom",
    ]
    _PRESET_GLYPHS = {
        "static": "☀", "breathing": "◉", "wave": "≋", "immersive": "ϟ",
        "rainbow": "◒", "heartbeat": "♥", "battery": "▣", "custom": "✦",
    }
    _QUICK_COLORS = [
        (22, 140, 255), (113, 78, 255), (198, 71, 230), (255, 67, 101),
        (255, 145, 40), (255, 202, 55), (52, 220, 112), (48, 209, 218),
        (245, 248, 255), (24, 39, 60),
    ]
    _ANIMATED_INTERVAL_RANGES = {
        "breathing": (0.5, 5.0), "wave": (0.3, 3.0), "heartbeat": (0.5, 3.0),
    }

    def __init__(self, state, on_change, engine_holder=None, connection_getter=None):
        super().__init__()
        self.state = state
        self.on_change = on_change
        self._slider_change_in_progress = False
        self.engine_holder = engine_holder or (lambda: None)
        self.connection_getter = connection_getter or (lambda: None)
        active = state["active"]

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel(t("led_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("led_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        heading.addWidget(hint)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        led_cfg = active.setdefault("led", copy.deepcopy(DEFAULT_CONFIG["led"]))
        preview_card = QFrame()
        preview_card.setObjectName('sectionCard')
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 13, 16, 15)
        preview_header = QHBoxLayout()
        preview_title = QLabel(t('led_preview_title'))
        preview_title.setProperty('role', 'h2')
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        self.preview_state = QLabel()
        self.preview_state.setProperty('role', 'accentLabel')
        preview_header.addWidget(self.preview_state)
        preview_layout.addLayout(preview_header)

        preview_body = QHBoxLayout()
        preview_body.setSpacing(14)
        self.preview_scene = LedPreviewScene()
        scene_layout = QVBoxLayout(self.preview_scene)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        self.gamepad = GamepadWidget()
        self.gamepad.set_skin(state.get('controller_skin', 'white'))
        self.gamepad.set_light_color(
            DEFAULT_GAMEPAD_LIGHT if led_cfg.get('enabled', False) else OFF_GAMEPAD_LIGHT)
        self.gamepad.setMinimumHeight(250)
        scene_layout.addWidget(self.gamepad)
        preview_body.addWidget(self.preview_scene, 3)

        controls = QFrame()
        controls.setObjectName('triggerPanel')
        controls.setMinimumWidth(245)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(16, 14, 16, 14)
        controls_layout.setSpacing(8)
        self.led_visualizer_check = QCheckBox(t("led_enabled_checkbox"))
        self.led_visualizer_check.setToolTip(t("led_hint"))
        self.led_visualizer_check.setChecked(led_cfg.get("enabled", False))
        self.led_visualizer_check.toggled.connect(self._set_enabled)
        controls_layout.addWidget(self.led_visualizer_check)
        selected_cfg = led_cfg.get(led_cfg.get("preset", "immersive"), {})
        self.brightness_slider = ParamSlider(
            t("label_led_brightness"), 0.0, 1.0, selected_cfg.get("brightness", 1.0), 2,
            None, self._set_selected_brightness)
        controls_layout.addWidget(self.brightness_slider)
        color_caption = QLabel(t('led_live_color'))
        color_caption.setProperty('role', 'hint')
        controls_layout.addWidget(color_caption)
        self.live_color = LightbarDots()
        controls_layout.addWidget(self.live_color)
        meter_caption = QLabel(t('led_player_meter'))
        meter_caption.setProperty('role', 'hint')
        controls_layout.addWidget(meter_caption)
        self.player_meter = PlayerLedMeter()
        controls_layout.addWidget(self.player_meter)
        controls_layout.addStretch(1)
        preview_body.addWidget(controls, 2)
        preview_layout.addLayout(preview_body)
        outer.addWidget(preview_card)

        mode_card = QFrame()
        mode_card.setObjectName('sectionCard')
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 13, 16, 15)
        mode_header = QHBoxLayout()
        mode_title = QLabel(t('home_mode'))
        mode_title.setProperty('role', 'h2')
        mode_header.addWidget(mode_title)
        mode_header.addStretch(1)
        self.preset_combo = QComboBox(self)
        for preset_id in self._PRESET_ORDER:
            self.preset_combo.addItem(t(f'led_preset_{preset_id}_label'), preset_id)
        self.preset_combo.currentIndexChanged.connect(self._select_preset_index)
        self.preset_combo.hide()
        self.reset_preset_btn = QPushButton(t('btn_reset_preset'))
        self.reset_preset_btn.clicked.connect(self._reset_selected_preset)
        mode_header.addWidget(self.reset_preset_btn)
        mode_layout.addLayout(mode_header)

        self.modes_grid = QGridLayout()
        self.modes_grid.setHorizontalSpacing(9)
        self.modes_grid.setVerticalSpacing(9)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        for index, preset_id in enumerate(self._PRESET_ORDER):
            button = LedModeButton(
                self._PRESET_GLYPHS[preset_id], t(f'led_preset_{preset_id}_label'), preset_id)
            button.clicked.connect(
                lambda checked=False, p=preset_id: self._select_preset(p) if checked else None)
            self.mode_group.addButton(button)
            self.mode_buttons[preset_id] = button
        self._layout_mode_buttons(4)
        mode_layout.addLayout(self.modes_grid)
        outer.addWidget(mode_card)

        self.editor_card = QFrame()
        self.editor_card.setObjectName('sectionCard')
        editor_layout = QVBoxLayout(self.editor_card)
        editor_layout.setContentsMargins(16, 13, 16, 15)
        self.editor_title = QLabel(t('label_led_color'))
        self.editor_title.setProperty('role', 'h2')
        editor_layout.addWidget(self.editor_title)
        self.preset_editor = QWidget()
        self.preset_editor_layout = QVBoxLayout(self.preset_editor)
        self.preset_editor_layout.setContentsMargins(0, 4, 0, 0)
        editor_layout.addWidget(self.preset_editor)
        outer.addWidget(self.editor_card)

        self.dynamics_card = QFrame()
        self.dynamics_card.setObjectName('sectionCard')
        dynamics_layout = QVBoxLayout(self.dynamics_card)
        dynamics_layout.setContentsMargins(16, 13, 16, 15)
        dynamics_title = QLabel(t('led_dynamics_title'))
        dynamics_title.setProperty('role', 'h2')
        dynamics_layout.addWidget(dynamics_title)
        slider_grid = QHBoxLayout()
        slider_grid.setSpacing(24)
        left_controls = QVBoxLayout()
        right_controls = QVBoxLayout()

        immersive_cfg = led_cfg.setdefault("immersive", {})
        self.led_attack_slider = ParamSlider(
            t("label_led_attack"), 0.05, 1.0, immersive_cfg.get("attack", 0.5), 2,
            t("led_attack_hint"), self._set_led_attack)
        left_controls.addWidget(self.led_attack_slider)
        self.led_release_slider = ParamSlider(
            t("label_led_release"), 0.01, 0.5, immersive_cfg.get("release", 0.08), 2,
            t("led_release_hint"), self._set_led_release)
        left_controls.addWidget(self.led_release_slider)
        self.led_gamma_slider = ParamSlider(
            t("label_led_gamma"), 0.5, 3.0, immersive_cfg.get("gamma", 1.8), 1,
            t("led_gamma_hint"), self._set_led_gamma)
        right_controls.addWidget(self.led_gamma_slider)
        self.led_bass_priority_slider = ParamSlider(
            t("label_led_bass_priority"), 0.0, 1.0, immersive_cfg.get("bass_priority", 0.6), 2,
            t("led_bass_priority_hint"), self._set_led_bass_priority)
        right_controls.addWidget(self.led_bass_priority_slider)
        slider_grid.addLayout(left_controls, 1)
        slider_grid.addLayout(right_controls, 1)
        dynamics_layout.addLayout(slider_grid)
        outer.addWidget(self.dynamics_card)
        outer.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._poll_preview)
        self.preview_timer.start(60)
        self.refresh()

    def _layout_mode_buttons(self, columns):
        while self.modes_grid.count():
            self.modes_grid.takeAt(0)
        for index, preset_id in enumerate(self._PRESET_ORDER):
            self.modes_grid.addWidget(
                self.mode_buttons[preset_id], index // columns, index % columns)

    def resizeEvent(self, event):
        columns = 2 if event.size().width() < 820 else 4
        if getattr(self, "_mode_columns", None) != columns:
            self._mode_columns = columns
            self._layout_mode_buttons(columns)
        super().resizeEvent(event)

    def _led_cfg(self):
        return self.state["active"].setdefault("led", copy.deepcopy(DEFAULT_CONFIG["led"]))

    def _set_enabled(self, checked):
        self._led_cfg()["enabled"] = checked
        if self.on_change:
            self.on_change()

    # Kept as a compatibility alias for callers from the pre-v1.10 UI.
    def _set_led_visualizer_enabled(self, checked):
        self._set_enabled(checked)

    def _poll_preview(self):
        led_cfg = self._led_cfg()
        enabled = self.led_visualizer_check.isChecked()
        preset_id = led_cfg.get("preset", "immersive")
        snapshot = fresh_visual_snapshot(self.engine_holder)
        rgb = None
        player_level = 0.0
        if enabled and preset_id == "immersive":
            if snapshot is not None:
                rgb = snapshot[1]
                player_level = max(rgb) / 255 if rgb is not None else 0.0
        elif enabled:
            rgb, player_mask = bt_hid_proxy.compute_led_output(led_cfg, time.monotonic())
            player_level = sum(player_mask) / 5
        self.preview_state.setText('ON' if enabled else 'OFF')
        self.live_color.set_enabled(enabled)
        self.live_color.set_color(rgb)
        fallback = led_cfg.get("immersive", {}).get("bass_color", DEFAULT_GAMEPAD_LIGHT)
        display_rgb = rgb if rgb is not None else (tuple(fallback) if enabled else OFF_GAMEPAD_LIGHT)
        self.preview_scene.set_color(display_rgb)
        self.gamepad.set_light_color(display_rgb)
        self.gamepad.set_feedback(dict(snapshot[2]) if snapshot is not None else {})
        if enabled and preset_id == "immersive" and rgb is None:
            player_level = 0.16
        self.player_meter.set_level(player_level)
        self.gamepad.set_level(player_level)
        self.connection_indicator.set_connection(self.connection_getter())

    def _set_led_attack(self, v):
        self._led_cfg().setdefault("immersive", {})["attack"] = v
        self._persist_slider_change()

    def _set_led_release(self, v):
        self._led_cfg().setdefault("immersive", {})["release"] = v
        self._persist_slider_change()

    def _set_led_gamma(self, v):
        self._led_cfg().setdefault("immersive", {})["gamma"] = v
        self._persist_slider_change()

    def _set_led_bass_priority(self, v):
        self._led_cfg().setdefault("immersive", {})["bass_priority"] = v
        self._persist_slider_change()

    def _persist_slider_change(self):
        """Save a drag without rebuilding the editor under the cursor."""
        if self.on_change:
            self._slider_change_in_progress = True
            try:
                self.on_change()
            finally:
                self._slider_change_in_progress = False

    def _set_selected_brightness(self, value):
        preset_id = self._led_cfg().get("preset", "immersive")
        if preset_id != "immersive":
            self._set_preset_value(preset_id, "brightness", value)

    def _select_preset(self, preset_id):
        index = self.preset_combo.findData(preset_id)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _select_preset_index(self, index):
        preset_id = self.preset_combo.itemData(index)
        if preset_id is None:
            return
        self._led_cfg()["preset"] = preset_id
        for button_id, button in self.mode_buttons.items():
            button.setChecked(button_id == preset_id)
        self._rebuild_preset_editor()
        if self.on_change:
            self.on_change()
        self._poll_preview()

    def _reset_selected_preset(self):
        preset_id = self._led_cfg().get("preset", "immersive")
        self._led_cfg()[preset_id] = copy.deepcopy(DEFAULT_CONFIG["led"].get(preset_id, {}))
        if self.on_change:
            self.on_change()
        self.refresh()

    def _clear_preset_editor(self):
        while self.preset_editor_layout.count():
            item = self.preset_editor_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    child = child_layout.takeAt(0).widget()
                    if child is not None:
                        child.deleteLater()

    def _rebuild_preset_editor(self):
        self._clear_preset_editor()
        led_cfg = self._led_cfg()
        preset_id = led_cfg.get("preset", "immersive")
        cfg = led_cfg.setdefault(preset_id, {})
        self.dynamics_card.setVisible(preset_id == "immersive")
        self.editor_title.setText(t(f"led_preset_{preset_id}_label"))
        self.editor_card.setVisible(True)
        has_brightness = preset_id != "immersive"
        self.brightness_slider.setVisible(has_brightness)
        if has_brightness:
            self.brightness_slider.set_value(cfg.get("brightness", 1.0))

        if preset_id == "immersive":
            hint = QLabel(t("led_visualizer_hint"))
            hint.setProperty("role", "hint")
            hint.setWordWrap(True)
            self.preset_editor_layout.addWidget(hint)
            colors = (
                ("bass_color", "label_led_immersive_bass_color", [255, 0, 0]),
                ("mid_color", "label_led_immersive_mid_color", [0, 255, 0]),
                ("treble_color", "label_led_immersive_treble_color", [0, 0, 255]),
            )
            self._add_color_row(preset_id, cfg, colors)
            return

        if preset_id == "static":
            self._add_color_row(preset_id, cfg, (("color", "label_led_color", [255, 255, 255]),))
        elif preset_id in self._ANIMATED_INTERVAL_RANGES:
            self._add_color_row(preset_id, cfg, (("color", "label_led_color", [255, 255, 255]),))
            lo, hi = self._ANIMATED_INTERVAL_RANGES[preset_id]
            self.preset_editor_layout.addWidget(ParamSlider(
                t("label_led_interval"), lo, hi, cfg.get("interval_s", (lo + hi) / 2), 2, None,
                lambda value, p=preset_id: self._set_preset_value(p, "interval_s", value)))
        elif preset_id == "rainbow":
            self.preset_editor_layout.addWidget(ParamSlider(
                t("label_led_interval"), 2.0, 20.0, cfg.get("interval_s", 6.0), 1, None,
                lambda value: self._set_preset_value("rainbow", "interval_s", value)))
        elif preset_id == "battery":
            self._add_color_row(preset_id, cfg, (
                ("low_color", "label_led_low_color", [255, 0, 0]),
                ("mid_color", "label_led_mid_color", [255, 200, 0]),
                ("high_color", "label_led_high_color", [0, 255, 0]),
            ))
            self.preset_editor_layout.addWidget(ParamSlider(
                t("label_led_low_threshold"), 0, 100, cfg.get("low_threshold", 25), 0, None,
                lambda value: self._set_preset_value("battery", "low_threshold", int(value))))
            self.preset_editor_layout.addWidget(ParamSlider(
                t("label_led_mid_threshold"), 0, 100, cfg.get("mid_threshold", 60), 0, None,
                lambda value: self._set_preset_value("battery", "mid_threshold", int(value))))
        elif preset_id == "custom":
            self._add_custom_controls(cfg)

    def _add_color_row(self, preset_id, cfg, color_specs):
        row = QHBoxLayout()
        for key, label_key, default in color_specs:
            row.addWidget(QLabel(t(label_key)))
            row.addWidget(ColorSwatchButton(
                cfg.get(key, default),
                lambda rgb, p=preset_id, k=key: self._set_preset_color(p, k, rgb)))
        row.addStretch(1)
        self.preset_editor_layout.addLayout(row)
        if len(color_specs) == 1:
            key, _label_key, _default = color_specs[0]
            palette = QHBoxLayout()
            palette.setSpacing(9)
            current = tuple(cfg.get(key, _default))
            for color in self._QUICK_COLORS:
                dot = QPushButton()
                dot.setObjectName("ledColorDot")
                dot.setFixedSize(28, 28)
                dot.setCursor(Qt.PointingHandCursor)
                border = "#bfe6ff" if tuple(color) == current else "rgba(255,255,255,45)"
                dot.setStyleSheet(
                    f"background: rgb({color[0]},{color[1]},{color[2]}); "
                    f"border: 2px solid {border}; border-radius: 14px; padding: 0;")
                dot.setToolTip('#%02X%02X%02X' % color)
                dot.clicked.connect(
                    lambda _=False, rgb=color, p=preset_id, k=key:
                    self._set_preset_color(p, k, rgb))
                palette.addWidget(dot)
            palette.addStretch(1)
            self.preset_editor_layout.addLayout(palette)

    def _add_custom_controls(self, cfg):
        colors = cfg.setdefault("colors", [[255, 0, 0], [0, 255, 0], [0, 0, 255]])
        row = QHBoxLayout()
        for index, color in enumerate(colors):
            row.addWidget(ColorSwatchButton(
                color, lambda rgb, i=index: self._set_custom_color(i, rgb)))
            remove = QPushButton("✕")
            remove.setFixedWidth(28)
            remove.setToolTip(t("btn_remove_color"))
            remove.setEnabled(len(colors) > 1)
            remove.clicked.connect(lambda _=False, i=index: self._remove_custom_color(i))
            row.addWidget(remove)
        add = QPushButton(t("btn_add_color"))
        add.setEnabled(len(colors) < 8)
        add.clicked.connect(self._add_custom_color)
        row.addWidget(add)
        row.addStretch(1)
        self.preset_editor_layout.addLayout(row)
        self.preset_editor_layout.addWidget(ParamSlider(
            t("label_led_interval"), 0.5, 5.0, cfg.get("interval_s", 3.0), 2, None,
            lambda value: self._set_preset_value("custom", "interval_s", value)))
        self.preset_editor_layout.addWidget(ParamSlider(
            t("label_led_fade"), 0.0, 3.0, cfg.get("fade_s", 0.5), 2, t("led_fade_hint"),
            lambda value: self._set_preset_value("custom", "fade_s", value)))

    def _set_preset_value(self, preset_id, key, value):
        self._led_cfg().setdefault(preset_id, {})[key] = value
        self._persist_slider_change()
        self._poll_preview()

    def _set_preset_color(self, preset_id, key, rgb):
        self._led_cfg().setdefault(preset_id, {})[key] = list(rgb)
        if self.on_change:
            self.on_change()
        self._rebuild_preset_editor()
        self._poll_preview()

    def _add_custom_color(self):
        colors = self._led_cfg().setdefault("custom", {}).setdefault("colors", [])
        if len(colors) < 8:
            colors.append([255, 255, 255])
            if self.on_change:
                self.on_change()
            self._rebuild_preset_editor()

    def _remove_custom_color(self, index):
        colors = self._led_cfg().setdefault("custom", {}).setdefault("colors", [])
        if len(colors) > 1 and 0 <= index < len(colors):
            colors.pop(index)
            if self.on_change:
                self.on_change()
            self._rebuild_preset_editor()

    def _set_custom_color(self, index, rgb):
        colors = self._led_cfg().setdefault("custom", {}).setdefault("colors", [])
        if 0 <= index < len(colors):
            colors[index] = list(rgb)
            if self.on_change:
                self.on_change()
            self._poll_preview()

    def refresh(self):
        led_cfg = self._led_cfg()
        self.led_visualizer_check.blockSignals(True)
        self.led_visualizer_check.setChecked(led_cfg.get("enabled", False))
        self.led_visualizer_check.blockSignals(False)
        preset_id = led_cfg.get("preset", "immersive")
        index = self.preset_combo.findData(preset_id)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, index))
        self.preset_combo.blockSignals(False)
        for button_id, button in self.mode_buttons.items():
            button.setChecked(button_id == preset_id)
        immersive = led_cfg.get("immersive", {})
        self.led_attack_slider.set_value(immersive.get("attack", 0.5))
        self.led_release_slider.set_value(immersive.get("release", 0.08))
        self.led_gamma_slider.set_value(immersive.get("gamma", 1.8))
        self.led_bass_priority_slider.set_value(immersive.get("bass_priority", 0.6))
        if not self._slider_change_in_progress:
            self._rebuild_preset_editor()
        self.gamepad.set_skin(self.state.get('controller_skin', 'white'))
        self._poll_preview()


class ExperimentalPage(QWidget):
    def __init__(self, state, on_change):
        super().__init__()
        self.state = state
        self.on_change = on_change
        active = state["active"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        title = QLabel(t("experimental_title"))
        title.setProperty("role", "h1")
        outer.addWidget(title)
        hint = QLabel(t("experimental_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        direct_box = QGroupBox(t("group_direct_audio"))
        dl = QVBoxLayout(direct_box)
        direct_hint = QLabel(t("direct_audio_hint"))
        direct_hint.setProperty("role", "hint")
        direct_hint.setWordWrap(True)
        dl.addWidget(direct_hint)
        direct_cfg = active["direct_audio"]
        self.direct_check = QCheckBox(t("direct_audio_checkbox"))
        self.direct_check.setChecked(direct_cfg.get("enabled", True))
        self.direct_check.toggled.connect(self._set_direct_enabled)
        dl.addWidget(self.direct_check)
        self.direct_gain_slider = ParamSlider(
            t("label_direct_gain"), 1.0, 8.0, direct_cfg.get("gain", 5.0), 1, None, self._set_direct_gain)
        dl.addWidget(self.direct_gain_slider)

        bt_hint = QLabel(t("direct_audio_bt_hint"))
        bt_hint.setProperty("role", "hint")
        bt_hint.setWordWrap(True)
        dl.addWidget(bt_hint)
        self.direct_bt_check = QCheckBox(t("direct_audio_bt_checkbox"))
        self.direct_bt_check.setChecked(direct_cfg.get("bt_enabled", False))
        self.direct_bt_check.toggled.connect(self._set_direct_bt_enabled)
        dl.addWidget(self.direct_bt_check)

        bt_chunk_ms_hint = QLabel(t("bt_chunk_ms_hint"))
        bt_chunk_ms_hint.setProperty("role", "hint")
        bt_chunk_ms_hint.setWordWrap(True)
        dl.addWidget(bt_chunk_ms_hint)
        self.bt_chunk_ms_combo = QComboBox()
        for value in BT_CHUNK_MS_CHOICES:
            self.bt_chunk_ms_combo.addItem(f"{value} ms", value)
        current_chunk_ms = direct_cfg.get("bt_chunk_ms", BT_CHUNK_MS)
        idx = next((i for i, v in enumerate(BT_CHUNK_MS_CHOICES) if v == current_chunk_ms), 1)
        self.bt_chunk_ms_combo.setCurrentIndex(idx)
        self.bt_chunk_ms_combo.currentIndexChanged.connect(
            lambda i: self._set_bt_chunk_ms(self.bt_chunk_ms_combo.itemData(i)))
        dl.addWidget(self.bt_chunk_ms_combo)

        saxense_restart_hint = QLabel(t("saxense_restart_hint"))
        saxense_restart_hint.setProperty("role", "hint")
        saxense_restart_hint.setWordWrap(True)
        dl.addWidget(saxense_restart_hint)
        saxense_restart_warning = QLabel(t("saxense_restart_warning"))
        saxense_restart_warning.setWordWrap(True)
        saxense_restart_warning.setStyleSheet("font-weight: 700; color: #d64545;")
        dl.addWidget(saxense_restart_warning)
        self.saxense_restart_check = QCheckBox(t("saxense_restart_checkbox"))
        self.saxense_restart_check.setChecked(direct_cfg.get("saxense_restart_on_stall", False))
        self.saxense_restart_check.toggled.connect(self._set_saxense_restart_on_stall)
        dl.addWidget(self.saxense_restart_check)

        inner_layout.addWidget(direct_box)

        proxy_box = QGroupBox(t("group_bt_proxy"))
        pl = QVBoxLayout(proxy_box)
        proxy_hint = QLabel(t("bt_proxy_hint"))
        proxy_hint.setProperty("role", "hint")
        proxy_hint.setWordWrap(True)
        pl.addWidget(proxy_hint)
        proxy_privilege_hint = QLabel(t("bt_proxy_privilege_hint"))
        proxy_privilege_hint.setProperty("role", "hint")
        proxy_privilege_hint.setWordWrap(True)
        pl.addWidget(proxy_privilege_hint)
        proxy_cfg = active["bt_hid_proxy"]
        self.bt_proxy_check = QCheckBox(t("bt_proxy_checkbox"))
        self.bt_proxy_check.setChecked(proxy_cfg.get("enabled", False))
        self.bt_proxy_check.toggled.connect(self._set_bt_proxy_enabled)
        pl.addWidget(self.bt_proxy_check)

        inner_layout.addWidget(proxy_box)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _set_direct_enabled(self, checked):
        self.state["active"]["direct_audio"]["enabled"] = checked
        if self.on_change:
            self.on_change()

    def _set_direct_gain(self, v):
        self.state["active"]["direct_audio"]["gain"] = v
        if self.on_change:
            self.on_change()

    def _set_bt_chunk_ms(self, v):
        self.state["active"]["direct_audio"]["bt_chunk_ms"] = v
        if self.on_change:
            self.on_change()

    def _set_direct_bt_enabled(self, checked):
        self.state["active"]["direct_audio"]["bt_enabled"] = checked
        if self.on_change:
            self.on_change()

    def _set_saxense_restart_on_stall(self, checked):
        self.state["active"]["direct_audio"]["saxense_restart_on_stall"] = checked
        if self.on_change:
            self.on_change()

    def _set_bt_proxy_enabled(self, checked):
        if checked:
            ok, _reason = bt_hid_proxy.preflight_check()
            if not ok:
                QMessageBox.warning(self, t("bt_proxy_unavailable_title"), t("bt_proxy_unavailable_body"))
                self.bt_proxy_check.blockSignals(True)
                self.bt_proxy_check.setChecked(False)
                self.bt_proxy_check.blockSignals(False)
                return
        self.state["active"]["bt_hid_proxy"]["enabled"] = checked
        if self.on_change:
            self.on_change()

    def refresh(self):
        direct_cfg = self.state["active"]["direct_audio"]
        self.direct_check.blockSignals(True)
        self.direct_check.setChecked(direct_cfg.get("enabled", True))
        self.direct_check.blockSignals(False)
        self.direct_gain_slider.set_value(direct_cfg.get("gain", 5.0))
        self.direct_bt_check.blockSignals(True)
        self.direct_bt_check.setChecked(direct_cfg.get("bt_enabled", False))
        self.direct_bt_check.blockSignals(False)
        current_chunk_ms = direct_cfg.get("bt_chunk_ms", BT_CHUNK_MS)
        idx = next((i for i, v in enumerate(BT_CHUNK_MS_CHOICES) if v == current_chunk_ms), 1)
        self.bt_chunk_ms_combo.blockSignals(True)
        self.bt_chunk_ms_combo.setCurrentIndex(idx)
        self.bt_chunk_ms_combo.blockSignals(False)
        self.saxense_restart_check.blockSignals(True)
        self.saxense_restart_check.setChecked(direct_cfg.get("saxense_restart_on_stall", False))
        self.saxense_restart_check.blockSignals(False)
        self.bt_proxy_check.blockSignals(True)
        self.bt_proxy_check.setChecked(self.state["active"]["bt_hid_proxy"].get("enabled", False))
        self.bt_proxy_check.blockSignals(False)


class ThemePreviewButton(QPushButton):
    """A full-card theme picker with a miniature window preview."""

    def __init__(self, theme_name, label):
        super().__init__(label)
        self.theme_name = theme_name
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumSize(130, 104)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.manager.palette
        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = QColor(pal['accent'] if self.isChecked() else pal['border'])
        fill = QColor(pal['pressed'] if self.isChecked() else pal['bg_card'])
        if self.underMouse() and not self.isChecked():
            fill = QColor(pal['hero_start'])
        p.setPen(QPen(border, 2 if self.isChecked() else 1))
        p.setBrush(fill)
        p.drawRoundedRect(card, 11, 11)

        preview = QRectF(13, 12, self.width() - 26, 54)
        p.setPen(QPen(QColor(pal['border']), 1))
        if self.theme_name == 'dark':
            p.setBrush(QColor(theme.DARK['bg']))
            p.drawRoundedRect(preview, 7, 7)
            p.fillRect(QRectF(preview.x(), preview.y(), preview.width() * .23, preview.height()), QColor(theme.DARK['bg_sidebar']))
        elif self.theme_name == 'light':
            p.setBrush(QColor(theme.LIGHT['bg']))
            p.drawRoundedRect(preview, 7, 7)
            p.fillRect(QRectF(preview.x(), preview.y(), preview.width() * .23, preview.height()), QColor(theme.LIGHT['pressed']))
        else:
            p.setBrush(QColor(theme.LIGHT['bg']))
            p.drawRoundedRect(preview, 7, 7)
            p.fillRect(QRectF(preview.center().x(), preview.y(), preview.width() / 2, preview.height()), QColor(theme.DARK['bg']))
            p.fillRect(QRectF(preview.x(), preview.y(), preview.width() * .18, preview.height()), QColor(theme.LIGHT['pressed']))
        accent = QColor(pal['accent'])
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(preview.x() + preview.width() * .32, preview.y() + 14,
                                 preview.width() * .48, 6), 3, 3)
        p.drawRoundedRect(QRectF(preview.x() + preview.width() * .32, preview.y() + 27,
                                 preview.width() * .34, 5), 2, 2)

        if self.isChecked():
            center = QPointF(self.width() - 18, 18)
            p.setBrush(accent)
            p.drawEllipse(center, 10, 10)
            p.setPen(QPen(Qt.white, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(QPointF(center.x() - 4, center.y()), QPointF(center.x() - 1, center.y() + 3))
            p.drawLine(QPointF(center.x() - 1, center.y() + 3), QPointF(center.x() + 5, center.y() - 4))

        p.setPen(QColor(pal['fg']))
        font = p.font()
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(QRectF(8, 72, self.width() - 16, 24), Qt.AlignCenter, self.text())
        p.end()


class SettingsPage(QWidget):
    def __init__(self, state, on_theme_change, on_language_change, connection_getter=None):
        super().__init__()
        self.state = state
        self.connection_getter = connection_getter or (lambda: None)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel(t("settings_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        subtitle = QLabel(t('settings_subtitle'))
        subtitle.setProperty('role', 'hint')
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        theme_box = QFrame()
        theme_box.setObjectName('sectionCard')
        theme_layout = QVBoxLayout(theme_box)
        theme_layout.setContentsMargins(16, 13, 16, 15)
        theme_title = QLabel(t('group_theme'))
        theme_title.setProperty('role', 'h2')
        theme_layout.addWidget(theme_title)
        theme_choices = [("dark", t("theme_dark")), ("light", t("theme_light")),
                         ("system", t("theme_system"))]
        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons = {}
        for value, label in theme_choices:
            button = ThemePreviewButton(value, label)
            button.clicked.connect(lambda _checked=False, v=value: on_theme_change(v))
            self.theme_group.addButton(button)
            self.theme_buttons[value] = button
            theme_row.addWidget(button, 1)
        current_theme = state.get("theme", "system")
        self.theme_buttons.get(current_theme, self.theme_buttons['system']).setChecked(True)
        theme_layout.addLayout(theme_row)
        outer.addWidget(theme_box)

        lang_box = QFrame()
        lang_box.setObjectName('sectionCard')
        lang_layout = QHBoxLayout(lang_box)
        lang_layout.setContentsMargins(16, 13, 16, 15)
        lang_text = QVBoxLayout()
        lang_title = QLabel(t('group_language'))
        lang_title.setProperty('role', 'h2')
        lang_text.addWidget(lang_title)
        lang_hint = QLabel(t('settings_language_hint'))
        lang_hint.setProperty('role', 'hint')
        lang_text.addWidget(lang_hint)
        lang_layout.addLayout(lang_text, 1)
        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(240)
        for code, native_name in LANGUAGES:
            self.lang_combo.addItem(native_name, code)
        current_lang = state.get("language", "en")
        idx = next((i for i, (code, _) in enumerate(LANGUAGES) if code == current_lang), 0)
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(lambda i: on_language_change(self.lang_combo.itemData(i)))
        lang_layout.addWidget(self.lang_combo)
        outer.addWidget(lang_box)

        about_card = QFrame()
        about_card.setObjectName('sectionCard')
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(16, 13, 16, 15)
        about_title = QLabel(t('settings_about_title'))
        about_title.setProperty('role', 'h2')
        about_layout.addWidget(about_title)
        about_row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(make_app_icon(theme.manager.palette).pixmap(52, 52))
        icon.setFixedSize(58, 58)
        icon.setAlignment(Qt.AlignCenter)
        about_row.addWidget(icon)
        about_text = QVBoxLayout()
        app_name = QLabel('DualSense Haptics')
        app_name.setStyleSheet('font-size: 15px; font-weight: 750;')
        about_text.addWidget(app_name)
        version = QLabel(f'{APP_VERSION}  ·  Python / PySide6  ·  MIT + MPL-2.0')
        version.setProperty('role', 'hint')
        about_text.addWidget(version)
        description = QLabel(t('home_subtitle'))
        description.setProperty('role', 'hint')
        description.setWordWrap(True)
        about_text.addWidget(description)
        about_row.addLayout(about_text, 1)
        source = QLabel('github.com/sendement/dualsense-haptics')
        source.setProperty('role', 'accentLabel')
        source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        about_row.addWidget(source, 0, Qt.AlignVCenter)
        about_layout.addLayout(about_row)
        outer.addWidget(about_card)
        outer.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self._refresh_connection)
        self.connection_timer.start(250)
        self._refresh_connection()

    def _refresh_connection(self):
        self.connection_indicator.set_connection(self.connection_getter())


class AppAudioRow(QFrame):
    """One selectable audio source with a separate live-routing status."""

    def __init__(self, name, button_group, checked, active, waiting, on_select, on_remove=None):
        super().__init__()
        self.name = name
        self.setObjectName("appAudioRow")
        self.setProperty("selected", checked)
        self.setProperty("active", active)
        self.setProperty("waiting", waiting)
        self.setMinimumHeight(82)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)
        icon = QLabel("◎" if on_remove is None else "♫")
        icon.setObjectName("appAudioIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(54, 54)
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(3)
        title_row = QHBoxLayout()
        title = QLabel(name)
        title.setProperty("role", "profileName")
        title_row.addWidget(title)
        if active:
            badge = QLabel("●  " + t("app_audio_active"))
            badge.setProperty("role", "audioActive")
            title_row.addWidget(badge)
        elif waiting:
            badge = QLabel(t("app_audio_waiting"))
            badge.setProperty("role", "audioWaiting")
            title_row.addWidget(badge)
        title_row.addStretch(1)
        text.addLayout(title_row)
        description = QLabel(
            t("app_audio_global_hint") if on_remove is None else t("app_audio_selected_hint"))
        description.setProperty("role", "hint")
        description.setWordWrap(True)
        text.addWidget(description)
        layout.addLayout(text, 1)

        self.radio = QRadioButton()
        self.radio.setChecked(checked)
        button_group.addButton(self.radio)
        self.radio.toggled.connect(lambda is_checked: on_select() if is_checked else None)
        layout.addWidget(self.radio)
        if on_remove is not None:
            remove = QPushButton("♲  " + t("btn_remove"))
            # clicked() carries a `checked` bool; passing on_remove straight
            # through let it overwrite the row's own `a=app` lambda default
            # (calling _remove_app(False)), so Remove silently did nothing.
            remove.clicked.connect(lambda _checked=False: on_remove())
            layout.addWidget(remove)


class AppAudioBindingPage(QWidget):
    """Desktop-only (see app_audio_binding.py): a list of apps the user has
    added, plus "Global" (always listed first, fixed) - all in one radio-
    button group, so at most one is ever selected and mixing multiple
    audio sources is never possible. While the selected app is playing
    sound, haptics narrow to just its audio; Global is in effect otherwise
    (nothing selected, or the selection isn't currently making sound).
    Purely narrows *which audio the engine listens to* - has no notion of
    presets/profiles at all, deliberately: this is its own page precisely
    so that concept never has to appear here."""

    _COMBO_REFRESH_MS = 2000

    def __init__(self, state, list_active_apps, on_toggle_enabled, on_change,
                 connection_getter=None, list_apps_snapshot=None):
        super().__init__()
        self.state = state
        self.list_active_apps = list_active_apps
        # Optional: () -> (picker names, every identity in play) from one
        # audio-server query; without it live status just uses the names.
        self.list_apps_snapshot = list_apps_snapshot
        self.on_change = on_change
        self.connection_getter = connection_getter or (lambda: None)
        self.live_apps = set()
        self._picker_apps = []
        self.app_rows = {}

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel(t("app_audio_binding_title"))
        title.setProperty("role", "h1")
        heading.addWidget(title)
        hint = QLabel(t("app_audio_binding_hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        heading.addWidget(hint)
        header.addLayout(heading, 1)
        self.connection_indicator = ConnectionIndicator()
        header.addWidget(self.connection_indicator, 0, Qt.AlignTop)
        outer.addLayout(header)

        workspace_widget = QWidget()
        self.workspace = QBoxLayout(QBoxLayout.Direction.LeftToRight, workspace_widget)
        self.workspace.setContentsMargins(0, 0, 0, 0)
        self.workspace.setSpacing(12)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        enable_card = QFrame()
        enable_card.setObjectName("audioToggleCard")
        enable_layout = QHBoxLayout(enable_card)
        enable_layout.setContentsMargins(16, 14, 16, 14)
        enable_icon = QLabel("♫")
        enable_icon.setObjectName("appAudioIcon")
        enable_icon.setAlignment(Qt.AlignCenter)
        enable_icon.setFixedSize(52, 52)
        enable_layout.addWidget(enable_icon)
        enable_text = QVBoxLayout()
        self.enable_check = QCheckBox(t("app_audio_binding_checkbox"))
        self.enable_check.setChecked(state.get("app_audio_binding_enabled", False))
        self.enable_check.toggled.connect(on_toggle_enabled)
        enable_text.addWidget(self.enable_check)
        enable_hint = QLabel(t("app_audio_focus_text"))
        enable_hint.setProperty("role", "hint")
        enable_hint.setWordWrap(True)
        enable_text.addWidget(enable_hint)
        enable_layout.addLayout(enable_text, 1)
        main_layout.addWidget(enable_card)

        add_card, add_layout = make_section_card(margins=(15, 12, 15, 14))
        add_title = QLabel(t("app_audio_add_title"))
        add_title.setProperty("role", "h2")
        add_layout.addWidget(add_title)
        add_row = QHBoxLayout()
        self.app_combo = QComboBox()
        # Editable, not just a picker over list_active_apps() - that list is
        # only ever whatever's making sound right now, so there'd otherwise
        # be no way to add an app that isn't currently playing anything
        # (e.g. a game not launched yet) at all.
        self.app_combo.setEditable(True)
        self.app_combo.lineEdit().setPlaceholderText(t("app_audio_binding_combo_placeholder"))
        add_btn = QPushButton(t("btn_add"))
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_app)
        add_row.addWidget(self.app_combo, 1)
        add_row.addWidget(add_btn)
        add_layout.addLayout(add_row)
        main_layout.addWidget(add_card)

        linked_card, linked_layout = make_section_card(margins=(15, 13, 15, 15))
        linked_header = QHBoxLayout()
        linked_title = QLabel(t("app_audio_linked_title"))
        linked_title.setProperty("role", "h2")
        linked_header.addWidget(linked_title)
        linked_header.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setProperty("role", "hint")
        linked_header.addWidget(self.count_label)
        linked_layout.addLayout(linked_header)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(9)
        linked_layout.addWidget(self.rows_widget)
        main_layout.addWidget(linked_card)
        main_layout.addStretch(1)
        self.workspace.addWidget(main, 3)

        info_card = QFrame()
        info_card.setObjectName("audioInfoCard")
        info_card.setMinimumWidth(300)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(17, 16, 17, 17)
        info_layout.setSpacing(13)
        info_title = QLabel("ⓘ  " + t("app_audio_how_title"))
        info_title.setProperty("role", "h2")
        info_layout.addWidget(info_title)
        for glyph, title_key, text_key in (
            ("◖", "app_audio_tracking_title", "app_audio_tracking_text"),
            ("⇄", "app_audio_switch_title", "app_audio_switch_text"),
            ("≋", "app_audio_focus_title", "app_audio_focus_text"),
        ):
            block = QHBoxLayout()
            block.setSpacing(12)
            icon = QLabel(glyph)
            icon.setObjectName("audioInfoIcon")
            icon.setAlignment(Qt.AlignCenter)
            icon.setFixedSize(54, 54)
            block.addWidget(icon, 0, Qt.AlignTop)
            copy_layout = QVBoxLayout()
            block_title = QLabel(t(title_key))
            block_title.setProperty("role", "h2")
            copy_layout.addWidget(block_title)
            block_text = QLabel(t(text_key))
            block_text.setProperty("role", "hint")
            block_text.setWordWrap(True)
            copy_layout.addWidget(block_text)
            block.addLayout(copy_layout, 1)
            info_layout.addLayout(block)
        info_layout.addStretch(1)
        self.workspace.addWidget(info_card, 2)
        outer.addWidget(workspace_widget)
        outer.addStretch(1)
        self.scroll.setWidget(content)
        page_layout.addWidget(self.scroll)

        # No manual "refresh" button - the add-picker's own list of
        # currently-playing apps keeps itself current on a timer instead.
        self._combo_refresh_timer = QTimer(self)
        self._combo_refresh_timer.timeout.connect(self._refresh_app_combo)
        self._combo_refresh_timer.start(self._COMBO_REFRESH_MS)

        self._refresh_app_combo()
        self.refresh()

    def resizeEvent(self, event):
        set_responsive_direction(event.size().width(), self.workspace)
        super().resizeEvent(event)

    def refresh(self):
        self.enable_check.blockSignals(True)
        self.enable_check.setChecked(self.state.get("app_audio_binding_enabled", False))
        self.enable_check.blockSignals(False)
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        apps = self.state.get("app_audio_binding_apps", [])
        selected = self.state.get("app_audio_binding_selected")
        enabled = self.state.get("app_audio_binding_enabled", False)
        actual_app = selected if enabled and selected in self.live_apps else None

        # One exclusive group per refresh (old radio buttons are being
        # thrown away above) - Global is a real member of it, not just a
        # fixed label, so picking it is how you clear the selection back to
        # "nothing bound" rather than needing a separate action for that.
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self.app_rows = {}
        global_row = self._make_row(
            t("target_global_option"), checked=(selected is None), active=enabled and actual_app is None,
            waiting=False, on_select=lambda: self._set_selected(None), on_remove=None)
        self.rows_layout.addWidget(global_row)
        self.app_rows[None] = global_row

        for app in sorted(apps):
            row = self._make_row(
                app, checked=(selected == app), active=(actual_app == app),
                waiting=(enabled and selected == app and actual_app != app),
                on_select=lambda a=app: self._set_selected(a),
                on_remove=lambda a=app: self._remove_app(a))
            self.rows_layout.addWidget(row)
            self.app_rows[app] = row
        self.rows_layout.addStretch(1)
        self.count_label.setText(str(len(apps)))
        self.connection_indicator.set_connection(self.connection_getter())

    def _make_row(self, label_text, checked, active, waiting, on_select, on_remove):
        return AppAudioRow(
            label_text, self._button_group, checked, active, waiting, on_select, on_remove)

    def _refresh_app_combo(self):
        if self.list_apps_snapshot is not None:
            live_apps, identities = self.list_apps_snapshot()
            live_apps = list(live_apps)
            identities = set(identities) | set(live_apps)
        else:
            live_apps = list(self.list_active_apps())
            identities = set(live_apps)
        if identities == self.live_apps and live_apps == self._picker_apps:
            # Nothing changed: rebuilding the rows every tick would delete
            # the very button being clicked (press and release landing on
            # different widgets) and collapse an open dropdown.
            return
        current_text = self.app_combo.currentText()
        self.live_apps = identities
        self._picker_apps = live_apps
        self.app_combo.clear()
        self.app_combo.addItems(live_apps)
        self.app_combo.setCurrentText(current_text)
        if self.app_rows:
            self.refresh()

    def _add_app(self):
        app = self.app_combo.currentText().strip()
        if not app:
            return
        apps = self.state.setdefault("app_audio_binding_apps", [])
        if app not in apps:
            apps.append(app)
            self.on_change()
            self.refresh()
        self.app_combo.setCurrentText("")

    def _set_selected(self, app):
        self.state["app_audio_binding_selected"] = app
        self.on_change()

    def _remove_app(self, app):
        apps = self.state.setdefault("app_audio_binding_apps", [])
        if app in apps:
            apps.remove(app)
            if self.state.get("app_audio_binding_selected") == app:
                self.state["app_audio_binding_selected"] = None
            self.on_change()
            self.refresh()


# ---------------------------------------------------------------- main window


class TitleBatteryIcon(QWidget):
    """Small theme-aware battery pictogram for the custom title bar."""

    def __init__(self):
        super().__init__()
        self._value = None
        self.setFixedSize(27, 16)

    def set_text(self, text):
        match = re.search(r"(\d{1,3})\s*%", text)
        self.set_value(int(match.group(1)) if match else None)

    def set_value(self, value):
        value = max(0, min(100, int(value))) if value is not None else None
        if value != self._value:
            self._value = value
            self.update()

    def paintEvent(self, event):
        pal = theme.manager.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QRectF(1, 2, 22, 12)
        painter.setPen(QPen(QColor(pal["accent_hover"]), 1.4))
        painter.setBrush(QColor(pal["hero_end"]))
        painter.drawRoundedRect(body, 2.5, 2.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pal["accent_hover"]))
        painter.drawRoundedRect(QRectF(24, 5, 2, 6), 1, 1)
        if self._value is not None:
            fill = body.adjusted(2.5, 2.5, -2.5, -2.5)
            fill.setWidth(fill.width() * self._value / 100)
            painter.setBrush(QColor(pal["good"] if self._value > 20 else pal["bad"]))
            painter.drawRoundedRect(fill, 1.5, 1.5)
        painter.end()


class WindowTitleBar(QFrame):
    """Frameless-window chrome with live controller and battery status."""

    settings_requested = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.host_window = window
        self.setObjectName("windowTitleBar")
        self.setFixedHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(10)

        self.brand_group = QWidget()
        brand_layout = QHBoxLayout(self.brand_group)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(9)
        self.brand_icon = QLabel()
        self.brand_icon.setObjectName("titleBrandIcon")
        self.brand_icon.setFixedSize(34, 34)
        self.brand_icon.setAlignment(Qt.AlignCenter)
        brand_layout.addWidget(self.brand_icon)
        brand = QLabel("DualSense Haptics")
        brand.setObjectName("titleBrandText")
        brand_layout.addWidget(brand)
        self.version_badge = QLabel(APP_VERSION)
        self.version_badge.setObjectName("titleVersionBadge")
        brand_layout.addWidget(self.version_badge)
        layout.addWidget(self.brand_group)
        layout.addStretch(1)

        self.center_title = QLabel("DualSense Haptics", self)
        self.center_title.setObjectName("titleCenterText")
        self.center_title.setAlignment(Qt.AlignCenter)
        self.center_title.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addStretch(1)

        self.device_pill = QFrame()
        self.device_pill.setObjectName("titleDevicePill")
        self.device_pill.setProperty("connected", False)
        device_layout = QHBoxLayout(self.device_pill)
        device_layout.setContentsMargins(11, 5, 11, 5)
        device_layout.setSpacing(7)
        self.controller_icon = QLabel()
        self.controller_icon.setObjectName("titleControllerIcon")
        self.controller_icon.setFixedSize(24, 24)
        self.controller_icon.setAlignment(Qt.AlignCenter)
        device_layout.addWidget(self.controller_icon)
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("titleStatusDot")
        device_layout.addWidget(self.status_dot)
        self.status_label = QLabel(t("status_searching"))
        self.status_label.setObjectName("titleStatusText")
        self.status_label.setMaximumWidth(150)
        device_layout.addWidget(self.status_label)
        divider = QFrame()
        divider.setObjectName("titleDivider")
        divider.setFrameShape(QFrame.VLine)
        device_layout.addWidget(divider)
        self.battery_icon = TitleBatteryIcon()
        self.battery_icon.setObjectName("titleBatteryIcon")
        device_layout.addWidget(self.battery_icon)
        self.battery_label = QLabel("—")
        self.battery_label.setObjectName("titleBatteryText")
        device_layout.addWidget(self.battery_label)
        layout.addWidget(self.device_pill)

        self.settings_btn = self._window_button("⚙", "titleSettingsButton")
        self.settings_btn.clicked.connect(self.settings_requested)
        layout.addWidget(self.settings_btn)
        window_divider = QFrame()
        window_divider.setObjectName("titleDivider")
        window_divider.setFrameShape(QFrame.VLine)
        layout.addWidget(window_divider)
        self.minimize_btn = self._window_button("−", "titleWindowButton")
        self.minimize_btn.clicked.connect(window.showMinimized)
        layout.addWidget(self.minimize_btn)
        self.maximize_btn = self._window_button("□", "titleWindowButton")
        self.maximize_btn.clicked.connect(self._toggle_maximized)
        layout.addWidget(self.maximize_btn)
        self.close_btn = self._window_button("×", "titleCloseButton")
        self.close_btn.clicked.connect(window.close)
        layout.addWidget(self.close_btn)
        self.refresh_theme()

    @staticmethod
    def _window_button(text, object_name):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedSize(38, 38)
        return button

    def refresh_theme(self):
        self.brand_icon.setPixmap(render_emoji_icon("🎮").pixmap(28, 28))
        self.controller_icon.setPixmap(render_emoji_icon("🎮").pixmap(22, 22))
        self.battery_icon.update()

    def set_status(self, text, connected=False):
        self.status_label.setText(text)
        self.status_label.setToolTip(text)
        self.device_pill.setProperty("connected", bool(connected))
        self.device_pill.style().unpolish(self.device_pill)
        self.device_pill.style().polish(self.device_pill)

    def set_battery(self, text, percent=None):
        if percent is None:
            match = re.search(r"(\d{1,3})\s*%", text)
            percent = int(match.group(1)) if match else None
        self.battery_label.setText(f"{percent}%" if percent is not None else "—")
        self.battery_label.setToolTip(text)
        self.battery_icon.set_value(percent)

    def set_compact(self, width):
        self.center_title.setVisible(width >= 1180)
        self.version_badge.setVisible(width >= 1030)
        self._position_center_title()

    def _position_center_title(self):
        self.center_title.adjustSize()
        size = self.center_title.sizeHint()
        self.center_title.setGeometry(
            (self.width() - size.width()) // 2,
            (self.height() - size.height()) // 2,
            size.width(), size.height())

    def resizeEvent(self, event):
        self._position_center_title()
        super().resizeEvent(event)

    def update_window_state(self):
        self.maximize_btn.setText("❐" if self.host_window.isMaximized() else "□")

    def _toggle_maximized(self):
        if self.host_window.isMaximized():
            self.host_window.showNormal()
        else:
            self.host_window.showMaximized()
        self.update_window_state()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.host_window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)


# One source of truth for the 8 frameless-window resize edges: each handle's
# own `edges` bitmask also drives its geometry formula in
# MainWindow._position_resize_handles, instead of a second parallel dict.
RESIZE_EDGE_SPECS = {
    "top": (Qt.TopEdge, Qt.SizeVerCursor),
    "bottom": (Qt.BottomEdge, Qt.SizeVerCursor),
    "left": (Qt.LeftEdge, Qt.SizeHorCursor),
    "right": (Qt.RightEdge, Qt.SizeHorCursor),
    "top_left": (Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor),
    "top_right": (Qt.TopEdge | Qt.RightEdge, Qt.SizeBDiagCursor),
    "bottom_left": (Qt.BottomEdge | Qt.LeftEdge, Qt.SizeBDiagCursor),
    "bottom_right": (Qt.BottomEdge | Qt.RightEdge, Qt.SizeFDiagCursor),
}


class WindowResizeHandle(QWidget):
    """Invisible native resize edge retained after removing system chrome."""

    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.host_window = window
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        handle = self.host_window.windowHandle()
        if event.button() == Qt.LeftButton and handle is not None:
            if handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class MainWindow(QWidget):
    def __init__(self, state, engine_holder, start_engine_cb, stop_engine_cb, save_cb,
                 capture_source_box=None):
        super().__init__()
        self.state = state
        self.engine_holder = engine_holder
        self.start_engine_cb = start_engine_cb
        self.stop_engine_cb = stop_engine_cb
        self.save_cb = save_cb
        self.enabled = True
        self._current_page_key = "home"
        self._managed_page_timers = {}
        # Desktop-only per-app audio binding (see app_audio_binding.py) -
        # optional so this class stays constructible without the feature
        # wired in (e.g. in a future headless/test context).
        self.capture_source_box = capture_source_box if capture_source_box is not None else {}

        self.setObjectName("appWindow")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowTitle("DualSense Haptics")
        self._apply_window_icon()
        self.resize(1280, 900)
        self.setMinimumSize(920, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = WindowTitleBar(self)
        self.title_bar.settings_requested.connect(lambda: self.show_page("settings"))
        root.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("windowBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root.addWidget(body, 1)

        self._sidebar_collapsed = self.state.get("sidebar_collapsed", False)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(14, 22, 14, 20)
        sb_layout.setSpacing(5)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.sidebar_toggle_btn = QPushButton()
        self.sidebar_toggle_btn.setObjectName("sidebarToggle")
        self.sidebar_toggle_btn.setIconSize(QSize(30, 30))
        self.sidebar_toggle_btn.setFixedSize(44, 44)
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar_collapsed)
        self._apply_sidebar_toggle_icon()
        top_row.addWidget(self.sidebar_toggle_btn)
        self.brand_text = QLabel()
        self.brand_text.setStyleSheet("font-size: 14px; font-weight: 800;")
        top_row.addWidget(self.brand_text, 1)
        sb_layout.addLayout(top_row)
        sb_layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, _label_key, icon_char in NAV_ITEMS:
            btn = QPushButton()
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.setIcon(render_emoji_icon(icon_char))
            btn.setIconSize(QSize(ICON_SIZE_BASE["navItem"], ICON_SIZE_BASE["navItem"]))
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            sb_layout.addWidget(btn)
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
        sb_layout.addStretch(1)

        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        body_layout.addWidget(self.stack, 1)

        self._build_pages()
        self._retranslate_sidebar()
        self.sidebar.setFixedWidth(74 if self._sidebar_collapsed else 250)
        self.show_page("home")

        theme.manager.changed.connect(self._on_theme_changed)
        i18n.manager.changed.connect(self._on_language_changed)
        self._resize_handles = {
            name: WindowResizeHandle(self, edges, cursor)
            for name, (edges, cursor) in RESIZE_EDGE_SPECS.items()
        }
        self._position_resize_handles()

    def resizeEvent(self, event):
        if hasattr(self, "title_bar"):
            self.title_bar.set_compact(event.size().width())
        if hasattr(self, "_resize_handles"):
            self._position_resize_handles()
        super().resizeEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.update_window_state()
            if hasattr(self, "_resize_handles"):
                self._position_resize_handles()
            if hasattr(self, "_managed_page_timers"):
                QTimer.singleShot(0, self._update_page_activity)
        super().changeEvent(event)

    def _position_resize_handles(self):
        """Derive each handle's rectangle from its own edges bitmask, so the
        edge list (RESIZE_EDGE_SPECS) stays the only place naming the 8
        handles - no second dict of geometries to keep in sync with it."""
        edge, corner = 6, 10
        width, height = self.width(), self.height()
        visible = not self.isMaximized()
        for handle in self._resize_handles.values():
            top = bool(handle.edges & Qt.TopEdge)
            left = bool(handle.edges & Qt.LeftEdge)
            vertical_only = bool(handle.edges & (Qt.TopEdge | Qt.BottomEdge)) and \
                not (handle.edges & (Qt.LeftEdge | Qt.RightEdge))
            horizontal_only = bool(handle.edges & (Qt.LeftEdge | Qt.RightEdge)) and \
                not (handle.edges & (Qt.TopEdge | Qt.BottomEdge))
            if vertical_only:
                geometry = (corner, 0 if top else height - edge, max(0, width - 2 * corner), edge)
            elif horizontal_only:
                geometry = (0 if left else width - edge, corner, edge, max(0, height - 2 * corner))
            else:
                geometry = (0 if left else width - corner, 0 if top else height - corner, corner, corner)
            handle.setGeometry(*geometry)
            handle.setVisible(visible)

    def _build_pages(self):
        self.home_page = HomePage(
            self.state, self.engine_holder, self._toggle, self._quick_trigger,
            self._on_controller_skin_change)
        self.presets_page = PresetsPage(
            self.state, self._apply_preset,
            lambda: self.home_page.connection_indicator.kind)
        self.profiles_page = ProfilesPage(
            self.state, self._apply_profile, self._on_state_changed,
            lambda: self.home_page.connection_indicator.kind)
        self.app_audio_binding_page = AppAudioBindingPage(
            self.state, app_audio_binding.list_active_app_names,
            self._set_app_audio_binding_enabled, self._on_state_changed,
            lambda: self.home_page.connection_indicator.kind,
            list_apps_snapshot=app_audio_binding.list_active_apps_snapshot)
        self.triggers_page = TriggersPage(
            self.state, self._apply_trigger_preset, self._turn_off_triggers, self._apply_custom_trigger,
            lambda: self.home_page.connection_indicator.kind,
            lambda: self.home_page.lightbar_rgb,
            self.engine_holder)
        self.button_haptic_page = ButtonHapticPage(
            self.state, self.save_cb, self.engine_holder,
            lambda: self.home_page.connection_indicator.kind,
            lambda: self.home_page.lightbar_rgb)
        self.advanced_page = AdvancedPage(
            self.state, self._on_advanced_change,
            None,
            lambda: self.home_page.connection_indicator.kind,
            lambda: self.home_page.lightbar_rgb,
            self.engine_holder)
        self.led_page = LedPage(
            self.state, self._on_advanced_change, self.engine_holder,
            lambda: self.home_page.connection_indicator.kind)
        self.experimental_page = ExperimentalPage(self.state, self._on_advanced_change)
        self.settings_page = SettingsPage(
            self.state, self._on_theme_pref_change, self._on_language_pref_change,
            lambda: self.home_page.connection_indicator.kind)

        self.pages = {
            "home": self.home_page,
            "presets": self.presets_page,
            "profiles": self.profiles_page,
            "app_audio": self.app_audio_binding_page,
            "triggers": self.triggers_page,
            "button_haptic": self.button_haptic_page,
            "advanced": self.advanced_page,
            "led": self.led_page,
            "experimental": self.experimental_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self._managed_page_timers = {
            key: [(timer, timer.interval()) for timer in page.findChildren(QTimer)
                  if timer.isActive()]
            for key, page in self.pages.items()
        }
        self.home_page.set_enabled_text(self.enabled)

    def _retranslate_sidebar(self):
        collapsed = self._sidebar_collapsed
        for key, label_key, _icon in NAV_ITEMS:
            label = t(label_key)
            btn = self.nav_buttons[key]
            btn.setText("" if collapsed else label)
            btn.setToolTip(label)
            btn.setProperty('collapsed', collapsed)
            btn.setFixedHeight(54 if collapsed else 44)
            btn.setStyleSheet('padding: 4px; text-align: center;' if collapsed else '')
            settle_icon_size(btn)
        self.brand_text.setText("DualSense Haptics")
        self.brand_text.setVisible(not collapsed)
        self.sidebar_toggle_btn.setToolTip(
            t("sidebar_expand_tooltip") if collapsed else t("sidebar_collapse_tooltip"))

    def _toggle_sidebar_collapsed(self):
        self._sidebar_collapsed = not self._sidebar_collapsed
        self.sidebar.setFixedWidth(74 if self._sidebar_collapsed else 250)
        self._retranslate_sidebar()
        self.state["sidebar_collapsed"] = self._sidebar_collapsed
        self.save_cb()

    def _apply_window_icon(self):
        self.setWindowIcon(make_app_icon(theme.manager.palette))

    def set_status_text(self, text, connected=False):
        self.home_page.set_status_text(text)
        self.title_bar.set_status(text, connected)

    def set_battery_text(self, text, percent=None):
        if percent is None:
            match = re.search(r"(\d{1,3})\s*%", text)
            percent = int(match.group(1)) if match else None
        self.home_page.set_battery_text(text, percent)
        self.title_bar.set_battery(text, percent)

    def _quick_trigger(self, preset_id, side):
        if preset_id is None:
            self._turn_off_triggers(side)
            return
        self._apply_trigger_preset(
            preset_id, side,
            overrides=self.state.get(f'trigger_preset_params_{side}', {}).get(preset_id),
            snap_click=self.state.get(f'trigger_snap_click_{side}', {}).get(preset_id),
            click_strength=self.state.get(f'trigger_snap_click_strength_{side}', {}).get(preset_id))

    def _apply_sidebar_toggle_icon(self):
        self.sidebar_toggle_btn.setIcon(draw_sidebar_toggle_icon(theme.manager.palette["fg_dim"]))

    def show_page(self, key):
        self._current_page_key = key
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        for btn in self.nav_buttons.values():
            settle_icon_size(btn)
        self._update_page_activity()

    def _update_page_activity(self):
        """Run only the timers belonging to the visible page.

        Qt timers continue firing for widgets hidden in a QStackedWidget, so
        relying on widget visibility alone wastes CPU and also kept engine
        telemetry enabled after the visual pages were left.
        """
        window_active = self.isVisible() and not self.isMinimized()
        for key, timers in self._managed_page_timers.items():
            active = window_active and key == self._current_page_key
            for timer, interval in timers:
                if active and not timer.isActive():
                    timer.start(interval)
                elif not active and timer.isActive():
                    timer.stop()
        engine = self.engine_holder()
        if engine is not None:
            engine.visual_feedback_enabled = bool(
                window_active and self._current_page_key in {
                    "home", "triggers", "button_haptic", "advanced", "led"})

    def showEvent(self, event):
        super().showEvent(event)
        self._update_page_activity()

    def hideEvent(self, event):
        for timers in self._managed_page_timers.values():
            for timer, _interval in timers:
                timer.stop()
        engine = self.engine_holder()
        if engine is not None:
            engine.visual_feedback_enabled = False
        super().hideEvent(event)

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

    def _set_app_audio_binding_enabled(self, checked):
        self.state["app_audio_binding_enabled"] = checked
        if checked:
            app_audio_binding.start_watching(self.state, self.capture_source_box)
        else:
            app_audio_binding.stop_watching()
            app_audio_binding.clear_narrowing(self.capture_source_box)
        self._on_state_changed()

    def _apply_trigger_preset(self, preset_id, side, overrides=None, snap_click=None, click_strength=None, silent=False):
        preset = TRIGGER_PRESETS[preset_id]
        values = dict(preset["values"])
        if overrides:
            values.update(overrides)
        ok, err = triggers.apply_custom_trigger(preset["mode"], values, side)
        if not ok:
            if not silent:
                QMessageBox.warning(self, t("trigger_apply_fail_title"), err)
            return
        self.state[f"trigger_preset_{side}"] = preset_id
        if overrides:
            self.state.setdefault(f"trigger_preset_params_{side}", {})[preset_id] = overrides
        if preset_id in TRIGGER_PRESET_SNAP_CLICK:
            click_on = TRIGGER_PRESET_SNAP_CLICK[preset_id] if snap_click is None else snap_click
            self.state.setdefault(f"trigger_snap_click_{side}", {})[preset_id] = click_on
            strength = 8 if click_strength is None else click_strength
            self.state.setdefault(f"trigger_snap_click_strength_{side}", {})[preset_id] = strength
            if click_on:
                # Everything from "end" through fully pressed (9), not just
                # the single "end" zone - past the snap the trigger keeps
                # travelling (and, freshly released from resistance, can
                # overshoot/bounce a little), so a single-zone wall lets it
                # drift back out and re-arm while still held down. Bow's
                # snap sits well before full travel (zone 7 of 9) so that
                # extra room is much more reachable than Hard Stop's
                # (zone 8), which is why this only showed up on Bow.
                triggers.start_snap_click(side, preset["mode"], values, set(range(values["end"], 10)),
                                           click_amplitude=strength)
            else:
                triggers.stop_snap_click(side)
        else:
            triggers.stop_snap_click(side)
        self._on_state_changed()

    def _turn_off_triggers(self, side):
        triggers.stop_snap_click(side)
        ok, err = triggers.turn_off_triggers(side)
        if ok:
            self.state[f"trigger_preset_{side}"] = None
            self._on_state_changed()
        else:
            QMessageBox.warning(self, t("trigger_off_fail_title"), err)

    def _apply_custom_trigger(self, mode, values, side, wall_click=False, silent=False):
        ok, err = triggers.apply_custom_trigger(mode, values, side)
        if ok:
            self.state[f"trigger_preset_{side}"] = "custom"
            self.state[f"trigger_custom_{side}"] = {"mode": mode, "values": values}
            if mode == "feedback_raw":
                self.state[f"trigger_custom_snap_click_{side}"] = bool(wall_click)
                if wall_click:
                    triggers.start_snap_click(side, mode, values, wall_zones_from_feedback_raw(values))
                else:
                    triggers.stop_snap_click(side)
            else:
                triggers.stop_snap_click(side)
            self._on_state_changed()
        elif not silent:
            QMessageBox.warning(self, t("trigger_apply_fail_title"), err)

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
        self._reapply_side(left, "left")
        self._reapply_side(right, "right")

    def _reapply_side(self, preset_id, side):
        if not preset_id:
            return
        if preset_id == "custom":
            custom = self.state.get(f"trigger_custom_{side}")
            if custom:
                wall_click = self.state.get(f"trigger_custom_snap_click_{side}", False)
                self._apply_custom_trigger(custom["mode"], custom["values"], side, wall_click=wall_click, silent=True)
        else:
            overrides = self.state.get(f"trigger_preset_params_{side}", {}).get(preset_id)
            snap_click = self.state.get(f"trigger_snap_click_{side}", {}).get(preset_id)
            click_strength = self.state.get(f"trigger_snap_click_strength_{side}", {}).get(preset_id)
            self._apply_trigger_preset(preset_id, side, overrides=overrides, snap_click=snap_click,
                                        click_strength=click_strength, silent=True)

    def _on_advanced_change(self):
        self.state["active_ref"] = "custom"
        self._on_state_changed()

    def _on_controller_skin_change(self):
        """Apply the visual finish to every existing controller preview."""
        skin = self.state.get('controller_skin', 'white')
        for gamepad in self.findChildren(GamepadWidget):
            gamepad.set_skin(skin)
        self.advanced_page.controller_outline.set_skin(skin)
        self.save_cb()

    def _on_state_changed(self):
        self.save_cb()
        self.home_page.refresh_active()
        self.presets_page.refresh()
        self.profiles_page.refresh()
        self.app_audio_binding_page.refresh()
        self.triggers_page.refresh()
        self.advanced_page.refresh()
        self.led_page.refresh()
        self.experimental_page.refresh()

    def _toggle(self):
        if self.enabled:
            self.stop_engine_cb()
            self.enabled = False
        else:
            self.start_engine_cb()
            self.enabled = True
        self._update_page_activity()
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
        self.title_bar.refresh_theme()
        self._apply_sidebar_toggle_icon()
        for key, _label_key, icon_char in NAV_ITEMS:
            self.nav_buttons[key].setIcon(render_emoji_icon(icon_char))
        for indicator in self.findChildren(ConnectionIndicator):
            indicator.set_connection(indicator.kind, force=True)
        self.home_page.gamepad.update()
        if hasattr(self, "on_theme_applied"):
            self.on_theme_applied()

    def _on_language_changed(self):
        key = self._current_page_key
        for timers in self._managed_page_timers.values():
            for timer, _interval in timers:
                timer.stop()
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
        if self._status_kind == "overridden":
            return t("status_overridden")
        if self._status_kind == "proxied":
            return t("status_proxied")
        if self._status_kind == "bt_proxy_unavailable":
            return t("status_bt_proxy_unavailable")
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
        status_text = self._status_display_text()
        battery_text = self._battery_display_text()
        self.status_action.setText(status_text)
        self.battery_action.setText(battery_text)
        self.main_window.set_status_text(
            status_text, not self._disabled and self._status_kind in ("connected", "proxied"))
        self.main_window.set_battery_text(battery_text, self._battery_percent)
        self.toggle_action.setText(t("tray_disable_vibration") if not self._disabled else t("tray_enable_vibration"))
        self.open_action.setText(t("tray_open"))
        self.quit_action.setText(t("tray_quit"))
        self._update_tooltip()

    def _on_toggle(self, enabled):
        self._disabled = not enabled
        self.toggle_action.setText(t("tray_disable_vibration") if enabled else t("tray_enable_vibration"))
        self._icon_status = "off" if not enabled else {
            "connected": "ok", "searching": "searching", "overridden": "searching",
            "proxied": "ok", "bt_proxy_unavailable": "error", "error": "error",
        }.get(self._status_kind, "searching")
        self._refresh_icon()
        self.status_action.setText(self._status_display_text())
        self.main_window.set_status_text(
            self._status_display_text(), enabled and self._status_kind in ("connected", "proxied"))
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
        elif status == "overridden":
            self._status_kind = "overridden"
        elif status == "proxied":
            self._status_kind = "proxied"
        elif status == "bt_proxy_unavailable":
            self._status_kind = "bt_proxy_unavailable"
        else:
            self._status_kind = "error"
            self._error_msg = status[len("error: "):] if status.startswith("error: ") else status

        if not self._disabled:
            self._icon_status = {
                "connected": "ok", "searching": "searching", "overridden": "searching",
                "proxied": "ok", "bt_proxy_unavailable": "error", "error": "error",
            }[self._status_kind]
            self._refresh_icon()

        text = self._status_display_text()
        self.status_action.setText(text)
        self.main_window.set_status_text(
            text, status in ("connected", "proxied"))
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
            self.main_window.set_battery_text(t("battery_unknown"), None)
            return
        self.battery_action.setText(self._battery_display_text())
        self.main_window.set_battery_text(
            f"{percent}% · {self._battery_status_localized()}", percent)

    def _quit(self):
        self.stop_engine_cb()
        self.app.quit()
