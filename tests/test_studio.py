import os

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
