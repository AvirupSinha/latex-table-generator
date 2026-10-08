"""Main window: 3-panel layout (data + controls | rendered preview | LaTeX code)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from core.csv_parser import (DELIMITER_CHOICES, LARGE_ROW_THRESHOLD, PREVIEW_ROW_LIMIT,
                             CSVParseError, delimiter_name, parse_csv_text, read_text_file)
from core.latex_generator import generate_latex
from ui.controls_widget import ControlsWidget
from ui.data_table import DataTableView, TableDataModel
from ui.preview_widget import CodePane, PreviewPane
from ui.style import Pane, apply_theme, system_prefers_dark

APP_NAME = "LaTeX Table Generator"
APP_VERSION = "1.0.0"
CSV_EXTENSIONS = (".csv", ".tsv", ".txt", ".dat")

SAMPLE_CSV = """Model,Params (M),Top-1 (%),Cost ($),Notes
ResNet-50,25.6,76.1,120,Baseline_v2
ViT-B/16,86.6,81.8,410,R&D build
EfficientNet-B0,5.3,77.1,65,~2x faster
ConvNeXt-T,28.6,82.1,150,#1 overall
"""
SAMPLE_CAPTION = ("Model comparison on ImageNet", "model-comparison")

class MainWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.settings = QSettings()

        theme = self.settings.value("theme", "dark" if system_prefers_dark() else "light")
        self.theme_name = theme if theme in ("light", "dark") else "light"
        self.theme = apply_theme(QApplication.instance(), self.theme_name)

        self.model = TableDataModel(self)
        self._source_text: str | None = None
        self._source_label = ""
        self._encoding = "utf-8"
        self._delimiter = ","

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_outputs)

        self._build_ui()
        self._build_menu()
        self._apply_theme_to_widgets()

        self.model.contentChanged.connect(self._schedule_update)
        self.model.structureChanged.connect(self._update_info)
        self.controls.optionsChanged.connect(self._schedule_update)

        self._restore_geometry()
        if initial_path:
            QTimer.singleShot(0, lambda: self.load_path(initial_path))
        else:
            self._load_text(SAMPLE_CSV, "Sample data", announce=False)
            self.controls.caption.setText(SAMPLE_CAPTION[0])
            self.controls.label.setText(SAMPLE_CAPTION[1])

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)

        self.h_split = QSplitter(Qt.Horizontal)
        self.h_split.setChildrenCollapsible(False)

        # Left: data pane above controls pane
        self.v_split = QSplitter(Qt.Vertical)
        self.v_split.setChildrenCollapsible(False)
        self.v_split.addWidget(self._build_data_pane())
        controls_pane = Pane("Customize", "live")
        self.controls = ControlsWidget(self.model)
        controls_pane.body.addWidget(self.controls)
        self.v_split.addWidget(controls_pane)
        self.v_split.setStretchFactor(0, 5)
        self.v_split.setStretchFactor(1, 6)

        self.preview = PreviewPane()
        self.code_pane = CodePane(self.theme)
        self.code_pane.status.connect(self._status)

        self.h_split.addWidget(self.v_split)
        self.h_split.addWidget(self.preview)
        self.h_split.addWidget(self.code_pane)
        self.h_split.setStretchFactor(0, 4)
        self.h_split.setStretchFactor(1, 5)
        self.h_split.setStretchFactor(2, 4)
        root.addWidget(self.h_split, 1)
        self.setCentralWidget(central)

        self.drop_overlay = QLabel("Drop a CSV file to load it", central)
        self.drop_overlay.setObjectName("DropOverlay")
        self.drop_overlay.setAlignment(Qt.AlignCenter)
        self.drop_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.drop_overlay.hide()

        self.size_label = QLabel()
        self.statusBar().addPermanentWidget(self.size_label)
        self.statusBar().setSizeGripEnabled(True)

    def _build_data_pane(self) -> Pane:
        pane = Pane("Data", "")
        self.data_pane = pane

        bar1 = QHBoxLayout()
        bar1.setContentsMargins(10, 8, 10, 4)
        bar1.setSpacing(6)
        open_btn = QPushButton("Open CSV…")
        open_btn.setToolTip("Open a CSV file (Ctrl+O) — or drag & drop one onto the window")
        open_btn.clicked.connect(self.open_csv)
        paste_btn = QPushButton("Paste")
        paste_btn.setToolTip("Load CSV / tab-separated text from the clipboard (Ctrl+Shift+V)\n"
                             "Works with cells copied from Excel, LibreOffice or Sheets.")
        paste_btn.clicked.connect(self.paste_csv)
        bar1.addWidget(open_btn)
        bar1.addWidget(paste_btn)
        bar1.addStretch(1)
        self.table_view = DataTableView()
        self.table_view.setModel(self.model)
        self.table_view.status.connect(self._status)
        for text, tip, slot in (("+ Row", "Add a row below the selection", self.table_view.add_row),
                                ("− Row", "Delete the selected rows", self.table_view.delete_rows),
                                ("+ Col", "Add a column after the selection",
                                 self.table_view.add_column),
                                ("− Col", "Delete the selected columns",
                                 self.table_view.delete_columns)):
            b = QToolButton(text=text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar1.addWidget(b)
        pane.body.addLayout(bar1)

        bar2 = QHBoxLayout()
        bar2.setContentsMargins(10, 2, 10, 8)
        bar2.setSpacing(8)
        bar2.addWidget(QLabel("Delimiter"))
        self.delim_combo = QComboBox()
        for label, d in DELIMITER_CHOICES.items():
            self.delim_combo.addItem(label, d)
        self.delim_combo.setToolTip("Auto-detect or force the CSV delimiter (re-parses the source)")
        self.delim_combo.currentIndexChanged.connect(self._reparse)
        bar2.addWidget(self.delim_combo)
        self.header_check = QCheckBox("First row is header")
        self.header_check.setToolTip("Toggle whether the first row is the table header")
        self.header_check.toggled.connect(self.model.set_has_header)
        bar2.addWidget(self.header_check)
        bar2.addStretch(1)
        pane.body.addLayout(bar2)

        pane.body.addWidget(self.table_view, 1)

        self.data_info = QLabel()
        self.data_info.setObjectName("Muted")
        self.data_warn = QLabel()
        self.data_warn.setObjectName("Banner")
        self.data_warn.setProperty("level", "warn")
        self.data_warn.setWordWrap(True)
        self.data_warn.hide()
        foot = QWidget()
        foot.setObjectName("PaneFooter")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.setSpacing(4)
        fl.addWidget(self.data_warn)
        fl.addWidget(self.data_info)
        pane.body.addWidget(foot)
        return pane

    def _build_menu(self) -> None:
        mb = self.menuBar()

        def act(menu, text, slot, shortcut=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = mb.addMenu("&File")
        act(m, "&Open CSV…", self.open_csv, QKeySequence.Open)
        act(m, "&Paste Table from Clipboard", self.paste_csv, "Ctrl+Shift+V")
        act(m, "Load &Sample Data", self._load_sample)
        m.addSeparator()
        act(m, "&Save LaTeX…", self.code_pane.save, QKeySequence.Save)
        m.addSeparator()
        act(m, "&Quit", self.close, QKeySequence.Quit)

        m = mb.addMenu("&Edit")
        act(m, "&Copy LaTeX to Clipboard", self.code_pane.copy, "Ctrl+Shift+C")
        m.addSeparator()
        act(m, "Add Row", self.table_view.add_row, "Ctrl+Shift+R")
        act(m, "Delete Selected Rows", self.table_view.delete_rows)
        act(m, "Add Column", self.table_view.add_column, "Ctrl+Shift+K")
        act(m, "Delete Selected Columns", self.table_view.delete_columns)

        m = mb.addMenu("&View")
        self.dark_action = act(m, "&Dark Theme", self.toggle_theme, "Ctrl+Shift+D",
                               checkable=True)
        self.dark_action.setChecked(self.theme_name == "dark")
        m.addSeparator()
        act(m, "Zoom &In", lambda: self.preview.zoom_by(1.15), QKeySequence.ZoomIn)
        act(m, "Zoom &Out", lambda: self.preview.zoom_by(1 / 1.15), QKeySequence.ZoomOut)
        act(m, "&Fit Preview Width", self.preview.fit_width, "Ctrl+0")

        m = mb.addMenu("&Help")
        act(m, "&About", self._about)

    # ------------------------------------------------------------------ theme
    def toggle_theme(self) -> None:
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.theme = apply_theme(QApplication.instance(), self.theme_name)
        self.settings.setValue("theme", self.theme_name)
        self.dark_action.setChecked(self.theme_name == "dark")
        self._apply_theme_to_widgets()

    def _apply_theme_to_widgets(self) -> None:
        self.preview.set_theme(self.theme)
        self.code_pane.set_theme(self.theme)

    # ------------------------------------------------------------------ loading
    def open_csv(self) -> None:
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV", start, "CSV files (*.csv *.tsv *.txt *.dat);;All files (*)")
        if path:
            self.settings.setValue("last_dir", os.path.dirname(path))
            self.load_path(path)

    def load_path(self, path: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text, enc = read_text_file(path)
        except CSVParseError as exc:
            QApplication.restoreOverrideCursor()
            self._error("Could not open file", str(exc))
            return
        except OSError as exc:
            QApplication.restoreOverrideCursor()
            self._error("Could not open file", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._load_text(text, path, encoding=enc)

    def paste_csv(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            self._error("Clipboard is empty", "Copy some CSV text or spreadsheet cells first.")
            return
        self._load_text(text, "Clipboard")

    def _load_text(self, text: str, source: str, encoding: str = "utf-8",
                   announce: bool = True, keep_header: bool = False) -> None:
        delim = self.delim_combo.currentData()
        has_header = self.header_check.isChecked() if keep_header else None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = parse_csv_text(text, delimiter=delim, has_header=has_header, source=source)
        except CSVParseError as exc:
            QApplication.restoreOverrideCursor()
            self._error("Could not load CSV", str(exc))
            return
        except Exception as exc:  # noqa: BLE001  (never crash on bad input)
            QApplication.restoreOverrideCursor()
            self._error("Could not load CSV", f"Unexpected error while parsing:\n{exc}")
            return

        # Drop the demo caption/label when real data replaces the sample.
        if source != "Sample data" and self._source_label == "Sample data":
            if self.controls.caption.text() == SAMPLE_CAPTION[0]:
                self.controls.caption.setText("")
            if self.controls.label.text() == SAMPLE_CAPTION[1]:
                self.controls.label.setText("")
        self._source_text, self._source_label = text, source
        self._encoding, self._delimiter = encoding, res.delimiter

        self.header_check.blockSignals(True)
        self.header_check.setChecked(res.header is not None)
        self.header_check.blockSignals(False)
        self.model.load(res.header, res.rows)
        self.table_view.autosize_columns()
        QApplication.restoreOverrideCursor()

        name = os.path.basename(source) if os.path.sep in source or "/" in source else source
        self.data_pane.subtitle.setText(name)
        self.data_pane.subtitle.setToolTip(source)

        warns = [w for w in res.warnings if not w.startswith("Large file")]
        self.data_warn.setText("\n".join("⚠ " + w for w in warns))
        self.data_warn.setVisible(bool(warns))
        self._update_info()
        self._schedule_update(immediate=True)

        if announce:
            self._status(f"Loaded {res.n_rows:,} rows × {res.n_cols} columns from {name}.")
        if res.is_large and announce:
            QMessageBox.information(
                self, "Large file",
                f"This file has {res.n_rows:,} rows (more than {LARGE_ROW_THRESHOLD:,}).\n\n"
                f"• The rendered preview is limited to the first {PREVIEW_ROW_LIMIT} rows.\n"
                "• The LaTeX code contains every row.\n\n"
                "Note: a table this long will not fit on one page — consider the "
                "longtable package.")

    def _load_sample(self) -> None:
        self._load_text(SAMPLE_CSV, "Sample data")
        if not self.controls.caption.text():
            self.controls.caption.setText(SAMPLE_CAPTION[0])
            self.controls.label.setText(SAMPLE_CAPTION[1])

    def _reparse(self) -> None:
        if self._source_text is not None:
            self._load_text(self._source_text, self._source_label, self._encoding,
                            announce=False, keep_header=True)

    # ------------------------------------------------------------------ live sync
    def _schedule_update(self, immediate: bool = False) -> None:
        n = self.model.rowCount()
        delay = 0 if immediate else (60 if n < 2000 else 250 if n < 20000 else 500)
        self._timer.start(delay)

    def _update_outputs(self) -> None:
        header, rows = self.model.header(), self.model.rows()
        cols, opts = self.model.columns(), self.controls.options()
        try:
            res = generate_latex(header, rows, cols, opts)
            code, notes = res.code, list(res.notes)
        except Exception as exc:  # noqa: BLE001
            code, notes = f"% Could not generate LaTeX: {exc}\n", []
        if len(rows) > 45 and opts.environment != "none":
            notes.append(f"{len(rows):,} rows will not fit on one page inside a table float "
                         "(floats cannot break across pages) — consider longtable.")
        self.code_pane.set_code(code, notes)
        limit = PREVIEW_ROW_LIMIT if len(rows) > LARGE_ROW_THRESHOLD else len(rows)
        self.preview.canvas.set_content(header, rows[:limit], cols, opts, len(rows))

    def _update_info(self) -> None:
        r, c = self.model.rowCount(), self.model.columnCount()
        hdr = "header" if self.model.has_header() else "no header"
        enc = self._encoding.replace("-sig", "").upper()
        self.data_info.setText(f"{r:,} rows × {c} columns · {hdr} · "
                               f"{delimiter_name(self._delimiter)}-separated · {enc}")
        self.size_label.setText(f"{r:,} × {c}  ")

    # ------------------------------------------------------------------ drag & drop
    def _csv_from_mime(self, mime) -> str | None:
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:
        path = self._csv_from_mime(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.drop_overlay.setGeometry(self.centralWidget().rect().adjusted(14, 14, -14, -14))
            ok = path.lower().endswith(CSV_EXTENSIONS)
            self.drop_overlay.setText(f"Drop to load  {os.path.basename(path)}" if ok else
                                      f"Drop to try loading  {os.path.basename(path)}")
            self.drop_overlay.raise_()
            self.drop_overlay.show()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.drop_overlay.hide()

    def dropEvent(self, event) -> None:
        self.drop_overlay.hide()
        path = self._csv_from_mime(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.load_path(path)

    # ------------------------------------------------------------------ misc
    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    def _error(self, title: str, text: str) -> None:
        self._status(text.splitlines()[0])
        QMessageBox.warning(self, title, text)

    def _about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
            "Convert CSV files into LaTeX <code>tabular</code> / <code>booktabs</code> "
            "tables with a live rendered preview.<br><br>"
            "Preview font: Latin Modern Roman (GUST Font License).<br>"
            "Built with Python, PySide6 and pandas.")

    def _restore_geometry(self) -> None:
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            scr = QGuiApplication.primaryScreen().availableGeometry()
            w, h = min(1520, int(scr.width() * 0.94)), min(940, int(scr.height() * 0.9))
            self.resize(w, h)
            self.move(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2)
        state = self.settings.value("h_split")
        if state is not None:
            self.h_split.restoreState(state)
        else:
            w = self.width() - 40
            self.h_split.setSizes([int(w * 0.31), int(w * 0.37), int(w * 0.32)])
        state = self.settings.value("v_split")
        if state is not None:
            self.v_split.restoreState(state)

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("h_split", self.h_split.saveState())
        self.settings.setValue("v_split", self.v_split.saveState())
        super().closeEvent(event)
