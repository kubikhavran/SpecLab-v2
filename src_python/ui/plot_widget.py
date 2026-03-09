"""
Interactive spectrum plot using PyQtGraph.
Replaces the Plotly-based PlotArea.tsx from the React app.

Features:
  - Renders one or many spectra (overlay / single mode)
  - Color-codes traces via the palette system
  - Highlights active spectrum with thicker line
  - Supports stack offset for overlaid spectra
  - Auto-range, invert X, grid toggle
  - Crosshair + coordinate readout in status bar
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.state import AppState
from core.palettes import get_color_for_index, get_palette_colors


class SpectrumPlotWidget(QWidget):
    """Central plot area — displays spectrum traces via PyQtGraph."""

    # Emitted when the user clicks on the plot canvas (x_data, y_data)
    plot_clicked = Signal(float, float)

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state

        # ── Trace book-keeping ──────────────────────────
        self._trace_items: List[pg.PlotDataItem] = []
        self._baseline_item: Optional[pg.PlotDataItem] = None
        self._peak_scatter: Optional[pg.ScatterPlotItem] = None
        self._peak_labels: List[pg.TextItem] = []
        self._peaks_panel: Optional["PeaksPanel"] = None  # set externally

        self._build_ui()
        self._connect_signals()
        self._redraw()

    def set_peaks_panel(self, panel) -> None:
        """Store a reference to the PeaksPanel for manual pick callbacks."""
        self._peaks_panel = panel

    # ── UI construction ────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(2)

        # PyQtGraph setup
        pg.setConfigOptions(antialias=True, background="w", foreground="k")

        self._plot_widget = pg.PlotWidget()
        self._plot_item = self._plot_widget.getPlotItem()

        # Axis labels (will be updated from graphics settings later)
        self._plot_item.setLabel("bottom", "X")
        self._plot_item.setLabel("left", "Y")

        # Enable built-in mouse interaction (zoom, pan)
        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_widget.enableAutoRange()

        # Crosshair
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#94a3b8", width=1, style=Qt.PenStyle.DashLine))
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#94a3b8", width=1, style=Qt.PenStyle.DashLine))
        self._plot_widget.addItem(self._vline, ignoreBounds=True)
        self._plot_widget.addItem(self._hline, ignoreBounds=True)
        self._vline.setVisible(False)
        self._hline.setVisible(False)

        # Mouse move proxy for crosshair
        self._proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse_moved,
        )

        # Click detection
        self._plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        layout.addWidget(self._plot_widget, stretch=1)

        # Coordinate readout label
        self._coord_label = QLabel("")
        self._coord_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 2px 4px;")
        layout.addWidget(self._coord_label)

    # ── Signal wiring ──────────────────────────────────────

    def _connect_signals(self) -> None:
        self._state.spectra_changed.connect(self._redraw)
        self._state.active_spectrum_changed.connect(self._redraw)
        self._state.plot_changed.connect(self._redraw)
        self._state.graphics_changed.connect(self._redraw)
        # Redraw when processing results change
        self._state.baseline_changed.connect(self._redraw)
        self._state.smoothing_changed.connect(self._redraw)
        self._state.cosmic_changed.connect(self._redraw)
        self._state.peaks_changed.connect(self._redraw)

    # ── Core drawing ───────────────────────────────────────

    def _redraw(self) -> None:
        """Clear all traces and redraw from current state."""
        # Remove old traces
        for item in self._trace_items:
            self._plot_widget.removeItem(item)
        self._trace_items.clear()

        if self._baseline_item is not None:
            self._plot_widget.removeItem(self._baseline_item)
            self._baseline_item = None

        state = self._state
        spectra = state.spectra
        if not spectra:
            self._coord_label.setText("No spectra loaded")
            return

        plot = state.plot
        graphics = state.graphics
        active_id = state.active_spectrum_id

        overlay_mode = len(spectra) > 1 and plot.show_all_spectra

        if overlay_mode:
            plotted = list(reversed(spectra)) if plot.reverse_overlay_order else list(spectra)
        else:
            active = state.active_spectrum
            plotted = [active] if active else [spectra[0]]

        n_traces = len(plotted)
        palette_colors = get_palette_colors(graphics.palette, n_traces)

        for i, spec in enumerate(plotted):
            if spec is None:
                continue

            # Resolve final Y through the processing chain
            y_data = state.displayed_y(spec.id)
            if y_data is None:
                y_data = spec.y

            x_arr = np.array(spec.x, dtype=np.float64)
            y_arr = np.array(y_data, dtype=np.float64)

            # Stack offset for overlay
            if overlay_mode:
                y_arr = y_arr + i * plot.stack_offset

            # Determine pen
            color_hex = get_color_for_index(palette_colors, i)
            is_active = spec.id == active_id
            base_w = max(1.0, graphics.trace_line_width / 2.0)

            if is_active:
                pen = pg.mkPen(color=color_hex, width=base_w + 1.0)
            else:
                # Slightly transparent for non-active traces
                color = QColor(color_hex)
                if overlay_mode:
                    color.setAlpha(140)
                pen = pg.mkPen(color=color, width=base_w)

            curve = self._plot_widget.plot(
                x_arr, y_arr,
                pen=pen,
                name=spec.name,
            )
            self._trace_items.append(curve)

        # Baseline overlay (single mode only)
        if not overlay_mode and plotted:
            spec = plotted[0]
            if spec and state.baseline.show_overlay and spec.id in state.baseline_y:
                bl_y = np.array(state.baseline_y[spec.id], dtype=np.float64)
                bl_x = np.array(spec.x[:len(bl_y)], dtype=np.float64)
                bl_pen = pg.mkPen(color="#94a3b8", width=1.5, style=Qt.PenStyle.DashLine)
                self._baseline_item = self._plot_widget.plot(
                    bl_x, bl_y, pen=bl_pen, name="baseline"
                )

        # ── Peak markers & labels ──────────────────────────
        # Clean up old peak items
        if self._peak_scatter is not None:
            self._plot_widget.removeItem(self._peak_scatter)
            self._peak_scatter = None
        for lbl in self._peak_labels:
            self._plot_widget.removeItem(lbl)
        self._peak_labels.clear()

        ps = state.peaks_settings
        if ps.enabled:
            peak_x_all = []
            peak_y_all = []
            label_items = []

            # Determine which spectra to show peaks for
            if ps.mode == "active":
                peak_specs = [state.active_spectrum] if state.active_spectrum else []
            else:
                peak_specs = list(plotted)

            for spec in peak_specs:
                if spec is None:
                    continue
                auto_peaks = state.peaks_auto.get(spec.id, [])
                manual_peaks = state.peaks_manual.get(spec.id, [])
                all_peaks = auto_peaks + manual_peaks

                y_disp = state.displayed_y(spec.id)
                if y_disp is None:
                    y_disp = spec.y

                for peak in all_peaks:
                    px = peak.x
                    # Find nearest Y value in displayed data
                    if spec.x and y_disp:
                        xa_arr = np.array(spec.x)
                        idx = int(np.argmin(np.abs(xa_arr - px)))
                        py = y_disp[idx] if idx < len(y_disp) else 0.0
                    else:
                        py = 0.0

                    # Apply stack offset if in overlay mode
                    if overlay_mode:
                        spec_idx = next((j for j, s in enumerate(plotted) if s and s.id == spec.id), 0)
                        py += spec_idx * plot.stack_offset

                    if ps.show_markers:
                        peak_x_all.append(px)
                        peak_y_all.append(py)

                    if ps.show_labels:
                        decimals = ps.decimals
                        label_text = f"{px:.{decimals}f}"
                        txt = pg.TextItem(
                            text=label_text,
                            color="#ef4444",
                            anchor=(0.5, 1.0),
                            angle=0,
                        )
                        txt.setFont(pg.QtGui.QFont("Arial", 8))
                        txt.setPos(px, py)
                        self._plot_widget.addItem(txt)
                        label_items.append(txt)

            if peak_x_all:
                scatter = pg.ScatterPlotItem(
                    x=peak_x_all, y=peak_y_all,
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush("#ef4444"),
                    size=7,
                    symbol="o",
                )
                self._plot_widget.addItem(scatter)
                self._peak_scatter = scatter

            self._peak_labels = label_items

        # Apply settings
        self._apply_plot_settings()
        self._apply_graphics_settings()

        # Update status
        total_pts = sum(len(s.x) for s in plotted if s)
        self._coord_label.setText(
            f"Traces: {n_traces} | Points: {total_pts:,}"
        )

    # ── Settings application ───────────────────────────────

    def _apply_plot_settings(self) -> None:
        plot = self._state.plot
        pi = self._plot_item

        # Grid
        pi.showGrid(x=plot.show_grid, y=plot.show_grid, alpha=0.3)

        # X-axis inversion
        pi.getViewBox().invertX(plot.invert_x)

        # Manual axis limits
        if plot.x_min is not None and plot.x_max is not None:
            self._plot_widget.setXRange(plot.x_min, plot.x_max, padding=0)
        if plot.y_min is not None and plot.y_max is not None:
            self._plot_widget.setYRange(plot.y_min, plot.y_max, padding=0)

    def _apply_graphics_settings(self) -> None:
        g = self._state.graphics
        pi = self._plot_item

        # Axis labels
        label_style = {"font-size": f"{max(10, g.base_font_size // 3)}pt"}
        if g.axis_label_bold:
            label_style["font-weight"] = "bold"
        if g.axis_label_italic:
            label_style["font-style"] = "italic"

        pi.setLabel("bottom", g.x_label, **label_style)
        pi.setLabel("left", g.y_label, **label_style)

        # Tick font
        tick_font = QFont(g.font_family, max(8, g.tick_font_size // 3))
        tick_font.setBold(g.tick_label_bold)
        tick_font.setItalic(g.tick_label_italic)
        for axis_name in ("bottom", "left"):
            axis = pi.getAxis(axis_name)
            axis.setTickFont(tick_font)
            axis.setStyle(showValues=True)

        # Axis line width & color
        for axis_name in ("bottom", "left", "top", "right"):
            axis = pi.getAxis(axis_name)
            pen = pg.mkPen(color=g.axis_line_color, width=max(1, g.axis_line_width // 2))
            axis.setPen(pen)

        # Show/hide tick labels
        pi.getAxis("bottom").setStyle(
            showValues=g.show_x_tick_labels
        )
        pi.getAxis("left").setStyle(
            showValues=g.show_y_tick_labels
        )

        # Frame mode (box = show top+right axes, open = hide them)
        pi.showAxis("top", show=(g.frame_mode == "box"))
        pi.showAxis("right", show=(g.frame_mode == "box"))
        if g.frame_mode == "box":
            for axis_name in ("top", "right"):
                axis = pi.getAxis(axis_name)
                axis.setStyle(showValues=False)
                pen = pg.mkPen(color=g.axis_line_color, width=max(1, g.axis_line_width // 2))
                axis.setPen(pen)

    # ── Crosshair / mouse ──────────────────────────────────

    def _on_mouse_moved(self, evt) -> None:
        pos = evt[0]
        if self._plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self._plot_item.getViewBox().mapSceneToView(pos)
            x_val = mouse_point.x()
            y_val = mouse_point.y()
            self._vline.setPos(x_val)
            self._hline.setPos(y_val)
            self._vline.setVisible(True)
            self._hline.setVisible(True)
            self._coord_label.setText(f"x = {x_val:.2f}   y = {y_val:.2f}")
        else:
            self._vline.setVisible(False)
            self._hline.setVisible(False)

    def _on_mouse_clicked(self, evt) -> None:
        """
        Handle mouse clicks on the plot:
          - Left click:        select the nearest spectrum as active
          - Ctrl + Left click: add manual peak label (if manual pick enabled)
          - Shift + Left click: remove nearest peak label (if manual pick enabled)
        """
        if evt.button() != Qt.MouseButton.LeftButton:
            return
        pos = evt.scenePos()
        if not self._plot_widget.sceneBoundingRect().contains(pos):
            return

        mouse_point = self._plot_item.getViewBox().mapSceneToView(pos)
        x_val = mouse_point.x()
        y_val = mouse_point.y()

        self.plot_clicked.emit(x_val, y_val)

        modifiers = evt.modifiers()

        # ── Ctrl+click: add manual peak ──
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if (
                self._peaks_panel is not None
                and self._state.peaks_settings.manual_pick_enabled
            ):
                self._peaks_panel.add_manual_peak(x_val)
            return

        # ── Shift+click: remove nearest peak ──
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if (
                self._peaks_panel is not None
                and self._state.peaks_settings.manual_pick_enabled
            ):
                self._peaks_panel.remove_nearest_peak(x_val)
            return

        # ── Plain click: select nearest spectrum ──
        self._select_nearest_spectrum(x_val, y_val)

    def _select_nearest_spectrum(self, x_click: float, y_click: float) -> None:
        """
        Find the spectrum trace nearest to the click point and make it active.

        For each plotted spectrum, find the Y value at x_click, compute the
        vertical distance to y_click (accounting for stack offset), and pick
        the closest one.
        """
        state = self._state
        spectra = state.spectra
        if not spectra:
            return

        plot = state.plot
        overlay_mode = len(spectra) > 1 and plot.show_all_spectra

        if not overlay_mode:
            # In single-spectrum mode, clicking doesn't change selection
            return

        # Determine plotted spectra (same order as in _redraw)
        if plot.reverse_overlay_order:
            plotted = list(reversed(spectra))
        else:
            plotted = list(spectra)

        best_dist = float("inf")
        best_id = None

        for i, spec in enumerate(plotted):
            if spec is None:
                continue

            y_disp = state.displayed_y(spec.id)
            if y_disp is None:
                y_disp = spec.y
            if not spec.x or not y_disp:
                continue

            # Find nearest X index
            x_arr = np.array(spec.x, dtype=np.float64)
            idx = int(np.argmin(np.abs(x_arr - x_click)))
            if idx >= len(y_disp):
                continue

            y_at_click = float(y_disp[idx])
            # Apply stack offset
            y_at_click += i * plot.stack_offset

            dist = abs(y_at_click - y_click)
            if dist < best_dist:
                best_dist = dist
                best_id = spec.id

        if best_id is not None and best_id != state.active_spectrum_id:
            state.set_active_spectrum(best_id)
