"""
Parse text-based spectrum files (CSV, TSV, whitespace-delimited).

Port of the React app's parseSpectrumText.ts logic.
Handles:
  - Lines with 2+ numeric columns (first col = X, second col = Y)
  - Skips header / comment lines that don't start with a digit, sign, or dot
  - Auto-detects comma vs tab vs whitespace delimiter
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.spa_parser import SPAParseError, parse_spa_file


_NUM_RE = re.compile(r"^[+\-\d.]")
_DELIMITERS = ["\t", ",", ";", r"\s+"]


class SpectrumParseError(Exception):
    """Raised when a spectrum file cannot be parsed safely."""


@dataclass(frozen=True)
class ImportedPeakData:
    """Peak entry parsed from an imported file."""

    x: float
    label: str = ""


@dataclass
class ParsedSpectrumData:
    """Normalized parsed spectrum payload used by UI import flows."""

    x: List[float]
    y: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    imported_peaks: List[ImportedPeakData] = field(default_factory=list)


def _try_split(line: str, delimiter: str) -> List[str]:
    """Split a line by the given delimiter (supports regex for whitespace)."""
    if delimiter == r"\s+":
        return line.split()
    return line.split(delimiter)


def _detect_delimiter(lines: List[str]) -> str:
    """Pick the delimiter that produces the most consistent column count >= 2."""
    best_delim = r"\s+"
    best_score = 0

    for delim in _DELIMITERS:
        counts: List[int] = []
        for ln in lines[:30]:          # sample first 30 data-like lines
            if not _NUM_RE.match(ln.strip()):
                continue
            parts = _try_split(ln.strip(), delim)
            if len(parts) >= 2:
                counts.append(len(parts))
        if not counts:
            continue
        # score = number of lines that have the same (modal) column count
        modal = max(set(counts), key=counts.count)
        score = counts.count(modal)
        if score > best_score and modal >= 2:
            best_score = score
            best_delim = delim

    return best_delim


def _parse_number(text: str) -> Optional[float]:
    """Try to parse a numeric string, accepting comma as decimal separator."""
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_spectrum_text(text: str) -> Optional[Tuple[List[float], List[float]]]:
    """
    Parse a block of text into (x_values, y_values).

    Returns None if fewer than 2 valid data points are found.
    """
    lines = text.splitlines()
    if not lines:
        return None

    delim = _detect_delimiter(lines)

    xs: List[float] = []
    ys: List[float] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or not _NUM_RE.match(stripped):
            continue
        parts = _try_split(stripped, delim)
        if len(parts) < 2:
            continue
        xv = _parse_number(parts[0])
        yv = _parse_number(parts[1])
        if xv is not None and yv is not None:
            xs.append(xv)
            ys.append(yv)

    if len(xs) < 2:
        return None

    return xs, ys


def parse_spectrum_file(filepath: str) -> Optional[ParsedSpectrumData]:
    """
    Parse one spectrum file based on extension.

    Supported:
      - text-like files (.txt, .csv, .tsv, .dat, .asc, .xy, .spc)
      - OMNIC SPA binary files (.spa)
    """
    ext = Path(filepath).suffix.lower()

    if ext == ".spa":
        try:
            parsed = parse_spa_file(filepath)
        except SPAParseError as exc:
            raise SpectrumParseError(str(exc)) from exc
        return ParsedSpectrumData(
            x=parsed.x,
            y=parsed.y,
            metadata=dict(parsed.metadata),
            imported_peaks=[
                ImportedPeakData(x=peak.x, label=peak.label)
                for peak in parsed.peaks
            ],
        )

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise SpectrumParseError(f"Cannot read file: {exc}") from exc

    result = parse_spectrum_text(text)
    if result is None:
        return None
    xs, ys = result
    return ParsedSpectrumData(x=xs, y=ys)


def extract_label_from_filename(filepath: str) -> str:
    """
    Derive a short display name from a file path.
    Strips directory and extension.
    """
    base = os.path.basename(filepath)
    name, _ = os.path.splitext(base)
    return name
