import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow


def test_studio_ai_preview_manual_continuation_and_peak_table(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.load_demo()
    app.processEvents()
    state = window._state
    original = list(state.active_spectrum.y)
    window.ai_panel._example()
    window.ai_panel._preview()
    assert state.preview and window.ai_panel.apply_button.isEnabled()
    assert state.active_spectrum.y == original
    window.ai_panel._apply()
    smoothed = list(state.active_spectrum.y)
    assert smoothed != original
    state.apply_operations([{"op": "normalize", "params": {"method": "max"}}])
    assert max(state.active_spectrum.y) == 1.0
    state.undo()
    assert state.active_spectrum.y == smoothed
    window.peaks_panel._on_detect()
    assert window.peaks_table.rowCount() > 0
    window._plot.set_show_original(True)
    app.processEvents()
    assert window.grab().save(str(tmp_path / "studio.png"))
    window._dirty = False
    window.close()


def test_selection_keeps_user_axis_settings_until_measurement_type_changes():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    first, second = state.spectra
    state.set_graphics(y_label="Counts (custom)")
    state.set_peaks(min_prominence=3.5)
    state.set_active_spectrum(first.id)
    state.set_active_spectrum(second.id)
    assert state.graphics.y_label == "Counts (custom)"
    assert state.peaks_settings.min_prominence == 3.5
    window._dirty = False
    state.set_active_spectrum(first.id)
    assert not window._dirty
    state.update_spectrum_metadata(first.id, technique="infrared", y_kind="transmittance_percent")
    assert state.graphics.y_label == "Transmittance (%)"
    assert state.plot.invert_x and window.invert.isChecked()
    assert state.peaks_settings.polarity == "min"
    # Browsing between measurement types re-derives display defaults only.
    window._dirty = False
    state.set_active_spectrum(second.id)
    assert state.graphics.y_label == "Intensity (a.u.)"
    assert not window._dirty
    window.close()


def test_shift_click_removes_only_a_nearby_peak():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    spec = state.active_spectrum
    peak = state.add_manual_peak(spec.id, 1000.0)
    assert not window.peaks_panel.remove_nearest_peak(1300.0, tolerance=20.0)
    assert [p.id for p in state.peaks_manual[spec.id]] == [peak.id]
    assert window.peaks_panel.remove_nearest_peak(1010.0, tolerance=20.0)
    assert state.peaks_manual[spec.id] == []
    window._dirty = False
    window.close()


def test_settings_only_preset_keeps_detected_peaks():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    assert state.detect_spectrum_peaks() > 0
    detected = [p.id for p in state.peaks_auto[state.active_spectrum_id]]
    state.apply_preset({"graphics": {"x_label": "Raman shift (cm^-1)"}})
    assert [p.id for p in state.peaks_auto[state.active_spectrum_id]] == detected
    window._dirty = False
    window.close()


def test_delete_shortcut_requires_selected_peak_row():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    spec = state.active_spectrum
    state.add_manual_peak(spec.id, 1000.0)
    window._delete_peak()
    assert len(state.peaks_manual[spec.id]) == 1
    window.peaks_table.selectRow(0)
    window._delete_peak()
    assert state.peaks_manual[spec.id] == []
    window._dirty = False
    window.close()


def test_history_is_shown_in_czech_and_imports_are_undoable():
    from app.main_window import history_text

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    assert window.undo_button.isEnabled()
    state.apply_operations([{"op": "smooth", "params": {}}])
    assert window.history_list.item(0).text() == "Vyhlazení · ručně"
    assert history_text({"label": "AI návrh", "source": "ai", "action": "undo"}) == "↶ Zpět: AI návrh · AI"
    state.undo()
    state.undo()
    assert state.spectra == []
    assert window.history_list.item(0).text() == "↶ Zpět: Import spekter · ručně"
    window._dirty = False
    window.close()


def test_text_tables_are_named_by_file_and_column():
    from app.main_window import spectrum_display_name

    single = {"name": "Intensity", "column_index": 1}
    assert spectrum_display_name("/data/sample_A.csv", single, 0, 1) == "sample_A"
    assert spectrum_display_name("/data/series.csv", {"name": "500 mV", "column_index": 2}, 1, 3) == "series · 500 mV"
    assert spectrum_display_name("/data/map.wdf", {"name": "Map [3]"}, 2, 88) == "Map [3]"
    assert spectrum_display_name("/data/multi.spc", {"name": "Run"}, 1, 4) == "Run · 2"
    assert spectrum_display_name("/data/one.spa", {"name": "Polystyrene"}, 0, 1) == "Polystyrene"


def test_auto_offset_separates_overlay_curves():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_demo()
    app.processEvents()
    state = window._state
    window._auto_offset()
    first, second = (np.asarray(state.displayed_y(s.id)) for s in state.spectra)
    offset = state.plot.stack_offset
    assert state.plot.show_all_spectra and offset > 0
    assert np.min(second) + offset > np.max(first)
    window._dirty = False
    window.close()


def test_ai_presentation_plan_styles_figure_and_detects_peaks():
    import json

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1500, 940)
    window.show()
    window.load_demo()
    app.processEvents()
    state = window._state
    ai = window.ai_panel
    plan = {
        "explanation": "Vyhlazení a popisky píků.",
        "warnings": [],
        "operations": [{"op": "smooth", "params": {"window": 9, "poly_order": 3}},
                       {"op": "normalize", "params": {"method": "max"}}],
        "presentation": {
            "graphics": {"x_label": "Raman shift (cm^{-1})", "font_family": "Times New Roman"},
            # Relative prominence survives the normalisation above.
            "peaks": {"relative_prominence": 0.2, "max_peaks": 6, "label_angle_deg": 90},
            "detect_peaks": True,
        },
    }
    ai._proposal_source, ai._proposal_ids = "ai", [state.active_spectrum_id]
    ai._proposal_revision = state.revision
    ai.editor.setPlainText(json.dumps(plan))
    ai._preview()
    assert ai.apply_button.isEnabled()
    ai._apply()
    assert state.graphics.font_family == "Times New Roman"
    assert state.graphics.x_label == "Raman shift (cm^{-1})"
    span = float(np.ptp(state.displayed_y(state.active_spectrum_id)))
    assert abs(state.peaks_settings.min_prominence - 0.2 * span) < 1e-9
    assert 1 <= len(state.peaks_auto[state.active_spectrum_id]) <= 6
    app.processEvents()
    assert window._plot._labels and all(label["item"].isVisible() for label in window._plot._labels)
    # Styling-only plans skip the data preview.
    plan = {"explanation": "Jen vzhled.", "warnings": [], "operations": [],
            "presentation": {"graphics": {"frame_mode": "box"}}}
    ai.editor.setPlainText(json.dumps(plan))
    ai._preview()
    ai._apply()
    assert state.graphics.frame_mode == "box"
    window._dirty = False
    window.close()
