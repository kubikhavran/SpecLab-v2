"""Filename extraction and numeric series used by both generations of SpecLab."""

from pathlib import Path
import re
import math

NUMBER = r"-?\d+(?:[.,]\d+)?"


def spectrum_names(
    spectra,
    method="sequence",
    prefix="",
    suffix="",
    start=1,
    step=1,
    reverse=False,
    pattern="",
    slice_start=0,
    slice_end=None,
    trim=True,
    numbers_only=False,
):
    if not all(
        isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
        for v in [start, step]
    ):
        raise ValueError("Začátek a krok musí být konečná čísla.")
    if len(prefix) > 100 or len(suffix) > 100 or len(pattern) > 200:
        raise ValueError("Text pravidla je příliš dlouhý.")
    regex = None
    if method == "regex":
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError("Neplatný regulární výraz.") from exc
        if regex.groups < 1:
            raise ValueError(
                "Regulární výraz musí obsahovat zachytávací skupinu (...)."
            )
    ordered = list(reversed(spectra)) if reverse else list(spectra)
    result = {}
    for index, spec in enumerate(ordered):
        # Spectra from multi-spectrum files (SPG groups, WiRE series) carry their
        # own name; the shared file name would give every one the same label.
        if spec.meta.get("sourceCount", 1) > 1:
            stem = spec.name
        else:
            stem = Path(spec.meta.get("sourceName") or spec.name).stem
        if method == "sequence":
            token = f"{start + index * step:g}"
        elif method == "filename":
            token = stem
        elif method == "slice":
            length = len(stem)
            begin = min(
                length, max(0, length + slice_start if slice_start < 0 else slice_start)
            )
            end = (
                length
                if slice_end is None
                else min(
                    length, max(0, length + slice_end if slice_end < 0 else slice_end)
                )
            )
            begin, end = sorted([begin, end])
            token = stem[begin:end]
            if trim:
                token = token.strip()
            if numbers_only:
                match = re.search(NUMBER, token)
                token = match[0] if match else ""
        elif method == "mv":
            # The potential is the last "<number> mV" (e.g. "..._50mV_-200mv",
            # where 50 mV is the step and -200 mV the electrode potential).
            matches = re.findall(f"({NUMBER})\\s*mV", stem, re.IGNORECASE)
            token = matches[-1] if matches else ""
        elif method in {"first", "last"}:
            matches = re.findall(NUMBER, stem)
            token = matches[0 if method == "first" else -1] if matches else ""
        elif method == "regex":
            match = regex.search(stem)
            token = match[1] if match else ""
        else:
            raise ValueError("Neznámé pravidlo názvů.")
        if token:
            if method in {"mv", "first", "last", "regex"}:
                try:
                    token = f"{float(token.replace(',', '.')):g}"
                except ValueError:
                    raise ValueError("Zachycená skupina musí být číslo.") from None
            result[spec.id] = (prefix + token + suffix)[:1000]
        else:
            result[spec.id] = spec.name
    return result
