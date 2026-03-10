"""Main application window: sidebar + central plot area + drag and drop."""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QSplitter

from app.models import Peak, Spectrum
from app.state import AppState
from core.spectrum_parser import (
    SpectrumParseError,
    extract_label_from_filename,
    parse_spectrum_file,
)
from ui.plot_widget import SpectrumPlotWidget
from ui.sidebar import Sidebar


# File extensions accepted by drag/drop.
_ACCEPTED_EXTENSIONS = {".txt", ".csv", ".tsv", ".dat", ".asc", ".xy", ".spc", ".spa"}


class MainWindow(QMainWindow):
    """Top-level window: resizable sidebar on the left, plot area on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SpecLab")
        self.resize(1200, 750)
        self.setAcceptDrops(True)

        # Central app state
        self._state = AppState(parent=self)

        # Layout
        splitter = QSplitter(Qt.Orientation.Horizontal)

        sidebar = Sidebar(self._state, get_plot_widget=lambda: self._plot)
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(500)
        splitter.addWidget(sidebar)

        self._plot = SpectrumPlotWidget(self._state)
        splitter.addWidget(self._plot)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 880])
        self.setCentralWidget(splitter)

        # Wire peaks panel to plot for manual picking.
        if sidebar.peaks_panel is not None:
            self._plot.set_peaks_panel(sidebar.peaks_panel)

    # Drag and drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag if it contains at least one valid local file."""
        mime: QMimeData = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                ext = Path(url.toLocalFile()).suffix.lower()
                if ext in _ACCEPTED_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        """Keep accepting while dragging over the window."""
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Load all dropped spectrum files."""
        mime: QMimeData = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        paths = self._extract_valid_paths(mime)
        if not paths:
            event.ignore()
            return

        self._load_files(paths)
        event.acceptProposedAction()

    def _extract_valid_paths(self, mime: QMimeData) -> List[str]:
        """Filter dropped URLs to local files with accepted extensions."""
        paths: List[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            filepath = url.toLocalFile()
            ext = Path(filepath).suffix.lower()
            if ext in _ACCEPTED_EXTENSIONS:
                paths.append(filepath)
        return paths

    def _load_files(self, paths: List[str]) -> None:
        """Parse dropped files and add them to AppState."""
        if paths:
            self._state.set_last_folder(paths[0], "import")

        errors: list[str] = []
        for path in paths:
            try:
                parsed = parse_spectrum_file(path)
            except SpectrumParseError as exc:
                errors.append(f"{Path(path).name}: {exc}")
                continue

            if parsed is None:
                continue

            name = extract_label_from_filename(path)
            meta = {"sourcePath": path, "sourceName": name}
            meta.update(parsed.metadata)
            imported_peaks = [
                Peak(x=peak.x, source="manual", label=peak.label or None)
                for peak in parsed.imported_peaks
            ]

            spectrum = Spectrum(name=name, x=parsed.x, y=parsed.y, meta=meta)
            self._state.add_spectrum(spectrum, imported_peaks=imported_peaks)

        if errors:
            details = "\n".join(errors[:8])
            if len(errors) > 8:
                details += f"\n... and {len(errors) - 8} more"
            QMessageBox.warning(self, "Some files could not be imported", details)

