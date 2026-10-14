"""JCAMP-DX AFFN/PAC reader; unsupported compressed/NTUPLES forms fail clearly.

Reference: IUPAC JCAMP-DX IR 1988 specification, including unscaled FIRSTX /
LASTX and XFACTOR / YFACTOR for the stored table.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


class JCAMPParseError(ValueError):
    pass


_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")


def _numbers(line: str) -> list[float]:
    matches = list(_NUMBER.finditer(line))
    remainder = _NUMBER.sub("", line)
    if remainder.strip(" \t,;"):
        raise JCAMPParseError("Compressed SQZ/DIF/DUP or invalid JCAMP data is unsupported; export AFFN/PAC or CSV")
    values = [float(match.group()) for match in matches]
    if not values or not all(math.isfinite(value) for value in values):
        raise JCAMPParseError("Invalid or non-finite JCAMP numeric data")
    return values


def _finish(headers: dict[str, str], rows: list[str], form: str) -> dict[str, Any]:
    def scalar(key: str, default=None) -> float:
        if key not in headers and default is not None:
            return default
        try:
            value = float(headers[key])
        except (KeyError, ValueError) as exc:
            raise JCAMPParseError(f"Missing or invalid JCAMP {key}") from exc
        if not math.isfinite(value):
            raise JCAMPParseError(f"Non-finite JCAMP {key}")
        return value

    xf, yf = scalar("XFACTOR", 1.0), scalar("YFACTOR", 1.0)
    if xf == 0 or yf == 0:
        raise JCAMPParseError("JCAMP scale factors cannot be zero")
    count_value = scalar("NPOINTS")
    if count_value < 2 or count_value != int(count_value):
        raise JCAMPParseError("Invalid JCAMP NPOINTS")
    count = int(count_value)
    x: list[float] = []
    y: list[float] = []
    if form == "XYDATA":
        if headers[form].replace(" ", "").upper() != "(X++(Y..Y))":
            raise JCAMPParseError("Unsupported JCAMP XYDATA layout")
        first, last = scalar("FIRSTX"), scalar("LASTX")
        step = (last - first) / (count - 1)
        if step == 0:
            raise JCAMPParseError("JCAMP X axis has zero spacing")
        tolerance = max(abs(step) * 0.02, abs(first) * 1e-7, 1e-9)
        for row in rows:
            values = _numbers(row)
            if len(values) < 2:
                raise JCAMPParseError("JCAMP XYDATA line has no ordinate values")
            expected = first + len(y) * step
            if not math.isclose(values[0] * xf, expected, rel_tol=0, abs_tol=tolerance):
                raise JCAMPParseError("JCAMP row X checkpoint disagrees with declared axis")
            y.extend(value * yf for value in values[1:])
            if len(y) > count:
                raise JCAMPParseError("JCAMP contains more data than declared NPOINTS")
        x = [first + index * step for index in range(count)]
    elif form == "XYPOINTS":
        for row in rows:
            values = _numbers(row)
            if len(values) % 2:
                raise JCAMPParseError("JCAMP XYPOINTS requires complete X/Y pairs")
            x.extend(value * xf for value in values[::2])
            y.extend(value * yf for value in values[1::2])
    if len(y) != count or len(x) != count:
        raise JCAMPParseError("JCAMP data length does not match NPOINTS")
    xunits = headers.get("XUNITS", "unknown")
    yunits = headers.get("YUNITS", "unknown")
    data_type = headers.get("DATATYPE", "").upper()
    technique = "raman" if "RAMAN" in data_type else "uvvis" if "UV" in data_type or "VIS" in data_type else "ir" if "INFRARED" in data_type else "unknown"
    ykind = "absorbance" if "ABSORB" in yunits.upper() else "transmittance_percent" if "%" in yunits and "TRANSM" in yunits.upper() else "transmittance" if "TRANSM" in yunits.upper() else "intensity" if "INTENS" in yunits.upper() or "COUNTS" in yunits.upper() else "unknown"
    xunit = "cm^-1" if xunits.upper() in {"1/CM", "CM-1", "CM^-1", "WAVENUMBERS"} else "nm" if xunits.upper() in {"NM", "NANOMETERS", "NANOMETRES"} else xunits
    return {"x": x, "y": y, "metadata": {"source_format": "jcamp", "name": headers.get("TITLE", "Spectrum"),
            "technique": technique, "x_unit": xunit, "y_kind": ykind, "y_unit": yunits,
            "jcamp_headers": dict(headers), "jcamp_encoding": "AFFN/PAC"}}


def parse_jcamp_file(filepath: str) -> list[dict[str, Any]]:
    try:
        text = Path(filepath).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise JCAMPParseError("JCAMP-DX must contain readable text") from exc
    headers: dict[str, str] = {}
    rows: list[str] = []
    form = ""
    results = []
    for line in text.splitlines():
        line = line.split("$$", 1)[0].strip()
        if not line:
            continue
        if line.startswith("##"):
            if "=" not in line:
                raise JCAMPParseError("Invalid JCAMP labelled data record")
            key, value = line[2:].split("=", 1)
            key = re.sub(r"[\s_-]", "", key).upper()
            value = value.strip()
            if key == "TITLE":
                if rows:
                    raise JCAMPParseError("JCAMP spectrum is missing its END record")
                headers, rows, form = {}, [], ""
            if key in {"NTUPLES", "DATATABLE", "PEAKTABLE", "PEAKASSIGNMENTS"}:
                raise JCAMPParseError("JCAMP NTUPLES or peak-table data is unsupported; export XYDATA/XYPOINTS or CSV")
            if key == "END":
                if form:
                    results.append(_finish(headers, rows, form))
                headers, rows, form = {}, [], ""
                continue
            if key in {"XYDATA", "XYPOINTS"}:
                if form:
                    raise JCAMPParseError("Several data tables in one JCAMP block are unsupported")
                form = key
            headers[key] = value
        elif form:
            rows.append(line)
    if rows or form:
        raise JCAMPParseError("JCAMP spectrum is missing its END record")
    if not results:
        raise JCAMPParseError("No supported JCAMP spectra found")
    return results
