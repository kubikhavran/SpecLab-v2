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
from typing import Any, Dict, Iterable, List

import numpy as np


_SIGNATURE = b"Spectral Data File"
_ENTRY_SIZE = 16
_ENTRY_START = 304
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
    if np.any(np.isinf(y)):
        raise SPAParseError("SPA obsahuje nekonečné hodnoty ordináty")
    # NaN marks regions blanked in OMNIC (e.g. absorption of a carrier film);
    # parse_spa_file removes them and records the ranges as gaps.
    if np.count_nonzero(np.isfinite(y)) < 2:
        raise SPAParseError("SPA neobsahuje dost platných hodnot ordináty")
    return header, y


_ANNOTATION_KEY = 104       # peak labels drawn on the spectrum in OMNIC
_REPORT_KEY = 130           # report blocks; one of them may hold a FIND PEAKS table
_PEAKTABLE_LINE = re.compile(
    r"Position:\s*([-+]?\d+(?:[.,]\d+)?)\s+Intensity:\s*([-+]?\d+(?:[.,]\d+)?)"
)


def _annotation_label(text: str, x: float) -> str:
    """OMNIC writes the rounded position as label text; keep only custom text."""
    try:
        if abs(float(text.replace(",", ".")) - x) <= 1.0:
            return ""
    except ValueError:
        pass
    return text[:120]


def _annotation_peaks(blob: bytes, entries: Iterable[_SPAEntry], lo: float, hi: float) -> List[SPAPeakEntry]:
    """Parse OMNIC annotation records: u32 count, then per label
    u16 flags, f32 peak x, f32 label x, f32 intensity, NUL-terminated text.
    A record that does not fit the layout invalidates the whole block."""
    for entry in entries:
        if entry.key != _ANNOTATION_KEY or entry.length < 4 or entry.offset + entry.length > len(blob):
            continue
        raw = blob[entry.offset: entry.offset + entry.length]
        count = struct.unpack_from("<I", raw, 0)[0]
        if count > 5000:
            return []
        position, peaks = 4, []
        for _ in range(count):
            if position + 14 > len(raw):
                return []
            x_peak, _x_label, intensity = struct.unpack_from("<fff", raw, position + 2)
            end = raw.find(b"\x00", position + 14)
            if end < 0 or end - position - 14 > 120:
                return []
            text = raw[position + 14:end].decode("latin-1").strip()
            position = end + 1
            if not (np.isfinite(x_peak) and np.isfinite(intensity) and lo <= x_peak <= hi):
                return []
            if not text or not text.isprintable():
                return []
            peaks.append(SPAPeakEntry(x=float(x_peak), label=_annotation_label(text, float(x_peak))))
        return peaks
    return []


def _peak_table_peaks(blob: bytes, entries: Iterable[_SPAEntry], lo: float, hi: float) -> List[SPAPeakEntry]:
    """Plain-text FIND PEAKS report ("Position: 1718  Intensity: 34.762")."""
    for entry in entries:
        if entry.key != _REPORT_KEY or entry.offset + entry.length > len(blob):
            continue
        text = blob[entry.offset: entry.offset + entry.length].decode("latin-1", errors="ignore")
        if "FIND PEAKS" not in text:
            continue
        found = [float(x.replace(",", ".")) for x, _ in _PEAKTABLE_LINE.findall(text)]
        peaks = [SPAPeakEntry(x=x) for x in found if lo <= x <= hi]
        if peaks:
            return peaks
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


def _extract_peaks(blob: bytes, entries: List[_SPAEntry], x: List[float]) -> tuple[List[SPAPeakEntry], str]:
    """Peaks labelled in OMNIC, else its FIND PEAKS table. Free text such as
    the processing history or instrument status is never read as peaks."""
    if not x:
        return [], ""
    lo, hi = float(min(x)), float(max(x))
    annotations = _annotation_peaks(blob, entries, lo, hi)
    if annotations:
        return _merge_peaks(annotations, x), "omnic_annotations"
    table = _peak_table_peaks(blob, entries, lo, hi)
    if table:
        return _merge_peaks(table, x), "omnic_peak_table"
    return [], ""


def _read_blob(filepath: str) -> bytes:
    try:
        with open(filepath, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        raise SPAParseError(f"Soubor SPA nelze načíst: {exc}") from exc
    if len(blob) < 600:
        raise SPAParseError("Soubor je příliš malý na to, aby mohl být platným spektrem SPA")
    if not blob.startswith(_SIGNATURE):
        raise SPAParseError("Soubor nebyl rozpoznán jako spektrum OMNIC SPA")
    return blob


def _spectrum(blob: bytes, entries: List[_SPAEntry], metadata: Dict[str, Any]) -> SPAParseResult:
    """One spectrum from its header (2), data (3) and annotation (104) entries."""
    metadata = dict(metadata)
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
    x_sorted, y_sorted = x_array[order], y_array[order]
    blank = np.isnan(y_sorted)
    if np.any(blank):
        edges = np.flatnonzero(np.diff(np.r_[False, blank, False].astype(int)))
        metadata["blanked_regions"] = [
            [float(x_sorted[start]), float(x_sorted[end - 1])]
            for start, end in zip(edges[::2], edges[1::2])
        ]
        x_sorted, y_sorted = x_sorted[~blank], y_sorted[~blank]
    x = x_sorted.tolist()
    y = y_sorted.tolist()
    peaks, peak_source = _extract_peaks(blob, entries, x)
    if peaks:
        metadata["imported_peaks_source"] = peak_source
    return SPAParseResult(x=x, y=y, metadata=metadata, peaks=peaks)


def _base_metadata(blob: bytes) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"source_format": "spa", "source_vendor": "omnic"}
    original_name = _read_name(blob)
    if original_name:
        metadata["omnic_name"] = original_name
    # Timestamp semantics depend on producer; preserve its raw value.
    metadata["omnic_raw_timestamp"] = _read_u32(blob, 296)
    return metadata


def parse_spa_file(filepath: str) -> SPAParseResult:
    """Parse an OMNIC `.spa` file and return spectrum plus embedded peak entries."""
    blob = _read_blob(filepath)
    return _spectrum(blob, _scan_entries(blob), _base_metadata(blob))


_TITLE_KEY = 107   # per-spectrum title in OMNIC groups (often the source file name)


def is_spectrum_group(filepath: str) -> bool:
    blob = _read_blob(filepath)
    return sum(entry.key == 2 for entry in _scan_entries(blob)) > 1


def parse_spg_file(filepath: str) -> List[SPAParseResult]:
    """OMNIC group (.SPG): consecutive header-led blocks, one spectrum each."""
    blob = _read_blob(filepath)
    entries = _scan_entries(blob)
    groups: List[List[_SPAEntry]] = []
    for entry in entries:
        if entry.key == 2:
            groups.append([])
        if groups:
            groups[-1].append(entry)
    groups = [group for group in groups if any(entry.key == 3 for entry in group)]
    if not groups:
        raise SPAParseError("Skupina SPG neobsahuje žádná spektra")
    base = _base_metadata(blob)
    base["source_format"] = "spg"
    results = []
    for index, group in enumerate(groups):
        metadata = dict(base, spectrum_index=index)
        title = next((entry for entry in group if entry.key == _TITLE_KEY), None)
        if title is not None and title.offset + title.length <= len(blob):
            text = blob[title.offset:title.offset + title.length].split(b"\x00", 1)[0]
            name = text.decode("latin-1").strip()
            if name:
                metadata["name"] = re.sub(r"\.(txt|spa|csv)$", "", name, flags=re.IGNORECASE)
        results.append(_spectrum(blob, group, metadata))
    return results
