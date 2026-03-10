"""
Central application state for SpecLab (signal-based, replaces React reducer).

All UI components connect to signals emitted here.
Mutations go through public methods — never modify attributes directly from outside.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .models import (
    BaselineSettings,
    CosmicSettings,
    ExportSettings,
    GraphicsSettings,
    Peak,
    PeaksSettings,
    PlotSettings,
    SmoothingSettings,
    Spectrum,
)


class AppState(QObject):
    """Singleton-style application state container."""

    # ── Signals ─────────────────────────────────────────────
    spectra_changed = Signal()           # list of spectra was modified
    active_spectrum_changed = Signal()   # active spectrum id changed
    plot_changed = Signal()              # PlotSettings changed
    baseline_changed = Signal()          # BaselineSettings changed
    smoothing_changed = Signal()         # SmoothingSettings changed
    cosmic_changed = Signal()            # CosmicSettings changed
    peaks_changed = Signal()             # PeaksSettings or peak data changed
    graphics_changed = Signal()          # GraphicsSettings changed
    export_changed = Signal()            # ExportSettings changed

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        # ── Core data ──────────────────────────────────────
        self._spectra: List[Spectrum] = []
        self._active_spectrum_id: Optional[str] = None

        # ── Settings (value objects) ───────────────────────
        self._plot = PlotSettings()
        self._baseline = BaselineSettings()
        self._smoothing = SmoothingSettings()
        self._cosmic = CosmicSettings()
        self._peaks = PeaksSettings()
        self._graphics = GraphicsSettings()
        self._export = ExportSettings()
        # ── Per-dialog last folder memory ─────────────────
        self._last_folders: dict[str, str] = {}

        # ── Per-spectrum derived data (keyed by spectrum id) ─
        self.cosmic_clean_y: Dict[str, List[float]] = {}
        self.processed_y: Dict[str, List[float]] = {}
        self.baseline_y: Dict[str, List[float]] = {}
        self.smoothed_y: Dict[str, List[float]] = {}
        self.peaks_auto: Dict[str, List[Peak]] = {}
        self.peaks_manual: Dict[str, List[Peak]] = {}

    # ── Read-only properties ───────────────────────────────

    @property
    def spectra(self) -> List[Spectrum]:
        return self._spectra

    @property
    def active_spectrum_id(self) -> Optional[str]:
        return self._active_spectrum_id

    @property
    def active_spectrum(self) -> Optional[Spectrum]:
        if self._active_spectrum_id is None:
            return None
        for s in self._spectra:
            if s.id == self._active_spectrum_id:
                return s
        return None

    @property
    def plot(self) -> PlotSettings:
        return self._plot

    @property
    def baseline(self) -> BaselineSettings:
        return self._baseline

    @property
    def smoothing(self) -> SmoothingSettings:
        return self._smoothing

    @property
    def cosmic(self) -> CosmicSettings:
        return self._cosmic

    @property
    def peaks_settings(self) -> PeaksSettings:
        return self._peaks

    @property
    def graphics(self) -> GraphicsSettings:
        return self._graphics

    @property
    def export_settings(self) -> ExportSettings:
        return self._export

    def last_folder(self, context: str = "default") -> str:
        """Get last used folder for a specific dialog context."""
        return self._last_folders.get(context, "")

    def set_last_folder(self, path: str, context: str = "default") -> None:
        """Remember the directory for a specific dialog context."""
        folder = os.path.dirname(path) if os.path.isfile(path) else path
        if os.path.isdir(folder):
            self._last_folders[context] = folder

    # ── Spectrum mutations ─────────────────────────────────

    def add_spectrum(
        self,
        spectrum: Spectrum,
        imported_peaks: Optional[List[Peak]] = None,
    ) -> None:
        self._spectra.append(spectrum)
        if imported_peaks:
            self.peaks_manual[spectrum.id] = list(imported_peaks)
            # Imported labels should be visible immediately.
            self._peaks.enabled = True
        self._active_spectrum_id = spectrum.id
        self.spectra_changed.emit()
        self.active_spectrum_changed.emit()
        if imported_peaks:
            self.peaks_changed.emit()

    def remove_spectrum(self, spectrum_id: str) -> None:
        self._spectra = [s for s in self._spectra if s.id != spectrum_id]
        # Clean up per-spectrum data
        for store in (
            self.cosmic_clean_y, self.processed_y,
            self.baseline_y, self.smoothed_y,
            self.peaks_auto, self.peaks_manual,
        ):
            store.pop(spectrum_id, None)
        # Fix active selection
        if self._active_spectrum_id == spectrum_id:
            self._active_spectrum_id = (
                self._spectra[0].id if self._spectra else None
            )
            self.active_spectrum_changed.emit()
        self.spectra_changed.emit()

    def clear_spectra(self) -> None:
        self._spectra.clear()
        self._active_spectrum_id = None
        for store in (
            self.cosmic_clean_y, self.processed_y,
            self.baseline_y, self.smoothed_y,
            self.peaks_auto, self.peaks_manual,
        ):
            store.clear()
        self.spectra_changed.emit()
        self.active_spectrum_changed.emit()

    def set_active_spectrum(self, spectrum_id: str) -> None:
        if self._active_spectrum_id != spectrum_id:
            self._active_spectrum_id = spectrum_id
            self.active_spectrum_changed.emit()

    def rename_spectrum(self, spectrum_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            return
        for s in self._spectra:
            if s.id == spectrum_id:
                s.name = new_name
                self.spectra_changed.emit()
                return

    def move_spectrum(self, spectrum_id: str, direction: str) -> None:
        """Move spectrum up or down in the list. direction = 'up' | 'down'."""
        idx = next(
            (i for i, s in enumerate(self._spectra) if s.id == spectrum_id),
            None,
        )
        if idx is None:
            return
        target = idx - 1 if direction == "up" else idx + 1
        if 0 <= target < len(self._spectra):
            self._spectra[idx], self._spectra[target] = (
                self._spectra[target],
                self._spectra[idx],
            )
            self.spectra_changed.emit()

    # ── Settings mutations (we'll expand these as panels are built) ──

    def set_plot(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._plot, k):
                setattr(self._plot, k, v)
        self.plot_changed.emit()

    def set_graphics(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._graphics, k):
                setattr(self._graphics, k, v)
        self.graphics_changed.emit()

    def set_baseline(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._baseline, k):
                setattr(self._baseline, k, v)
        self.baseline_changed.emit()

    def set_smoothing(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._smoothing, k):
                setattr(self._smoothing, k, v)
        self.smoothing_changed.emit()

    def set_cosmic(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._cosmic, k):
                setattr(self._cosmic, k, v)
        self.cosmic_changed.emit()

    def set_peaks(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._peaks, k):
                setattr(self._peaks, k, v)
        self.peaks_changed.emit()

    def set_export(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._export, k):
                setattr(self._export, k, v)
        self.export_changed.emit()

    # ── Helpers for displayed Y data ───────────────────────

    def displayed_y(self, spectrum_id: str) -> Optional[List[float]]:
        """
        Return the 'final' Y array for a spectrum, following the processing chain:
        smoothed > processed (baseline-corrected) > cosmic-cleaned > raw y.
        """
        if spectrum_id in self.smoothed_y:
            return self.smoothed_y[spectrum_id]
        if spectrum_id in self.processed_y:
            return self.processed_y[spectrum_id]
        if spectrum_id in self.cosmic_clean_y:
            return self.cosmic_clean_y[spectrum_id]
        spec = next((s for s in self._spectra if s.id == spectrum_id), None)
        return spec.y if spec else None
