"""Workflow contracts: scope, isolation, publication fidelity and reusable series."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from app.state import AppState
from app.models import Spectrum
from core.figure import figure_spec, render
from core.presets import (
    capture_preset_payload,
    apply_preset_payload,
    normalize_preset_payload,
)
from core.project_io import save_project, load_project


@pytest.fixture
def state():
    application = QApplication.instance() or QApplication([])
    assert application is not None
    s = AppState()
    x = np.linspace(0, 100, 201)
    s.add_spectra(
        [
            (
                Spectrum(
                    name=f"Sample {i}",
                    x=x.tolist(),
                    y=(i + 1 + 10 * (i + 1) * np.exp(-(((x - 50) / 4) ** 2))).tolist(),
                    meta={"technique": "raman", "x_unit": "cm⁻¹"},
                ),
                None,
            )
            for i in range(3)
        ]
    )
    return s


def test_combined_plan_is_isolated_atomic_and_fully_undoable(state):
    a, b, c = state.spectra
    original = state._snapshot()
    count = len(state.history)
    state.preview_workflow(
        [{"op": "scale", "params": {"factor": 2}}],
        presentation={
            "graphics": {"axis_line_color": "#123456", "trace_line_width": 5},
            "detect_peaks": True,
            "peaks": {"min_prominence": 1},
        },
        collection={
            "rename": {a.id: "Reference"},
            "order": [c.id, b.id, a.id],
            "styles": {a.id: {"color": "#cc5500", "width": 2.5, "line": "dash"}},
        },
        spectrum_ids=[a.id],
    )
    assert state._snapshot() == original
    staged = state.preview_state()
    assert staged.spectra[-1].name == "Reference"
    assert staged.peaks_auto[a.id]
    state.apply_preview()
    assert len(state.history) == count + 1
    assert state.spectra[-1].name == "Reference"
    assert state.spectra[-1].y == [v * 2 for v in a.y]
    assert state.spectra[0].y == c.y
    state.undo()
    assert state._snapshot() == original
    state.redo()
    assert state.spectra[-1].meta["trace_style"]["line"] == "dash"


def test_failed_or_stale_combined_preview_cannot_change_workspace(state):
    sid = state.spectra[0].id
    before = state._snapshot()
    with pytest.raises(ValueError):
        state.preview_workflow(
            [{"op": "scale", "params": {"factor": 3}}],
            presentation={"graphics": {"grid_color": "garbage"}},
            spectrum_ids=[sid],
        )
    assert state._snapshot() == before
    state.preview_workflow(
        presentation={"graphics": {"palette": "pubBold"}}, spectrum_ids=[sid]
    )
    state.set_graphics(axis_line_width=7)
    with pytest.raises(ValueError):
        state.apply_preview()
    assert state.graphics.axis_line_width == 7
    assert state.graphics.palette == before["_graphics"].palette
    assert state.preview is None


def test_collection_scope_and_order_validation(state):
    a, b, c = state.spectra
    for edits in (
        {"order": [a.id, a.id, b.id]},
        {"rename": {b.id: "outside scope"}},
        {"styles": {a.id: {"width": float("nan")}}},
    ):
        with pytest.raises(ValueError):
            state.preview_workflow(collection=edits, spectrum_ids=[a.id])
    state.reorder_spectra([c.id, a.id, b.id])
    assert [s.id for s in state.spectra] == [c.id, a.id, b.id]
    state.undo()
    assert [s.id for s in state.spectra] == [a.id, b.id, c.id]


def test_view_modes_preserve_data_and_match_export(state):
    original = [s.y[:] for s in state.spectra]
    state.set_plot(show_all_spectra=True, scale_mode="full", stack_offset=0.4)
    full = figure_spec(state)
    for i, curve in enumerate(full.curves):
        assert min(curve.y) == 0 and max(curve.y) == 1
        assert curve.offset == i * 0.4
    assert [s.y for s in state.spectra] == original
    state.set_plot(scale_mode="common")
    for curve, data in zip(figure_spec(state).curves, original):
        np.testing.assert_array_equal(curve.y, data)


def test_series_preset_and_project_keep_distinct_recipes_and_styles(state, tmp_path):
    a, b, c = state.spectra
    for index, spec in enumerate(state.spectra):
        state.apply_operations(
            [{"op": "scale", "params": {"factor": index + 2}}], [spec.id]
        )
        state.preview_workflow(
            collection={
                "styles": {spec.id: {"color": "#123456", "width": index + 1.5}}
            },
            spectrum_ids=[spec.id],
        )
        state.apply_preview()
    payload = capture_preset_payload(state)
    checked, _ = normalize_preset_payload(json.loads(json.dumps(payload)))
    expected = [s.y[:] for s in state.spectra]
    state.reset_processing([s.id for s in state.spectra])
    history_count = len(state.history)
    apply_preset_payload(state, checked)
    assert len(state.history) == history_count + 1
    assert [s.y for s in state.spectra] == expected
    assert [s.meta["trace_style"]["width"] for s in state.spectra] == [1.5, 2.5, 3.5]
    path = tmp_path / "project.speclab"
    save_project(state, path)
    restored = AppState()
    load_project(restored, path)
    assert [s.meta["trace_style"] for s in restored.spectra] == [
        s.meta["trace_style"] for s in state.spectra
    ]


def test_publication_keeps_manual_labels_and_visual_settings(state):
    spec = state.active_spectrum
    p = state.add_manual_peak(spec.id, 50, "band")
    state.set_peak_label_offset(spec.id, p.id, 7, 10)
    state.set_peaks(
        enabled=True,
        label_angle_deg=30,
        label_bold=True,
        leader_color_mode="custom",
        leader_color="#aa1122",
        leader_line_width=3,
    )
    state.set_graphics(
        axis_line_color="#334455",
        axis_label_italic=True,
        show_grid=True,
        grid_color="#ddeeff",
        tick_label_bold=True,
        inline_spectrum_labels=False,
    )
    state.preview_workflow(
        collection={
            "styles": {spec.id: {"color": "#225588", "width": 2.5, "line": "dash"}}
        }
    )
    state.apply_preview()
    specification = figure_spec(state)
    assert specification.curves[0].label_offsets[0] == [7, 10]
    fig = render(specification, 1200, 800, 150)
    ax = fig.axes[0]
    text = next(t for t in ax.texts if t.get_text() == "band")
    anchor = np.interp(50, spec.x, spec.y)
    assert tuple(text.get_position()) == (57, anchor + 10)
    assert text.get_rotation() == 30
    assert ax.lines[0].get_linestyle() == "--"
    assert ax.lines[0].get_linewidth() == 1
    assert ax.spines["bottom"].get_edgecolor()[:3] == pytest.approx(
        (0.2, 0.2666666667, 0.3333333333)
    )
    assert ax.xaxis.label.get_fontstyle() == "italic"


def test_workflow_navigation_scope_numbers_and_ai_continuation(qtbot):
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.processEvents()
    w = MainWindow()
    qtbot.addWidget(w)
    w.load_demo()
    for i in range(11):
        w._go_step(i)
        assert w.workflow_pages.currentIndex() == i
    w.list.selectAll()
    w.scope.setCurrentIndex(1)
    assert w._target_ids() == [s.id for s in w._state.spectra]
    state = w._state
    state.set_graphics(axis_line_width=6)
    assert w._target_ids() == [s.id for s in state.spectra]
    baseline = w.data_steps[2]
    baseline.fields["lam"].setValue(1234567.0)
    baseline.fields["p"].setValue(0.002)
    baseline._apply()
    assert all(
        state.processing_recipe(s.id)[-1]["params"]["lam"] == 1234567
        for s in state.spectra
    )
    assert state.baseline.p == 0.002
    baseline._reset()
    assert all(not state.processing_recipe(s.id) for s in state.spectra)
    page = w.appearance_steps["lines"]
    page.trace_color.setText("#884422")
    page.trace_width.setValue(2.75)
    page._apply_trace()
    assert all(s.meta["trace_style"]["width"] == 2.75 for s in state.spectra)
    w.list.clearSelection()
    w.list.item(0).setSelected(True)
    w._show_selection(False)
    assert len(figure_spec(state).curves) == 1
    assert figure_spec(state).curves[0].name == state.spectra[0].name
    w._show_selection(True)
    w.list.selectAll()
    # The chat assistant receives the current workflow selection; names follow the privacy toggle.
    assert w.ai_panel._selected_ids() == [s.id for s in state.spectra]
    w.ai_panel.send_names.setChecked(False)
    assert w.ai_panel._session.toolbox.hide_names
    w.ai_panel.send_names.setChecked(True)
    assert not w.ai_panel._session.toolbox.hide_names
    w._dirty = False
    w.close()


def test_dragging_label_moves_leader_and_stores_physical_offset_in_full_scale(
    state, qtbot
):
    from PySide6.QtCore import Qt, QPointF
    from ui.plot_widget import SpectrumPlotWidget

    spec = state.active_spectrum
    peak = state.add_manual_peak(spec.id, 50, "test")
    state.set_peaks(enabled=True)
    state.set_plot(scale_mode="full")
    graph = SpectrumPlotWidget(state)
    qtbot.addWidget(graph)
    graph.resize(900, 600)
    graph.show()
    QApplication.processEvents()
    item = graph._labels[0]["item"]

    class Drag:
        def __init__(self, start, finish):
            self.start, self.finish = start, finish

        def button(self):
            return Qt.MouseButton.LeftButton

        def accept(self):
            pass

        def isStart(self):
            return self.start

        def isFinish(self):
            return self.finish

        def pos(self):
            return QPointF(12, -7)

        def buttonDownPos(self):
            return QPointF(0, 0)

    item.mouseDragEvent(Drag(True, False))
    lx, ly = item.leader.getData()
    assert lx[-1] == item.pos().x() and ly[-1] == item.pos().y()
    expected_dx = item.pos().x() - item.origin[0]
    expected_dy = item.pos().y() - item.origin[1]
    item.mouseDragEvent(Drag(False, True))
    saved = state.active_spectrum.meta["peak_label_offsets"][peak.id]
    assert saved == pytest.approx([expected_dx, expected_dy * np.ptp(spec.y)])
    collected = figure_spec(state).curves[0].label_offsets[0]
    assert collected == pytest.approx([expected_dx, expected_dy])
    state.set_plot(scale_mode="common")
    assert figure_spec(state).curves[0].label_offsets[0] == pytest.approx(saved)
    graph.close()


def test_marker_only_export_and_reset_preserve_individual_appearance(state):
    spec = state.active_spectrum
    state.add_manual_peak(spec.id, 50, "hidden text")
    state.set_peaks(enabled=True, show_labels=False, show_markers=True)
    state.preview_workflow(
        collection={"styles": {spec.id: {"color": "#aabbcc", "width": 2.75}}}
    )
    state.apply_preview()
    state.apply_operations([{"op": "smooth", "params": {"window": 5, "poly_order": 2}}])
    state.reset_operation("smooth")
    assert state.active_spectrum.meta["trace_style"]["width"] == 2.75
    state.reset_processing()
    assert state.active_spectrum.meta["trace_style"]["color"] == "#aabbcc"
    specification = figure_spec(state)
    assert specification.curves[0].peaks
    fig = render(specification, 1000, 600, 150)
    assert all(t.get_text() != "hidden text" for t in fig.axes[0].texts)
    assert any(line.get_marker() == "o" for line in fig.axes[0].lines)


def test_numeric_fields_are_visible_and_accept_scientific_entry(qtbot):
    from PySide6.QtCore import Qt
    from ui.controls import NumberField

    field = NumberField(0.000001, 1e12, 1e6, log=True)
    qtbot.addWidget(field)
    field.resize(300, 40)
    field.show()
    QApplication.processEvents()
    assert field.spin.geometry().right() <= field.width()
    assert field.spin.width() >= 96
    edit = field.spin.lineEdit()
    edit.selectAll()
    qtbot.keyClicks(edit, "2.5e8")
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert field.value() == 250000000
    field.slider.setValue(0)
    assert field.value() == pytest.approx(0.000001)
    field.slider.setValue(2000)
    assert field.value() == pytest.approx(1e12)


def test_series_step_applies_its_subset_preview_without_switching_algorithm(qtbot):
    from ui.workflow import DataStep

    application = QApplication.instance() or QApplication([])
    assert application is not None
    state = AppState()
    x = np.linspace(300, 1700, 1401)
    rng = np.random.default_rng(5)
    spectra = []
    for k in range(6):
        y = 100 + 800 * np.exp(-0.5 * ((x - 1000) / 8) ** 2) + rng.normal(0, 5, len(x))
        if k == 3:
            y[400:407] += [900, 2500, 1200, 3000, 1500, 600, 300]
            y[600] += 5000
        spectra.append((Spectrum(name=str(k), x=x.tolist(), y=y.tolist()), None))
    state.add_spectra(spectra)
    ids = [s.id for s in state.spectra]
    page = DataStep(state, ["despike", "interpolate"], lambda: ids)
    qtbot.addWidget(page)
    before = [s.y[:] for s in state.spectra]
    page._series()
    preview = state.preview
    assert preview["spectrum_ids"] == [ids[3]]
    expected = preview["results"][ids[3]]["y"]
    page._apply()
    assert state.spectra[3].y == expected
    assert all(s.y == before[i] for i, s in enumerate(state.spectra) if i != 3)
    assert all(op["op"] == "interpolate" for op in state.processing_recipe(ids[3]))


def test_dark_canvas_and_transparent_export_keep_requested_background(state, tmp_path):
    from matplotlib.colors import to_hex
    from core.figure import save

    state.set_graphics(plot_canvas="dark")
    fig = render(figure_spec(state), 1000, 600, 150)
    assert to_hex(fig.get_facecolor()) == "#162629"
    assert to_hex(fig.axes[0].xaxis.label.get_color()) == "#b5c7c7"
    save(fig, str(tmp_path / "dark.png"))
    transparent = render(figure_spec(state), 1000, 600, 150, transparent=True)
    assert transparent.patch.get_alpha() == 0
