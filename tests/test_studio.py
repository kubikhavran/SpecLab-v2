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
