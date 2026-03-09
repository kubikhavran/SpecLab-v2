"""
Color palettes for spectrum traces.
Direct port of src/features/graphics/palettes.ts.
"""

from __future__ import annotations

import math
from typing import List, Optional


DEFAULT_COLORWAY = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

_COLORBLIND = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#F0E442", "#56B4E9", "#E69F00", "#000000",
]

_PUB_BOLD = [
    "#1F77B4", "#D62728", "#2CA02C", "#9467BD", "#FF7F0E",
    "#17BECF", "#8C564B", "#E377C2", "#BCBD22", "#7F7F7F",
]

_PUB_COLORBLIND = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00",
    "#56B4E9", "#999933", "#000000", "#882255", "#44AA99",
]

_TOL_BRIGHT = [
    "#4477AA", "#EE6677", "#228833", "#CCBB44",
    "#66CCEE", "#AA3377", "#BBBBBB", "#000000",
]

_TOL_MUTED = [
    "#332288", "#88CCEE", "#44AA99", "#117733", "#999933",
    "#DDCC77", "#CC6677", "#882255", "#AA4499",
]

_DEEP_RAINBOW = [
    "#7A0403", "#B42000", "#D84A05", "#F07818", "#E7A21A",
    "#B7B31A", "#6FAF2D", "#2C9F50", "#008D7A", "#007F9F",
    "#2C6DB2", "#5A59B0", "#7A42A8", "#9C2A8F",
]

_TABLEAU10 = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
]

_DARK2 = [
    "#1B9E77", "#D95F02", "#7570B3", "#E7298A",
    "#66A61E", "#E6AB02", "#A6761D", "#666666",
]

_PAIRED = [
    "#A6CEE3", "#1F78B4", "#B2DF8A", "#33A02C", "#FB9A99",
    "#E31A1C", "#FDBF6F", "#FF7F00", "#CAB2D6", "#6A3D9A",
    "#FFFF99", "#B15928",
]

_VIRIDIS = [
    "#440154", "#482878", "#3E4989", "#31688E", "#26828E",
    "#1F9E89", "#35B779", "#6CCE59", "#B4DE2C", "#FDE725",
]

_VIRIDIS_DARK = [
    "#440154", "#482475", "#414487", "#355F8D", "#2A788E",
    "#21908C", "#22A884", "#44BF70", "#7AD151",
]

_PLASMA = [
    "#0D0887", "#41049D", "#6A00A8", "#8F0DA4", "#B12A90",
    "#CC4778", "#E16462", "#F2844B", "#FCA636", "#F0F921",
]

_PLASMA_DARK = [
    "#0D0887", "#46039F", "#7201A8", "#9C179E", "#BD3786",
    "#D8576B", "#ED7953", "#FB9F3A", "#FDCA26",
]

_MAGMA = [
    "#000004", "#1B0C41", "#4F0A6D", "#781C6D", "#A52C60",
    "#CF4446", "#ED6925", "#FB9B06", "#F7D13D", "#FCFDBF",
]

_CIVIDIS = [
    "#00204C", "#00306F", "#2A3F85", "#4A4C8C", "#67598E",
    "#81658A", "#9A7083", "#B37C78", "#CC886B", "#E69B5E",
]

_CIVIDIS_DARK = [
    "#00224E", "#123570", "#3B496C", "#575D6D", "#707173",
    "#8A8678", "#A39B7C", "#BCB07E", "#D5C57F",
]

_ELECTROCHEM = [
    "#B40426", "#D73027", "#F46D43", "#FDAE61", "#FEE08B",
    "#D9EF8B", "#A6D96A", "#66C2A5", "#3288BD", "#5E4FA2",
    "#6A3D9A", "#7B3294", "#4D004B",
]

_MONO = [
    "#111827", "#1F2937", "#374151", "#4B5563",
    "#6B7280", "#9CA3AF", "#D1D5DB", "#E5E7EB",
]

_NEON = [
    "#00E5FF", "#FF00E5", "#7CFF00", "#FFD500",
    "#FF3B30", "#5E5CE6", "#00FF9C", "#FF6B00",
]


def _sample_even(base: List[str], count: int) -> List[str]:
    """Evenly sample *count* colors from *base* palette."""
    if not base:
        return []
    if count <= 1:
        return [base[0]]
    return [
        base[round(i * (len(base) - 1) / (count - 1))]
        for i in range(count)
    ]


def _gradient(base: List[str], count: Optional[int]) -> List[str]:
    if count is not None and math.isfinite(count) and count > 0:
        return _sample_even(base, max(1, int(count)))
    return list(base)


# Maps palette name → (list, is_gradient)
_FIXED: dict[str, List[str]] = {
    "pubBold": _PUB_BOLD,
    "pubColorblind": _PUB_COLORBLIND,
    "tolBright": _TOL_BRIGHT,
    "tolMuted": _TOL_MUTED,
    "colorblind": _COLORBLIND,
    "tableau10": _TABLEAU10,
    "dark2": _DARK2,
    "paired": _PAIRED,
    "mono": _MONO,
    "neon": _NEON,
}

_GRADIENT: dict[str, List[str]] = {
    "deepRainbow": _DEEP_RAINBOW,
    "viridisDark": _VIRIDIS_DARK,
    "plasmaDark": _PLASMA_DARK,
    "cividisDark": _CIVIDIS_DARK,
    "viridis": _VIRIDIS,
    "plasma": _PLASMA,
    "magma": _MAGMA,
    "cividis": _CIVIDIS,
    "electrochem": _ELECTROCHEM,
}


def get_palette_colors(
    palette: str, count: Optional[int] = None
) -> Optional[List[str]]:
    """
    Return the color list for *palette*, or None for 'auto'.

    For gradient palettes, *count* controls how many evenly-spaced samples
    are drawn from the base gradient.
    """
    if palette == "auto":
        return None
    if palette in _FIXED:
        return list(_FIXED[palette])
    if palette in _GRADIENT:
        return _gradient(_GRADIENT[palette], count)
    return None


def get_color_for_index(
    palette_colors: Optional[List[str]], index: int
) -> str:
    """Return the color for trace *index*, falling back to DEFAULT_COLORWAY."""
    if palette_colors and len(palette_colors) > 0:
        return palette_colors[index % len(palette_colors)]
    return DEFAULT_COLORWAY[index % len(DEFAULT_COLORWAY)]
