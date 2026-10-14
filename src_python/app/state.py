"""
Central application state for SpecLab (signal-based, replaces React reducer).

All UI components connect to signals emitted here.
Mutations go through public methods — never modify attributes directly from outside.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import fields, is_dataclass

import numpy as np

from PySide6.QtCore import QObject, Signal

from .models import (
    BaselineSettings,
    CosmicSettings,
    ExportSettings,
    GraphicsSettings,
    Peak,
    PeaksSettings,
    PlotSettings,
    SPECTRAL_MODES,
    SpectralModeDefaults,
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
    spectral_mode_changed = Signal()     # Spectral mode changed
    history_changed = Signal()
    preview_changed = Signal()

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
        self._spectral_mode: str = "custom"
        # ── Per-dialog last folder memory ─────────────────
        self._last_folders: dict[str, str] = {}

        # ── Per-spectrum derived data (keyed by spectrum id) ─
        self.cosmic_clean_y: Dict[str, List[float]] = {}
        self.processed_y: Dict[str, List[float]] = {}
        self.baseline_y: Dict[str, List[float]] = {}
        self.smoothed_y: Dict[str, List[float]] = {}
        self.peaks_auto: Dict[str, List[Peak]] = {}
        self.peaks_manual: Dict[str, List[Peak]] = {}
        # Imported data stay independent of current editable data and undo copies.
        self._original: Dict[str, dict] = {}
        self._recipes: Dict[str, list] = {}
        self._history: list[dict] = []
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._revision = 0
        self._preview: Optional[dict] = None

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

    @property
    def spectral_mode(self) -> str:
        return self._spectral_mode

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def history(self) -> list[dict]:
        """Recent provenance; the undo stack is deliberately session-local."""
        return copy.deepcopy(self._history)

    @property
    def preview(self) -> Optional[dict]:
        return copy.deepcopy(self._preview)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def original_data(self, spectrum_id: str) -> Optional[tuple[list, list]]:
        raw = self._original.get(spectrum_id)
        return (list(raw['x']), list(raw['y'])) if raw is not None else None

    def original_metadata(self, spectrum_id: str) -> dict:
        return copy.deepcopy(self._original.get(spectrum_id, {}).get('meta', {}))

    def processing_recipe(self, spectrum_id: str) -> list[dict]:
        return copy.deepcopy(self._recipes.get(spectrum_id, []))

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
        if any(s.id == spectrum.id for s in self._spectra):
            raise ValueError('A spectrum with this id is already loaded.')
        self._validate_data(spectrum.x, spectrum.y)
        spectrum.x = list(spectrum.x)
        spectrum.y = list(spectrum.y)
        spectrum.meta = self._validated_metadata(spectrum.meta)
        self._original[spectrum.id] = copy.deepcopy({
            'x': spectrum.x, 'y': spectrum.y, 'meta': spectrum.meta,
        })
        self._recipes[spectrum.id] = []
        self._discard_session_undo()
        self._spectra.append(spectrum)
        self._invalidate()
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
        if not any(s.id == spectrum_id for s in self._spectra):
            return
        self._spectra = [s for s in self._spectra if s.id != spectrum_id]
        self._original.pop(spectrum_id, None)
        self._recipes.pop(spectrum_id, None)
        self._discard_session_undo()
        self._invalidate()
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
        self._original.clear()
        self._recipes.clear()
        self._discard_session_undo()
        self._invalidate()
        for store in (
            self.cosmic_clean_y, self.processed_y,
            self.baseline_y, self.smoothed_y,
            self.peaks_auto, self.peaks_manual,
        ):
            store.clear()
        self.spectra_changed.emit()
        self.active_spectrum_changed.emit()

    def set_active_spectrum(self, spectrum_id: str) -> None:
        if not any(s.id == spectrum_id for s in self._spectra):
            return
        if self._active_spectrum_id != spectrum_id:
            self._active_spectrum_id = spectrum_id
            self.active_spectrum_changed.emit()

    def rename_spectrum(self, spectrum_id: str, new_name: str) -> None:
        self.rename_spectra({spectrum_id: new_name})

    def rename_spectra(self, mapping: dict[str, str]) -> Optional[dict]:
        if not isinstance(mapping, dict):
            raise ValueError('Spectrum renaming requires an id-to-name mapping.')
        if not mapping:
            return None
        self._resolve_ids(list(mapping))
        if any(not isinstance(name, str) or not name.strip() or len(name) > 1000 for name in mapping.values()):
            raise ValueError('Spectrum names must contain between 1 and 1000 characters.')
        changed = {sid: name.strip() for sid, name in mapping.items()
                   if next(s.name for s in self._spectra if s.id == sid) != name.strip()}
        if not changed:
            return None
        before = self._snapshot()
        for spec in self._spectra:
            if spec.id in changed:
                spec.name = changed[spec.id]
        return self._record_transaction(before, 'Rename spectra', 'manual', [], list(changed))

    def move_spectrum(self, spectrum_id: str, direction: str) -> None:
        """Move spectrum up or down in the list. direction = 'up' | 'down'."""
        idx = next(
            (i for i, s in enumerate(self._spectra) if s.id == spectrum_id),
            None,
        )
        if idx is None:
            return
        if direction not in {'up', 'down'}:
            raise ValueError('Spectrum move direction must be up or down.')
        target = idx - 1 if direction == "up" else idx + 1
        if 0 <= target < len(self._spectra):
            before = self._snapshot()
            self._spectra[idx], self._spectra[target] = (
                self._spectra[target],
                self._spectra[idx],
            )
            self._record_transaction(before, 'Reorder spectra', 'manual', [], [spectrum_id])

    def update_spectrum_metadata(self, spectrum_id: str, **kwargs) -> None:
        spec = next((s for s in self._spectra if s.id == spectrum_id), None)
        if spec is None:
            raise ValueError('Spectrum is no longer loaded.')
        meta = self._validated_metadata({**spec.meta, **kwargs})
        if meta == spec.meta:
            return
        before = self._snapshot()
        spec.meta = meta
        # A modality selection describes the imported data until processing starts.
        # After processing, current ordinate semantics must not relabel the raw data.
        if not self._recipes.get(spectrum_id):
            raw_meta = copy.deepcopy(meta)
            raw_meta.pop('peak_label_positions', None)
            self._original[spectrum_id]['meta'] = raw_meta
        self._record_transaction(before, 'Change spectrum metadata', 'manual', [], [spectrum_id])

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

    def set_spectral_mode(self, mode: str, apply_defaults: bool = True) -> None:
        """
        Switch the active spectral mode.
        When apply_defaults is True (default), recommended settings for the
        technique are applied to plot, graphics, baseline, and peaks.
        """
        if mode not in SPECTRAL_MODES:
            return
        self._spectral_mode = mode
        if apply_defaults:
            self._apply_mode_defaults(mode)
        self.spectral_mode_changed.emit()

    def _apply_mode_defaults(self, mode: str) -> None:
        """Apply recommended defaults from a spectral mode definition."""
        defaults: Optional[SpectralModeDefaults] = SPECTRAL_MODES.get(mode)
        if defaults is None:
            return

        # Graphics: axis labels
        self._graphics.x_label = defaults.x_label
        self._graphics.y_label = defaults.y_label
        self.graphics_changed.emit()

        # Plot: X-axis inversion
        self._plot.invert_x = defaults.invert_x
        self.plot_changed.emit()

        # Baseline: recommended parameters
        self._baseline.lambda_ = defaults.baseline_lambda
        self._baseline.p = defaults.baseline_p
        self._baseline.iterations = defaults.baseline_iterations
        self.baseline_changed.emit()

        # Peaks: polarity, prominence, decimals
        self._peaks.polarity = defaults.peak_polarity
        self._peaks.min_prominence = defaults.peak_min_prominence
        self._peaks.decimals = defaults.peak_decimals
        self.peaks_changed.emit()

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

    # ── Sequential processing, preview, and session undo ────────────────────

    @staticmethod
    def _validate_data(x, y) -> None:
        xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        if xa.ndim != 1 or ya.ndim != 1 or len(xa) != len(ya) or len(xa) < 2:
            raise ValueError('Spectrum must contain equally sized X/Y arrays with at least two points.')
        if len(xa) > 1_000_000 or not np.all(np.isfinite(xa)) or not np.all(np.isfinite(ya)):
            raise ValueError('Spectrum data must be finite and contain at most 1,000,000 points.')
        dx = np.diff(xa)
        if not (np.all(dx > 0) or np.all(dx < 0)):
            raise ValueError('Spectrum X values must be strictly increasing or decreasing.')

    @staticmethod
    def _validated_metadata(meta: dict) -> dict:
        if not isinstance(meta, dict):
            raise ValueError('Spectrum metadata must be an object.')
        result = copy.deepcopy(meta)
        result.setdefault('technique', 'custom')
        result.setdefault('y_kind', 'intensity')
        result.setdefault('x_unit', 'unknown')
        if not isinstance(result['technique'], str) or result['technique'] not in {'raman', 'infrared', 'uv_vis', 'custom'}:
            raise ValueError('Unknown spectral technique.')
        if not isinstance(result['y_kind'], str) or result['y_kind'] not in {
            'intensity', 'absorbance', 'transmittance_percent', 'transmittance_fraction',
        }:
            raise ValueError('Unknown ordinate type.')
        if not isinstance(result['x_unit'], str) or len(result['x_unit']) > 100:
            raise ValueError('X unit must be a short string.')
        positions = result.get('peak_label_positions', {})
        if not isinstance(positions, dict) or len(positions) > 10000:
            raise ValueError('Peak label positions must be a bounded object.')
        for pid, coords in positions.items():
            if not isinstance(pid, str) or not isinstance(coords, list) or len(coords) != 2:
                raise ValueError('Peak label positions require an id and two coordinates.')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in coords):
                raise ValueError('Peak label coordinates must be finite.')
        return result

    def _discard_session_undo(self) -> None:
        # Membership changes make older whole-workspace snapshots obsolete.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.history_changed.emit()

    def _invalidate(self) -> None:
        self._revision += 1
        self.clear_preview()

    def clear_preview(self) -> None:
        if self._preview is not None:
            self._preview = None
            self.preview_changed.emit()

    def _resolve_ids(self, spectrum_ids=None) -> list[str]:
        ids = ([self._active_spectrum_id] if spectrum_ids is None else list(spectrum_ids))
        ids = list(dict.fromkeys(ids))
        loaded = {s.id for s in self._spectra}
        if not ids or any(sid not in loaded for sid in ids):
            raise ValueError('Select at least one loaded spectrum.')
        return ids

    def _data_signature(self, ids: list[str]) -> str:
        digest = hashlib.sha256()
        for spec in self._spectra:
            if spec.id not in ids:
                continue
            digest.update(spec.id.encode())
            digest.update(np.asarray(spec.x, dtype='<f8').tobytes())
            digest.update(np.asarray(self.displayed_y(spec.id), dtype='<f8').tobytes())
            digest.update(json.dumps(spec.meta, sort_keys=True, default=str).encode())
        return digest.hexdigest()

    def preview_operations(
        self, operations: list[dict], spectrum_ids=None,
        source: str = 'manual', label: Optional[str] = None,
    ) -> dict:
        """Compute a reviewable proposal without changing spectra or history."""
        from core.processing import run_operations, validate_operations

        ids = self._resolve_ids(spectrum_ids)
        operations = validate_operations(operations)
        if source not in {'manual', 'ai', 'preset'}:
            raise ValueError('Unknown processing source.')
        label = str(label or ' → '.join(op['op'] for op in operations))[:240]
        results = {}
        for spec in self._spectra:
            if spec.id in ids:
                if len(self._recipes.get(spec.id, [])) + len(operations) > 100:
                    raise ValueError('A spectrum recipe supports at most 100 operations. Restore original data before starting another recipe.')
                result = run_operations(spec.x, self.displayed_y(spec.id), spec.meta, operations)
                result['meta'] = self._validated_metadata(result['meta'])
                self._validate_data(result['x'], result['y'])
                results[spec.id] = result
        proposal = {
            'id': uuid.uuid4().hex, 'revision': self._revision,
            'signature': self._data_signature(ids), 'spectrum_ids': ids,
            'operations': operations, 'source': source, 'label': label,
            'results': results,
        }
        self._preview = copy.deepcopy(proposal)
        self.preview_changed.emit()
        return proposal

    def apply_operations(
        self, operations: list[dict], spectrum_ids=None,
        source: str = 'manual', label: Optional[str] = None,
    ) -> dict:
        proposal = self.preview_operations(operations, spectrum_ids, source, label)
        return self.apply_preview(proposal)

    def apply_preview(self, preview: Optional[dict] = None) -> dict:
        """Accept only the exact locally computed proposal for unchanged data."""
        preview = self._preview if preview is None else preview
        if not isinstance(preview, dict) or self._preview is None:
            raise ValueError('There is no preview to apply.')
        if preview != self._preview:
            raise ValueError('Preview was modified or replaced; generate a new preview.')
        ids = preview['spectrum_ids']
        if preview['revision'] != self._revision or preview['signature'] != self._data_signature(ids):
            self.clear_preview()
            raise ValueError('Spectrum changed after the preview. Generate a new preview.')
        before = self._snapshot()
        for spec in self._spectra:
            if spec.id not in ids:
                continue
            result = preview['results'][spec.id]
            spec.x, spec.y = list(result['x']), list(result['y'])
            spec.meta = copy.deepcopy(result['meta'])
            self._clear_derived(spec.id)
            old_recipe = self._recipes.get(spec.id, [])
            self._shift_manual_peaks(spec.id, old_recipe, old_recipe + preview['operations'])
            self._recipes.setdefault(spec.id, []).extend(copy.deepcopy(preview['operations']))
            # The overlay is descriptive only; it is never another processing input.
            if preview['operations'][-1]['op'] == 'baseline':
                details = result.get('details', [])
                baseline = details[-1].get('baseline') if details else None
                if baseline is not None and len(baseline) == len(spec.y):
                    self.baseline_y[spec.id] = list(baseline)
            self._refresh_manual_indices(spec)
        self._baseline.enabled = any(op['op'] == 'baseline' for recipe in self._recipes.values() for op in recipe)
        return self._record_transaction(before, preview['label'], preview['source'],
                                        preview['operations'], ids)

    def _clear_derived(self, sid: str) -> None:
        spec = next(s for s in self._spectra if s.id == sid)
        for peak in self.peaks_auto.get(sid, []):
            spec.meta.get('peak_label_positions', {}).pop(peak.id, None)
        for store in (self.cosmic_clean_y, self.processed_y, self.baseline_y,
                      self.smoothed_y, self.peaks_auto):
            store.pop(sid, None)

    def _refresh_manual_indices(self, spec: Spectrum) -> None:
        xa = np.asarray(spec.x)
        lo, hi = float(np.min(xa)), float(np.max(xa))
        for peak in self.peaks_manual.get(spec.id, []):
            peak.i = int(np.argmin(np.abs(xa - peak.x))) if lo <= peak.x <= hi else None

    def _shift_manual_peaks(self, sid, old_recipe, new_recipe) -> None:
        def x_shift(recipe):
            return sum(op.get('params', {}).get('x', 0) for op in recipe if op['op'] == 'shift')
        delta = x_shift(new_recipe) - x_shift(old_recipe)
        for peak in self.peaks_manual.get(sid, []):
            peak.x += delta
        spec = next(s for s in self._spectra if s.id == sid)
        positions = spec.meta.get('peak_label_positions', {})
        for pid in {peak.id for peak in self.peaks_manual.get(sid, [])}:
            if pid in positions:
                positions[pid][0] += delta

    @staticmethod
    def _carry_peak_positions(old_meta, new_meta) -> None:
        if 'peak_label_positions' in old_meta:
            new_meta['peak_label_positions'] = copy.deepcopy(old_meta['peak_label_positions'])

    def reset_processing(self, ids=None) -> dict:
        selected = self._resolve_ids(ids)
        before = self._snapshot()
        for spec in self._spectra:
            if spec.id not in selected:
                continue
            raw = self._original[spec.id]
            meta = copy.deepcopy(raw['meta'])
            self._carry_peak_positions(spec.meta, meta)
            spec.x, spec.y = list(raw['x']), list(raw['y'])
            spec.meta = meta
            self._shift_manual_peaks(spec.id, self._recipes.get(spec.id, []), [])
            self._recipes[spec.id] = []
            self._clear_derived(spec.id)
            self._refresh_manual_indices(spec)
        self._baseline.enabled = any(op['op'] == 'baseline' for recipe in self._recipes.values() for op in recipe)
        return self._record_transaction(before, 'Restore original data', 'manual', [], selected)

    def reset_operation(self, operation: str, ids=None) -> dict:
        """Remove one processing stage and replay subsequent operations from originals."""
        from core.processing import run_operations

        if operation not in {'baseline', 'smooth', 'despike'}:
            raise ValueError('This processing stage cannot be reset separately.')
        selected = self._resolve_ids(ids)
        results, recipes = {}, {}
        for sid in selected:
            recipes[sid] = [copy.deepcopy(op) for op in self._recipes.get(sid, []) if op['op'] != operation]
            raw = self._original[sid]
            results[sid] = (run_operations(raw['x'], raw['y'], raw['meta'], recipes[sid])
                            if recipes[sid] else copy.deepcopy(raw))
        before = self._snapshot()
        for spec in self._spectra:
            if spec.id not in selected:
                continue
            result = results[spec.id]
            self._carry_peak_positions(spec.meta, result['meta'])
            spec.x, spec.y, spec.meta = result['x'], result['y'], result['meta']
            self._shift_manual_peaks(spec.id, self._recipes.get(spec.id, []), recipes[spec.id])
            self._recipes[spec.id] = recipes[spec.id]
            self._clear_derived(spec.id)
            self._refresh_manual_indices(spec)
        self._baseline.enabled = any(op['op'] == 'baseline' for recipe in self._recipes.values() for op in recipe)
        return self._record_transaction(before, f'Remove {operation}', 'manual', [], selected)

    def apply_preset(self, settings: dict, recipe: Optional[list[dict]] = None,
                     detect_auto: bool = False) -> dict:
        """Apply settings and an optional recipe from originals in one undo transaction."""
        from core.processing import run_operations, validate_operations
        from core.project_io import SETTINGS, settings_from_dict
        from core.peak_detection import detect_peaks, detected_to_peaks

        if not isinstance(settings, dict) or set(settings) - (set(SETTINGS) | {'spectral_mode'}):
            raise ValueError('Invalid preset settings.')
        parsed = {attr: settings_from_dict(cls, settings[key])
                  for key, (attr, cls) in SETTINGS.items() if key in settings}
        mode = settings.get('spectral_mode', self._spectral_mode)
        if mode not in SPECTRAL_MODES:
            raise ValueError('Unknown preset spectral mode.')
        if recipe is not None:
            recipe = validate_operations(recipe) if recipe else []
        results, auto = {}, {}
        p = parsed.get('_peaks', self._peaks)
        mixed = len({spec.meta.get('y_kind', 'intensity') for spec in self._spectra}) > 1
        for spec in self._spectra:
            if recipe is not None:
                raw = self._original[spec.id]
                results[spec.id] = (run_operations(raw['x'], raw['y'], raw['meta'], recipe)
                                    if recipe else copy.deepcopy(raw))
            result = results.get(spec.id, {'x': spec.x, 'y': self.displayed_y(spec.id)})
            if detect_auto and p.enabled:
                result_meta = results.get(spec.id, {}).get('meta', spec.meta)
                prominence, polarity = self._peak_parameters(p, result_meta, mixed)
                detected = detect_peaks(result['x'], result['y'], min_prominence=prominence,
                                        min_distance_x=p.min_distance, max_peaks=p.max_peaks,
                                        polarity=polarity, x_min=p.x_min if p.region_enabled else None,
                                        x_max=p.x_max if p.region_enabled else None)
                auto[spec.id] = detected_to_peaks(detected)
        before = self._snapshot()
        for attr, value in parsed.items():
            setattr(self, attr, value)
        self._spectral_mode = mode
        for spec in self._spectra:
            if recipe is not None:
                result = results[spec.id]
                self._carry_peak_positions(spec.meta, result['meta'])
                spec.x, spec.y, spec.meta = result['x'], result['y'], result['meta']
                self._shift_manual_peaks(spec.id, self._recipes.get(spec.id, []), recipe)
                self._clear_derived(spec.id)
                self._recipes[spec.id] = copy.deepcopy(recipe)
                self._refresh_manual_indices(spec)
        self.peaks_auto.clear()
        self.peaks_auto.update(auto)
        if recipe is not None:
            self._baseline.enabled = any(op['op'] == 'baseline' for op in recipe)
        return self._record_transaction(before, 'Apply preset from original data' if recipe is not None else 'Apply preset settings',
                                        'preset', recipe or [], [s.id for s in self._spectra])

    def edit_peak_label(self, spectrum_id: str, peak_id: str, label: str) -> dict:
        self._resolve_ids([spectrum_id])
        if not isinstance(label, str) or len(label) > 1000:
            raise ValueError('Peak label must contain at most 1000 characters.')
        for store in (self.peaks_auto, self.peaks_manual):
            peak = next((p for p in store.get(spectrum_id, []) if p.id == peak_id), None)
            if peak is not None:
                before = self._snapshot()
                peak.label = label.strip() or None
                return self._record_transaction(before, 'Edit peak label', 'manual', [], [spectrum_id])
        raise ValueError('Peak is no longer present.')

    def set_peak_label_position(self, spectrum_id: str, peak_id: str, x: float, y: float) -> dict:
        self._resolve_ids([spectrum_id])
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in (x, y)):
            raise ValueError('Peak label position must be finite.')
        if not any(p.id == peak_id for p in self.peaks_auto.get(spectrum_id, []) + self.peaks_manual.get(spectrum_id, [])):
            raise ValueError('Peak is no longer present.')
        before = self._snapshot()
        spec = next(s for s in self._spectra if s.id == spectrum_id)
        spec.meta.setdefault('peak_label_positions', {})[peak_id] = [float(x), float(y)]
        return self._record_transaction(before, 'Move peak label', 'manual', [], [spectrum_id])

    def reset_peak_label_positions(self, ids=None) -> dict:
        selected = self._resolve_ids(ids)
        before = self._snapshot()
        for spec in self._spectra:
            if spec.id in selected:
                spec.meta.pop('peak_label_positions', None)
        return self._record_transaction(before, 'Reset peak label positions', 'manual', [], selected)

    def add_manual_peak(self, spectrum_id: str, x: float, label: Optional[str] = None) -> Peak:
        self._resolve_ids([spectrum_id])
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not np.isfinite(x):
            raise ValueError('Manual peak position must be finite.')
        spec = next(s for s in self._spectra if s.id == spectrum_id)
        if not min(spec.x) <= x <= max(spec.x):
            raise ValueError('Manual peak must lie within the current spectrum.')
        if label is not None and (not isinstance(label, str) or len(label) > 1000):
            raise ValueError('Peak label must contain at most 1000 characters.')
        before = self._snapshot()
        peak = Peak(x=float(x), source='manual', label=label,
                    i=int(np.argmin(np.abs(np.asarray(spec.x) - x))))
        self.peaks_manual.setdefault(spectrum_id, []).append(peak)
        self._peaks.enabled = True
        self._record_transaction(before, 'Add manual peak', 'manual', [], [spectrum_id])
        return copy.deepcopy(peak)

    def detect_spectrum_peaks(self, ids=None) -> int:
        from core.peak_detection import detect_peaks, detected_to_peaks
        selected = self._resolve_ids(ids)
        results = {}
        p = self._peaks
        mixed = len({spec.meta.get('y_kind', 'intensity') for spec in self._spectra if spec.id in selected}) > 1
        for spec in self._spectra:
            if spec.id in selected:
                prominence, polarity = self._peak_parameters(p, spec.meta, mixed)
                results[spec.id] = detected_to_peaks(detect_peaks(
                    spec.x, self.displayed_y(spec.id), min_prominence=prominence,
                    min_distance_x=p.min_distance, max_peaks=p.max_peaks, polarity=polarity,
                    x_min=p.x_min if p.region_enabled else None,
                    x_max=p.x_max if p.region_enabled else None))
        before = self._snapshot()
        self.peaks_auto.update(results)
        self._peaks.enabled = True
        self._record_transaction(before, 'Detect peaks', 'manual', [], selected)
        return sum(len(peaks) for peaks in results.values())

    @staticmethod
    def _peak_parameters(settings, meta, mixed: bool):
        if not mixed or not settings.mixed_defaults:
            return settings.min_prominence, settings.polarity
        kind = meta.get('y_kind', 'intensity')
        defaults = {'absorbance': (0.01, 'max'), 'transmittance_fraction': (0.05, 'min'),
                    'transmittance_percent': (5.0, 'min'), 'intensity': (20.0, 'max')}
        prominence, polarity = defaults.get(kind, (settings.min_prominence, settings.polarity))
        if settings.polarity == 'both':
            polarity = 'both'
        return prominence, polarity

    def clear_peaks(self, ids=None) -> None:
        selected = self._resolve_ids(ids)
        before = self._snapshot()
        for sid in selected:
            self.peaks_auto.pop(sid, None)
            self.peaks_manual.pop(sid, None)
            spec = next(s for s in self._spectra if s.id == sid)
            spec.meta.pop('peak_label_positions', None)
        self._record_transaction(before, 'Clear peaks', 'manual', [], selected)

    def remove_peak(self, spectrum_id: str, peak_id: str) -> dict:
        self._resolve_ids([spectrum_id])
        for store in (self.peaks_auto, self.peaks_manual):
            if any(p.id == peak_id for p in store.get(spectrum_id, [])):
                before = self._snapshot()
                store[spectrum_id] = [p for p in store[spectrum_id] if p.id != peak_id]
                spec = next(s for s in self._spectra if s.id == spectrum_id)
                spec.meta.get('peak_label_positions', {}).pop(peak_id, None)
                return self._record_transaction(before, 'Remove peak', 'manual', [], [spectrum_id])
        raise ValueError('Peak is no longer present.')

    def _snapshot(self) -> dict:
        names = ('_spectra', '_active_spectrum_id', '_original', '_recipes',
                 '_plot', '_baseline', '_smoothing', '_cosmic', '_peaks',
                 '_graphics', '_export', '_spectral_mode',
                 'cosmic_clean_y', 'processed_y', 'baseline_y', 'smoothed_y',
                 'peaks_auto', 'peaks_manual')
        return copy.deepcopy({name: getattr(self, name) for name in names})

    def _restore(self, snapshot: dict) -> None:
        for name, value in copy.deepcopy(snapshot).items():
            setattr(self, name, value)

    @classmethod
    def _merge_unchanged(cls, before, after, target, current):
        """Keep later edits to fields that this transaction did not touch."""
        if before == after:
            return copy.deepcopy(current)
        if is_dataclass(before) and is_dataclass(after) and is_dataclass(current):
            result = copy.deepcopy(target)
            for field in fields(result):
                name = field.name
                setattr(result, name, cls._merge_unchanged(getattr(before, name), getattr(after, name),
                                                          getattr(target, name), getattr(current, name)))
            return result
        if all(isinstance(item, dict) for item in (before, after, target, current)):
            result = copy.deepcopy(target)
            for key in set(before) | set(after) | set(current):
                same_membership = (key in before) == (key in after)
                if same_membership and before.get(key) == after.get(key):
                    if key in current:
                        result[key] = copy.deepcopy(current[key])
                    else:
                        result.pop(key, None)
                elif all(key in item for item in (before, after, target, current)):
                    result[key] = cls._merge_unchanged(before[key], after[key], target[key], current[key])
            return result
        return copy.deepcopy(target)

    def _restore_transaction(self, entry, direction: str) -> None:
        before, after = entry['before'], entry['after']
        target = before if direction == 'undo' else after
        result = {}
        for attr, value in target.items():
            if attr == '_spectra':
                b = {s.id: s for s in before[attr]}
                a = {s.id: s for s in after[attr]}
                current = {s.id: s for s in self._spectra}
                target_by_id = {s.id: s for s in value}
                order = ([s.id for s in self._spectra] if [s.id for s in before[attr]] == [s.id for s in after[attr]]
                         else [s.id for s in value])
                result[attr] = [self._merge_unchanged(b[sid], a[sid], target_by_id[sid], current[sid])
                                for sid in order]
            else:
                result[attr] = self._merge_unchanged(before[attr], after[attr], value, getattr(self, attr))
        self._restore(result)

    def _record_transaction(self, before, label, source, operations, ids) -> dict:
        record = {
            'id': uuid.uuid4().hex, 'timestamp': datetime.now(timezone.utc).isoformat(),
            'label': label, 'source': source, 'spectrum_ids': list(ids),
            'operations': copy.deepcopy(operations), 'action': 'apply',
        }
        self._undo_stack.append({'before': before, 'after': self._snapshot(), 'record': record})
        self._undo_stack = self._undo_stack[-40:]
        self._redo_stack.clear()
        self._history.append(copy.deepcopy(record))
        self._history = self._history[-200:]
        self._invalidate()
        self._emit_workspace_changed()
        return copy.deepcopy(record)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        entry = self._undo_stack.pop()
        self._restore_transaction(entry, 'undo')
        self._redo_stack.append(entry)
        self._history.append({**copy.deepcopy(entry['record']), 'action': 'undo',
                              'timestamp': datetime.now(timezone.utc).isoformat()})
        self._history = self._history[-200:]
        self._invalidate()
        self._emit_workspace_changed()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        entry = self._redo_stack.pop()
        self._restore_transaction(entry, 'redo')
        self._undo_stack.append(entry)
        self._history.append({**copy.deepcopy(entry['record']), 'action': 'redo',
                              'timestamp': datetime.now(timezone.utc).isoformat()})
        self._history = self._history[-200:]
        self._invalidate()
        self._emit_workspace_changed()
        return True

    def _emit_workspace_changed(self) -> None:
        for signal in (self.spectra_changed, self.active_spectrum_changed,
                       self.plot_changed, self.baseline_changed, self.smoothing_changed,
                       self.cosmic_changed, self.peaks_changed, self.graphics_changed,
                       self.export_changed, self.spectral_mode_changed, self.history_changed):
            signal.emit()
