"""Tests for the GUI-independent core.  Run:  python -m pytest -q"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.csv_parser import (LARGE_ROW_THRESHOLD, CSVParseError, detect_delimiter,  # noqa: E402
                             parse_csv, parse_csv_text)
from core.latex_generator import (ColumnSpec, TableOptions, build_row_sequence,  # noqa: E402
                                  column_spec_string, escape_latex, generate_latex,
                                  required_packages, sanitize_label, width_to_pt)


# --------------------------------------------------------------------------- escaping
@pytest.mark.parametrize("raw, expected", [
    ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
    ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"), ("\\", r"\textbackslash{}"),
    ("R&D 50% $5", r"R\&D 50\% \$5"),
    ("\\&", r"\textbackslash{}\&"),          # single pass: no double escaping
    ("plain text", "plain text"),
])
def test_escape(raw, expected):
    assert escape_latex(raw) == expected


# --------------------------------------------------------------------------- parsing
@pytest.mark.parametrize("text, delim", [
    ("a,b,c\n1,2,3\n", ","), ("a;b;c\n1;2;3\n", ";"),
    ("a\tb\tc\n1\t2\t3\n", "\t"), ("a|b|c\n1|2|3\n", "|"),
])
def test_detect_delimiter(text, delim):
    assert detect_delimiter(text) == delim


def test_header_detection_and_strings_preserved():
    r = parse_csv_text("id,value\n001,0.10\n002,\n")
    assert r.header == ["id", "value"]
    assert r.rows == [["001", "0.10"], ["002", ""]]      # no float/NaN conversion


def test_no_header_detected_for_numeric_first_row():
    r = parse_csv_text("1,2\n3,4\n")
    assert r.header is None and r.n_rows == 2


def test_forced_header_flag():
    assert parse_csv_text("1,2\n3,4\n", has_header=True).header == ["1", "2"]


def test_ragged_rows_are_padded_with_warning():
    r = parse_csv_text("a,b,c\n1,2\n3,4,5,6\n")
    assert r.n_cols == 4 and all(len(row) == 4 for row in r.rows)
    assert r.warnings


def test_quoted_fields():
    r = parse_csv_text('Name,City\n"Smith, John","Paris"\n')
    assert r.rows == [["Smith, John", "Paris"]]


@pytest.mark.parametrize("text", ["", "   \n\n", ",,,\n,,,\n"])
def test_empty_inputs_raise(text):
    with pytest.raises(CSVParseError):
        parse_csv_text(text)


def test_binary_file_rejected(tmp_path):
    f = tmp_path / "x.csv"
    f.write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(CSVParseError):
        parse_csv(str(f))


def test_latin1_file(tmp_path):
    f = tmp_path / "x.csv"
    f.write_bytes("Café,Naïve\n1,2\n".encode("cp1252"))
    r = parse_csv(str(f))
    assert r.header == ["Café", "Naïve"]


def test_large_flag():
    text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(LARGE_ROW_THRESHOLD + 5))
    r = parse_csv_text(text)
    assert r.is_large and r.n_rows == LARGE_ROW_THRESHOLD + 5


# --------------------------------------------------------------------------- generation
HEADER = ["Name", "Value"]
ROWS = [["a_1", "10%"], ["b", "20"]]
COLS = [ColumnSpec("l"), ColumnSpec("r")]


def test_booktabs_default():
    code = generate_latex(HEADER, ROWS, COLS, TableOptions()).code
    for token in (r"\begin{table}[htbp]", r"\centering", r"\begin{tabular}{lr}",
                  r"\toprule", r"\midrule", r"\bottomrule", r"a\_1", r"10\%",
                  r"\textbf{Name}"):
        assert token in code


def test_tabular_full_grid():
    o = TableOptions(booktabs=False, outer_vlines=True, inner_vlines=True, hlines="all")
    code = generate_latex(HEADER, ROWS, COLS, o).code
    assert r"\begin{tabular}{|l|r|}" in code
    assert code.count(r"\hline") == 4


def test_row_sequence_header_only():
    seq = build_row_sequence(2, True, TableOptions())
    assert seq == [("rule", "toprule"), ("row", -1), ("rule", "midrule"),
                   ("row", 0), ("row", 1), ("rule", "bottomrule")]


def test_column_spec_with_p():
    cols = [ColumnSpec("p", "3cm"), ColumnSpec("c"), ColumnSpec("r", include=False)]
    assert column_spec_string(cols, TableOptions()) == "p{3cm}c"


def test_caption_label_and_position():
    o = TableOptions(caption="My caption", label="tab:Some Label", caption_pos="bottom")
    code = generate_latex(HEADER, ROWS, COLS, o).code
    assert code.index(r"\end{tabular}") < code.index(r"\caption{My caption}")
    assert r"\label{tab:Some-Label}" in code


def test_packages():
    o = TableOptions(resize=True, striped=True, rotate="sideways", placement="H")
    names = [p for p, _ in required_packages(o)]
    assert names == ["booktabs", "graphicx", "rotating", "xcolor"]   # [H] unused when sideways


def test_widths_and_labels():
    assert abs(width_to_pt("1in", {}) - 72.27) < 1e-6
    assert width_to_pt("0.5\\linewidth", {"linewidth": 300}) == 150
    assert width_to_pt("banana", {}) is None
    assert sanitize_label("tab:My Label!") == "My-Label"


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_standalone_compiles(tmp_path):
    o = TableOptions(standalone=True, striped=True, resize=True, caption="100% & more",
                     label="x", rotate="rotatebox")
    rows = ROWS + [["~^\\{}#$", "x"]]
    (tmp_path / "t.tex").write_text(generate_latex(HEADER, rows, COLS, o).code)
    r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t.tex"],
                       cwd=tmp_path, capture_output=True)
    assert r.returncode == 0
