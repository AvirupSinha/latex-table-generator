"""Rendered WYSIWYG preview (middle pane) and LaTeX code view (right pane).

The preview is drawn with QPainter using LaTeX's own metrics (\\tabcolsep,
\\arrayrulewidth, booktabs rule widths and spacing, \\arraystretch, caption
skips, \\textwidth ...) and the bundled Latin Modern font, so it looks like the
compiled table without needing a TeX installation or a web engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen,
                           QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from core.latex_generator import (FONT_SIZES, XCOLOR_RGB, ColumnSpec, TableOptions,
                                  build_row_sequence, effective_rotate, included_columns,
                                  stripe_rowcolors, width_to_pt)
from ui.style import Pane, code_font, preview_font_family

# --------------------------------------------------------------------------- #
# LaTeX metrics (pt)
# --------------------------------------------------------------------------- #
S = 10.0                       # internal font units per pt (fonts are sized in px)
PX_PER_PT = 96.0 / 72.27       # 100 % zoom = 96 dpi
ARRAYRULEWIDTH = 0.4
HEAVYRULE, LIGHTRULE = 0.8, 0.5          # booktabs .08em / .05em at 10pt
ABOVERULESEP, BELOWRULESEP = 1.72, 2.795  # booktabs .4ex / .65ex
ABOVECAPTIONSKIP, BELOWCAPTIONSKIP = 10.0, 0.0
PAGE_MX, PAGE_MY = 24.0, 22.0
CANVAS_PAD = 18                 # px of grey around the page

PAGE_LAYOUTS: dict[str, dict] = {
    "Article (single column)": dict(textwidth=345.0, columnwidth=345.0, columnsep=0.0,
                                    textheight=550.0, twocolumn=False),
    "1-inch margins (Letter)": dict(textwidth=469.75, columnwidth=469.75, columnsep=0.0,
                                    textheight=650.0, twocolumn=False),
    "Two-column (IEEE-like)": dict(textwidth=516.0, columnwidth=252.0, columnsep=12.0,
                                   textheight=682.0, twocolumn=True),
}


def _xcolor(spec: str) -> QColor | None:
    """'gray!10' -> QColor (white mixed in), 'white' -> None (no fill)."""
    if spec == "white":
        return None
    name, _, pct = spec.partition("!")
    r, g, b = XCOLOR_RGB.get(name, (0.5, 0.5, 0.5))
    t = (float(pct) if pct else 100.0) / 100.0
    return QColor.fromRgbF(r * t + (1 - t), g * t + (1 - t), b * t + (1 - t))


# --------------------------------------------------------------------------- #
# Layout model
# --------------------------------------------------------------------------- #
class _Fonts:
    def __init__(self, family: str, size_pt: float):
        self.reg = QFont(family)
        self.reg.setPixelSize(max(1, round(size_pt * S)))
        self.reg.setHintingPreference(QFont.PreferNoHinting)
        self.reg.setKerning(True)
        self.bold = QFont(self.reg)
        self.bold.setBold(True)
        self._m = (QFontMetricsF(self.reg), QFontMetricsF(self.bold))
        self._cache: dict[tuple[str, bool], float] = {}

    def width(self, text: str, bold: bool = False) -> float:
        key = (text, bold)
        w = self._cache.get(key)
        if w is None:
            w = self._m[bold].horizontalAdvance(text) / S
            self._cache[key] = w
        return w

    def font(self, bold: bool) -> QFont:
        return self.bold if bold else self.reg


_TYPESET = str.maketrans({"~": "\u02dc", "^": "\u02c6", "\n": " ", "\t": " "})


def _as_typeset(text: str, escaped: bool) -> str:
    """Approximate how LaTeX prints an escaped cell (raised ~ and ^, dash ligatures)."""
    text = str(text)
    if not escaped:
        return text.replace("\n", " ")
    return text.translate(_TYPESET).replace("---", "\u2014").replace("--", "\u2013")


def _wrap(text: str, width: float, measure) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        cand = f"{cur} {w}"
        if measure(cand) <= width:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


@dataclass
class _Row:
    y: float
    h: float
    baseline: float
    cells: list[list[str]]
    bold: bool
    fill: QColor | None


@dataclass
class _TableBox:
    w: float = 0.0
    h: float = 0.0
    col_x: list[float] = field(default_factory=list)      # content left edge
    col_w: list[float] = field(default_factory=list)      # content width
    aligns: list[str] = field(default_factory=list)
    vlines: list[float] = field(default_factory=list)
    vsegments: list[tuple[float, float]] = field(default_factory=list)
    rules: list[tuple[float, float]] = field(default_factory=list)   # (y, thickness)
    rows: list[_Row] = field(default_factory=list)
    baselineskip: float = 12.0


def build_table_box(header, rows, columns: list[ColumnSpec], opts: TableOptions,
                    fonts: _Fonts, baselineskip: float, lengths: dict[str, float],
                    em: float) -> _TableBox:
    idx = included_columns(columns)
    box = _TableBox(baselineskip=baselineskip)
    sep = opts.tabcolsep
    strut_h = 0.7 * baselineskip * opts.arraystretch
    strut_d = 0.3 * baselineskip * opts.arraystretch
    bold_header = header is not None and opts.bold_header

    def cells_of(row):
        n = len(row)
        return [_as_typeset(row[i] if i < n else "", opts.escape) for i in idx]

    head = cells_of(header) if header is not None else None
    body = [cells_of(r) for r in rows]

    # -- column widths --------------------------------------------------------
    widths, aligns = [], []
    for j, ci in enumerate(idx):
        spec = columns[ci]
        if spec.align == "p":
            w = width_to_pt(spec.width, lengths, em) or width_to_pt("3cm", lengths, em)
        else:
            w = 0.0
            if head is not None:
                w = fonts.width(head[j], bold_header)
            for r in body:
                cw = fonts.width(r[j])
                if cw > w:
                    w = cw
        widths.append(w)
        aligns.append(spec.align)

    # -- horizontal geometry ---------------------------------------------------
    x = 0.0
    if opts.outer_vlines:
        box.vlines.append(x)
        x += ARRAYRULEWIDTH
    for j, w in enumerate(widths):
        box.col_x.append(x + sep)
        x += sep + w + sep
        if opts.inner_vlines and j < len(widths) - 1:
            box.vlines.append(x)
            x += ARRAYRULEWIDTH
    if opts.outer_vlines:
        box.vlines.append(x)
        x += ARRAYRULEWIDTH
    box.w, box.col_w, box.aligns = x, widths, aligns

    # -- vertical geometry -----------------------------------------------------
    seq = build_row_sequence(len(body), head is not None, opts)
    stripe = stripe_rowcolors(opts, head is not None) if opts.striped else None
    y, rownum = 0.0, 0
    for kind, val in seq:
        if kind == "rule":
            if val == "hline":
                box.rules.append((y, ARRAYRULEWIDTH))
                box.vsegments.append((y, y + ARRAYRULEWIDTH))
                y += ARRAYRULEWIDTH
            elif val == "toprule":
                box.rules.append((y, HEAVYRULE))
                y += HEAVYRULE + BELOWRULESEP
            elif val == "midrule":
                y += ABOVERULESEP
                box.rules.append((y, LIGHTRULE))
                y += LIGHTRULE + BELOWRULESEP
            else:  # bottomrule
                y += ABOVERULESEP
                box.rules.append((y, HEAVYRULE))
                y += HEAVYRULE
            continue
        rownum += 1
        is_head = val == -1
        texts = head if is_head else body[val]
        cells = []
        n_lines = 1
        for j, t in enumerate(texts):
            if aligns[j] == "p":
                lines = _wrap(t, widths[j], lambda s, b=is_head and bold_header:
                              fonts.width(s, b))
                n_lines = max(n_lines, len(lines))
                cells.append(lines)
            else:
                cells.append([t])
        depth = max(strut_d, (n_lines - 1) * baselineskip + 0.3 * baselineskip)
        h = strut_h + depth
        fill = None
        if stripe and rownum >= stripe[0]:
            fill = _xcolor(stripe[1] if rownum % 2 == 1 else stripe[2])
        box.rows.append(_Row(y, h, y + strut_h, cells, is_head and bold_header, fill))
        box.vsegments.append((y, y + h))
        y += h
    box.h = y
    return box


# --------------------------------------------------------------------------- #
# Preview canvas
# --------------------------------------------------------------------------- #
class PreviewCanvas(QWidget):
    """Paints a LaTeX-looking page containing the table float."""

    messages = Signal(list)       # list[(level, text)]
    zoomChanged = Signal(float)
    userZoomed = Signal()         # zoom changed by the user (Ctrl+wheel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._zoom = 1.0
        self._page = next(iter(PAGE_LAYOUTS))
        self._canvas_color = QColor("#e4e6ea")
        self._data = None
        self._lay = None

    # ------------------------------------------------------------- public API
    def set_content(self, header, rows, columns, opts: TableOptions, total_rows: int) -> None:
        self._data = (header, rows, [ColumnSpec(c.align, c.width, c.include) for c in columns],
                      opts, total_rows)
        self._relayout()

    def set_page_layout(self, name: str) -> None:
        self._page = name
        self._relayout()

    def set_canvas_color(self, color: str) -> None:
        self._canvas_color = QColor(color)
        self.update()

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, z: float) -> None:
        z = max(0.25, min(4.0, z))
        if abs(z - self._zoom) > 1e-6:
            self._zoom = z
            self._update_size()
            self.zoomChanged.emit(z)

    def fit_zoom(self, viewport_width: int) -> float:
        page_w = self._lay["page_w"] if self._lay else \
            PAGE_LAYOUTS[self._page]["textwidth"] + 2 * PAGE_MX
        return min(2.5, (viewport_width - 2 * CANVAS_PAD) / (page_w * PX_PER_PT))

    # ------------------------------------------------------------- layout
    def _relayout(self) -> None:
        if self._data is None:
            return
        header, rows, columns, opts, total_rows = self._data
        page = PAGE_LAYOUTS[self._page]
        tw, cw, th = page["textwidth"], page["columnwidth"], page["textheight"]
        rot = effective_rotate(opts)
        line_w = cw if (page["twocolumn"] and opts.environment != "table*") else tw
        float_w = th if rot == "sideways" else line_w
        lengths = {"textwidth": tw, "columnwidth": cw, "textheight": th, "linewidth": float_w}

        size, bs = FONT_SIZES.get(opts.font_size or "normalsize")
        fonts = _Fonts(preview_font_family(), size)
        msgs: list[tuple[str, str]] = []

        idx = included_columns(columns)
        empty = not idx or (header is None and not rows)
        box = None if empty else build_table_box(header, rows, columns, opts, fonts, bs,
                                                 lengths, size)

        # Table transform: \resizebox (inner) then \rotatebox (outer)
        scale = 1.0
        bw = bh = 0.0
        if box:
            if opts.resize and box.w > 0:
                target = opts.resize_fraction * lengths.get(opts.resize_target.lstrip("\\"), tw)
                scale = target / box.w
            bw, bh = box.w * scale, box.h * scale
            if rot == "rotatebox":
                bw, bh = bh, bw

        # Caption
        floating = opts.environment != "none"
        cap_lines: list[tuple[list[str], float, float, bool]] = []  # words, x, extra, justify
        caption = opts.caption.strip() if floating else ""
        if caption:
            text = f"Table 1: {_as_typeset(caption, opts.escape)}"
            cwid = fonts.width(text)
            if cwid <= float_w:
                cap_lines.append(([text], (float_w - cwid) / 2, 0.0, False))
            else:
                lines = _wrap(text, float_w, fonts.width)
                for k, ln in enumerate(lines):
                    words = ln.split()
                    last = k == len(lines) - 1
                    extra = 0.0
                    if not last and len(words) > 1:
                        natural = sum(fonts.width(w) for w in words)
                        extra = (float_w - natural) / (len(words) - 1)
                    cap_lines.append((words if not last else [ln], 0.0, extra, not last))

        # Float vertical stacking
        y = 0.0
        cap_y = table_y = 0.0
        cap_h = len(cap_lines) * bs
        if cap_lines and opts.caption_pos == "top":
            y += ABOVECAPTIONSKIP
            cap_y = y
            y += cap_h + BELOWCAPTIONSKIP
        table_y = y
        y += bh if box else 3 * bs
        if cap_lines and opts.caption_pos == "bottom":
            y += ABOVECAPTIONSKIP
            cap_y = y
            y += cap_h
        float_h = y

        # Horizontal placement of the table inside the float
        overflow = bw - float_w
        if overflow > 0.05 or opts.table_align == "left":
            table_x = 0.0
        elif opts.table_align == "right":
            table_x = float_w - bw
        else:
            table_x = (float_w - bw) / 2

        # Page
        page_w = tw + 2 * PAGE_MX
        if rot == "sideways":
            page_h = 2 * PAGE_MY + max(th, bw)
            float_x = max(0.0, (tw - float_h) / 2)
        else:
            page_h = 2 * PAGE_MY + max(float_h, 60.0)
            float_x = 0.0

        self._lay = dict(
            page_w=page_w, page_h=page_h, tw=tw, cw=cw, colsep=page["columnsep"],
            twocolumn=page["twocolumn"], rot=rot, float_w=float_w, float_h=float_h,
            float_x=float_x, cap_lines=cap_lines, cap_y=cap_y, table_x=table_x,
            table_y=table_y, box=box, scale=scale, bw=bw, bh=bh, fonts=fonts, bs=bs,
            overflow=overflow if box else 0.0, empty=empty, line_w=line_w,
        )

        # Messages
        if empty:
            msgs.append(("info", "Nothing to preview yet — load a CSV or add rows/columns."))
        if box and overflow > 0.05:
            what = r"\textheight" if rot == "sideways" else r"\linewidth"
            msgs.append(("warn", f"Table is {overflow:.1f}pt wider than {what} "
                                 f"({float_w:.0f}pt). Try \\resizebox, a smaller font, "
                                 "less column spacing or p{} columns."))
        if box and rot == "rotatebox" and bh > th:
            msgs.append(("warn", f"Rotated table is {bh - th:.0f}pt taller than \\textheight."))
        if total_rows > len(rows):
            msgs.append(("info", f"Preview shows the first {len(rows):,} of {total_rows:,} rows; "
                                 "the LaTeX code contains all rows."))
        if not opts.escape:
            msgs.append(("info", "Raw LaTeX mode: cells are shown as typed (markup not rendered)."))
        self.messages.emit(msgs)
        self._update_size()

    def _update_size(self) -> None:
        if not self._lay:
            return
        k = PX_PER_PT * self._zoom
        self.setMinimumSize(int(self._lay["page_w"] * k) + 2 * CANVAS_PAD,
                            int(self._lay["page_h"] * k) + 2 * CANVAS_PAD)
        self.update()

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._canvas_color)
        lay = self._lay
        if not lay:
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        k = PX_PER_PT * self._zoom
        page_px_w = lay["page_w"] * k
        ox = max(CANVAS_PAD, (self.width() - page_px_w) / 2)
        oy = CANVAS_PAD

        # Paper with soft shadow
        page_rect = QRectF(ox, oy, page_px_w, lay["page_h"] * k)
        for i, a in ((4, 18), (2, 28), (1, 40)):
            p.fillRect(page_rect.adjusted(-i + 1, -i + 2, i - 1, i + 2), QColor(0, 0, 0, a))
        p.fillRect(page_rect, Qt.white)

        p.translate(ox, oy)
        p.scale(k, k)
        p.translate(PAGE_MX, PAGE_MY)
        dpr = self.devicePixelRatioF()
        px = 1.0 / (k * dpr)          # one device pixel, in pt

        self._paint_guides(p, lay, px)

        p.save()
        if lay["rot"] == "sideways":
            # rotate the whole float counter-clockwise (bottom of table to the right)
            p.translate(lay["float_x"], lay["float_w"])
            p.rotate(-90)
        else:
            p.translate(lay["float_x"], 0)
        self._paint_float(p, lay, px, event.rect())
        p.restore()

    def _paint_guides(self, p: QPainter, lay: dict, px: float) -> None:
        h = lay["page_h"] - 2 * PAGE_MY
        pen = QPen(QColor(120, 140, 210, 90))
        pen.setWidthF(px)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        xs = [0.0, lay["tw"]]
        if lay["twocolumn"]:
            xs += [lay["cw"], lay["cw"] + lay["colsep"]]
        for x in xs:
            p.drawLine(QPointF(x, -PAGE_MY * 0.5), QPointF(x, h + PAGE_MY * 0.5))

    def _paint_float(self, p: QPainter, lay: dict, px: float, clip: QRect) -> None:
        fonts: _Fonts = lay["fonts"]
        bs = lay["bs"]
        # Caption
        p.setPen(Qt.black)
        y = lay["cap_y"]
        for words, x, extra, justify in lay["cap_lines"]:
            base = y + 0.7 * bs
            if justify:
                cx = x
                for w in words:
                    self._text(p, cx, base, w, fonts.reg)
                    cx += fonts.width(w) + extra
            else:
                self._text(p, x, base, words[0], fonts.reg)
            y += bs

        box: _TableBox = lay["box"]
        if box is None:
            f = QFont(fonts.reg)
            f.setItalic(True)
            p.setPen(QColor(150, 150, 150))
            self._text(p, 0, lay["table_y"] + 1.6 * bs, "(empty table)", f)
            return

        p.save()
        p.translate(lay["table_x"], lay["table_y"])
        if lay["rot"] == "rotatebox":
            p.translate(0, lay["bh"])
            p.rotate(-90)
        p.scale(lay["scale"], lay["scale"])
        unit = px / lay["scale"]  # one device pixel in table units
        visible = p.transform().inverted()[0].mapRect(QRectF(clip))
        self._paint_table(p, box, fonts, unit, visible)
        p.restore()

        # Overflow marker
        if lay["overflow"] > 0.05 and lay["rot"] != "rotatebox":
            p.fillRect(QRectF(lay["float_w"], lay["table_y"], lay["overflow"], lay["bh"]),
                       QColor(220, 40, 40, 38))
            pen = QPen(QColor(210, 40, 40, 200))
            pen.setWidthF(1.5 * px)
            p.setPen(pen)
            p.drawLine(QPointF(lay["float_w"], lay["table_y"] - 4),
                       QPointF(lay["float_w"], lay["table_y"] + lay["bh"] + 4))

    def _paint_table(self, p: QPainter, box: _TableBox, fonts: _Fonts, unit: float,
                     visible: QRectF) -> None:
        top, bottom = visible.top() - 20, visible.bottom() + 20
        p.setRenderHint(QPainter.Antialiasing, False)
        for row in box.rows:
            if row.fill is not None and row.y + row.h >= top and row.y <= bottom:
                p.fillRect(QRectF(0, row.y, box.w, row.h), row.fill)
        black = QColor(0, 0, 0)
        for y, t in box.rules:
            p.fillRect(QRectF(0, y, box.w, max(t, unit)), black)
        vw = max(ARRAYRULEWIDTH, unit)
        for x in box.vlines:
            for y0, y1 in box.vsegments:
                if y1 >= top and y0 <= bottom:
                    p.fillRect(QRectF(x, y0, vw, y1 - y0), black)
        p.setRenderHint(QPainter.Antialiasing, True)

        p.setPen(black)
        bs = box.baselineskip
        for row in box.rows:
            if row.y + row.h < top or row.y > bottom:
                continue
            font = fonts.font(row.bold)
            for j, lines in enumerate(row.cells):
                a, cx, cw = box.aligns[j], box.col_x[j], box.col_w[j]
                for k, text in enumerate(lines):
                    if not text:
                        continue
                    if a in ("l", "p"):
                        x = cx
                    else:
                        tw = fonts.width(text, row.bold)
                        x = cx + (cw - tw) / 2 if a == "c" else cx + cw - tw
                    self._text(p, x, row.baseline + k * bs, text, font)

    @staticmethod
    def _text(p: QPainter, x: float, baseline: float, text: str, font: QFont) -> None:
        p.save()
        p.translate(x, baseline)
        p.scale(1 / S, 1 / S)
        p.setFont(font)
        p.drawText(QPointF(0, 0), text)
        p.restore()

    # ------------------------------------------------------------- interaction
    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            step = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            self.set_zoom(self._zoom * step)
            self.userZoomed.emit()
            event.accept()
        else:
            super().wheelEvent(event)


class PreviewPane(Pane):
    """Middle pane: toolbar (page layout, zoom), message banner and the canvas."""

    def __init__(self, parent=None):
        super().__init__("Preview", "rendered")
        self.page_combo = QComboBox()
        for name in PAGE_LAYOUTS:
            self.page_combo.addItem(name)
        self.page_combo.setToolTip("Page geometry used for \\textwidth / \\columnwidth")
        self.header.addWidget(self.page_combo)

        self.zoom_out = QToolButton(text="−")
        self.zoom_label = QPushButton("100%")
        self.zoom_label.setToolTip("Fit to width")
        self.zoom_label.setFixedWidth(58)
        self.zoom_in = QToolButton(text="+")
        for b in (self.zoom_out, self.zoom_in):
            b.setFixedWidth(28)
        self.header.addWidget(self.zoom_out)
        self.header.addWidget(self.zoom_label)
        self.header.addWidget(self.zoom_in)

        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        banner_wrap = QWidget()
        bl = QVBoxLayout(banner_wrap)
        bl.setContentsMargins(8, 6, 8, 0)
        bl.addWidget(self.banner)
        self.body.addWidget(banner_wrap)

        self.canvas = PreviewCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.body.addWidget(self.scroll, 1)

        self._auto_fit = True   # follow the pane width until the user zooms manually
        self.page_combo.currentTextChanged.connect(self._page_changed)
        self.zoom_in.clicked.connect(lambda: self.zoom_by(1.15))
        self.zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.15))
        self.zoom_label.clicked.connect(self.fit_width)
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self.canvas.userZoomed.connect(lambda: setattr(self, "_auto_fit", False))
        self.canvas.messages.connect(self._show_messages)
        self.scroll.installEventFilter(self)

    def set_theme(self, theme: dict) -> None:
        self.canvas.set_canvas_color(theme["canvas"])

    def zoom_by(self, factor: float) -> None:
        self._auto_fit = False
        self.canvas.set_zoom(self.canvas.zoom() * factor)

    def fit_width(self) -> None:
        self._auto_fit = True
        self._refit()

    def _refit(self) -> None:
        # Assume a vertical scrollbar is present so the zoom never oscillates.
        avail = self.scroll.width() - self.scroll.verticalScrollBar().sizeHint().width() - 4
        if avail > 50:
            self.canvas.set_zoom(self.canvas.fit_zoom(avail))

    def _zoom_changed(self, z: float) -> None:
        self.zoom_label.setText(f"{z * 100:.0f}%")
        self.zoom_label.setToolTip("Fit to width" + ("  (active)" if self._auto_fit else ""))

    def eventFilter(self, obj, event) -> bool:
        if obj is self.scroll and event.type() == event.Type.Resize and self._auto_fit:
            QTimer.singleShot(0, self._refit)
        return super().eventFilter(obj, event)

    def _page_changed(self, name: str) -> None:
        self.canvas.set_page_layout(name)
        if self._auto_fit:
            self._refit()

    def _show_messages(self, msgs: list) -> None:
        if not msgs:
            self.banner.hide()
            return
        level = "warn" if any(l == "warn" for l, _ in msgs) else msgs[0][0]
        self.banner.setProperty("level", level)
        self.banner.setText("\n".join(("⚠ " if l == "warn" else "ⓘ ") + t for l, t in msgs))
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.show()


# --------------------------------------------------------------------------- #
# LaTeX code view
# --------------------------------------------------------------------------- #
class LatexHighlighter(QSyntaxHighlighter):
    def __init__(self, document, theme: dict):
        super().__init__(document)
        self.set_theme(theme, rehighlight=False)

    def set_theme(self, t: dict, rehighlight: bool = True) -> None:
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(italic)
            return f
        self._rules = [
            (re.compile(r"[{}\[\]]"), 0, fmt(t["hl_brace"])),
            (re.compile(r"(?<=[{\[!])\d*\.?\d+(?:pt|cm|mm|in|em|ex|bp)?(?=[}\]\\])"), 0,
             fmt(t["hl_number"])),
            (re.compile(r"\\[A-Za-z@]+\*?"), 0, fmt(t["hl_command"])),
            (re.compile(r"\\(?:toprule|midrule|bottomrule|hline|cmidrule)\b"), 0,
             fmt(t["hl_rule"], bold=True)),
            (re.compile(r"\\(?:begin|end)\{([^}]*)\}"), 1, fmt(t["hl_env"], bold=True)),
            (re.compile(r"\\[&%$#_{}]"), 0, fmt(t["hl_escape"])),
            (re.compile(r"(?<!\\)&"), 0, fmt(t["hl_amp"], bold=True)),
            (re.compile(r"\\\\"), 0, fmt(t["hl_newline"], bold=True)),
            (re.compile(r"(?<!\\)%.*$"), 0, fmt(t["hl_comment"], italic=True)),
        ]
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for rx, group, f in self._rules:
            for m in rx.finditer(text):
                s, e = m.span(group)
                self.setFormat(s, e - s, f)


class _LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """Read-only code view with a line-number gutter."""

    HIGHLIGHT_LIMIT = 4000   # lines; larger outputs are shown without colours

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(code_font())
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self._gutter = _LineNumbers(self)
        self._theme = theme
        self._last_code = ""
        self.highlighter = LatexHighlighter(self.document(), theme)
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._update_gutter)
        self._update_margins()

    def set_theme(self, theme: dict) -> None:
        self._theme = theme
        self.setStyleSheet(f"QPlainTextEdit {{ background: {theme['code_bg']}; "
                           f"color: {theme['code_text']}; border: none; "
                           f"selection-background-color: {theme['selection']}; }}")
        self.highlighter.set_theme(theme, rehighlight=self.highlighter.document() is not None)
        self._gutter.update()

    def set_code(self, code: str) -> None:
        if code == self._last_code:
            return
        self._last_code = code
        bar_v, bar_h = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
        big = code.count("\n") > self.HIGHLIGHT_LIMIT
        if big and self.highlighter.document() is not None:
            self.highlighter.setDocument(None)
        self.setPlainText(code)
        if not big and self.highlighter.document() is None:
            self.highlighter.setDocument(self.document())
        self.verticalScrollBar().setValue(bar_v)
        self.horizontalScrollBar().setValue(bar_h)

    def highlighting_active(self) -> bool:
        return self.highlighter.document() is not None

    # gutter --------------------------------------------------------------
    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * max(2, digits)

    def _update_margins(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        p = QPainter(self._gutter)
        p.fillRect(event.rect(), QColor(self._theme["gutter_bg"]))
        p.setPen(QColor(self._theme["gutter"]))
        p.setFont(self.font())
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        h = self.fontMetrics().height()
        w = self._gutter.width() - 8
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                p.drawText(0, top, w, h, Qt.AlignRight | Qt.AlignVCenter, str(num + 1))
            block = block.next()
            top += round(self.blockBoundingRect(block).height()) if block.isValid() else h
            num += 1


class CodePane(Pane):
    """Right pane: highlighted LaTeX, one-click copy and save."""

    status = Signal(str)

    def __init__(self, theme: dict, parent=None):
        super().__init__("LaTeX", "")
        self.editor = CodeEditor(theme)
        self.body.addWidget(self.editor, 1)

        footer = QWidget()
        footer.setObjectName("PaneFooter")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(10, 8, 10, 10)
        fl.setSpacing(6)
        self.notes = QLabel()
        self.notes.setObjectName("Banner")
        self.notes.setProperty("level", "warn")
        self.notes.setWordWrap(True)
        self.notes.hide()
        fl.addWidget(self.notes)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setObjectName("Primary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("Copy the LaTeX code  (Ctrl+Shift+C)")
        self.save_btn = QPushButton("Save .tex…")
        row.addWidget(self.copy_btn, 1)
        row.addWidget(self.save_btn)
        fl.addLayout(row)
        self.body.addWidget(footer)

        self._code = ""
        self.copy_btn.clicked.connect(self.copy)
        self.save_btn.clicked.connect(self.save)

    def set_theme(self, theme: dict) -> None:
        self.editor.set_theme(theme)

    def set_code(self, code: str, notes: list[str]) -> None:
        self._code = code
        self.editor.set_code(code)
        n_lines = code.count("\n")
        size = len(code.encode("utf-8"))
        size_s = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
        extra = "" if self.editor.highlighting_active() else " · highlighting off (large)"
        self.subtitle.setText(f"{n_lines:,} lines · {size_s}{extra}")
        if notes:
            self.notes.setText("\n".join("ⓘ " + n for n in notes))
            self.notes.show()
        else:
            self.notes.hide()

    def code(self) -> str:
        return self._code

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self._code)
        self.copy_btn.setText("✓  Copied!")
        self.status.emit(f"Copied {self._code.count(chr(10)):,} lines of LaTeX to the clipboard.")
        QTimer.singleShot(1400, lambda: self.copy_btn.setText("Copy to Clipboard"))

    def save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save LaTeX", "table.tex",
                                              "LaTeX files (*.tex);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._code)
            self.status.emit(f"Saved {path}")
        except OSError as exc:
            self.status.emit(f"Could not save: {exc}")
