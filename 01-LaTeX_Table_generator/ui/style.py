"""Fonts, colour themes and the application style sheet."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Pane(QFrame):
    """Rounded card with a title bar; ``header`` and ``body`` are layouts to fill."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Pane")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("PaneHeader")
        bar.setAttribute(Qt.WA_StyledBackground)
        self.header = QHBoxLayout(bar)
        self.header.setContentsMargins(12, 7, 8, 7)
        self.header.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("PaneTitle")
        self.header.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PaneSubtitle")
        self.header.addWidget(self.subtitle)
        self.header.addStretch(1)
        outer.addWidget(bar)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        outer.addWidget(body, 1)


def resource_path(relative: str) -> Path:
    """Path to a bundled resource, working both from source and PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
_PREVIEW_FAMILIES = ["LM Roman 10", "Latin Modern Roman", "CMU Serif",
                     "Computer Modern Serif", "Times New Roman", "Liberation Serif",
                     "Nimbus Roman", "DejaVu Serif", "Georgia", "Noto Serif"]
_CODE_FAMILIES = ["JetBrains Mono", "Cascadia Code", "SF Mono", "Menlo", "Consolas",
                  "Fira Code", "Source Code Pro", "DejaVu Sans Mono", "Liberation Mono",
                  "Courier New"]
_preview_family: str | None = None


def load_bundled_fonts() -> None:
    """Register the bundled Latin Modern fonts (if present) with Qt."""
    folder = resource_path("assets/fonts")
    if folder.is_dir():
        for f in sorted(folder.glob("*.otf")) + sorted(folder.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(f))


def _first_available(candidates: list[str]) -> str | None:
    available = {f.lower(): f for f in QFontDatabase.families()}
    for name in candidates:
        if name.lower() in available:
            return available[name.lower()]
    return None


def preview_font_family() -> str:
    """Serif family used by the rendered preview (LaTeX look-alike)."""
    global _preview_family
    if _preview_family is None:
        _preview_family = _first_available(_PREVIEW_FAMILIES) or "serif"
    return _preview_family


def code_font(point_size: float = 10.5) -> QFont:
    family = _first_available(_CODE_FAMILIES)
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setStyleHint(QFont.Monospace)
    font.setPointSizeF(point_size)
    return font


# --------------------------------------------------------------------------- #
# Themes
# --------------------------------------------------------------------------- #
THEMES: dict[str, dict[str, str]] = {
    "light": dict(
        window="#f4f5f7", panel="#ffffff", header="#fafbfc", border="#dfe2e7",
        text="#1d2129", muted="#6b7280", accent="#3554d1", accent_hover="#2a45b3",
        accent_text="#ffffff", accent_soft="#e8edfc", input="#ffffff",
        selection="#cdd8fb", canvas="#e4e6ea", warn_bg="#fff4e0", warn_text="#8a5300",
        error_bg="#fdecec", error_text="#a32020", ok_text="#13795b",
        code_bg="#fbfbfd", code_text="#24292f", gutter="#9aa1ab", gutter_bg="#f3f4f6",
        hl_command="#7239c9", hl_env="#0b7a6e", hl_brace="#8a94a3", hl_comment="#8b949e",
        hl_amp="#d1590c", hl_newline="#cf222e", hl_rule="#1f6feb", hl_escape="#a1661a",
        hl_number="#0a6fae",
    ),
    "dark": dict(
        window="#1b1d22", panel="#22252b", header="#262a31", border="#353a43",
        text="#e3e6eb", muted="#9097a3", accent="#6d8bff", accent_hover="#8aa2ff",
        accent_text="#0f1220", accent_soft="#2c3557", input="#1a1c21",
        selection="#3a4a86", canvas="#15171b", warn_bg="#3a2f17", warn_text="#f3c56b",
        error_bg="#3d1f22", error_text="#ff9b9b", ok_text="#5ed3a5",
        code_bg="#1a1c21", code_text="#d8dde5", gutter="#5f6672", gutter_bg="#1f2227",
        hl_command="#c19bff", hl_env="#4fd1bd", hl_brace="#7d8696", hl_comment="#6c7480",
        hl_amp="#ff9e57", hl_newline="#ff7b7b", hl_rule="#79b8ff", hl_escape="#e3b56a",
        hl_number="#7cc4ff",
    ),
}


def system_prefers_dark() -> bool:
    try:
        hints = QApplication.styleHints()
        return hints.colorScheme() == Qt.ColorScheme.Dark  # Qt >= 6.5
    except Exception:  # noqa: BLE001
        return False


def apply_theme(app: QApplication, name: str) -> dict[str, str]:
    t = THEMES[name]
    app.setStyle("Fusion")
    pal = QPalette()
    c = QColor
    pal.setColor(QPalette.Window, c(t["window"]))
    pal.setColor(QPalette.WindowText, c(t["text"]))
    pal.setColor(QPalette.Base, c(t["input"]))
    pal.setColor(QPalette.AlternateBase, c(t["header"]))
    pal.setColor(QPalette.Text, c(t["text"]))
    pal.setColor(QPalette.Button, c(t["panel"]))
    pal.setColor(QPalette.ButtonText, c(t["text"]))
    pal.setColor(QPalette.ToolTipBase, c(t["panel"]))
    pal.setColor(QPalette.ToolTipText, c(t["text"]))
    pal.setColor(QPalette.Highlight, c(t["accent"]))
    pal.setColor(QPalette.HighlightedText, c(t["accent_text"]))
    pal.setColor(QPalette.PlaceholderText, c(t["muted"]))
    pal.setColor(QPalette.Link, c(t["accent"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c(t["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(t))
    return t


def _arrow_images(t: dict[str, str]) -> dict[str, str]:
    """Render small arrow PNGs (1x and @2x) for combo/spin boxes; returns paths."""
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter, QPolygonF

    folder = Path(tempfile.gettempdir()) / "latex_table_gen_icons"
    folder.mkdir(exist_ok=True)
    out = {}
    for name, color, up in (("down", t["muted"], False), ("up", t["muted"], True),
                            ("up_accent", t["accent"], True)):
        stem = f"{name}_{color.lstrip('#')}"
        for scale, suffix in ((1, ""), (2, "@2x")):
            w, h = 9 * scale, 6 * scale
            img = QImage(w, h, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            pts = [QPointF(0, h), QPointF(w, h), QPointF(w / 2, 0)] if up else \
                  [QPointF(0, 0), QPointF(w, 0), QPointF(w / 2, h)]
            p.drawPolygon(QPolygonF(pts))
            p.end()
            img.save(str(folder / f"{stem}{suffix}.png"))
        out[name] = (folder / f"{stem}.png").as_posix()

    # Check mark for check boxes
    from PySide6.QtGui import QPen
    stem = f"check_{t['accent_text'].lstrip('#')}"
    for scale, suffix in ((1, ""), (2, "@2x")):
        n = 11 * scale
        img = QImage(n, n, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(t["accent_text"]), 1.9 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(n * 0.16, n * 0.52), QPointF(n * 0.42, n * 0.76),
                        QPointF(n * 0.86, n * 0.24)])
        p.end()
        img.save(str(folder / f"{stem}{suffix}.png"))
    out["check"] = (folder / f"{stem}.png").as_posix()
    return out


def build_stylesheet(t: dict[str, str]) -> str:
    try:
        a = _arrow_images(t)
    except Exception:  # noqa: BLE001  (read-only temp dir: fall back to no arrows)
        a = {"down": "", "up": "", "up_accent": "", "check": ""}
    return f"""
    QMainWindow, QDialog {{ background: {t['window']}; }}
    QToolTip {{ color: {t['text']}; background: {t['panel']}; border: 1px solid {t['border']};
               padding: 4px 6px; }}

    #Pane {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    #PaneHeader {{ background: {t['header']}; border-bottom: 1px solid {t['border']};
                  border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    #PaneTitle {{ font-weight: 600; font-size: 11pt; color: {t['text']}; }}
    #PaneSubtitle, #Muted {{ color: {t['muted']}; }}
    #PaneFooter {{ border-top: 1px solid {t['border']}; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 8px; }}
    QSplitter::handle:vertical {{ height: 8px; }}

    QPushButton, QToolButton {{
        background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 6px; padding: 4px 10px; min-height: 20px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {t['accent']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t['accent_soft']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t['muted']}; }}
    QToolButton::menu-indicator {{ image: none; }}

    QPushButton#Primary {{ background: {t['accent']}; color: {t['accent_text']};
        border: 1px solid {t['accent']}; font-weight: 600; padding: 7px 16px; }}
    QPushButton#Primary:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}

    QPushButton[segment="true"] {{ border-radius: 0px; padding: 4px 8px; margin: 0px; }}
    QPushButton[segment="true"][first="true"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QPushButton[segment="true"][last="true"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QPushButton[segment="true"]:checked {{ background: {t['accent']}; color: {t['accent_text']};
        border-color: {t['accent']}; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: {t['input']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 6px; padding: 3px 6px; selection-background-color: {t['selection']};
        selection-color: {t['text']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{
        color: {t['muted']}; background: {t['window']}; border-color: {t['border']}; }}
    QLineEdit[invalid="true"] {{ border: 1px solid {t['error_text']}; background: {t['error_bg']}; }}
    QComboBox {{ padding-right: 20px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
        border: none; width: 20px; }}
    QComboBox::down-arrow {{ image: url("{a['down']}"); width: 9px; height: 6px; }}
    QComboBox::down-arrow:on {{ image: url("{a['up_accent']}"); }}
    QAbstractSpinBox {{ padding-right: 20px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border; width: 18px; border: none;
        border-left: 1px solid {t['border']}; background: transparent; }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {t['accent_soft']}; }}
    QAbstractSpinBox::up-arrow {{ image: url("{a['up']}"); width: 8px; height: 5px; }}
    QAbstractSpinBox::down-arrow {{ image: url("{a['down']}"); width: 8px; height: 5px; }}
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
    QComboBox QAbstractItemView {{ background: {t['panel']}; color: {t['text']};
        selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
        border: 1px solid {t['border']}; }}

    QTabWidget::pane {{ border: none; border-top: 1px solid {t['border']}; }}
    QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 7px 10px;
        border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {t['text']}; }}

    QTableView {{ background: {t['input']}; alternate-background-color: {t['header']};
        gridline-color: {t['border']}; border: none; color: {t['text']};
        selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
    QHeaderView::section {{ background: {t['header']}; color: {t['text']}; border: none;
        border-right: 1px solid {t['border']}; border-bottom: 1px solid {t['border']};
        padding: 4px 6px; font-weight: 600; }}
    QHeaderView::section:vertical {{ color: {t['muted']}; font-weight: 400; padding: 2px 6px; }}
    QTableCornerButton::section {{ background: {t['header']}; border: none;
        border-right: 1px solid {t['border']}; border-bottom: 1px solid {t['border']}; }}

    QScrollArea {{ border: none; }}
    QCheckBox {{ spacing: 7px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;
        border: 1px solid {t['muted']}; background: {t['input']}; }}
    QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']};
        image: url("{a['check']}"); }}
    QCheckBox::indicator:disabled {{ border-color: {t['border']}; background: {t['window']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {t['border']}; }}
    QGroupBox {{ border: none; margin-top: 14px; font-weight: 600; color: {t['muted']}; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0px; padding: 0px; }}

    #Banner[level="warn"] {{ background: {t['warn_bg']}; color: {t['warn_text']};
        border-radius: 6px; padding: 5px 8px; }}
    #Banner[level="error"] {{ background: {t['error_bg']}; color: {t['error_text']};
        border-radius: 6px; padding: 5px 8px; }}
    #Banner[level="info"] {{ background: {t['accent_soft']}; color: {t['text']};
        border-radius: 6px; padding: 5px 8px; }}
    #DropOverlay {{ background: rgba(53, 84, 209, 0.10); border: 2px dashed {t['accent']};
        border-radius: 10px; color: {t['accent']}; font-size: 14pt; font-weight: 600; }}
    QStatusBar {{ color: {t['muted']}; }}
    """
