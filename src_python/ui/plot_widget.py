"""Interactive spectrum canvas with accurate styles, originals and local previews."""

from __future__ import annotations

from core.view import view_y, trace_style
import html
import math
import re
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from app.models import AXIS_Y_LABELS
from app.state import LABEL_OFFSETS
from core.label_layout import LabelRequest, LayoutStyle, layout_with_thinning
from core.palettes import get_color_for_index, get_palette_colors
from core.sampling import with_gap_breaks

# Automatic Y labels (current and earlier versions) may follow the active ordinate.
_AUTOMATIC_Y_LABELS = set(AXIS_Y_LABELS.values()) | {
    "Y",
    "Intenzita (a.u.)",
    "Transmitance (%)",
    "Transmitance (0–1)",
}


def axis_html(text):
    """Escape plain labels before rendering the documented ^/_ math shorthand."""
    value = html.escape(text)
    return re.sub(
        r"([\^_])(?:\{([^}]+)\}|([A-Za-z0-9−+\-]+))",
        lambda match: (
            f"<{'sup' if match[1] == '^' else 'sub'}>{match[2] or match[3]}</{'sup' if match[1] == '^' else 'sub'}>"
        ),
        value,
    )


LABEL_GAP_PX = 6  # free space between the curve and a label
LEADER_KINK_PX = 12  # vertical part of an elbow leader line


def label_anchor(angle: float, upward: bool) -> tuple[float, float]:
    """Anchor so a label starts at the curve and grows away from it.

    TextItem angles are counter-clockwise; anchor (0, 0.5) is the start of
    the text, (1, 0.5) its end, (0.5, 1) the bottom centre.
    """
    sine = math.sin(math.radians(angle))
    if abs(sine) > 0.5:
        return (0.0, 0.5) if (sine > 0) == upward else (1.0, 0.5)
    return (0.5, 1.0) if upward else (0.5, 0.0)


class _PeakLabel(pg.TextItem):
    def __init__(
        self, text, color, position, callback, delete_callback, leader=None, **kwargs
    ):
        super().__init__(text=text, color=color, **kwargs)
        self.callback = callback
        self.delete_callback = delete_callback
        self.leader = leader
        self.origin = position
        self._start = None
        self.setPos(*position)
        self.setZValue(20)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(
            "Tažením posuň popisek · Shift + klik nebo pravý klik jej odebere"
        )

    def mouseDragEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        event.accept()
        if event.isStart():
            self._start = self.pos()
        delta = self.mapToParent(event.pos()) - self.mapToParent(event.buttonDownPos())
        self.setPos(self._start + delta)
        if self.leader is not None:
            self.leader.setData(
                [self.origin[0], self.pos().x()], [self.origin[1], self.pos().y()]
            )
        if event.isFinish():
            self.callback(self.pos().x() - self.origin[0], self.pos().y() - self.origin[1])

    def mouseClickEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.delete_callback()
        elif event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.delete_callback()
        else:
            event.ignore()


class SpectrumPlotWidget(QWidget):
    plot_clicked = Signal(float, float)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state
        self._peaks_panel = None
        self._items = []
        self._trace_items = []
        self._show_original = False
        self._label_positions = {}
        self._labels = []
        self._hidden_labels = 0
        self._plotted = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        pg.setConfigOptions(antialias=True)
        self._plot_widget = pg.PlotWidget(background="white")
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.hideButtons()
        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_item.getViewBox().setDefaultPadding(0.08)
        self._plot_item.addLegend(
            offset=(15, 10),
            labelTextSize="11pt",
            labelTextColor="#1f2a30",
            brush=pg.mkBrush(255, 255, 255, 210),
            pen=pg.mkPen(None),
        )
        layout.addWidget(self._plot_widget, 1)
        view = self._plot_item.getViewBox()
        view.sigRangeChanged.connect(self._layout_labels)
        view.sigResized.connect(self._layout_labels)
        self._coord_label = QLabel("Importuj spektra nebo načti demonstrační data.")
        self._coord_label.setObjectName("muted")
        layout.addWidget(self._coord_label)
        self._vline = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#c4d5d3", style=Qt.PenStyle.DashLine)
        )
        self._hline = pg.InfiniteLine(
            angle=0, movable=False, pen=pg.mkPen("#c4d5d3", style=Qt.PenStyle.DashLine)
        )
        for line in (self._vline, self._hline):
            self._plot_widget.addItem(line, ignoreBounds=True)
            line.hide()
        self._proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved, rateLimit=40, slot=self._mouse_move
        )
        self._plot_widget.scene().sigMouseClicked.connect(self._mouse_click)
        for signal in [
            state.spectra_changed,
            state.active_spectrum_changed,
            state.plot_changed,
            state.graphics_changed,
            state.baseline_changed,
            state.smoothing_changed,
            state.cosmic_changed,
            state.peaks_changed,
            state.spectral_mode_changed,
            state.preview_changed,
        ]:
            signal.connect(self._redraw)
        self._redraw()

    def set_peaks_panel(self, panel):
        self._peaks_panel = panel

    def set_show_original(self, value):
        self._show_original = value
        self._redraw()

    def fit(self):
        self._plot_item.getViewBox().enableAutoRange()

    def fit_y_visible(self):
        low, high = self._plot_item.getViewBox().viewRange()[0]
        values = []
        for curve in self._trace_items:
            x, y = curve.getData()
            if x is None or y is None:
                continue
            selected = (x >= low) & (x <= high) & np.isfinite(y)
            if np.any(selected):
                values.extend(y[selected].tolist())
        if values:
            pad = max(
                float(np.ptp(values)) * 0.08,
                max(abs(min(values)), abs(max(values)), 1) * 1e-6,
            )
            self._state.set_plot(y_min=min(values) - pad, y_max=max(values) + pad)

    def auto_stack_offset(self) -> float:
        """Smallest common offset that keeps neighbouring overlay curves apart."""
        state = self._state
        order = (
            list(reversed(state.spectra))
            if state.plot.reverse_overlay_order
            else list(state.spectra)
        )
        order = [s for s in order if s.meta.get("trace_style",{}).get("visible",True)]
        curves = [
            view_y(state.displayed_y(spec.id), state.plot.scale_mode) for spec in order
        ]
        if len(curves) < 2:
            return 0.0
        gap = max(
            float(np.max(lower) - np.min(upper))
            for lower, upper in zip(curves, curves[1:])
        )
        span = max(float(np.ptp(curve)) for curve in curves)
        return max(gap, 0.0) + 0.05 * span

    def reset_label_positions(self):
        if self._state.spectra:
            self._state.reset_peak_label_positions()

    def _add(self, item, ignore_bounds=False):
        self._plot_widget.addItem(item, ignoreBounds=ignore_bounds)
        self._items.append(item)
        return item

    def _curve(self, x, y, color, width=2, style=Qt.PenStyle.SolidLine, name=None):
        # Gaps in the sampling (e.g. regions blanked in OMNIC) are not bridged.
        x, y = with_gap_breaks(x, y)
        curve = self._plot_widget.plot(
            x, y, pen=pg.mkPen(color=color, width=width, style=style), name=name,
            connect="finite",
        )
        curve.setDownsampling(auto=True, method="peak")
        curve.setClipToView(True)
        self._items.append(curve)
        return curve

    def _redraw(self):
        for item in self._items:
            self._plot_widget.removeItem(item)
        self._items.clear()
        self._trace_items.clear()
        self._labels = []
        if self._plot_item.legend:
            self._plot_item.legend.clear()
        state = self._state
        graphics = state.graphics
        plot = state.plot
        self._style()
        if self._plot_item.legend:
            self._plot_item.legend.setVisible(not graphics.inline_spectrum_labels)
        if not state.spectra:
            self._plotted = []
            self._coord_label.setText("Importuj spektra nebo načti demonstrační data.")
            return
        self._plotted = (
            list(reversed(state.spectra))
            if plot.reverse_overlay_order
            else list(state.spectra)
        )
        if plot.show_all_spectra:
            self._plotted = [s for s in self._plotted if s.meta.get("trace_style",{}).get("visible",True)]
        if not plot.show_all_spectra:
            self._plotted = [state.active_spectrum or state.spectra[0]]
        colors = get_palette_colors(graphics.palette, len(state.spectra))
        preview = state.preview
        all_kind = {s.meta.get("y_kind", "intensity") for s in self._plotted}
        all_units = {s.meta.get("x_unit", s.meta.get("x_units")) for s in self._plotted}
        for index, spec in enumerate(self._plotted):
            color_index = next(
                i for i, s in enumerate(state.spectra) if s.id == spec.id
            )
            color = get_color_for_index(colors, color_index)
            x = np.asarray(spec.x)
            y = view_y(state.displayed_y(spec.id), plot.scale_mode)
            offset = index * plot.stack_offset if plot.show_all_spectra else 0
            color, trace_width, line_style = trace_style(
                spec, color, graphics.trace_line_width
            )
            width = max(0.1, trace_width / 2)
            pen_style = {
                "solid": Qt.PenStyle.SolidLine,
                "dash": Qt.PenStyle.DashLine,
                "dot": Qt.PenStyle.DotLine,
                "dashdot": Qt.PenStyle.DashDotLine,
            }[line_style]
            if self._show_original:
                raw = state.original_data(spec.id)
                if raw:
                    self._curve(
                        raw[0],
                        view_y(raw[1], plot.scale_mode) + offset,
                        "#a2b7b5",
                        1.2,
                        Qt.PenStyle.DashLine,
                        "Původní data" if spec.id == state.active_spectrum_id else None,
                    )
            trace = self._curve(
                x,
                y + offset,
                color,
                width + (0.4 if spec.id == state.active_spectrum_id else 0),
                name=spec.name,
                style=pen_style,
            )
            self._trace_items.append(trace)
            if graphics.inline_spectrum_labels:
                inline = pg.TextItem(spec.name, color=color, anchor=(1, 1))
                name_font = QFont(
                    graphics.font_family, max(7, round(graphics.tick_font_size / 2.5))
                )
                name_font.setBold(graphics.spectrum_label_bold)
                name_font.setItalic(graphics.spectrum_label_italic)
                inline.setFont(name_font)
                inline.setPos(float(x[-1]), float(y[-1] + offset))
                self._add(inline)
            if (
                spec.id == state.active_spectrum_id
                and state.baseline.show_overlay
                and spec.id in state.baseline_y
            ):
                baseline = state.baseline_y[spec.id]
                if len(baseline) == len(x):
                    self._curve(
                        x,
                        view_y(baseline, plot.scale_mode) + offset,
                        "#9da9b4",
                        1,
                        Qt.PenStyle.DashLine,
                        "Odhad baseline",
                    )
            if preview and spec.id in preview.get("results", {}):
                result = preview["results"][spec.id]
                self._curve(
                    result["x"],
                    view_y(result["y"], plot.scale_mode) + offset,
                    "#14877b",
                    2.3,
                    Qt.PenStyle.DotLine,
                    "Náhled úpravy" if spec.id == state.active_spectrum_id else None,
                )
            if state.peaks_settings.enabled and (
                state.peaks_settings.mode == "all"
                or spec.id == state.active_spectrum_id
            ):
                self._draw_peaks(spec, x, y + offset, color)
        self._add_label_headroom()
        self._layout_labels()
        note = f"{len(self._plotted)} křivek · {sum(len(s.x) for s in self._plotted):,} bodů"
        if len(all_kind) > 1 or len(all_units) > 1:
            note += " · Porovnáváš různé jednotky / typy Y"
        if plot.scale_mode == "full":
            note += " · Full scale: každá křivka 0–1 (pouze zobrazení)"
        if preview:
            note += " · Tečkovaná křivka: dosud nepoužitý náhled"
        if self._show_original:
            spec = state.active_spectrum
            if spec and state.processing_recipe(spec.id):
                note += " · Původní data mají původní měřítko a jednotky"
        self._note = note
        self._show_note()
        self._coord_label.setText(self._note_text())

    def _draw_peaks(self, spec, x, y, color):
        settings = self._state.peaks_settings
        positions = []
        # Transmittance bands and minima point down; their labels go below.
        transmittance = str(spec.meta.get("y_kind", "")).startswith("transmittance")
        offsets = spec.meta.get(LABEL_OFFSETS, {})
        label_y_scale = (
            float(np.ptp(self._state.displayed_y(spec.id)))
            if self._state.plot.scale_mode == "full"
            else 1.0
        )
        label_y_scale = label_y_scale or 1.0
        anchor_up = label_anchor(settings.label_angle_deg, True)
        anchor_down = label_anchor(settings.label_angle_deg, False)
        font = QFont(
            self._state.graphics.font_family,
            max(7, round(settings.label_font_size / 2)),
        )
        font.setBold(settings.label_bold)
        font.setItalic(settings.label_italic)
        text_color = (
            color if settings.label_color_mode == "trace" else settings.label_color
        )
        leader_color = (
            color if settings.leader_color_mode == "trace" else settings.leader_color
        )
        ascending = x[-1] > x[0]
        median = float(np.median(y))
        for peak in self._state.peaks_auto.get(
            spec.id, []
        ) + self._state.peaks_manual.get(spec.id, []):
            if not min(x[0], x[-1]) <= peak.x <= max(x[0], x[-1]):
                continue
            px = float(peak.x)
            py = float(
                np.interp(px, x, y) if ascending else np.interp(px, x[::-1], y[::-1])
            )
            positions.append((px, py))
            if not settings.show_labels:
                continue
            upward = not (transmittance or peak.kind == "min")
            leader = None
            if settings.show_leader_lines:
                leader = pg.PlotDataItem(
                    pen=pg.mkPen(color=leader_color, width=settings.leader_line_width)
                )
                self._add(leader, ignore_bounds=True)
            item = _PeakLabel(
                peak.label or f"{px:.{settings.decimals}f}",
                text_color,
                (px, py),
                lambda dx, dy, sid=spec.id, pid=peak.id: (
                    self._state.set_peak_label_offset(sid, pid, dx, dy * label_y_scale)
                ),
                lambda sid=spec.id, pid=peak.id: self._state.remove_peak(sid, pid),
                leader=leader,
                anchor=anchor_up if upward else anchor_down,
                angle=settings.label_angle_deg,
            )
            item.setFont(font)
            self._add(item, ignore_bounds=True)
            self._labels.append(
                {
                    "item": item,
                    "leader": leader,
                    "px": px,
                    "py": py,
                    "upward": upward,
                    "offset": [offsets[peak.id][0], offsets[peak.id][1] / label_y_scale]
                    if peak.id in offsets
                    else None,
                    "x": x,
                    "y": y,
                    # Stronger bands win the space next to the curve.
                    "importance": peak.prominence
                    if peak.prominence is not None
                    else abs(py - median),
                }
            )
        if settings.show_markers and positions:
            self._add(
                pg.ScatterPlotItem(
                    x=[p[0] for p in positions],
                    y=[p[1] for p in positions],
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(color),
                    size=6,
                )
            )

    def _label_extent_px(self):
        """Largest distance (px) a label reaches away from the curve."""
        angle = math.radians(self._state.peaks_settings.label_angle_deg)
        extent = 0.0
        for label in self._labels:
            rect = label["item"].textItem.boundingRect()
            extent = max(extent, abs(math.sin(angle)) * rect.width() + abs(math.cos(angle)) * rect.height())
        return extent + LABEL_GAP_PX + LEADER_KINK_PX + 6

    def _add_label_headroom(self):
        """Invisible bounds so auto-range leaves room for labels above/below."""
        if not self._labels:
            return
        height = max(self._plot_item.getViewBox().height(), 200.0)
        fraction = min(0.6, self._label_extent_px() / height)
        traces = [c.getData() for c in self._trace_items]
        values = np.concatenate([d[1][np.isfinite(d[1])] for d in traces if d[1] is not None])
        xs = np.concatenate([d[0][np.isfinite(d[0])] for d in traces if d[0] is not None])
        if not len(values):
            return
        span = max(float(np.ptp(values)), 1e-12)
        room = fraction * span / (1 - fraction)
        points = []
        if any(label["upward"] for label in self._labels):
            points.append(float(np.max(values)) + room)
        if any(not label["upward"] for label in self._labels):
            points.append(float(np.min(values)) - room)
        middle = float(np.median(xs))
        # A transparent pen (not pen=None) keeps the points in the auto-range bounds.
        self._add(pg.PlotDataItem([middle] * len(points), points, pen=pg.mkPen((0, 0, 0, 0))))

    def _layout_labels(self, *_):
        """Place labels with core.label_layout: no overlaps, no crossing leaders."""
        if not self._labels:
            return
        view = self._plot_item.getViewBox()
        try:
            px_w, px_h = view.viewPixelSize()
        except Exception:  # view not laid out yet
            return
        if not (np.isfinite(px_w) and np.isfinite(px_h) and px_w > 0 and px_h > 0):
            return
        direction = -1.0 if self._state.plot.invert_x else 1.0
        (x0, x1), _ = view.viewRange()
        low, high = sorted((direction * x0 / px_w, direction * x1 / px_w))
        style = LayoutStyle(gap=3, stub=6, bend_min=6, bend_max=20, spacing=2, label_gap=2)
        angle = math.radians(self._state.peaks_settings.label_angle_deg)
        sine, cosine = abs(math.sin(angle)), abs(math.cos(angle))
        groups = {}
        for label in self._labels:
            if label["offset"] is not None:   # dragged by hand: keep it there
                lx = label["px"] + label["offset"][0]
                ly = label["py"] + label["offset"][1]
                label["item"].setPos(lx, ly)
                label["item"].setVisible(True)
                if label["leader"] is not None:
                    label["leader"].setData([label["px"], lx], [label["py"], ly])
                    label["leader"].setVisible(True)
                continue
            groups.setdefault((id(label["x"]), label["upward"]), []).append(label)
        hidden = 0
        for (_key, upward), labels in groups.items():
            sign = 1.0 if upward else -1.0
            x, y = labels[0]["x"], labels[0]["y"]
            cx = direction * x / px_w
            order = np.argsort(cx)
            cx, cy = cx[order], sign * y[order] / px_h
            requests = []
            for label in labels:
                rect = label["item"].textItem.boundingRect()
                requests.append(LabelRequest(
                    direction * label["px"] / px_w, sign * label["py"] / px_h,
                    cosine * rect.width() + sine * rect.height(),
                    sine * rect.width() + cosine * rect.height(), label["importance"]))
            kept = layout_with_thinning(requests, cx, cy, low, high, style)
            for index, label in enumerate(labels):
                placement = kept.get(index)
                label["item"].setVisible(placement is not None)
                if label["leader"] is not None:
                    label["leader"].setVisible(placement is not None)
                if placement is None:
                    hidden += 1
                    continue
                label["item"].setPos(direction * placement.x * px_w, sign * placement.base * px_h)
                if label["leader"] is not None:
                    points = np.asarray(placement.leader)
                    label["leader"].setData(direction * points[:, 0] * px_w, sign * points[:, 1] * px_h)
        self._hidden_labels = hidden
        self._show_note()

    def _note_text(self):
        note = getattr(self, "_note", "")
        if self._hidden_labels:
            note += f" · {self._hidden_labels} popisků píků skryto pro nedostatek místa (přibliž graf)"
        return note

    def _show_note(self):
        self._coord_label.setText(self._note_text())

    def _style(self):
        g = self._state.graphics
        p = self._state.plot
        pi = self._plot_item
        dark = g.plot_canvas == "dark"
        self._plot_widget.setBackground("#162629" if dark else "white")
        axis_color = (
            "#b5c7c7" if dark and g.axis_line_color == "#000000" else g.axis_line_color
        )
        font = QFont(g.font_family, max(8, round(g.tick_font_size / 2.5)))
        font.setBold(g.tick_label_bold)
        font.setItalic(g.tick_label_italic)
        text_color = "#b5c7c7" if dark else "#1f2a30"
        style = {
            "color": text_color,
            "font-size": f"{max(10, round(g.base_font_size / 2.5))}pt",
        }
        if g.axis_label_bold:
            style["font-weight"] = "bold"
        if g.axis_label_italic:
            style["font-style"] = "italic"
        if pi.legend is not None:
            pi.legend.setLabelTextSize(f"{font.pointSize()}pt")
        pi.setLabel("bottom", axis_html(g.x_label), **style)
        y_label = g.y_label
        active = self._state.active_spectrum
        if active and y_label in _AUTOMATIC_Y_LABELS:
            y_label = AXIS_Y_LABELS.get(active.meta.get("y_kind"), y_label)
            if active.meta.get("ordinate_processing", "").startswith("derivative"):
                y_label = f"Derivative ({active.meta.get('y_unit', 'a.u.')})"
            elif active.meta.get("ordinate_processing", "").startswith("normalize"):
                y_label = "Normalized intensity (a.u.)"
        if p.scale_mode == "full":
            y_label = "Relative intensity (full scale)"
        pi.setLabel("left", axis_html(y_label), **style)
        for name in ("bottom", "left", "top", "right"):
            axis = pi.getAxis(name)
            # No automatic "(x0.001)" multipliers in axis titles of figures.
            axis.enableAutoSIPrefix(False)
            axis.setTickFont(font)
            axis.setPen(pg.mkPen(axis_color, width=max(1, g.axis_line_width / 2)))
            axis.setTextPen(pg.mkPen(text_color))
        for name, marks, values in [
            ("bottom", g.show_x_tick_marks, g.show_x_tick_labels),
            ("left", g.show_y_tick_marks, g.show_y_tick_labels),
        ]:
            axis = pi.getAxis(name)
            axis.setStyle(showValues=values, tickLength=-5 if marks else 0)
            axis.setTickPen(
                pg.mkPen(g.grid_color, width=g.grid_width)
                if p.show_grid or g.show_grid
                else pg.mkPen(axis_color, width=1)
            )
        pi.showAxis("top", g.frame_mode == "box")
        pi.showAxis("right", g.frame_mode == "box")
        pi.getAxis("top").setStyle(showValues=False)
        pi.getAxis("right").setStyle(showValues=False)
        pi.showGrid(
            x=p.show_grid or g.show_grid, y=p.show_grid or g.show_grid, alpha=0.15
        )
        pi.getViewBox().invertX(p.invert_x)
        if p.x_min is not None and p.x_max is not None:
            self._plot_widget.setXRange(p.x_min, p.x_max, padding=0)
        if p.y_min is not None and p.y_max is not None:
            self._plot_widget.setYRange(p.y_min, p.y_max, padding=0)

    def _mouse_move(self, event):
        pos = event[0]
        view = self._plot_item.getViewBox()
        if view.sceneBoundingRect().contains(pos):
            point = view.mapSceneToView(pos)
            self._vline.setPos(point.x())
            self._hline.setPos(point.y())
            self._vline.show()
            self._hline.show()
            self._coord_label.setText(f"X = {point.x():.6g}    Y = {point.y():.6g}")
        else:
            self._vline.hide()
            self._hline.hide()

    def _mouse_click(self, event):
        if event.isAccepted() or event.button() != Qt.MouseButton.LeftButton:
            return
        view = self._plot_item.getViewBox()
        if not view.sceneBoundingRect().contains(event.scenePos()):
            return
        point = view.mapSceneToView(event.scenePos())
        self.plot_clicked.emit(point.x(), point.y())
        modifiers = event.modifiers()
        settings = self._state.peaks_settings
        if self._peaks_panel and settings.manual_pick_enabled:
            if modifiers & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
            ):
                self._peaks_panel.add_manual_peak(point.x())
                return
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                low, high = view.viewRange()[0]
                self._peaks_panel.remove_nearest_peak(point.x(), 0.015 * abs(high - low))
                return
        if self._state.plot.show_all_spectra:
            candidates = []
            for index, spec in enumerate(self._plotted):
                if (
                    min(spec.x[0], spec.x[-1])
                    <= point.x()
                    <= max(spec.x[0], spec.x[-1])
                ):
                    xs = np.asarray(spec.x)
                    ys = np.asarray(self._state.displayed_y(spec.id))
                    if xs[0] > xs[-1]:  # np.interp needs ascending X
                        xs, ys = xs[::-1], ys[::-1]
                    y = np.interp(point.x(), xs, ys) + index * self._state.plot.stack_offset
                    candidates.append((abs(y - point.y()), spec.id))
            if candidates:
                self._state.set_active_spectrum(min(candidates)[1])
