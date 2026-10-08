"""Editable data table: a QAbstractTableModel + QTableView pair.

The model is the single source of truth for the table content (header, rows)
and per-column formatting (:class:`ColumnSpec`).
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QInputDialog, QMenu,
                               QTableView)

from core.csv_parser import _looks_numeric
from core.latex_generator import ColumnSpec


def guess_alignment(values: list[str]) -> str:
    """Right-align numeric columns, left-align everything else."""
    vals = [v for v in values if v.strip()]
    if vals and sum(_looks_numeric(v) for v in vals) / len(vals) >= 0.8:
        return "r"
    return "l"


class TableDataModel(QAbstractTableModel):
    contentChanged = Signal()      # anything that affects the output changed
    structureChanged = Signal()    # columns added/removed/renamed, header toggled, reload
    columnSpecChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header: list[str] | None = None
        self._rows: list[list[str]] = []
        self._columns: list[ColumnSpec] = []
        self._n_cols = 0

    # ------------------------------------------------------------------ access
    def header(self) -> list[str] | None:
        return self._header

    def rows(self) -> list[list[str]]:
        return self._rows

    def columns(self) -> list[ColumnSpec]:
        return self._columns

    def has_header(self) -> bool:
        return self._header is not None

    def column_name(self, col: int) -> str:
        if self._header is not None and col < len(self._header) and self._header[col].strip():
            return self._header[col]
        return f"Column {col + 1}"

    # ------------------------------------------------------------------ loading
    def load(self, header: list[str] | None, rows: list[list[str]]) -> None:
        n = max([len(header or [])] + [len(r) for r in rows[:1]] + [0])
        if rows:
            n = max(n, max(len(r) for r in rows))
        self.beginResetModel()
        self._n_cols = n
        self._header = None if header is None else self._pad(list(header), n)
        self._rows = [self._pad(list(r), n) if len(r) != n else list(r) for r in rows]
        sample = self._rows[:300]
        self._columns = [ColumnSpec(align=guess_alignment([r[j] for r in sample]))
                         for j in range(n)]
        self.endResetModel()
        self.structureChanged.emit()
        self.contentChanged.emit()

    @staticmethod
    def _pad(row: list[str], n: int) -> list[str]:
        if len(row) < n:
            row.extend([""] * (n - len(row)))
        return row[:n]

    # ------------------------------------------------------------------ Qt API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._n_cols

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._rows[r][c]
        if role == Qt.TextAlignmentRole:
            a = self._columns[c].align
            h = {"c": Qt.AlignHCenter, "r": Qt.AlignRight}.get(a, Qt.AlignLeft)
            return int(h | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and not self._columns[c].include:
            return QColor(150, 150, 150)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        value = "" if value is None else str(value)
        r, c = index.row(), index.column()
        if self._rows[r][c] == value:
            return False
        self._rows[r][c] = value
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.contentChanged.emit()
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if section >= self._n_cols:
                return None
            spec = self._columns[section]
            if role == Qt.DisplayRole:
                return self.column_name(section)
            if role == Qt.ToolTipRole:
                state = "" if spec.include else " (excluded)"
                return (f"Alignment: {spec.latex()}{state}\n"
                        "Double-click to rename · right-click for options")
            if role == Qt.FontRole:
                f = QFont()
                f.setBold(self._header is not None)
                f.setItalic(self._header is None or not spec.include)
                f.setStrikeOut(not spec.include)
                return f
            if role == Qt.ForegroundRole and (self._header is None or not spec.include):
                return QColor(140, 140, 140)
        elif role == Qt.DisplayRole:
            return str(section + 1)
        return None

    # ------------------------------------------------------------------ editing
    def set_has_header(self, on: bool) -> None:
        """Promote the first row to header, or demote the header to a data row."""
        if on == self.has_header():
            return
        self.beginResetModel()
        if on:
            self._header = self._rows.pop(0) if self._rows else [""] * self._n_cols
        else:
            self._rows.insert(0, self._header)
            self._header = None
        self.endResetModel()
        self.structureChanged.emit()
        self.contentChanged.emit()

    def rename_column(self, col: int, name: str) -> None:
        if self._header is None:
            return
        self._header[col] = name
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        self.structureChanged.emit()
        self.contentChanged.emit()

    def insert_rows(self, pos: int, count: int = 1) -> None:
        pos = max(0, min(pos, len(self._rows)))
        self.beginInsertRows(QModelIndex(), pos, pos + count - 1)
        for _ in range(count):
            self._rows.insert(pos, [""] * self._n_cols)
        self.endInsertRows()
        self.contentChanged.emit()

    def remove_rows(self, rows: list[int]) -> None:
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self._rows):
                self.beginRemoveRows(QModelIndex(), r, r)
                del self._rows[r]
                self.endRemoveRows()
        self.contentChanged.emit()

    def insert_column(self, pos: int) -> None:
        pos = max(0, min(pos, self._n_cols))
        self.beginInsertColumns(QModelIndex(), pos, pos)
        for row in self._rows:
            row.insert(pos, "")
        if self._header is not None:
            self._header.insert(pos, f"Column {pos + 1}")
        self._columns.insert(pos, ColumnSpec())
        self._n_cols += 1
        self.endInsertColumns()
        self.structureChanged.emit()
        self.contentChanged.emit()

    def remove_columns(self, cols: list[int]) -> None:
        for c in sorted(set(cols), reverse=True):
            if 0 <= c < self._n_cols and self._n_cols > 1:
                self.beginRemoveColumns(QModelIndex(), c, c)
                for row in self._rows:
                    del row[c]
                if self._header is not None:
                    del self._header[c]
                del self._columns[c]
                self._n_cols -= 1
                self.endRemoveColumns()
        self.structureChanged.emit()
        self.contentChanged.emit()

    def set_column_spec(self, col: int, spec: ColumnSpec) -> None:
        if not (0 <= col < self._n_cols) or self._columns[col] == spec:
            return
        self._columns[col] = spec
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        if self._rows:
            self.dataChanged.emit(self.index(0, col), self.index(len(self._rows) - 1, col))
        self.columnSpecChanged.emit(col)
        self.contentChanged.emit()

    def set_all_alignments(self, align: str) -> None:
        for c in range(self._n_cols):
            s = self._columns[c]
            self._columns[c] = ColumnSpec(align, s.width, s.include)
            self.columnSpecChanged.emit(c)
        self.headerDataChanged.emit(Qt.Horizontal, 0, max(0, self._n_cols - 1))
        if self._rows and self._n_cols:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, self._n_cols - 1))
        self.contentChanged.emit()

    def set_block(self, top: int, left: int, block: list[list[str]]) -> None:
        """Paste a 2-D block of text, growing the table with new rows if needed."""
        if not block:
            return
        need = top + len(block) - len(self._rows)
        if need > 0:
            self.insert_rows(len(self._rows), need)
        for i, line in enumerate(block):
            for j, val in enumerate(line):
                c = left + j
                if c < self._n_cols:
                    self._rows[top + i][c] = val
        bottom = top + len(block) - 1
        right = min(self._n_cols - 1, left + max(len(l) for l in block) - 1)
        self.dataChanged.emit(self.index(top, left), self.index(bottom, right))
        self.contentChanged.emit()

    def clear_cells(self, indexes: list[QModelIndex]) -> None:
        changed = [i for i in indexes if self._rows[i.row()][i.column()]]
        if not changed:
            return
        for idx in changed:
            self._rows[idx.row()][idx.column()] = ""
        rows = [i.row() for i in changed]
        cols = [i.column() for i in changed]
        self.dataChanged.emit(self.index(min(rows), min(cols)),
                              self.index(max(rows), max(cols)))
        self.contentChanged.emit()


class DataTableView(QTableView):
    """Spreadsheet-like editor with context menus, copy/paste and delete."""

    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                             | QAbstractItemView.AnyKeyPressed)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(True)
        self.verticalHeader().setDefaultSectionSize(26)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setDefaultSectionSize(110)
        hh.setMinimumSectionSize(40)
        hh.setSectionsClickable(True)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        hh.sectionDoubleClicked.connect(self._rename_column)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._cell_menu)

    def model(self) -> TableDataModel:  # type: ignore[override]
        return super().model()

    def autosize_columns(self) -> None:
        self.resizeColumnsToContents()
        hh = self.horizontalHeader()
        for c in range(self.model().columnCount()):
            hh.resizeSection(c, max(70, min(hh.sectionSize(c) + 16, 260)))

    # ------------------------------------------------------------- selection
    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectedIndexes()})

    def selected_columns(self) -> list[int]:
        return sorted({i.column() for i in self.selectedIndexes()})

    # ------------------------------------------------------------- actions
    def add_row(self) -> None:
        rows = self.selected_rows()
        pos = rows[-1] + 1 if rows else self.model().rowCount()
        self.model().insert_rows(pos)
        self.scrollTo(self.model().index(pos, 0))

    def delete_rows(self) -> None:
        rows = self.selected_rows()
        if not rows:
            if self.model().rowCount():
                rows = [self.model().rowCount() - 1]
            else:
                return
        self.model().remove_rows(rows)

    def add_column(self) -> None:
        cols = self.selected_columns()
        self.model().insert_column(cols[-1] + 1 if cols else self.model().columnCount())

    def delete_columns(self) -> None:
        cols = self.selected_columns() or ([self.model().columnCount() - 1]
                                           if self.model().columnCount() else [])
        if self.model().columnCount() - len(cols) < 1:
            self.status.emit("A table needs at least one column.")
            return
        self.model().remove_columns(cols)

    def _rename_column(self, col: int) -> None:
        m = self.model()
        if not m.has_header():
            self.status.emit("Turn on 'First row is header' to name columns.")
            return
        name, ok = QInputDialog.getText(self, "Rename column", "Column header:",
                                        text=m.header()[col])
        if ok:
            m.rename_column(col, name)

    # ------------------------------------------------------------- menus
    def _cell_menu(self, pos) -> None:
        idx = self.indexAt(pos)
        menu = QMenu(self)
        r = idx.row() if idx.isValid() else self.model().rowCount()
        c = idx.column() if idx.isValid() else self.model().columnCount()
        menu.addAction("Insert row above", lambda: self.model().insert_rows(r))
        menu.addAction("Insert row below", lambda: self.model().insert_rows(r + 1))
        menu.addAction("Delete selected row(s)", self.delete_rows)
        menu.addSeparator()
        menu.addAction("Insert column left", lambda: self.model().insert_column(c))
        menu.addAction("Insert column right", lambda: self.model().insert_column(c + 1))
        menu.addAction("Delete selected column(s)", self.delete_columns)
        menu.addSeparator()
        menu.addAction("Copy  (Ctrl+C)", self.copy_selection)
        menu.addAction("Paste  (Ctrl+V)", self.paste_block)
        menu.addAction("Clear cells  (Del)", self.clear_selection)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _header_menu(self, pos) -> None:
        m = self.model()
        col = self.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        spec = m.columns()[col]
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self._rename_column(col)).setEnabled(m.has_header())
        menu.addSeparator()
        for a, label in (("l", "Align left  (l)"), ("c", "Align center  (c)"),
                         ("r", "Align right  (r)")):
            act = QAction(label, menu, checkable=True, checked=spec.align == a)
            act.triggered.connect(lambda _=False, a=a: m.set_column_spec(
                col, ColumnSpec(a, spec.width, spec.include)))
            menu.addAction(act)
        act = QAction(f"Paragraph  p{{{spec.width}}}", menu, checkable=True,
                      checked=spec.align == "p")
        act.triggered.connect(lambda: m.set_column_spec(col, ColumnSpec("p", spec.width,
                                                                        spec.include)))
        menu.addAction(act)
        menu.addSeparator()
        inc = QAction("Include in LaTeX output", menu, checkable=True, checked=spec.include)
        inc.triggered.connect(lambda on: m.set_column_spec(col, ColumnSpec(spec.align,
                                                                           spec.width, on)))
        menu.addAction(inc)
        menu.addSeparator()
        menu.addAction("Insert column left", lambda: m.insert_column(col))
        menu.addAction("Insert column right", lambda: m.insert_column(col + 1))
        menu.addAction("Delete column", lambda: m.remove_columns([col])).setEnabled(
            m.columnCount() > 1)
        menu.exec(self.horizontalHeader().mapToGlobal(pos))

    # ------------------------------------------------------------- clipboard
    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.Paste):
            self.paste_block()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and \
                self.state() != QAbstractItemView.EditingState:
            self.clear_selection()
        else:
            super().keyPressEvent(event)

    def copy_selection(self) -> None:
        idxs = self.selectedIndexes()
        if not idxs:
            return
        rows = sorted({i.row() for i in idxs})
        cols = sorted({i.column() for i in idxs})
        data = self.model().rows()
        text = "\n".join("\t".join(data[r][c] for c in cols) for r in rows)
        QGuiApplication.clipboard().setText(text)
        self.status.emit(f"Copied {len(rows)}×{len(cols)} cells.")

    def paste_block(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            return
        cur = self.currentIndex()
        top = cur.row() if cur.isValid() else 0
        left = cur.column() if cur.isValid() else 0
        lines = text.rstrip("\r\n").split("\n")
        block = [ln.rstrip("\r").split("\t") for ln in lines]
        self.model().set_block(top, left, block)

    def clear_selection(self) -> None:
        self.model().clear_cells(self.selectedIndexes())
