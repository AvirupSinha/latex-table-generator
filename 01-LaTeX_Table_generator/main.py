"""LaTeX Table Generator — convert CSV files into LaTeX tables with a live preview.

Run with:  python main.py [optional/path/to/file.csv]
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `core` and `ui` importable no matter where the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.main_window import APP_NAME, MainWindow  # noqa: E402
from ui.style import load_bundled_fonts  # noqa: E402


def make_app_icon() -> QIcon:
    """A small booktabs-style icon (heavy / light / heavy rules) drawn in code."""
    icon = QIcon()
    for size in (16, 32, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#3554d1"))
        p.setPen(Qt.NoPen)
        r = size * 0.2
        p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
        p.setBrush(QColor("white"))
        m, w = size * 0.2, size * 0.6
        for y, t in ((0.27, 0.085), (0.47, 0.045), (0.62, 0.045), (0.75, 0.085)):
            p.drawRect(QRectF(m, size * y, w, max(1.0, size * t)))
        p.end()
        icon.addPixmap(pm)
    return icon


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("LatexTableGen")
    app.setWindowIcon(make_app_icon())
    load_bundled_fonts()

    initial = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    window = MainWindow(initial_path=initial)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
