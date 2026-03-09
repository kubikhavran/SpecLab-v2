"""Main application window — sidebar + central plot area + drag & drop."""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QMimeData
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMainWindow, QSplitter

from app.models import Spectrum
from app.state import AppState
from core.spectrum_parser import extract_label_from_filename, parse_spectrum_text
from ui.plot_widget import SpectrumPlotWidget
from ui.sidebar import Sidebar


# File extensions we accept via drag & drop
_ACCEPTED_EXTENSIONS = {".txt", ".csv", ".tsv", ".dat", ".asc", ".xy", ".spc"}


class MainWindow(QMainWindow):
    """Top-level window: resizable sidebar on the left, plot area on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SpecLab")
        self.resize(1200, 750)

        # Enable drag & drop on the window
        self.setAcceptDrops(True)

        # ── Central state ────────────────
        self._state = AppState(parent=self)

        # ── Layout ───────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: sidebar
        sidebar = Sidebar(self._state, get_plot_widget=lambda: self._plot)
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(500)
        splitter.addWidget(sidebar)

        # Right: real plot widget
        self._plot = SpectrumPlotWidget(self._state)
        splitter.addWidget(self._plot)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 880])

        self.setCentralWidget(splitter)

        # Wire peaks panel to plot for manual picking
        if sidebar.peaks_panel is not None:
            self._plot.set_peaks_panel(sidebar.peaks_panel)

    # ── Drag & Drop ──────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept the drag if it contains file URLs."""
        mime: QMimeData = event.mimeData()
        if mime.hasUrls():
            # Check if at least one file has an accepted extension
            for url in mime.urls():
                if url.isLocalFile():
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
        """Parse and add spectrum files to the state (same logic as ImportPanel)."""
        if paths:
            self._state.set_last_folder(paths[0])
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue

            result = parse_spectrum_text(text)
            if result is None:
                continue

            xs, ys = result
            name = extract_label_from_filename(path)
            spectrum = Spectrum(
                name=name,
                x=xs,
                y=ys,
                meta={"sourcePath": path, "sourceName": name},
            )
            self._state.add_spectrum(spectrum)
