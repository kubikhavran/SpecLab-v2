"""Colour helpers: forgiving colour parsing and print-safe laser-line colours."""

from __future__ import annotations

import re

# Laser lines with an established colour convention in Raman labs.  Visible
# lines follow the spectrum; NIR lines get progressively darker reds/browns so
# that 785 and 1064 nm stay distinguishable and readable in print.
_NIR = (
    (700.0, (0.70, 0.07, 0.07)),
    (785.0, (0.55, 0.04, 0.10)),
    (830.0, (0.44, 0.05, 0.12)),
    (1064.0, (0.30, 0.10, 0.09)),
    (1300.0, (0.22, 0.10, 0.10)),
)


def parse_color(value) -> str:
    """'#abc', '#AABBCC', 'darkred', (r, g, b) → '#rrggbb'; ValueError if unknown."""
    from matplotlib.colors import to_hex

    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[0-9a-fA-F]{6}", text):
            text = "#" + text
        try:
            return to_hex(text.lower().replace(" ", "")).lower()
        except ValueError:
            pass
        try:
            return to_hex(text).lower()
        except ValueError:
            raise ValueError(f"Neznámá barva: {value!r} (použij #RRGGBB nebo název CSS).") from None
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        scale = 255.0 if any(float(v) > 1 for v in value[:3]) else 1.0
        return to_hex([float(v) / scale for v in value[:3]]).lower()
    raise ValueError(f"Neznámá barva: {value!r}.")


def _visible_rgb(nm: float) -> tuple[float, float, float]:
    """Approximate perceived colour of monochromatic light (380–700 nm)."""
    if nm < 440:
        r, g, b = -(nm - 440) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, -(nm - 510) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, -(nm - 645) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    return r, g, b


def wavelength_color(nm: float) -> str:
    """Print-safe colour for a laser line in nm (e.g. 532 → green, 785 → dark red)."""
    nm = float(nm)
    if nm >= 700:
        points = _NIR
        if nm >= points[-1][0]:
            rgb = points[-1][1]
        else:
            for (a, ca), (b, cb) in zip(points, points[1:]):
                if a <= nm <= b:
                    t = (nm - a) / (b - a)
                    rgb = tuple(x + (y - x) * t for x, y in zip(ca, cb))
                    break
    else:
        rgb = _darken_to_luminance(_visible_rgb(max(380.0, nm)), 0.20)
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _darken_to_luminance(rgb, limit: float):
    """Scale light colours (spectral greens, cyans, yellows) until they read on
    white paper; relative luminance ≤ ``limit`` keeps a contrast of about 3.5:1."""
    def linear(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def gamma(c):
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    values = [linear(c) for c in rgb]
    luminance = 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
    if luminance <= limit:
        return rgb
    return tuple(gamma(c * limit / luminance) for c in values)


def palette_colors(name: str, count: int) -> list[str]:
    """Evenly sampled colours of a matplotlib colormap or a SpecLab palette."""
    from matplotlib import colormaps
    from matplotlib.colors import to_hex

    from core.palettes import get_color_for_index, get_palette_colors

    count = max(1, int(count))
    if name in colormaps:
        cmap = colormaps[name]
        if count == 1:
            return [to_hex(cmap(0.5)).lower()]
        # Avoid the near-white ends of sequential maps.
        return [to_hex(cmap(0.08 + 0.80 * i / (count - 1))).lower() for i in range(count)]
    if name != "auto" and get_palette_colors(name, count) is None:
        raise ValueError(f"Neznámá paleta {name!r}.")
    # 'auto' is SpecLab's default colourway (get_color_for_index falls back to it).
    colors = get_palette_colors(name, count)
    return [parse_color(get_color_for_index(colors, i)) for i in range(count)]
