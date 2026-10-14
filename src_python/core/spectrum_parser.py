"""Validated spectrum import, including files containing several spectra."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.spa_parser import SPAParseError, parse_spa_file


class SpectrumParseError(Exception):
    """Malformed data or a file variant that cannot be interpreted safely."""


@dataclass(frozen=True)
class ImportedPeakData:
    x: float
    label: str = ""


@dataclass
class ParsedSpectrumData:
    x: List[float]
    y: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    imported_peaks: List[ImportedPeakData] = field(default_factory=list)


_TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".dat", ".asc", ".xy", ".dpt"}
_NUMBER_START = re.compile(r"^[+\-\d.,]")
_COMMENTS = ("#", "//", "$$")


def _normalize(parsed: ParsedSpectrumData) -> ParsedSpectrumData:
    """Sort paired data without dropping, averaging, or inventing measurements."""
    try:
        x = np.asarray(parsed.x, dtype=np.float64)
        y = np.asarray(parsed.y, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SpectrumParseError("Spektrum obsahuje nečíselné hodnoty") from exc
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
        raise SpectrumParseError("Spektrum musí obsahovat alespoň dva odpovídající body X/Y")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise SpectrumParseError("Spektrum obsahuje hodnoty NaN nebo nekonečno")
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    if np.any(np.diff(x) == 0):
        raise SpectrumParseError("Duplicitní souřadnice X: před importem vyber nebo sjednoť měření")
    parsed.x, parsed.y = x.tolist(), y.tolist()
    parsed.metadata.setdefault("point_count", int(x.size))
    if "technique" in parsed.metadata:
        parsed.metadata["technique"] = {"ir": "infrared", "uvvis": "uv_vis", "unknown": "custom"}.get(
            parsed.metadata["technique"], parsed.metadata["technique"])
    if parsed.metadata.get("y_kind") == "transmittance":
        parsed.metadata["y_kind"] = "transmittance_fraction"
    if parsed.metadata.get("y_kind") == "unknown":
        # Preserve native labels/codes, leaving interpretation to the import controls.
        parsed.metadata.pop("y_kind")
        parsed.metadata["ordinate_interpretation_required"] = True
    return parsed


def _split(line: str, delimiter: str) -> List[str]:
    if delimiter == "whitespace":
        return line.split()
    try:
        return next(csv.reader([line], delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise SpectrumParseError(f"Neplatný řádek CSV s uvozovkami: {exc}") from exc


def _number(value: str, delimiter: str) -> float:
    value = value.strip()
    if delimiter != ",":
        value = value.replace(",", ".")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nekonečná nebo nečíselná hodnota")
    return result


def _detect_delimiter(lines: List[str]) -> str:
    best = None
    for delimiter in (";", "\t", ",", "whitespace"):
        counts: Dict[int, int] = {}
        for line in lines[:100]:
            if not _NUMBER_START.match(line.lstrip().lstrip('"')):
                continue
            try:
                parts = _split(line, delimiter)
            except SpectrumParseError:
                # Quoting can be invalid for a candidate that is not the real delimiter.
                continue
            if len(parts) < 2:
                continue
            try:
                [_number(value, delimiter) for value in parts]
            except ValueError:
                continue
            counts[len(parts)] = counts.get(len(parts), 0) + 1
        if counts:
            count, score = max(counts.items(), key=lambda pair: pair[1])
            if best is None or score > best[0]:
                best = (score, delimiter, count)
    if best is None:
        raise SpectrumParseError("Nebyla nalezena číselná tabulka X/Y; zkontroluj oddělovač a desetinný znak")
    return best[1]


def _axis_metadata(x_label: str, y_label: str) -> Dict[str, str]:
    combined = f"{x_label} {y_label}".lower()
    result: Dict[str, str] = {}
    if "raman" in combined:
        result["technique"] = "raman"
    elif "uv" in combined or "vis" in combined:
        result["technique"] = "uvvis"
    if any(token in x_label.lower() for token in ("wavenumber", "cm-1", "cm^-1", "cm⁻¹", "raman shift")):
        result["x_unit"] = "cm^-1"
    elif re.search(r"\bnm\b", x_label.lower()):
        result["x_unit"] = "nm"
    if "absorb" in y_label.lower():
        result["y_kind"] = "absorbance"
    elif "transmit" in y_label.lower() or "%t" in y_label.lower():
        result["y_kind"] = "transmittance_percent" if "%" in y_label else "transmittance"
    elif "intensity" in y_label.lower() or "counts" in y_label.lower():
        result["y_kind"] = "intensity"
    return result


def _parse_text_curves(text: str) -> List[ParsedSpectrumData]:
    lines = [line.strip() for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    table_lines = [line for line in lines if not line.startswith(_COMMENTS)]
    delimiter = _detect_delimiter(table_lines)
    data: List[List[float]] = []
    header: List[str] = []
    metadata: Dict[str, Any] = {"delimiter": delimiter}
    for line_number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(_COMMENTS):
            for key, value in re.findall(r"\b(x_unit|y_unit|y_kind|technique)\s*=\s*([^;\s]+)", line):
                metadata[key] = value
            continue
        parts = _split(line, delimiter)
        try:
            values = [_number(value, delimiter) for value in parts]
        except ValueError as exc:
            if data or _NUMBER_START.match(line.lstrip('"')):
                raise SpectrumParseError(f"Neplatná nebo chybějící číselná hodnota na řádku {line_number}") from exc
            if len(parts) >= 2:
                header = [value.strip() for value in parts]
            continue
        if len(values) < 2:
            if data:
                raise SpectrumParseError(f"Na řádku {line_number} se očekávají sloupce X a Y")
            continue
        if data and len(values) != len(data[0]):
            raise SpectrumParseError(f"Nekonzistentní počet sloupců na řádku {line_number}")
        data.append(values)
    if len(data) < 2:
        raise SpectrumParseError("Spektrum obsahuje méně než dva řádky dat")
    if header and len(header) != len(data[0]):
        raise SpectrumParseError("Záhlaví sloupců neodpovídá číselné tabulce")
    columns = list(zip(*data))
    results = []
    for column, values in enumerate(columns[1:], 1):
        name = header[column] if header else f"Spectrum {column}"
        item_metadata = _axis_metadata(header[0] if header else "", name)
        item_metadata.update(metadata)
        item_metadata.update({"name": name, "column_index": column, "column_names": header})
        results.append(_normalize(ParsedSpectrumData(list(columns[0]), list(values), item_metadata)))
    return results


def parse_spectrum_text(text: str) -> Optional[Tuple[List[float], List[float]]]:
    """Legacy two-column API. New import flows use parse_spectrum_files."""
    try:
        parsed = _parse_text_curves(text)[0]
    except SpectrumParseError:
        return None
    return parsed.x, parsed.y


def _read_text(path: Path) -> str:
    blob = path.read_bytes()
    if b"\x00" in blob and not blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise SpectrumParseError("Binární data nelze načíst jako textové spektrum")
    encodings = ("utf-16",) if blob.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp1250")
    for encoding in encodings:
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SpectrumParseError("Nerozpoznané kódování textu")


def parse_spectrum_files(filepath: str) -> List[ParsedSpectrumData]:
    """Import every spectrum in a supported file; malformed rows are never dropped."""
    path = Path(filepath)
    extension = path.suffix.lower()
    try:
        if extension == ".spa":
            item = parse_spa_file(str(path))
            results = [ParsedSpectrumData(item.x, item.y, dict(item.metadata),
                       [ImportedPeakData(peak.x, peak.label) for peak in item.peaks])]
        elif extension == ".wdf":
            from core.wdf_parser import parse_wdf_file
            results = [ParsedSpectrumData(item["x"], item["y"], item["metadata"]) for item in parse_wdf_file(str(path))]
        elif extension in {".jdx", ".dx", ".jcamp"}:
            from core.jcamp_parser import parse_jcamp_file
            results = [ParsedSpectrumData(item["x"], item["y"], item["metadata"]) for item in parse_jcamp_file(str(path))]
        elif extension == ".spc":
            from core.spc_parser import parse_spc_file
            blob = path.read_bytes()
            if len(blob) > 1 and blob[1] in (0x4B, 0x4C, 0x4D):
                item = parse_spc_file(str(path))
                results = [ParsedSpectrumData(item["x"], item["y"], item["metadata"])]
            else:
                results = _parse_text_curves(_read_text(path))
        elif extension in _TEXT_EXTENSIONS:
            results = _parse_text_curves(_read_text(path))
        else:
            raise SpectrumParseError(f"Nepodporovaný formát '{extension or '(no extension)'}'; exportuj soubor do CSV/TXT nebo JCAMP-DX")
    except (OSError, ValueError, SPAParseError) as exc:
        raise SpectrumParseError(str(exc)) from exc
    for index, item in enumerate(results):
        item.metadata.setdefault("source_format", extension.lstrip("."))
        item.metadata["source_file"] = path.name
        if len(results) == 1 and (not item.metadata.get("name") or item.metadata.get("name") == "Spectrum 1"):
            item.metadata["name"] = path.stem
        item.metadata.setdefault("spectrum_index", index)
        _normalize(item)
    if not results:
        raise SpectrumParseError("Soubor neobsahuje žádná naměřená spektra")
    return results


def parse_spectrum_file(filepath: str) -> Optional[ParsedSpectrumData]:
    """Legacy single-spectrum API; reject multi-spectrum files to prevent data loss."""
    results = parse_spectrum_files(filepath)
    if len(results) != 1:
        raise SpectrumParseError("Soubor obsahuje několik spekter; pro import všech použij parse_spectrum_files")
    return results[0]


def extract_label_from_filename(filepath: str) -> str:
    return Path(filepath).stem
