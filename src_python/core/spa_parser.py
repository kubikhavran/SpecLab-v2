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
  - malformed sections are skipped
  - unknown variants raise SPAParseError with a clear message
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import numpy as np


_SIGNATURE = b"Spectral Data File"
_BASE_TIME = datetime(1899, 12, 31, tzinfo=timezone.utc)
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
_ASCII_BLOCK_RE = re.compile(rb"[\x09\x0A\x0D\x20-\x7E]{24,}")
_UTF16_BLOCK_RE = re.compile(rb"(?:[\x20-\x7E]\x00){12,}")

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
        raise SPAParseError("Unexpected end of SPA file")
    return blob[offset]


def _read_u16(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(blob):
        raise SPAParseError("Unexpected end of SPA file")
    return struct.unpack_from("<H", blob, offset)[0]


def _read_u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        raise SPAParseError("Unexpected end of SPA file")
    return struct.unpack_from("<I", blob, offset)[0]


def _read_i32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        raise SPAParseError("Unexpected end of SPA file")
    return struct.unpack_from("<i", blob, offset)[0]


def _read_f32(blob: bytes, offset: int) -> float:
    if offset < 0 or offset + 4 > len(blob):
        raise SPAParseError("Unexpected end of SPA file")
    return struct.unpack_from("<f", blob, offset)[0]


def _read_text(blob: bytes, offset: int, length: int) -> str:
    if offset < 0 or length <= 0 or offset + length > len(blob):
        return ""
    data = blob[offset : offset + length]
    # Replace NUL runs with newlines for readability.
    data = re.sub(rb"\x00+", b"\n", data)
    text = data.decode("utf-8", errors="ignore").strip()
    if not text:
        text = data.decode("latin-1", errors="ignore").strip()
    return text


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
    entries: List[_SPAEntry] = []

    # Most files expose line count here. If not sane, we fallback to sentinel scan.
    nlines: Optional[int] = None
    if len(blob) >= 296:
        try:
            candidate = _read_u16(blob, 294)
            if 0 < candidate <= 4096:
                nlines = int(candidate)
        except SPAParseError:
            nlines = None

    if nlines is not None:
        for i in range(nlines):
            pos = _ENTRY_START + i * _ENTRY_SIZE
            if pos + _ENTRY_SIZE > len(blob):
                break
            key = _read_u8(blob, pos)
            if key in (0, 1):
                break
            offset = _read_u32(blob, pos + 2)
            length = _read_u32(blob, pos + 6)
            entries.append(_SPAEntry(key=key, offset=offset, length=length))
        return entries

    pos = _ENTRY_START
    max_scan = min(len(blob), _ENTRY_START + 4096 * _ENTRY_SIZE)
    while pos + _ENTRY_SIZE <= max_scan:
        key = _read_u8(blob, pos)
        if key in (0, 1):
            break
        offset = _read_u32(blob, pos + 2)
        length = _read_u32(blob, pos + 6)
        entries.append(_SPAEntry(key=key, offset=offset, length=length))
        pos += _ENTRY_SIZE

    return entries


def _parse_header(blob: bytes, header_offset: int) -> Dict[str, Any]:
    if header_offset <= 0 or header_offset + 192 > len(blob):
        raise SPAParseError("SPA header position is invalid")

    nx = _read_u32(blob, header_offset + 4)
    if nx < 2:
        raise SPAParseError("SPA header contains too few points")

    first_x = _read_f32(blob, header_offset + 16)
    last_x = _read_f32(blob, header_offset + 20)
    if not np.isfinite(first_x) or not np.isfinite(last_x):
        raise SPAParseError("SPA header contains invalid x-axis limits")

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

    # Additional metadata (best effort).
    try:
        info["n_scan"] = int(_read_u32(blob, header_offset + 36))
        info["n_background_scan"] = int(_read_u32(blob, header_offset + 52))
        info["collection_length_1_100_s"] = int(_read_u32(blob, header_offset + 68))
        info["reference_frequency_cm1"] = float(_read_f32(blob, header_offset + 80))
        info["optical_velocity"] = float(_read_f32(blob, header_offset + 188))
    except SPAParseError:
        pass

    return info


def _read_float_vector(blob: bytes, offset: int, count: int) -> np.ndarray:
    if count <= 0:
        raise SPAParseError("SPA data block has no points")
    n_bytes = count * 4
    if offset < 0 or offset + n_bytes > len(blob):
        raise SPAParseError("SPA data block points outside file bounds")
    return np.frombuffer(blob, dtype="<f4", count=count, offset=offset).astype(
        np.float64,
        copy=False,
    )


def _extract_main_curve(blob: bytes, entries: Iterable[_SPAEntry]) -> tuple[Dict[str, Any], np.ndarray]:
    header_entry = next((entry for entry in entries if entry.key == 2), None)
    if header_entry is None:
        raise SPAParseError("SPA header marker (key=2) was not found")

    header = _parse_header(blob, header_entry.offset)

    spectral_entry = next((entry for entry in entries if entry.key == 3), None)
    if spectral_entry is None:
        raise SPAParseError("SPA spectrum data marker (key=3) was not found")

    expected_n = int(header["nx"])
    if spectral_entry.length >= 4 and spectral_entry.length % 4 == 0:
        count = spectral_entry.length // 4
    else:
        count = expected_n
    count = min(count, expected_n) if expected_n > 0 else count

    y = _read_float_vector(blob, spectral_entry.offset, count)
    if len(y) < 2:
        raise SPAParseError("SPA spectrum data contains too few points")

    return header, y


def _legacy_curve_fallback(blob: bytes) -> tuple[np.ndarray, np.ndarray]:
    """
    Fallback parser for older SPA variants that may not expose full key blocks.
    """
    if len(blob) < 584:
        raise SPAParseError("SPA file is too small for legacy fallback parser")

    points = _read_i32(blob, 564)
    if points < 2:
        raise SPAParseError("Legacy SPA fallback: invalid point count")

    high_x = _read_f32(blob, 576)
    low_x = _read_f32(blob, 580)
    if not np.isfinite(high_x) or not np.isfinite(low_x):
        raise SPAParseError("Legacy SPA fallback: invalid x-axis limits")

    data_offset = -1
    scan_limit = min(len(blob) - 8, 4096)
    for pos in range(288, scan_limit, 2):
        flag = _read_u16(blob, pos)
        if flag != 3:
            continue
        maybe_u32 = _read_u32(blob, pos + 2)
        if 0 <= maybe_u32 <= len(blob) - 8:
            data_offset = maybe_u32
            break
        maybe_u16 = _read_u16(blob, pos + 2)
        if 0 <= maybe_u16 <= len(blob) - 8:
            data_offset = maybe_u16
            break

    if data_offset < 0:
        raise SPAParseError("Legacy SPA fallback: data offset not found")

    count = min(points, (len(blob) - data_offset) // 4)
    if count < 2:
        raise SPAParseError("Legacy SPA fallback: not enough data points")

    y = np.frombuffer(blob, dtype="<f4", count=count, offset=data_offset).astype(
        np.float64,
        copy=False,
    )
    x = np.linspace(low_x, high_x, count, dtype=np.float64)
    return x, y


def _is_text_like(raw: bytes) -> bool:
    if not raw:
        return False
    printable = sum(1 for b in raw if b in (9, 10, 13) or 32 <= b <= 126)
    return printable / max(1, len(raw)) >= 0.45


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
        if entry.key in _TEXT_KEYS or _is_text_like(raw):
            blocks.extend(_decode_text_block(raw))

    for match in _ASCII_BLOCK_RE.finditer(blob):
        text = match.group(0).decode("latin-1", errors="ignore").strip()
        if text:
            blocks.append(text)

    for match in _UTF16_BLOCK_RE.finditer(blob):
        text = match.group(0).decode("utf-16-le", errors="ignore").strip()
        if text:
            blocks.append(text)

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
        raise SPAParseError(f"Cannot read SPA file: {exc}") from exc

    if len(blob) < 600:
        raise SPAParseError("File is too small to be a valid SPA spectrum")
    if not blob.startswith(_SIGNATURE):
        raise SPAParseError("File is not recognized as an OMNIC SPA spectrum")

    entries = _scan_entries(blob)
    metadata: Dict[str, Any] = {"source_format": "spa", "source_vendor": "omnic"}

    original_name = _read_name(blob)
    if original_name:
        metadata["omnic_name"] = original_name

    try:
        raw_ts = _read_u32(blob, 296)
        acquired = _BASE_TIME + timedelta(seconds=int(raw_ts))
        metadata["acquired_at_utc"] = acquired.isoformat()
    except SPAParseError:
        pass

    x_array: np.ndarray
    y_array: np.ndarray

    try:
        header, y_array = _extract_main_curve(blob, entries)
        n = int(header["nx"])
        x_array = np.linspace(
            float(header["first_x"]),
            float(header["last_x"]),
            n,
            dtype=np.float64,
        )
        metadata.update(
            {
                "x_units": header.get("x_units"),
                "y_units": header.get("y_units"),
                "x_title": header.get("x_title"),
                "y_title": header.get("y_title"),
            }
        )
        for key in (
            "n_scan",
            "n_background_scan",
            "collection_length_1_100_s",
            "reference_frequency_cm1",
            "optical_velocity",
        ):
            if key in header:
                metadata[key] = header[key]
    except SPAParseError:
        # Try fallback parser for older variants.
        x_array, y_array = _legacy_curve_fallback(blob)

    n_points = min(len(x_array), len(y_array))
    if n_points < 2:
        raise SPAParseError("SPA spectrum contains too few valid points")

    x = x_array[:n_points].astype(np.float64, copy=False).tolist()
    y = y_array[:n_points].astype(np.float64, copy=False).tolist()
    peaks = _extract_peaks(blob, entries, x)

    return SPAParseResult(x=x, y=y, metadata=metadata, peaks=peaks)
