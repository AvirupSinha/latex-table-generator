"""CSV parsing with delimiter / header detection and graceful error handling.

Everything is read as text (``dtype=str``) so values appear exactly as they do
in the file: no ``1`` -> ``1.0`` conversion, no ``NaN`` for empty cells and no
loss of leading zeros.
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field

import pandas as pd

#: Above this many data rows the UI warns and limits the rendered preview.
LARGE_ROW_THRESHOLD = 10_000
#: Number of rows drawn in the rendered preview for large files.
PREVIEW_ROW_LIMIT = 100

#: Delimiters offered in the UI (label -> character). ``None`` = auto-detect.
DELIMITER_CHOICES: dict[str, str | None] = {
    "Auto-detect": None,
    "Comma  ( , )": ",",
    "Semicolon  ( ; )": ";",
    "Tab  ( \\t )": "\t",
    "Pipe  ( | )": "|",
}

_CANDIDATE_DELIMITERS = ",;\t|"
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
_SNIFF_BYTES = 64 * 1024


class CSVParseError(Exception):
    """Raised with a user-friendly message when a CSV cannot be used."""


@dataclass
class ParseResult:
    header: list[str] | None          # None when the file has no header row
    rows: list[list[str]]             # data rows, all padded to the same width
    delimiter: str
    encoding: str
    source: str = ""                  # file path or "clipboard"
    warnings: list[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        if self.header is not None:
            return len(self.header)
        return len(self.rows[0]) if self.rows else 0

    @property
    def is_large(self) -> bool:
        return self.n_rows > LARGE_ROW_THRESHOLD


def delimiter_name(delim: str) -> str:
    return {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe", " ": "space"}.get(
        delim, repr(delim)
    )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def read_text_file(path: str) -> tuple[str, str]:
    """Return ``(text, encoding)``, trying UTF-8 first, then Windows/Latin-1."""
    if not os.path.isfile(path):
        raise CSVParseError(f"File not found:\n{path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw.strip():
        raise CSVParseError("The file is empty.")
    if b"\x00" in raw[:_SNIFF_BYTES]:
        raise CSVParseError(
            "This does not look like a text CSV file (it contains binary data).\n"
            "If it is an Excel workbook, export it as CSV first."
        )
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise CSVParseError("Could not decode the file as text.")  # pragma: no cover


def detect_delimiter(sample: str) -> str:
    """Guess the delimiter from a text sample (Sniffer first, then counting)."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        pass
    # Fallback: the candidate that appears most consistently across lines.
    lines = [ln for ln in sample.splitlines()[:50] if ln.strip()]
    best, best_score = ",", 0.0
    for d in _CANDIDATE_DELIMITERS:
        counts = [ln.count(d) for ln in lines]
        if not counts or max(counts) == 0:
            continue
        consistent = sum(1 for c in counts if c == counts[0]) / len(counts)
        score = consistent * (counts[0] > 0) + 0.01 * sum(counts) / len(counts)
        if score > best_score:
            best, best_score = d, score
    return best


def _looks_numeric(s: str) -> bool:
    s = s.strip().replace(",", "").rstrip("%")
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def detect_header(rows: list[list[str]]) -> bool:
    """Heuristic header detection on already-split rows.

    A first row is treated as a header when it is non-empty, contains no purely
    numeric cells, and (if there is enough data) at least one column below it is
    numeric or the first row's values do not reappear in the body.
    """
    if not rows:
        return False
    first = rows[0]
    if not any(c.strip() for c in first):
        return False
    if any(_looks_numeric(c) for c in first):
        return False
    body = rows[1:51]
    if not body:
        return True
    for j in range(len(first)):
        col = [r[j] for r in body if j < len(r) and r[j].strip()]
        if col and all(_looks_numeric(c) for c in col):
            return True
    # All-text table: header if its values never repeat in the body.
    body_vals = {c for r in body for c in r}
    return not any(c in body_vals for c in first if c.strip())


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_csv(path: str, delimiter: str | None = None,
              has_header: bool | None = None) -> ParseResult:
    """Parse a CSV file from disk. See :func:`parse_csv_text`."""
    text, encoding = read_text_file(path)
    result = parse_csv_text(text, delimiter=delimiter, has_header=has_header,
                            source=path)
    result.encoding = encoding
    return result


def parse_csv_text(text: str, delimiter: str | None = None,
                   has_header: bool | None = None, source: str = "") -> ParseResult:
    """Parse CSV text.

    Args:
        text: the CSV content.
        delimiter: force a delimiter, or ``None`` to auto-detect.
        has_header: force header on/off, or ``None`` to auto-detect.
        source: label stored in the result (path or "clipboard").
    """
    if text.startswith("﻿"):
        text = text[1:]
    if not text.strip():
        raise CSVParseError("The file is empty.")

    warnings: list[str] = []
    delim = delimiter or detect_delimiter(text[:_SNIFF_BYTES])

    # Pass 1 (csv module): find the widest row so ragged rows never break pandas.
    try:
        widths = [len(r) for r in csv.reader(io.StringIO(text), delimiter=delim) if r]
    except csv.Error as exc:
        raise CSVParseError(f"Malformed CSV: {exc}") from exc
    if not widths:
        raise CSVParseError("The file contains no rows.")
    n_cols = max(widths)
    ragged = sum(1 for w in widths if w != widths[0])
    if ragged:
        warnings.append(
            f"{ragged:,} row(s) had a different number of fields than the first row; "
            "missing cells were left empty."
        )

    # Pass 2 (pandas): the actual parse, everything as strings.
    read_kwargs = dict(
        sep=delim, header=None, names=list(range(n_cols)), dtype=str,
        keep_default_na=False, na_filter=False, skip_blank_lines=True,
        quotechar='"',
    )
    try:
        df = pd.read_csv(io.StringIO(text), engine="c", **read_kwargs)
    except pd.errors.EmptyDataError as exc:
        raise CSVParseError("The file is empty.") from exc
    except (pd.errors.ParserError, ValueError):
        try:
            df = pd.read_csv(io.StringIO(text), engine="python",
                             on_bad_lines="skip", **read_kwargs)
            warnings.append("Some malformed lines could not be parsed and were skipped.")
        except Exception as exc:  # noqa: BLE001
            raise CSVParseError(f"Malformed CSV: {exc}") from exc

    df = df.fillna("").astype(str)
    df = df.apply(lambda col: col.str.strip())

    # Drop fully-empty rows and fully-empty trailing columns (Excel artefacts).
    df = df[(df != "").any(axis=1)]
    while df.shape[1] > 1 and (df.iloc[:, -1] == "").all():
        df = df.iloc[:, :-1]

    rows: list[list[str]] = df.values.tolist()
    if not rows:
        raise CSVParseError("The file contains no data (only empty rows).")

    if has_header is None:
        has_header = detect_header(rows)

    header: list[str] | None = None
    if has_header:
        header = rows.pop(0)
        if not rows:
            warnings.append("The file only contains a header row.")

    if len(rows) > LARGE_ROW_THRESHOLD:
        warnings.append(
            f"Large file ({len(rows):,} rows): the rendered preview is limited to the "
            f"first {PREVIEW_ROW_LIMIT} rows, but the LaTeX code contains every row."
        )

    return ParseResult(header=header, rows=rows, delimiter=delim, encoding="utf-8",
                       source=source, warnings=warnings)
