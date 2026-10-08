"""Live customization panel (Structure / Design / Caption / Columns / Advanced)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                               QTableWidget, QTabWidget, QVBoxLayout, QWidget)

from core.latex_generator import (FONT_SIZES, PLACEMENTS, PRESETS, RESIZE_TARGETS,
                                  XCOLOR_RGB, ColumnSpec, TableOptions)
from ui.data_table import TableDataModel


# --------------------------------------------------------------------------- #
# Small reusable widgets
# --------------------------------------------------------------------------- #
class SegmentedControl(QWidget):
    """A row of mutually exclusive toggle buttons."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None, tooltips=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for i, (value, label) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("segment", True)
            b.setProperty("first", i == 0)
            b.setProperty("last", i == len(options) - 1)
            b.setCursor(Qt.PointingHandCursor)
            if tooltips and value in tooltips:
                b.setToolTip(tooltips[value])
            self._group.addButton(b)
            self._buttons[value] = b
            lay.addWidget(b)
            b.toggled.connect(lambda on, v=value: on and self.changed.emit(v))
        lay.addStretch(1)

    def value(self) -> str:
        for v, b in self._buttons.items():
            if b.isChecked():
                return v
        return next(iter(self._buttons))

    def set_value(self, value: str) -> None:
        if value in self._buttons:
            self._buttons[value].setChecked(True)


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


def _form() -> tuple[QWidget, QFormLayout]:
    w = QWidget()
    f = QFormLayout(w)
    f.setContentsMargins(12, 10, 12, 10)
    f.setHorizontalSpacing(12)
    f.setVerticalSpacing(9)
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return w, f


def _scroll(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.NoFrame)
    sa.setWidget(widget)
    return sa


def _swatch(rgb: tuple[float, float, float]) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor.fromRgbF(*rgb))
    return QIcon(pm)


# --------------------------------------------------------------------------- #
# Per-column editor
# --------------------------------------------------------------------------- #
class ColumnsEditor(QWidget):
    """Per-column include / alignment / p-width editor bound to the data model."""

    def __init__(self, model: TableDataModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._building = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Set all:"))
        for a, tip in (("l", "Left"), ("c", "Center"), ("r", "Right"), ("p", "Paragraph p{width}")):
            b = QPushButton(a if a != "p" else "p{…}")
            b.setToolTip(f"{tip}-align every column")
            b.setFixedWidth(46 if a != "p" else 56)
            b.clicked.connect(lambda _=False, a=a: self._model.set_all_alignments(a))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Use", "Column", "Align", "p width"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        hh.resizeSection(3, 110)
        self.table.verticalHeader().setDefaultSectionSize(34)
        lay.addWidget(self.table, 1)
        lay.addWidget(_hint("p{width} accepts e.g. 3cm, 1.5in, 40mm, 80pt, 0.3\\linewidth. "
                            "Right-click a header in the data table for the same options."))

        model.structureChanged.connect(self.rebuild)
        model.columnSpecChanged.connect(self._sync_row)
        self.rebuild()

    def rebuild(self) -> None:
        self._building = True
        m = self._model
        n = m.columnCount()
        self.table.setRowCount(n)
        for c in range(n):
            spec = m.columns()[c]
            chk = QCheckBox()
            chk.setChecked(spec.include)
            chk.setToolTip("Include this column in the output")
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 0, 4, 0)
            hl.addWidget(chk)
            self.table.setCellWidget(c, 0, holder)

            name = QLabel(m.column_name(c))
            name.setContentsMargins(4, 0, 4, 0)
            name.setToolTip(m.column_name(c))
            self.table.setCellWidget(c, 1, name)

            combo = QComboBox()
            for a, label in (("l", "l  left"), ("c", "c  center"), ("r", "r  right"),
                             ("p", "p  paragraph")):
                combo.addItem(label, a)
            combo.setCurrentIndex(["l", "c", "r", "p"].index(spec.align))
            self.table.setCellWidget(c, 2, combo)

            width = QLineEdit(spec.width)
            width.setPlaceholderText("3cm")
            width.setEnabled(spec.align == "p")
            width.setProperty("invalid", spec.align == "p" and not spec.width_valid)
            self.table.setCellWidget(c, 3, width)

            chk.toggled.connect(lambda _=False, c=c: self._commit(c))
            combo.currentIndexChanged.connect(lambda _=0, c=c: self._commit(c))
            width.textChanged.connect(lambda _="", c=c: self._commit(c))
        self._building = False

    def _widgets(self, c: int):
        chk = self.table.cellWidget(c, 0).findChild(QCheckBox)
        return chk, self.table.cellWidget(c, 2), self.table.cellWidget(c, 3)

    def _commit(self, c: int) -> None:
        if self._building or c >= self._model.columnCount():
            return
        chk, combo, width = self._widgets(c)
        spec = ColumnSpec(combo.currentData(), width.text().strip() or "3cm", chk.isChecked())
        width.setEnabled(spec.align == "p")
        width.setProperty("invalid", spec.align == "p" and not spec.width_valid)
        width.style().unpolish(width)
        width.style().polish(width)
        self._model.set_column_spec(c, spec)

    def _sync_row(self, c: int) -> None:
        if self._building or c >= self.table.rowCount():
            return
        spec = self._model.columns()[c]
        chk, combo, width = self._widgets(c)
        self._building = True
        chk.setChecked(spec.include)
        combo.setCurrentIndex(["l", "c", "r", "p"].index(spec.align))
        if width.text().strip() != spec.width:
            width.setText(spec.width)
        width.setEnabled(spec.align == "p")
        self._building = False


# --------------------------------------------------------------------------- #
# Main controls panel
# --------------------------------------------------------------------------- #
class ControlsWidget(QWidget):
    optionsChanged = Signal()

    def __init__(self, model: TableDataModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Preset row
        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 4)
        top.addWidget(QLabel("Preset"))
        self.preset = QComboBox()
        self.preset.addItem("Custom")
        for name in PRESETS:
            self.preset.addItem(name)
        self.preset.setToolTip("One-click table styles")
        self.preset.activated.connect(self._apply_preset)
        top.addWidget(self.preset, 1)
        reset = QPushButton("Reset")
        reset.setToolTip("Restore default formatting (keeps caption and label)")
        reset.clicked.connect(self.reset)
        top.addWidget(reset)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(_scroll(self._build_structure()), "Structure")
        self.tabs.addTab(_scroll(self._build_design()), "Design")
        self.tabs.addTab(_scroll(self._build_caption()), "Caption")
        self.columns_editor = ColumnsEditor(model)
        self.tabs.addTab(self.columns_editor, "Columns")
        self.tabs.addTab(_scroll(self._build_advanced()), "Advanced")
        root.addWidget(self.tabs, 1)

        self.set_options(TableOptions())

    # ------------------------------------------------------------------ tabs
    def _build_structure(self) -> QWidget:
        w, f = _form()
        self.booktabs = QCheckBox("booktabs style  (\\toprule · \\midrule · \\bottomrule)")
        self.booktabs.setToolTip("Unchecked: classic tabular with \\hline")
        self.top_bottom = QCheckBox("Top && bottom border")
        self.outer_v = QCheckBox("Left && right border")
        self.inner_v = QCheckBox("Vertical lines between columns")
        self.hlines = SegmentedControl([("all", "All rows"), ("header", "Header only"),
                                        ("none", "None")])
        f.addRow(self.booktabs)
        f.addRow(_hint("Borders"))
        f.addRow(self.top_bottom)
        f.addRow(self.outer_v)
        f.addRow(self.inner_v)
        f.addRow("Horizontal lines", self.hlines)
        borders = QHBoxLayout()
        b_all = QPushButton("All borders")
        b_none = QPushButton("Remove borders")
        b_all.clicked.connect(lambda: self._set_borders(True))
        b_none.clicked.connect(lambda: self._set_borders(False))
        borders.addWidget(b_all)
        borders.addWidget(b_none)
        borders.addStretch(1)
        f.addRow("Quick", borders)

        for wdg in (self.booktabs, self.top_bottom, self.outer_v, self.inner_v):
            wdg.toggled.connect(self._changed)
        self.hlines.changed.connect(self._changed)
        return w

    def _build_design(self) -> QWidget:
        w, f = _form()
        self.font_size = QComboBox()
        self.font_size.addItem("Document default", "")
        for name in FONT_SIZES:
            self.font_size.addItem(f"\\{name}", name)
        f.addRow("Font size", self.font_size)

        self.table_align = SegmentedControl(
            [("left", "Left"), ("center", "Center"), ("right", "Right")],
            tooltips={"left": "Flush left (no command)", "center": "\\centering",
                      "right": "\\raggedleft"})
        f.addRow("Table alignment", self.table_align)

        col_row = QHBoxLayout()
        for a in ("l", "c", "r"):
            b = QPushButton(a)
            b.setFixedWidth(40)
            b.setToolTip(f"Set every column to '{a}'  (per-column: Columns tab)")
            b.clicked.connect(lambda _=False, a=a: self._model.set_all_alignments(a))
            col_row.addWidget(b)
        col_row.addStretch(1)
        f.addRow("Column alignment", col_row)

        self.bold_header = QCheckBox("Bold header row  (\\textbf)")
        f.addRow("", self.bold_header)

        self.rotate = QComboBox()
        self.rotate.addItem("None", "none")
        self.rotate.addItem("90°  (\\rotatebox)", "rotatebox")
        self.rotate.addItem("Landscape page  (sidewaystable)", "sideways")
        f.addRow("Rotate", self.rotate)

        self.resize = QCheckBox("Scale with \\resizebox")
        f.addRow("Scale", self.resize)
        rs = QHBoxLayout()
        self.resize_fraction = QDoubleSpinBox()
        self.resize_fraction.setRange(0.1, 2.0)
        self.resize_fraction.setSingleStep(0.05)
        self.resize_fraction.setDecimals(2)
        self.resize_fraction.setSuffix(" ×")
        self.resize_target = QComboBox()
        for t in RESIZE_TARGETS:
            self.resize_target.addItem(t, t)
        rs.addWidget(self.resize_fraction)
        rs.addWidget(self.resize_target, 1)
        f.addRow("Width", rs)

        self.font_size.currentIndexChanged.connect(self._changed)
        self.table_align.changed.connect(self._align_changed)
        self.bold_header.toggled.connect(self._changed)
        self.rotate.currentIndexChanged.connect(self._changed)
        self.resize.toggled.connect(self._changed)
        self.resize_fraction.valueChanged.connect(self._changed)
        self.resize_target.currentIndexChanged.connect(self._changed)
        return w

    def _build_caption(self) -> QWidget:
        w, f = _form()
        self.caption = QLineEdit()
        self.caption.setPlaceholderText("e.g. Summary of experimental results")
        self.caption.setClearButtonEnabled(True)
        f.addRow("Caption", self.caption)
        self.caption_pos = SegmentedControl([("top", "Top"), ("bottom", "Bottom")])
        f.addRow("Position", self.caption_pos)

        lab = QHBoxLayout()
        prefix = QLabel("tab:")
        prefix.setObjectName("Muted")
        self.label = QLineEdit()
        self.label.setPlaceholderText("results")
        self.label.setClearButtonEnabled(True)
        auto = QPushButton("From caption")
        auto.setToolTip("Generate a label from the caption text")
        auto.clicked.connect(self._label_from_caption)
        lab.addWidget(prefix)
        lab.addWidget(self.label, 1)
        lab.addWidget(auto)
        f.addRow("Label", lab)

        self.centering = QCheckBox("Add \\centering")
        self.centering.setToolTip("Linked to Design → Table alignment")
        f.addRow("", self.centering)
        f.addRow("", _hint("Reference the table in your text with \\ref{tab:…}."))

        self.caption.textChanged.connect(self._changed)
        self.caption_pos.changed.connect(self._changed)
        self.label.textChanged.connect(self._changed)
        self.centering.toggled.connect(self._centering_changed)
        return w

    def _build_advanced(self) -> QWidget:
        w, f = _form()
        self.striped = QCheckBox("Striped rows  (\\rowcolors)")
        f.addRow("Rows", self.striped)
        st = QHBoxLayout()
        self.stripe_color = QComboBox()
        for name, rgb in XCOLOR_RGB.items():
            self.stripe_color.addItem(_swatch(rgb), name, name)
        self.stripe_intensity = QSpinBox()
        self.stripe_intensity.setRange(3, 60)
        self.stripe_intensity.setSuffix(" %")
        self.stripe_intensity.setToolTip("Tint strength, xcolor syntax color!N")
        st.addWidget(self.stripe_color, 1)
        st.addWidget(self.stripe_intensity)
        f.addRow("Stripe color", st)

        self.tabcolsep = QDoubleSpinBox()
        self.tabcolsep.setRange(0.0, 40.0)
        self.tabcolsep.setSingleStep(0.5)
        self.tabcolsep.setDecimals(1)
        self.tabcolsep.setSuffix(" pt")
        self.tabcolsep.setToolTip("\\tabcolsep — half the space between columns (default 6pt)")
        f.addRow("Column spacing", self.tabcolsep)

        self.arraystretch = QDoubleSpinBox()
        self.arraystretch.setRange(0.5, 3.0)
        self.arraystretch.setSingleStep(0.05)
        self.arraystretch.setDecimals(2)
        self.arraystretch.setSuffix(" ×")
        self.arraystretch.setToolTip("\\arraystretch — row height factor (default 1.0)")
        f.addRow("Row spacing", self.arraystretch)

        self.environment = QComboBox()
        self.environment.addItem("table", "table")
        self.environment.addItem("table*  (span both columns)", "table*")
        self.environment.addItem("None  (bare tabular)", "none")
        f.addRow("Environment", self.environment)

        self.placement = QComboBox()
        for p in PLACEMENTS:
            self.placement.addItem(f"[{p}]" if p else "(none)", p)
        self.placement.setToolTip("Float placement specifier. [H] requires the float package.")
        f.addRow("Placement", self.placement)

        self.escape = QCheckBox("Escape special characters  (&& % $ # _ { } ~ ^ \\)")
        self.escape.setToolTip("Uncheck if your cells already contain LaTeX (e.g. $x^2$)")
        self.align_code = QCheckBox("Align && columns in source code")
        self.package_hints = QCheckBox("Show required \\usepackage lines")
        self.standalone = QCheckBox("Full standalone document  (compiles as-is)")
        f.addRow("Output", self.escape)
        f.addRow("", self.align_code)
        f.addRow("", self.package_hints)
        f.addRow("", self.standalone)

        self.striped.toggled.connect(self._changed)
        self.stripe_color.currentIndexChanged.connect(self._changed)
        self.stripe_intensity.valueChanged.connect(self._changed)
        self.tabcolsep.valueChanged.connect(self._changed)
        self.arraystretch.valueChanged.connect(self._changed)
        self.environment.currentIndexChanged.connect(self._changed)
        self.placement.currentIndexChanged.connect(self._changed)
        for c in (self.escape, self.align_code, self.package_hints, self.standalone):
            c.toggled.connect(self._changed)
        return w

    # ------------------------------------------------------------------ state
    def options(self) -> TableOptions:
        return TableOptions(
            booktabs=self.booktabs.isChecked(),
            top_bottom_rules=self.top_bottom.isChecked(),
            outer_vlines=self.outer_v.isChecked(),
            inner_vlines=self.inner_v.isChecked(),
            hlines=self.hlines.value(),
            font_size=self.font_size.currentData(),
            table_align=self.table_align.value(),
            bold_header=self.bold_header.isChecked(),
            rotate=self.rotate.currentData(),
            resize=self.resize.isChecked(),
            resize_target=self.resize_target.currentData(),
            resize_fraction=self.resize_fraction.value(),
            caption=self.caption.text(),
            caption_pos=self.caption_pos.value(),
            label=self.label.text(),
            striped=self.striped.isChecked(),
            stripe_color=self.stripe_color.currentData(),
            stripe_intensity=self.stripe_intensity.value(),
            tabcolsep=self.tabcolsep.value(),
            arraystretch=self.arraystretch.value(),
            environment=self.environment.currentData(),
            placement=self.placement.currentData(),
            escape=self.escape.isChecked(),
            align_code=self.align_code.isChecked(),
            package_hints=self.package_hints.isChecked(),
            standalone=self.standalone.isChecked(),
        )

    def set_options(self, o: TableOptions) -> None:
        self._updating = True
        try:
            self.booktabs.setChecked(o.booktabs)
            self.top_bottom.setChecked(o.top_bottom_rules)
            self.outer_v.setChecked(o.outer_vlines)
            self.inner_v.setChecked(o.inner_vlines)
            self.hlines.set_value(o.hlines)
            self._set_combo(self.font_size, o.font_size)
            self.table_align.set_value(o.table_align)
            self.centering.setChecked(o.table_align == "center")
            self.bold_header.setChecked(o.bold_header)
            self._set_combo(self.rotate, o.rotate)
            self.resize.setChecked(o.resize)
            self._set_combo(self.resize_target, o.resize_target)
            self.resize_fraction.setValue(o.resize_fraction)
            self.caption.setText(o.caption)
            self.caption_pos.set_value(o.caption_pos)
            self.label.setText(o.label)
            self.striped.setChecked(o.striped)
            self._set_combo(self.stripe_color, o.stripe_color)
            self.stripe_intensity.setValue(o.stripe_intensity)
            self.tabcolsep.setValue(o.tabcolsep)
            self.arraystretch.setValue(o.arraystretch)
            self._set_combo(self.environment, o.environment)
            self._set_combo(self.placement, o.placement)
            self.escape.setChecked(o.escape)
            self.align_code.setChecked(o.align_code)
            self.package_hints.setChecked(o.package_hints)
            self.standalone.setChecked(o.standalone)
        finally:
            self._updating = False
        self._refresh_enabled()
        self._sync_preset()
        self.optionsChanged.emit()

    @staticmethod
    def _set_combo(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    # ------------------------------------------------------------------ slots
    def _changed(self, *_):
        if self._updating:
            return
        self._refresh_enabled()
        self._sync_preset()
        self.optionsChanged.emit()

    def _align_changed(self, value: str) -> None:
        if self._updating:
            return
        self._updating = True
        self.centering.setChecked(value == "center")
        self._updating = False
        self._changed()

    def _centering_changed(self, on: bool) -> None:
        if self._updating:
            return
        self._updating = True
        self.table_align.set_value("center" if on else "left")
        self._updating = False
        self._changed()

    def _set_borders(self, on: bool) -> None:
        self._updating = True
        self.top_bottom.setChecked(on)
        self.outer_v.setChecked(on)
        self.inner_v.setChecked(on)
        self.hlines.set_value("all" if on else "none")
        if on:
            self.booktabs.setChecked(False)  # a full grid is a classic \hline table
        self._updating = False
        self._changed()

    def _label_from_caption(self) -> None:
        words = re.findall(r"[A-Za-z0-9]+", self.caption.text().lower())
        stop = {"a", "an", "the", "of", "and", "for", "in", "on", "with", "to", "by"}
        words = [w for w in words if w not in stop][:4]
        self.label.setText("-".join(words) or "table")

    def _apply_preset(self, index: int) -> None:
        name = self.preset.itemText(index)
        if name in PRESETS:
            self.set_options(self.options().copy(**PRESETS[name]))

    def _sync_preset(self) -> None:
        cur = self.options().as_dict()
        match = "Custom"
        for name, fields in PRESETS.items():
            if all(cur[k] == v for k, v in fields.items()):
                match = name
                break
        self.preset.blockSignals(True)
        self.preset.setCurrentText(match)
        self.preset.blockSignals(False)

    def _refresh_enabled(self) -> None:
        on = self.resize.isChecked()
        self.resize_fraction.setEnabled(on)
        self.resize_target.setEnabled(on)
        s = self.striped.isChecked()
        self.stripe_color.setEnabled(s)
        self.stripe_intensity.setEnabled(s)
        floating = self.environment.currentData() != "none"
        self.caption.setEnabled(floating)
        self.label.setEnabled(floating)
        self.caption_pos.setEnabled(floating)
        self.placement.setEnabled(floating and self.rotate.currentData() != "sideways")
        self.package_hints.setEnabled(not self.standalone.isChecked())

    def reset(self) -> None:
        cur = self.options()
        self.set_options(TableOptions(caption=cur.caption, label=cur.label))
