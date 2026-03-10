"""Core data models for SpecLab – mirrors the TypeScript types from core.ts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Spectrum:
    id: str = field(default_factory=_new_id)
    name: str = ""
    x: List[float] = field(default_factory=list)    # wavenumber / wavelength
    y: List[float] = field(default_factory=list)    # raw intensity
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlotSettings:
    show_grid: bool = True
    show_all_spectra: bool = False
    reverse_overlay_order: bool = False
    stack_offset: float = 0.0
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    invert_x: bool = False


@dataclass
class BaselineSettings:
    enabled: bool = False
    show_overlay: bool = True
    lambda_: float = 1e6        # underscore to avoid Python keyword
    p: float = 0.01
    iterations: int = 10


@dataclass
class SmoothingSettings:
    window: int = 11
    poly_order: int = 3


@dataclass
class CosmicSettings:
    window: int = 11
    threshold: float = 6.0
    max_width: int = 3
    positive_only: bool = True
    iterations: int = 1
    manual_enabled: bool = False


@dataclass
class Peak:
    id: str = field(default_factory=_new_id)
    x: float = 0.0
    source: str = "auto"        # "auto" | "manual"
    label: Optional[str] = None
    i: Optional[int] = None
    kind: str = "max"           # "max" | "min"
    prominence: Optional[float] = None
    width: Optional[float] = None


@dataclass
class PeaksSettings:
    enabled: bool = False
    mode: str = "active"        # "active" | "all"
    source: str = "displayed"   # "displayed" | "processed"
    polarity: str = "max"       # "max" | "min" | "both"
    min_prominence: float = 20.0
    min_distance: int = 10
    max_peaks: int = 20
    manual_pick_enabled: bool = False
    show_markers: bool = True
    show_labels: bool = True
    show_leader_lines: bool = True
    label_angle_deg: float = -90.0
    label_font_size: int = 24
    label_bold: bool = False
    label_italic: bool = False
    label_color_mode: str = "trace"   # "trace" | "custom"
    label_color: str = "#111827"
    leader_color_mode: str = "trace"
    leader_color: str = "#111827"
    leader_line_width: int = 1
    decimals: int = 0


@dataclass
class GraphicsSettings:
    x_label: str = "X"
    y_label: str = "Y"
    axis_label_bold: bool = False
    axis_label_italic: bool = False
    tick_label_bold: bool = False
    tick_label_italic: bool = False
    show_x_tick_marks: bool = True
    show_y_tick_marks: bool = True
    show_x_tick_labels: bool = True
    show_y_tick_labels: bool = False
    show_grid: bool = False
    grid_color: str = "#e2e8f0"
    grid_width: int = 1
    axis_line_width: int = 4
    axis_line_color: str = "#000000"
    frame_mode: str = "open"          # "open" | "box"
    trace_line_width: int = 4
    font_family: str = "Arial"
    base_font_size: int = 32
    tick_font_size: int = 30
    palette: str = "auto"
    inline_spectrum_labels: bool = True
    plot_canvas: str = "auto"         # "auto" | "white" | "dark"
    export_width: int = 1600
    export_height: int = 900


@dataclass
class ExportSettings:
    filename: str = ""
    folder: str = ""
