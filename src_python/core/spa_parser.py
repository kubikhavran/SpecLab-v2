"""
OMNIC SPA parser.

This module parses Thermo OMNIC `.spa` files and extracts:
  - x/y spectral data
  - useful metadata from the SPA header
  - embedded peak table/label information when present

Peak labels in SPA files are not always stored in one canonical structure across
all OMNIC variants. The parser therefore combines:
  - key/offset based section parsing
  - text block decoding from likely metadata sections
  - conservative text pattern extraction for peak positions and labels

The parser is intentionally defensive:
  - malformed or truncated primary sections are rejected
  - unknown variants raise SPAParseError with a clear message
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np


_SIGNATURE = b"Spectral Data File"
_ENTRY_SIZE = 16
_ENTRY_START = 304
_TEXT_KEYS = {4, 27, 130, 146}
_PEAK_HINT_WORDS = (
    "peak",
    "band",
    "assignment",
    "marker",
    "label",
    "wavenumber",
    "cm-1",
    "cm^-1",
    "position",
)
_NOISE_LABELS = {
    "intensity",
    "height",
    "area",
    "width",
    "fwhm",
    "prominence",
    "amplitude",
}
_NUM_TOKEN_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

_X_UNIT_MAP = {
    1: ("cm^-1", "wavenumber"),
    2: (None, "data points"),
    3: ("nm", "wavelength"),
    4: ("um", "wavelength"),
    32: ("cm^-1", "raman shift"),
}
_Y_UNIT_MAP = {
    11: ("percent", "reflectance"),
    12: (None, "log(1/R)"),
    15: (None, "single beam"),
    16: ("percent", "transmittance"),
    17: ("absorbance", "absorbance"),
    20: ("Kubelka_Munk", "Kubelka-Munk"),
    21: (None, "reflectance"),
    22: ("V", "detector signal"),
    23: (None, "transmittance"),
    26: (None, "photoacoustic"),
    31: (None, "Raman intensity"),
}


class SPAParseError(Exception):
    """Raised when an SPA file cannot be parsed safely."""


@dataclass(frozen=True)
class SPAPeakEntry:
    """One peak label/entry extracted from the SPA file."""

    x: float
    label: str = ""


@dataclass
class SPAParseResult:
    """Parsed SPA content used by the import pipeline."""

    x: List[float]
    y: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    peaks: List[SPAPeakEntry] = field(default_factory=list)


@dataclass(frozen=True)
class _SPAEntry:
    key: int
    offset: int
    length: int


def _read_u8(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 1 > len(blob):
        raise SPAParseError("Neočekávaný konec souboru SPA")
    return blob[offset]


def _read_u16(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(blob):
        raise SPAParseError("Neočekávaný konec souboru SPA")
    return struct.unpack_from("<H", blob, offset)[0]


def _read_u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        raise SPAParseError("Neočekávaný konec souboru SPA")
    return struct.unpack_from("<I", blob, offset)[0]


def _read_f32(blob: bytes, offset: int) -> float:
    if offset < 0 or offset + 4 > len(blob):
        raise SPAParseError("Neočekávaný konec souboru SPA")
    return struct.unpack_from("<f", blob, offset)[0]


def _read_name(blob: bytes) -> str:
    if len(blob) < 31:
        return ""
    raw = blob[30 : 30 + 256]
    if b"\x00" in raw:
        raw = raw.split(b"\x00", 1)[0]
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        text = raw.decode("latin-1", errors="ignore").strip()
    return text


def _scan_entries(blob: bytes) -> List[_SPAEntry]:
    """Read the counted table; a corrupt count cannot trigger a guessed fallback."""
    nlines = _read_u16(blob, 294)
    table_end = _ENTRY_START + nlines * _ENTRY_SIZE
    if not 0 < nlines <= 4096 or table_end > len(blob):
        raise SPAParseError("Neplatná nebo zkrácená tabulka záznamů SPA")
    entries: List[_SPAEntry] = []
    for index in range(nlines):
        pos = _ENTRY_START + index * _ENTRY_SIZE
        key = _read_u8(blob, pos)
        offset = _read_u32(blob, pos + 2)
        length = _read_u32(blob, pos + 6)
        if key in (0, 1) and offset == 0 and length == 0:
            continue
        if length and (offset < table_end or offset + length > len(blob)):
            raise SPAParseError(f"Sekce SPA {key} odkazuje mimo platnou oblast dat")
        entries.append(_SPAEntry(key=key, offset=offset, length=length))
    return entries


def _parse_header(blob: bytes, header_offset: int, header_length: int) -> Dict[str, Any]:
    if header_length < 24 or header_offset <= 0 or header_offset + header_length > len(blob):
        raise SPAParseError("Pozice hlavičky SPA je neplatná")

    nx = _read_u32(blob, header_offset + 4)
    if nx < 2:
        raise SPAParseError("Hlavička SPA obsahuje příliš málo bodů")

    first_x = _read_f32(blob, header_offset + 16)
    last_x = _read_f32(blob, header_offset + 20)
    if not np.isfinite(first_x) or not np.isfinite(last_x) or first_x == last_x:
        raise SPAParseError("Hlavička SPA obsahuje neplatné meze osy X")

    x_unit_key = _read_u8(blob, header_offset + 8)
    y_unit_key = _read_u8(blob, header_offset + 12)
    x_units, x_title = _X_UNIT_MAP.get(x_unit_key, (None, "xaxis"))
    y_units, y_title = _Y_UNIT_MAP.get(y_unit_key, (None, "intensity"))

    info: Dict[str, Any] = {
        "nx": int(nx),
        "first_x": float(first_x),
        "last_x": float(last_x),
        "x_unit_key": int(x_unit_key),
        "y_unit_key": int(y_unit_key),
        "x_units": x_units,
        "x_title": x_title,
        "y_units": y_units,
        "y_title": y_title,
    }

    # Read only fields present in this declared block. Acquisition fields vary.
    for key, relative_offset, reader in (
        ("n_scan", 36, _read_u32),
        ("n_background_scan", 52, _read_u32),
        ("collection_length_1_100_s", 68, _read_u32),
        ("reference_frequency_cm1", 80, _read_f32),
    ):
        if relative_offset + 4 <= header_length:
            value = reader(blob, header_offset + relative_offset)
            if np.isfinite(value):
                info[key] = value

    return info


def _read_float_vector(blob: bytes, offset: int, count: int) -> np.ndarray:
    if count <= 0:
        raise SPAParseError("Datový blok SPA neobsahuje žádné body")
    n_bytes = count * 4
    if offset < 0 or offset + n_bytes > len(blob):
        raise SPAParseError("Datový blok SPA přesahuje rozsah souboru")
    return np.frombuffer(blob, dtype="<f4", count=count, offset=offset).astype(
        np.float64,
        copy=False,
    )


def _extract_main_curve(blob: bytes, entries: Iterable[_SPAEntry]) -> tuple[Dict[str, Any], np.ndarray]:
    header_entry = next((entry for entry in entries if entry.key == 2), None)
    if header_entry is None:
        raise SPAParseError("Značka hlavičky SPA (key=2) nebyla nalezena")

    if sum(entry.key == 2 for entry in entries) != 1 or sum(entry.key == 3 for entry in entries) != 1:
        raise SPAParseError("SPA musí obsahovat právě jednu hlavní hlavičku a datovou část")
    header = _parse_header(blob, header_entry.offset, header_entry.length)
    if header["x_unit_key"] == 2:
        raise SPAParseError("Datové body/interferogram SPA nejsou podporovaným spektrem")
    spectral_entry = next((entry for entry in entries if entry.key == 3), None)
    if spectral_entry is None:
        raise SPAParseError("Značka spektrálních dat SPA (key=3) nebyla nalezena")
    expected_n = int(header["nx"])
    if spectral_entry.length != expected_n * 4:
        raise SPAParseError("Délka datové části SPA neodpovídá deklarovanému počtu bodů; data nebudou přepočítána")
    y = _read_float_vector(blob, spectral_entry.offset, expected_n)
    if not np.all(np.isfinite(y)):
        raise SPAParseError("SPA obsahuje nekonečné nebo nečíselné hodnoty ordináty")
    return header, y


def _decode_text_block(raw: bytes) -> List[str]:
    texts: List[str] = []
    if not raw:
        return texts

    latin = re.sub(rb"\x00+", b"\n", raw).decode("latin-1", errors="ignore").strip()
    if latin:
        texts.append(latin)

    utf8 = re.sub(rb"\x00+", b"\n", raw).decode("utf-8", errors="ignore").strip()
    if utf8 and utf8 != latin:
        texts.append(utf8)

    if raw.count(0) > len(raw) // 6:
        utf16 = raw.decode("utf-16-le", errors="ignore").strip()
        if utf16:
            texts.append(utf16)

    # Deduplicate while preserving order.
    unique: List[str] = []
    seen = set()
    for txt in texts:
        key = txt[:400]
        if key in seen:
            continue
        seen.add(key)
        unique.append(txt)
    return unique


def _collect_text_blocks(blob: bytes, entries: Iterable[_SPAEntry]) -> List[str]:
    blocks: List[str] = []

    for entry in entries:
        if entry.offset <= 0 or entry.length <= 0:
            continue
        if entry.offset + entry.length > len(blob):
            continue
        raw = blob[entry.offset : entry.offset + entry.length]
        if entry.key in _TEXT_KEYS:
            blocks.extend(_decode_text_block(raw))

    # Deduplicate big repeats.
    unique: List[str] = []
    seen = set()
    for block in blocks:
        key = block[:500]
        if key in seen:
            continue
        seen.add(key)
        unique.append(block)
    return unique


def _to_float(token: str) -> Optional[float]:
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


def _clean_label(text: str) -> str:
    label = re.sub(r"\s+", " ", text).strip(" \t;,:|/-")
    if not label:
        return ""
    low = label.lower()
    if low in _NOISE_LABELS:
        return ""
    if len(label) > 120:
        label = label[:120].rstrip()
    return label


def _extract_peaks_from_block(text: str, x_min: float, x_max: float) -> List[SPAPeakEntry]:
    if not text:
        return []

    x_lo, x_hi = (x_min, x_max) if x_min <= x_max else (x_max, x_min)
    span = abs(x_hi - x_lo)
    margin = max(1e-6, span * 0.05)
    lo = x_lo - margin
    hi = x_hi + margin

    lower_text = text.lower()
    block_has_hint = any(word in lower_text for word in _PEAK_HINT_WORDS)

    candidates: List[SPAPeakEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 2:
            continue
        matches = list(_NUM_TOKEN_RE.finditer(line))
        if not matches:
            continue

        in_range: List[tuple[float, int, int]] = []
        for match in matches:
            value = _to_float(match.group(0))
            if value is None or not np.isfinite(value):
                continue
            if lo <= value <= hi:
                in_range.append((float(value), match.start(), match.end()))

        if not in_range:
            continue

        # Avoid noisy generic lines unless they clearly look like peak tables.
        if not block_has_hint and len(matches) > 3 and "\t" not in line and "," not in line and ";" not in line:
            continue

        x_value, start_idx, end_idx = in_range[0]
        tail = line[end_idx:]
        head = line[:start_idx]
        label = _clean_label(tail) if re.search(r"[A-Za-z]", tail) else ""
        if not label and block_has_hint and re.search(r"[A-Za-z]", head):
            label = _clean_label(head)

        if not block_has_hint and not label and len(matches) > 2:
            continue

        candidates.append(SPAPeakEntry(x=x_value, label=label))

    if block_has_hint:
        return candidates
    if len(candidates) >= 2:
        return candidates
    return []


def _merge_peaks(peaks: Iterable[SPAPeakEntry], x: List[float]) -> List[SPAPeakEntry]:
    peak_list = sorted(peaks, key=lambda peak: peak.x)
    if not peak_list:
        return []

    tolerance = 1e-3
    if len(x) > 2:
        diffs = np.abs(np.diff(np.asarray(sorted(x), dtype=np.float64)))
        finite_diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
        if len(finite_diffs) > 0:
            tolerance = max(tolerance, float(np.median(finite_diffs) * 0.35))

    merged: List[SPAPeakEntry] = []
    for peak in peak_list:
        if not merged:
            merged.append(peak)
            continue
        prev = merged[-1]
        if abs(peak.x - prev.x) <= tolerance:
            # Prefer entries with explicit labels.
            if peak.label and (not prev.label or len(peak.label) > len(prev.label)):
                merged[-1] = peak
        else:
            merged.append(peak)

    # Keep this bounded in pathological files.
    return merged[:500]


def _extract_peaks(blob: bytes, entries: List[_SPAEntry], x: List[float]) -> List[SPAPeakEntry]:
    if not x:
        return []
    x_min = float(min(x))
    x_max = float(max(x))

    blocks = _collect_text_blocks(blob, entries)
    found: List[SPAPeakEntry] = []
    for block in blocks:
        found.extend(_extract_peaks_from_block(block, x_min, x_max))

    return _merge_peaks(found, x)


def parse_spa_file(filepath: str) -> SPAParseResult:
    """
    Parse an OMNIC `.spa` file and return spectrum plus embedded peak entries.
    """
    try:
        with open(filepath, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        raise SPAParseError(f"Soubor SPA nelze načíst: {exc}") from exc

    if len(blob) < 600:
        raise SPAParseError("Soubor je příliš malý na to, aby mohl být platným spektrem SPA")
    if not blob.startswith(_SIGNATURE):
        raise SPAParseError("Soubor nebyl rozpoznán jako spektrum OMNIC SPA")

    entries = _scan_entries(blob)
    metadata: Dict[str, Any] = {"source_format": "spa", "source_vendor": "omnic"}

    original_name = _read_name(blob)
    if original_name:
        metadata["omnic_name"] = original_name

    # Timestamp semantics depend on producer; preserve its raw value.
    metadata["omnic_raw_timestamp"] = _read_u32(blob, 296)

    x_array: np.ndarray
    y_array: np.ndarray

    header, y_array = _extract_main_curve(blob, entries)
    x_array = np.linspace(header["first_x"], header["last_x"], header["nx"], dtype=np.float64)
    metadata.update({"x_units": header["x_units"], "y_units": header["y_units"],
                     "x_unit": header["x_units"] or "unknown", "x_title": header["x_title"],
                     "y_title": header["y_title"], "y_unit": header["y_units"] or "unknown",
                     "x_unit_code": header["x_unit_key"], "y_unit_code": header["y_unit_key"],
                     "technique": "raman" if header["x_unit_key"] == 32 else "ir" if header["x_unit_key"] == 1 else "unknown",
                     "y_kind": {16: "transmittance_percent", 17: "absorbance", 23: "transmittance", 31: "intensity"}.get(header["y_unit_key"], "unknown")})
    for key in ("n_scan", "n_background_scan", "collection_length_1_100_s", "reference_frequency_cm1"):
        if key in header:
            metadata[key] = header[key]
    order = np.argsort(x_array, kind="stable")
    x = x_array[order].tolist()
    y = y_array[order].tolist()
    peaks = _extract_peaks(blob, entries, x)

    if peaks:
        metadata["imported_peaks_source"] = "embedded_text_heuristic"
    return SPAParseResult(x=x, y=y, metadata=metadata, peaks=peaks)
