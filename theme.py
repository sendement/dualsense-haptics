"""Color palettes (dark/light) and QSS generation, with live system-theme
tracking so "System" follows the desktop's color scheme without a restart."""
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QGuiApplication

DARK = {
    "accent": "#5fb2ff",
    "accent_hover": "#78bfff",
    "accent_ink": "#08131f",
    "bg": "#14161c",
    "bg_card": "#1c1f28",
    "bg_sidebar": "#0f1116",
    "fg": "#e7e9ee",
    "fg_dim": "#8a8f9c",
    "good": "#57d68d",
    "warn": "#f2c94c",
    "bad": "#f2555a",
    "border": "#2a2e3a",
    "pressed": "#262a35",
}

LIGHT = {
    "accent": "#2e7dd6",
    "accent_hover": "#4a97e8",
    "accent_ink": "#ffffff",
    "bg": "#f4f5f8",
    "bg_card": "#ffffff",
    "bg_sidebar": "#e9ebf0",
    "fg": "#1b1d24",
    "fg_dim": "#666b7a",
    "good": "#1e9e5a",
    "warn": "#a3730a",
    "bad": "#c8373d",
    "border": "#d7dae1",
    "pressed": "#e4e6ec",
}

PALETTES = {"dark": DARK, "light": LIGHT}


def system_theme():
    """Best-effort read of the desktop color scheme (Qt >= 6.5). Falls back
    to dark, which matches this app's original look, if unavailable."""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return "light"
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
    except Exception:
        pass
    return "dark"


def resolve(preference):
    if preference == "system":
        return system_theme()
    return preference if preference in PALETTES else "dark"


def build_stylesheet(p):
    return f"""
QWidget {{ background: {p['bg']}; color: {p['fg']}; font-size: 13px; }}
QGroupBox {{
    background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 10px;
    margin-top: 14px; padding: 12px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p['accent']}; }}
QLabel[role="hint"] {{ color: {p['fg_dim']}; font-size: 11px; }}
QLabel[role="value"] {{ color: {p['accent']}; font-weight: 600; min-width: 42px; }}
QLabel[role="h1"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 14px; font-weight: 600; color: {p['fg_dim']}; }}
QSlider::groove:horizontal {{ height: 5px; background: {p['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {p['accent']}; width: 15px; height: 15px; margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {p['accent_hover']}; }}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
QProgressBar {{ background: {p['border']}; border-radius: 4px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 4px; }}
QCheckBox {{ spacing: 8px; }}
QComboBox {{
    background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 30px 6px 10px;
}}
QComboBox:hover {{ border-color: {p['accent']}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right; width: 24px;
    border: none; background: transparent;
}}
QComboBox::down-arrow {{
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {p['fg_dim']};
    margin-right: 10px;
}}
QComboBox::down-arrow:on {{ border-top-color: {p['accent']}; }}
QComboBox QAbstractItemView {{
    background: {p['bg_card']}; color: {p['fg']}; border: 1px solid {p['border']};
    selection-background-color: {p['accent']}; selection-color: {p['accent_ink']};
}}
QPushButton {{
    background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 8px 16px;
}}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton#danger:hover {{ border-color: {p['bad']}; }}
QPushButton#primary {{ background: {p['accent']}; color: {p['accent_ink']}; border: none; font-weight: 700; }}
QPushButton#primary:hover {{ background: {p['accent_hover']}; }}
QPushButton#primary:pressed {{ background: {p['accent']}; }}
QPushButton#navItem {{
    background: transparent; border: none; border-radius: 8px; text-align: left;
    padding: 10px 14px; font-size: 13px; color: {p['fg_dim']};
}}
QPushButton#navItem:checked {{ background: {p['bg_card']}; color: {p['fg']}; font-weight: 600; }}
QPushButton#navItem:hover {{ color: {p['fg']}; }}
QPushButton#sidebarToggle {{
    background: transparent; border: none; border-radius: 8px;
    padding: 10px 14px; font-size: 13px; color: {p['fg_dim']};
}}
QPushButton#sidebarToggle:hover {{ color: {p['fg']}; background: {p['bg_card']}; }}
QFrame#card {{ background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#cardActive {{ background: {p['bg_card']}; border: 1px solid {p['accent']}; border-radius: 12px; }}
QListWidget {{ background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {p['border']}; color: {p['fg']}; }}
QLineEdit {{ background: {p['bg_card']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


class ThemeManager(QObject):
    """Owns the resolved palette and notifies listeners (`changed`) whenever
    it changes - either the user picked a different preference, or the
    preference is "system" and the desktop's own scheme changed."""

    changed = Signal()

    def __init__(self, preference="system"):
        super().__init__()
        self.preference = preference
        self.name = resolve(preference)
        self.palette = PALETTES[self.name]
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_change)
        except Exception:
            pass

    def _on_system_change(self, *_args):
        if self.preference == "system":
            self._recompute()

    def set_preference(self, preference):
        if preference == self.preference:
            return
        self.preference = preference
        self._recompute()

    def _recompute(self):
        self.name = resolve(self.preference)
        self.palette = PALETTES[self.name]
        self.changed.emit()

    def stylesheet(self):
        return build_stylesheet(self.palette)


manager = ThemeManager()
