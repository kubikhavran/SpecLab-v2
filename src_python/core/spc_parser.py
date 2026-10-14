"""Read a single float32 Galactic SPC spectrum, uniform or explicit X axis.

Both new-format byte orders (0x4B and 0x4C) are supported. Integer-scaled,
multifile and XYXY variants are rejected rather than interpreted as text.
Layout reference: SpectroChemPy read_spc and Galactic Universal Data Format.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any


class SPCParseError(ValueError):
    pass


def parse_spc_file(filepath: str) -> dict[str, Any]:
    blob = Path(filepath).read_bytes()
    if len(blob) < 544 or blob[1] not in (0x4B, 0x4C):
        raise SPCParseError("Unsupported or truncated SPC header (only new-format 0x4B/0x4C is supported)")
    endian = "<" if blob[1] == 0x4B else ">"
    flags, technique_code = blob[0], blob[2]
    exponent = struct.unpack_from("b", blob, 3)[0]
    points = struct.unpack_from(endian + "I", blob, 4)[0]
    first, last = struct.unpack_from(endian + "dd", blob, 8)
    subfiles = struct.unpack_from(endian + "I", blob, 24)[0]
    xtype, ytype = blob[28], blob[29]
    if flags & (0x04 | 0x40) or subfiles != 1:
        raise SPCParseError("SPC multifile/XYXY variants are unsupported; export each spectrum to CSV")
    if exponent != -128:
        raise SPCParseError("Integer-scaled SPC data is unsupported; export floating data or CSV")
    if points < 2 or points > len(blob) // 4 or not all(math.isfinite(value) for value in (first, last)):
        raise SPCParseError("Invalid SPC point count or axis limits")
    cursor = 512
    if flags & 0x80:
        if cursor + 4 * points + 32 > len(blob):
            raise SPCParseError("Truncated SPC explicit X values")
        x = list(struct.unpack_from(endian + f"{points}f", blob, cursor))
        cursor += points * 4
    else:
        x = [first + index * (last - first) / (points - 1) for index in range(points)]
    subpoints = struct.unpack_from(endian + "I", blob, cursor + 16)[0]
    if subpoints not in (0, points):
        raise SPCParseError("SPC subfile point count disagrees with header")
    cursor += 32
    if cursor + points * 4 > len(blob):
        raise SPCParseError("Truncated SPC ordinate data")
    y = list(struct.unpack_from(endian + f"{points}f", blob, cursor))
    metadata = {"source_format": "spc", "source_vendor": "galactic", "name": Path(filepath).stem,
                "x_unit": {1: "cm^-1", 2: "um", 3: "nm", 13: "cm^-1", 14: "eV"}.get(xtype, "unknown"),
                "y_kind": {2: "absorbance", 11: "transmittance_percent", 128: "transmittance", 0: "intensity", 4: "intensity", 12: "intensity", 13: "intensity"}.get(ytype, "unknown"),
                "technique": "raman" if technique_code == 11 or xtype == 13 else "uvvis" if technique_code == 7 else "ir" if technique_code == 5 else "unknown",
                "spc_technique_code": technique_code, "x_unit_code": xtype, "y_unit_code": ytype,
                "comment": blob[88:218].split(b"\0", 1)[0].decode("latin-1")}
    if flags & 0x20:
        labels = blob[218:248].split(b"\0")
        if labels[0]:
            metadata["x_title"] = labels[0].decode("latin-1")
            metadata["x_unit"] = "unknown"
        if len(labels) > 1 and labels[1]:
            metadata["y_title"] = labels[1].decode("latin-1")
            metadata["y_kind"] = "unknown"
    if ytype == 1:
        raise SPCParseError("SPC interferograms are not supported as spectra")
    return {"x": x, "y": y, "metadata": metadata}
