#!/usr/bin/env python3
"""Deterministic Immutable Anchor Extractor for Academic Language Polishing (v2.1).

Extracts numbers, statistical expressions, citations, figure/table/equation
cross-references, LaTeX math/labels, abbreviations, and encoding/format signals
from plain text, Markdown, or LaTeX manuscripts using Python stdlib only.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

UNITS_GROUP = (
    r"%|°C|K|mg/mL|μg/mL|ug/mL|mol/L|mM|μM|nM|M|nm|μm|mm|cm|m|km|g|mg|kg|"
    r"mL|L|s|ms|min|h|Hz|kHz|MHz|GHz|V|mV|A|mA|W|mW|J|kJ|eV|Pa|kPa|MPa|GPa|bar|atm|rpm|wt%|vol%|at%"
)

PATTERNS = {
    "latex_math_display": re.compile(r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]"),
    "latex_math_inline": re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)|\\\((.+?)\\\)"),
    "latex_labels": re.compile(r"\\label\{[^}]+\}"),
    "latex_citations": re.compile(r"\\cite[a-zA-Z*]*\{[^}]+\}"),
    "numeric_citations": re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]"),
    "author_year_citations": re.compile(
        r"\((?:[A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.|&\s+[A-Z][A-Za-z\-']+|and\s+[A-Z][A-Za-z\-']+))?,\s*(?:19|20)\d{2}[a-z]?(?:;\s*)?)+\)"
    ),
    "cross_refs": re.compile(
        r"(?:\\(?:eq)?ref\{[^}]+\}|(?:Fig\.|Figure|Figs\.|Table|Tables|Eq\.|Eqs\.|Equation|Section|Sec\.|Scheme|Chart)\s*\(?S?\d+[A-Za-z]?(?:\.\d+)?\)?|(?:图|表|式|公式|第\s*\d+\s*章)\s*[S]?\d+(?:[-–.]\d+)?[A-Za-z]?)"
    ),
    "stat_values": re.compile(
        r"(?:\b[pPRrFtz]\s*[<>≤≥=]\s*0?\.\d+(?:e[-+]?\d+)?|\bR\^?2\s*=\s*0?\.\d+|\bn\s*=\s*\d+|\bSD\s*=\s*\d+(?:\.\d+)?|\bCI\s*[:=]?\s*[\[\(]?[^\]\)\n]{2,20}[\]\)])"
    ),
    "numbers_and_units": re.compile(
        rf"(?<![A-Za-z_])[-+]?\d+(?:,\d{{3}})*(?:\.\d+)?(?:\s*[±]\s*\d+(?:\.\d+)?)?(?:\s*[×x]\s*10\^?[-+]?\d+|\s*[eE][-+]?\d+)?(?:\s*(?:{UNITS_GROUP}))?"
    ),
}

UNIT_SPACING_RE = re.compile(rf"(\d)\s*({UNITS_GROUP})$")
ABBREV_DEF_RE = re.compile(r"([A-Za-z][A-Za-z0-9\-/\s]{3,80}?)\s*\(([A-Z][A-Z0-9\-/]{1,10})\)")
ABBREV_USE_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})\b")
COMMON_NON_ABBREV = {
    "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII",
    "AM", "PM", "NO", "OR", "IN", "ON", "AT", "BY", "TO", "OF", "AS", "IS", "IT",
    "US", "UK", "EU", "UN", "FIG", "EQ", "SD", "SE", "CI", "ID", "VS", "ET", "AL",
}


def detect_encoding_anomalies(text: str) -> list[dict[str, Any]]:
    """Detect replacement characters, stray control chars, or likely mojibake."""
    anomalies: list[dict[str, Any]] = []
    if "\ufffd" in text:
        anomalies.append({
            "type": "REPLACEMENT_CHAR",
            "count": text.count("\ufffd"),
            "message": "Found Unicode replacement character (U+FFFD), indicating possible source decoding corruption.",
        })
    ctrl_chars = [ch for ch in text if ord(ch) < 32 and ch not in ("\n", "\r", "\t")]
    if ctrl_chars:
        anomalies.append({
            "type": "CONTROL_CHARS",
            "count": len(ctrl_chars),
            "message": "Found non-whitespace ASCII control characters.",
        })
    if re.search(r"Ã[\x80-\xbf]|â€[™“”–—]", text):
        anomalies.append({
            "type": "MOJIBAKE_SUSPECTED",
            "count": 1,
            "message": "Detected UTF-8/Latin-1 mojibake byte sequences (e.g., 'Ã©', 'â€™').",
        })
    return anomalies


def _normalize_anchor(s: str) -> str:
    norm = re.sub(r"\s+", " ", s.strip())
    # CJK typography allows 图2 / 图 2; the space is not part of the reference itself.
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=\d)", "", norm)


def _normalize_number_unit(s: str) -> str:
    """Canonicalize SI unit spacing (e.g., '25°C' == '25 °C') without masking value/unit changes."""
    norm = _normalize_anchor(s)
    return UNIT_SPACING_RE.sub(r"\1 \2", norm)


def extract_anchors(text: str) -> dict[str, Any]:
    """Extract immutable anchors and structural metadata from text."""
    math_display = [_normalize_anchor(m.group(0)) for m in PATTERNS["latex_math_display"].finditer(text)]
    masked = PATTERNS["latex_math_display"].sub(" __MATH_DISP__ ", text)

    math_inline = [_normalize_anchor(m.group(0)) for m in PATTERNS["latex_math_inline"].finditer(masked)]
    masked = PATTERNS["latex_math_inline"].sub(" __MATH_INL__ ", masked)

    latex_labels = [_normalize_anchor(m.group(0)) for m in PATTERNS["latex_labels"].finditer(masked)]
    latex_citations = [_normalize_anchor(m.group(0)) for m in PATTERNS["latex_citations"].finditer(masked)]
    numeric_citations = [_normalize_anchor(m.group(0)) for m in PATTERNS["numeric_citations"].finditer(masked)]
    author_year_citations = [_normalize_anchor(m.group(0)) for m in PATTERNS["author_year_citations"].finditer(masked)]
    cross_refs = [_normalize_anchor(m.group(0)) for m in PATTERNS["cross_refs"].finditer(masked)]
    stat_values = [_normalize_anchor(m.group(0)) for m in PATTERNS["stat_values"].finditer(masked)]

    num_scan = PATTERNS["latex_citations"].sub(" ", masked)
    num_scan = PATTERNS["numeric_citations"].sub(" ", num_scan)
    num_scan = PATTERNS["author_year_citations"].sub(" ", num_scan)
    num_scan = PATTERNS["cross_refs"].sub(" ", num_scan)
    numbers_and_units = [
        _normalize_number_unit(m.group(0))
        for m in PATTERNS["numbers_and_units"].finditer(num_scan)
        if _normalize_anchor(m.group(0))
    ]

    abbrev_definitions: dict[str, list[str]] = {}
    for m in ABBREV_DEF_RE.finditer(masked):
        full_form = _normalize_anchor(m.group(1))
        abbr = m.group(2)
        abbrev_definitions.setdefault(abbr, []).append(full_form)

    abbrev_counts = Counter(
        m.group(1)
        for m in ABBREV_USE_RE.finditer(masked)
        if m.group(1) not in COMMON_NON_ABBREV
    )

    has_latex = bool(math_display or math_inline or latex_citations or latex_labels or re.search(r"\\(section|begin|end)\{", text))
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    has_japanese = bool(re.search(r"[\u3040-\u30ff]", text))

    return {
        "stats": {
            "char_count": len(text),
            "line_count": len(text.splitlines()),
            "has_latex": has_latex,
            "has_cjk": has_cjk,
            "has_japanese_kana": has_japanese,
        },
        "encoding_anomalies": detect_encoding_anomalies(text),
        "anchors": {
            "latex_math_display": dict(Counter(math_display)),
            "latex_math_inline": dict(Counter(math_inline)),
            "latex_labels": dict(Counter(latex_labels)),
            "latex_citations": dict(Counter(latex_citations)),
            "numeric_citations": dict(Counter(numeric_citations)),
            "author_year_citations": dict(Counter(author_year_citations)),
            "cross_refs": dict(Counter(cross_refs)),
            "stat_values": dict(Counter(stat_values)),
            "numbers_and_units": dict(Counter(numbers_and_units)),
        },
        "abbreviations": {
            "defined": abbrev_definitions,
            "usage_counts": dict(abbrev_counts),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract immutable factual/structural anchors from academic text.")
    parser.add_argument("--input", required=True, help="Path to input text/markdown/tex file.")
    parser.add_argument("--output", help="Optional path to write JSON anchor report.")
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    report = extract_anchors(text)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
