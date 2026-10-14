"""Constrained native Renishaw WDF1 reader, with no reader dependency.

Binary layouts verified against Renishaw's renishaw-wdf 1.4.0 distribution:
https://pypi.org/project/renishaw-wdf/ (Apache-2.0). Single-track float32
spectra and series/map origins are supported. Multitrack, XYXY and filter
images are rejected. Fits and embedded images are not interpreted.
"""

from __future__ import annotations

import math
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class WDFParseError(ValueError):
    pass


_UNITS = {0: "a.u.", 1: "cm^-1", 2: "cm^-1", 3: "nm", 4: "eV", 5: "um", 6: "counts",
          8: "mm", 9: "m", 10: "K", 11: "Pa", 12: "s", 13: "ms", 18: "relative intensity",
          21: "degC", 24: "FILETIME", 26: "V"}
_ORIGIN_NAMES = {3: "stage_x", 4: "stage_y", 5: "stage_z", 9: "temperature", 10: "pressure",
                 11: "time", 17: "flags", 18: "elapsed_time"}


def _unpack(blob: bytes, fmt: str, offset: int):
    if offset < 0 or offset + struct.calcsize(fmt) > len(blob):
        raise WDFParseError("Truncated WDF header or data block")
    return struct.unpack_from(fmt, blob, offset)


def _text(blob: bytes) -> str:
    return blob.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()


def parse_wdf_file(filepath: str) -> list[dict[str, Any]]:
    blob = Path(filepath).read_bytes()
    if len(blob) < 512 or blob[:4] != b"WDF1":
        raise WDFParseError("Not a valid Renishaw WDF1 file")
    version = _unpack(blob, "<I", 4)[0]
    header_size, flags = _unpack(blob, "<QQ", 8)
    ntracks, status, points = _unpack(blob, "<III", 52)
    capacity, collected = _unpack(blob, "<QQ", 64)
    xcount = _unpack(blob, "<I", 88)[0]
    scan_type, measurement_type = _unpack(blob, "<II", 128)
    y_unit = _unpack(blob, "<I", 152)[0]
    laser = _unpack(blob, "<f", 156)[0]
    if version != 1 or header_size < 512 or header_size > len(blob):
        raise WDFParseError("Unsupported WDF header version or length")
    if flags & 0x09 or ntracks > 1:
        raise WDFParseError("WDF multitrack/XYXY data requires a dedicated reader; export single-track spectra from WiRE")
    if (scan_type & 0xFF) in (4, 5) or measurement_type not in (1, 2, 3):
        raise WDFParseError("Unsupported WDF image or measurement layout")
    if points < 2 or xcount != points or not 0 < collected <= capacity:
        raise WDFParseError("Invalid WDF point count, X list, or collected spectrum count")
    if collected * points > (len(blob) // 4):
        raise WDFParseError("WDF dimensions exceed available data")
    sections: dict[bytes, list[tuple[int, int]]] = {}
    position = header_size
    while position < len(blob):
        tag, uid, size = _unpack(blob, "<4sIQ", position)
        if size < 16 or position + size > len(blob):
            raise WDFParseError("Invalid or truncated WDF section length")
        sections.setdefault(tag, []).append((position + 16, size - 16))
        position += size
    for tag in (b"DATA", b"XLST"):
        if len(sections.get(tag, [])) != 1:
            raise WDFParseError(f"WDF requires exactly one {tag.decode()} section")
    xpos, xsize = sections[b"XLST"][0]
    xtype, xunit = _unpack(blob, "<II", xpos)
    if xsize != 8 + points * 4 or xtype not in (1, 19):
        raise WDFParseError("Unsupported WDF X-list dimensions or data type")
    x = list(_unpack(blob, f"<{points}f", xpos + 8))
    dpos, dsize = sections[b"DATA"][0]
    if dsize % 4 or dsize < collected * points * 4 or dsize > capacity * points * 4:
        raise WDFParseError("Truncated or inconsistent WDF spectral DATA section")
    base = {"source_format": "wdf", "source_vendor": "renishaw", "name": _text(blob[240:400]) or Path(filepath).stem,
            "technique": "raman" if xunit == 1 else "unknown", "x_unit": _UNITS.get(xunit, "unknown"),
            "y_kind": "intensity", "y_unit": _UNITS.get(y_unit, "unknown"), "x_unit_code": xunit,
            "measurement_type": measurement_type, "scan_type": scan_type, "wdf_flags": flags,
            "collected_count": collected, "capacity": capacity, "status": status}
    if math.isfinite(laser) and laser > 0:
        base["laser_wavenumber_cm1"] = float(laser)
    origins: list[dict[str, Any]] = [{} for _ in range(collected)]
    if b"ORGN" in sections:
        if len(sections[b"ORGN"]) != 1:
            raise WDFParseError("Unsupported multiple WDF ORGN sections")
        opos, osize = sections[b"ORGN"][0]
        origin_count = _unpack(blob, "<I", opos)[0]
        if 4 + origin_count * (24 + capacity * 8) != osize:
            raise WDFParseError("Inconsistent WDF origin record length")
        cursor = opos + 4
        for _ in range(origin_count):
            dtype, unit = _unpack(blob, "<II", cursor)
            dtype &= 0x7FFFFFFF
            label = _text(blob[cursor + 8:cursor + 24])
            fmt = "Q" if unit == 24 or dtype in (16, 17) else "d"
            values = _unpack(blob, f"<{collected}{fmt}", cursor + 24)
            key = _ORIGIN_NAMES.get(dtype, f"origin_{dtype}")
            for index, value in enumerate(values):
                if unit == 24:
                    try:
                        value = (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value // 10)).isoformat()
                    except OverflowError as exc:
                        raise WDFParseError("Invalid WDF timestamp") from exc
                elif not math.isfinite(value):
                    raise WDFParseError("Non-finite WDF origin value")
                origins[index][key] = value
                origins[index][f"{key}_unit"] = _UNITS.get(unit, str(unit))
                if label:
                    origins[index][f"{key}_label"] = label
            cursor += 24 + capacity * 8
    if b"WMAP" in sections:
        mpos, msize = sections[b"WMAP"][0]
        if msize < 48:
            raise WDFParseError("Truncated WDF map definition")
        mapflags = _unpack(blob, "<I", mpos)[0]
        start = _unpack(blob, "<3f", mpos + 8)
        step = _unpack(blob, "<3f", mpos + 20)
        shape = _unpack(blob, "<3I", mpos + 32)
        if not all(math.isfinite(value) for value in (*start, *step)):
            raise WDFParseError("Non-finite WDF map coordinates")
        base["map_definition"] = {"flags": mapflags, "start": list(start), "step": list(step), "shape": list(shape)}
    results = []
    for index in range(collected):
        y = list(_unpack(blob, f"<{points}f", dpos + index * points * 4))
        metadata = dict(base)
        metadata.update(origins[index])
        metadata["spectrum_index"] = index
        if collected > 1:
            metadata["name"] = f"{base['name']} [{index + 1}]"
        results.append({"x": x.copy(), "y": y, "metadata": metadata})
    return results
