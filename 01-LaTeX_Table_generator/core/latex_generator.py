"""LaTeX table code generation.

This module is GUI-independent.  The rendered preview imports the same
helpers (``build_row_sequence``, ``stripe_rowcolors``, ``width_to_pt`` ...) so
the picture and the code can never disagree about where rules go.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace

# --------------------------------------------------------------------------- #
# Constants shared with the UI / preview
# --------------------------------------------------------------------------- #
#: LaTeX size command -> (font size pt, baselineskip pt) for a 10pt document.
FONT_SIZES: dict[str, tuple[float, float]] = {
    "tiny": (5.0, 6.0),
    "scriptsize": (7.0, 8.0),
    "footnotesize": (8.0, 9.5),
    "small": (9.0, 11.0),
    "normalsize": (10.0, 12.0),
    "large": (12.0, 14.0),
    "Large": (14.4, 18.0),
    "LARGE": (17.28, 22.0),
    "huge": (20.74, 25.0),
    "Huge": (24.88, 30.0),
}

#: xcolor base colours (name -> RGB 0..1); used for stripes and their preview.
XCOLOR_RGB: dict[str, tuple[float, float, float]] = {
    "gray": (0.5, 0.5, 0.5),
    "blue": (0.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0),
    "teal": (0.0, 0.5, 0.5),
    "green": (0.0, 1.0, 0.0),
    "lime": (0.75, 1.0, 0.0),
    "olive": (0.5, 0.5, 0.0),
    "yellow": (1.0, 1.0, 0.0),
    "orange": (1.0, 0.5, 0.0),
    "red": (1.0, 0.0, 0.0),
    "pink": (1.0, 0.75, 0.75),
    "magenta": (1.0, 0.0, 1.0),
    "purple": (0.75, 0.0, 0.25),
    "violet": (0.5, 0.0, 0.5),
    "brown": (0.75, 0.5, 0.25),
}

RESIZE_TARGETS = (r"\textwidth", r"\linewidth", r"\columnwidth", r"\textheight")
PLACEMENTS = ("htbp", "!htbp", "h", "t", "b", "p", "H", "")
ALIGNMENTS = ("l", "c", "r", "p")

_UNIT_PT = {
    "pt": 1.0, "bp": 72.27 / 72.0, "in": 72.27, "cm": 72.27 / 2.54,
    "mm": 72.27 / 25.4, "pc": 12.0, "em": 10.0, "ex": 4.3,
}
_ABS_WIDTH_RE = re.compile(r"^\s*(\d*\.?\d+)\s*(pt|bp|in|cm|mm|pc|em|ex)\s*$")
_REL_WIDTH_RE = re.compile(
    r"^\s*(\d*\.?\d*)\s*\\(textwidth|linewidth|columnwidth|textheight)\s*$")

# LaTeX special characters -> safe replacements (single pass, no double escaping).
_ESCAPES = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\\": r"\textbackslash{}",
    # Not special, but print as wrong glyphs with the default OT1 font encoding:
    "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}",
    "\n": " ", "\r": "", "\t": " ",
}
_ESCAPE_TABLE = str.maketrans(_ESCAPES)
_CLEAN_TABLE = str.maketrans({"\n": " ", "\r": "", "\t": " "})


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class ColumnSpec:
    align: str = "l"          # one of "l", "c", "r", "p"
    width: str = "3cm"        # only used when align == "p"
    include: bool = True      # excluded columns are left out of code and preview

    @property
    def width_valid(self) -> bool:
        return is_valid_width(self.width)

    def latex(self) -> str:
        if self.align == "p":
            return f"p{{{self.width.strip() if self.width_valid else '3cm'}}}"
        return self.align if self.align in ("l", "c", "r") else "l"


@dataclass
class TableOptions:
    # Structure
    booktabs: bool = True              # \toprule/\midrule/\bottomrule vs \hline
    top_bottom_rules: bool = True      # outer horizontal border
    outer_vlines: bool = False         # outer vertical border  |l c r|
    inner_vlines: bool = False         # vertical lines between columns
    hlines: str = "header"             # "all" | "header" | "none"
    # Design
    font_size: str = ""                # "" = document default, or a FONT_SIZES key
    table_align: str = "center"        # "center" | "left" | "right"
    bold_header: bool = True
    rotate: str = "none"               # "none" | "rotatebox" | "sideways"
    resize: bool = False
    resize_target: str = r"\textwidth"
    resize_fraction: float = 1.0
    # Caption & label
    caption: str = ""
    caption_pos: str = "top"           # "top" | "bottom"
    label: str = ""                    # without the "tab:" prefix
    # Advanced
    striped: bool = False
    stripe_color: str = "gray"
    stripe_intensity: int = 10         # percent, xcolor "gray!10"
    tabcolsep: float = 6.0             # pt (LaTeX default 6pt)
    arraystretch: float = 1.0
    environment: str = "table"         # "table" | "table*" | "none"
    placement: str = "htbp"
    escape: bool = True
    align_code: bool = True            # pad cells so the & line up in the source
    package_hints: bool = True
    standalone: bool = False           # emit a full compilable document

    def copy(self, **changes) -> "TableOptions":
        return replace(self, **changes)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GenerateResult:
    code: str
    packages: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


#: One-click style presets (only the structural fields they set).
PRESETS: dict[str, dict] = {
    "Academic (booktabs)": dict(booktabs=True, top_bottom_rules=True, outer_vlines=False,
                                inner_vlines=False, hlines="header", striped=False),
    "Full grid": dict(booktabs=False, top_bottom_rules=True, outer_vlines=True,
                      inner_vlines=True, hlines="all", striped=False),
    "Boxed, header rule": dict(booktabs=False, top_bottom_rules=True, outer_vlines=True,
                               inner_vlines=False, hlines="header", striped=False),
    "Striped rows": dict(booktabs=True, top_bottom_rules=True, outer_vlines=False,
                         inner_vlines=False, hlines="header", striped=True),
    "Minimal (header rule only)": dict(booktabs=True, top_bottom_rules=False,
                                       outer_vlines=False, inner_vlines=False,
                                       hlines="header", striped=False),
    "No borders": dict(booktabs=False, top_bottom_rules=False, outer_vlines=False,
                       inner_vlines=False, hlines="none", striped=False),
}


# --------------------------------------------------------------------------- #
# Helpers (shared with the preview)
# --------------------------------------------------------------------------- #
def escape_latex(text: str) -> str:
    r"""Escape ``& % $ # _ { } ~ ^ \`` (and ``< > |``) for use in LaTeX text."""
    return str(text).translate(_ESCAPE_TABLE)


def clean_cell(text: str, escape: bool) -> str:
    return str(text).translate(_ESCAPE_TABLE if escape else _CLEAN_TABLE)


def is_valid_width(width: str) -> bool:
    return bool(_ABS_WIDTH_RE.match(width or "") or _REL_WIDTH_RE.match(width or ""))


def width_to_pt(width: str, lengths: dict[str, float], em: float = 10.0) -> float | None:
    """Convert a LaTeX width ("3cm", "0.3\\linewidth") to points, or ``None``."""
    m = _ABS_WIDTH_RE.match(width or "")
    if m:
        value, unit = float(m.group(1)), m.group(2)
        if unit == "em":
            return value * em
        if unit == "ex":
            return value * em * 0.43
        return value * _UNIT_PT[unit]
    m = _REL_WIDTH_RE.match(width or "")
    if m:
        factor = float(m.group(1)) if m.group(1) not in ("", ".") else 1.0
        return factor * lengths.get(m.group(2), 345.0)
    return None


def sanitize_label(label: str) -> str:
    label = (label or "").strip()
    if label.lower().startswith("tab:"):
        label = label[4:]
    label = re.sub(r"\s+", "-", label)
    return re.sub(r"[^A-Za-z0-9:_\-.]", "", label)


def included_columns(columns: list[ColumnSpec]) -> list[int]:
    return [i for i, c in enumerate(columns) if c.include]


def column_spec_string(columns: list[ColumnSpec], opts: TableOptions) -> str:
    cols = [columns[i].latex() for i in included_columns(columns)]
    inner = "|" if opts.inner_vlines else ""
    outer = "|" if opts.outer_vlines else ""
    return outer + inner.join(cols) + outer


def build_row_sequence(n_body: int, has_header: bool, opts: TableOptions) -> list[tuple]:
    """Ordered plan of the tabular body.

    Items are ``("row", i)`` (``i == -1`` is the header row) or
    ``("rule", kind)`` with kind in ``hline/toprule/midrule/bottomrule``.
    """
    bt = opts.booktabs
    seq: list[tuple] = []
    if opts.top_bottom_rules:
        seq.append(("rule", "toprule" if bt else "hline"))
    rows = ([-1] if has_header else []) + list(range(n_body))
    inner = "midrule" if bt else "hline"
    for k, r in enumerate(rows):
        seq.append(("row", r))
        if k == len(rows) - 1:
            break
        if opts.hlines == "all" or (opts.hlines == "header" and r == -1):
            seq.append(("rule", inner))
    if opts.top_bottom_rules:
        seq.append(("rule", "bottomrule" if bt else "hline"))
    return seq


def stripe_color_spec(opts: TableOptions) -> str:
    return f"{opts.stripe_color}!{int(opts.stripe_intensity)}"


def stripe_rowcolors(opts: TableOptions, has_header: bool) -> tuple[int, str, str]:
    r"""Arguments for ``\rowcolors{start}{odd}{even}``.

    Chosen so the header is never coloured and the 2nd, 4th, ... body rows are
    shaded.  xcolor numbers rows from 1 (the header counts) and applies the
    *odd* colour to odd row numbers - the preview uses the same rule.
    """
    shade = stripe_color_spec(opts)
    if has_header:
        return 2, shade, "white"
    return 1, "white", shade


def effective_rotate(opts: TableOptions) -> str:
    # sidewaystable needs a float; without one fall back to \rotatebox.
    if opts.rotate == "sideways" and opts.environment == "none":
        return "rotatebox"
    return opts.rotate


def required_packages(opts: TableOptions, has_rules: bool = True) -> list[tuple[str, str]]:
    """List of ``(package, options)`` needed by the generated code."""
    pk: list[tuple[str, str]] = []
    if opts.booktabs and has_rules:
        pk.append(("booktabs", ""))
    rot = effective_rotate(opts)
    if opts.resize or rot == "rotatebox":
        pk.append(("graphicx", ""))
    if rot == "sideways":
        pk.append(("rotating", ""))
    if opts.striped:
        pk.append(("xcolor", "table"))
    if opts.placement == "H" and opts.environment != "none" and rot != "sideways":
        pk.append(("float", ""))
    return pk


def _usepackage(name: str, options: str) -> str:
    return rf"\usepackage[{options}]{{{name}}}" if options else rf"\usepackage{{{name}}}"


def _fmt_num(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def generate_latex(header: list[str] | None, rows: list[list[str]],
                   columns: list[ColumnSpec], opts: TableOptions) -> GenerateResult:
    """Generate LaTeX table code.

    Args:
        header: header cells, or ``None`` when the data has no header row.
        rows: body rows (lists of strings, may be ragged).
        columns: one :class:`ColumnSpec` per data column.
        opts: styling options.
    """
    notes: list[str] = []
    idx = included_columns(columns)
    if not idx:
        return GenerateResult("% No columns selected - enable at least one column.",
                              notes=["All columns are excluded."])

    esc = opts.escape
    has_header = header is not None

    # ---- cell matrix (escaped, header bolded) --------------------------------
    def pick(row: list[str]) -> list[str]:
        n = len(row)
        return [clean_cell(row[i], esc) if i < n else "" for i in idx]

    out_rows = [pick(r) for r in rows]
    out_header: list[str] | None = None
    if has_header:
        out_header = pick(header)
        if opts.bold_header:
            out_header = [rf"\textbf{{{c}}}" if c else "" for c in out_header]

    if opts.align_code:
        widths = [0] * len(idx)
        for r in ([out_header] if out_header else []) + out_rows:
            for j, c in enumerate(r):
                if len(c) > widths[j]:
                    widths[j] = len(c)
        def join(cells: list[str]) -> str:
            last = len(cells) - 1
            return " & ".join(c if j == last else c.ljust(widths[j])
                              for j, c in enumerate(cells)).rstrip()
    else:
        def join(cells: list[str]) -> str:
            return " & ".join(cells)

    # ---- tabular body ---------------------------------------------------------
    seq = build_row_sequence(len(out_rows), has_header, opts)
    has_rules = any(item[0] == "rule" for item in seq)
    last_row_pos = max((k for k, it in enumerate(seq) if it[0] == "row"), default=-1)
    body: list[str] = []
    for k, item in enumerate(seq):
        if item[0] == "rule":
            body.append("\\" + item[1])
            continue
        cells = out_header if item[1] == -1 else out_rows[item[1]]
        line = join(cells)
        # Every row ends with \\ except a final row with no rule after it.
        if k != last_row_pos or k + 1 < len(seq):
            line += r" \\"
        body.append(line)
    if not out_rows and not has_header:
        notes.append("The table has no rows.")

    # ---- wrappers -------------------------------------------------------------
    I = "  "
    rot = effective_rotate(opts)
    env = opts.environment
    lines: list[str] = []
    packages = required_packages(opts, has_rules)

    if opts.standalone:
        lines.append(r"\documentclass{article}")
        lines += [_usepackage(p, o) for p, o in packages]
        lines += ["", r"\begin{document}", ""]
    elif opts.package_hints and packages:
        lines.append("% Add to your preamble:")
        lines += ["% " + _usepackage(p, o) for p, o in packages]

    if env == "none":
        group = {"center": "center", "right": "flushright"}.get(opts.table_align, "flushleft")
        lines.append(rf"\begin{{{group}}}")
        close_env = rf"\end{{{group}}}"
    else:
        name = ("sidewaystable" + ("*" if env == "table*" else "")) if rot == "sideways" else env
        place = f"[{opts.placement}]" if opts.placement and rot != "sideways" else ""
        lines.append(rf"\begin{{{name}}}{place}")
        close_env = rf"\end{{{name}}}"
        if opts.table_align == "center":
            lines.append(I + r"\centering")
        elif opts.table_align == "right":
            lines.append(I + r"\raggedleft")
    depth = 1

    pre = I * depth
    if opts.font_size in FONT_SIZES:
        lines.append(pre + "\\" + opts.font_size)
    if abs(opts.tabcolsep - 6.0) > 1e-9:
        lines.append(pre + rf"\setlength{{\tabcolsep}}{{{_fmt_num(opts.tabcolsep)}pt}}")
    if abs(opts.arraystretch - 1.0) > 1e-9:
        lines.append(pre + rf"\renewcommand{{\arraystretch}}{{{_fmt_num(opts.arraystretch)}}}")
    if opts.striped:
        start, odd, even = stripe_rowcolors(opts, has_header)
        lines.append(pre + rf"\rowcolors{{{start}}}{{{odd}}}{{{even}}}")

    caption_lines: list[str] = []
    label = sanitize_label(opts.label)
    caption = opts.caption.strip()
    if env == "none":
        if caption or label:
            notes.append(r"Caption and label need a float (table / table*); they were omitted.")
    else:
        if caption:
            caption_lines.append(pre + rf"\caption{{{clean_cell(caption, esc)}}}")
        if label:
            caption_lines.append(pre + rf"\label{{tab:{label}}}")
            if not caption:
                notes.append(r"\label without \caption: \ref will not point to this table.")

    if opts.caption_pos == "top":
        lines += caption_lines

    open_wrappers: list[str] = []
    if rot == "rotatebox":
        open_wrappers.append(r"\rotatebox{90}{%")
    if opts.resize:
        frac = "" if abs(opts.resize_fraction - 1.0) < 1e-9 else _fmt_num(opts.resize_fraction)
        open_wrappers.append(rf"\resizebox{{{frac}{opts.resize_target}}}{{!}}{{%")
    for w in open_wrappers:
        lines.append(I * depth + w)
        depth += 1

    tab = I * depth
    lines.append(tab + rf"\begin{{tabular}}{{{column_spec_string(columns, opts)}}}")
    lines += [tab + I + b for b in body]
    lines.append(tab + r"\end{tabular}" + ("%" if open_wrappers else ""))

    for _ in open_wrappers:
        depth -= 1
        lines.append(I * depth + "}")

    if opts.caption_pos == "bottom":
        lines += caption_lines
    lines.append(close_env)

    if opts.standalone:
        lines += ["", r"\end{document}"]

    if opts.booktabs and (opts.inner_vlines or opts.outer_vlines) and has_rules:
        notes.append("booktabs rules leave small gaps where they cross vertical lines "
                     "(booktabs is designed for tables without them).")
    if opts.placement == "H" and env != "none" and rot != "sideways":
        notes.append(r"Placement [H] needs \usepackage{float}.")

    return GenerateResult("\n".join(lines) + "\n", packages, notes)
