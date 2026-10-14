"""Publication images, precise data tables and batch archives."""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)
from app.state import AppState


_EXTENSIONS = {'.png', '.svg', '.pdf', '.csv', '.tsv', '.zip'}
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.I)


def safe_export_name(name: str, fallback: str = 'spectrum') -> str:
    """Return one portable basename; input cannot escape an export folder."""
    value = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', '_', str(name)).strip(' .')
    suffix = Path(value).suffix
    if suffix.lower() in _EXTENSIONS:
        value = value[:-len(suffix)].rstrip(' .')
    value = re.sub(r'\s+', '_', value)[:80].strip(' .') or fallback
    return '_' + value if _RESERVED.fullmatch(value.split('.')[0]) else value


def unique_export_names(spectra, extension: str) -> list[str]:
    """Avoid collisions, including on case-insensitive filesystems."""
    used: set[str] = set()
    names = []
    for spec in spectra:
        base = safe_export_name(spec.name)
        candidate, suffix = f'{base}.{extension}', 2
        while candidate.casefold() in used:
            candidate = f'{base}_{suffix}.{extension}'
            suffix += 1
        names.append(candidate)
        used.add(candidate.casefold())
    return names


def _number(value, decimal_comma=False) -> str:
    if value is None:
        return ''
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError('Export data must contain only finite numbers.')
    text = repr(numeric)
    return text.replace('.', ',') if decimal_comma else text


def _spectrum_data(state, spec, original=False):
    if original:
        data = state.original_data(spec.id)
        if data is None:
            raise ValueError(f'Imported data are unavailable for {spec.name}.')
        x, y = data
        meta = state.original_metadata(spec.id)
    else:
        x = spec.x
        y = state.displayed_y(spec.id)
        y = spec.y if y is None else y
        meta = spec.meta
    if len(x) != len(y) or not x:
        raise ValueError(f'Inconsistent X/Y data in {spec.name}.')
    return x, y, meta


def spectrum_to_text(state, spec, delimiter=';', decimal_comma=False, original=False) -> str:
    """Full-precision ordinates without the visual stack offset."""
    x, y, meta = _spectrum_data(state, spec, original)
    name = str(spec.name).replace('\n', ' ').replace('\r', ' ')
    version = 'imported_original' if original else 'current'
    output = io.StringIO(newline='')
    output.write(f'# name: {name}\n# points: {len(x)}\n')
    output.write(f'# exportedAt: {datetime.now(timezone.utc).isoformat()}\n')
    output.write(f'# data_version={version}\n')
    for key in ('x_unit', 'y_kind', 'y_unit', 'technique'):
        value = str(meta.get(key, 'unknown')).replace('\n', '_').replace('\r', '_')
        output.write(f'# {key}={value}\n')
    writer = csv.writer(output, delimiter=delimiter, lineterminator='\n')
    writer.writerow(['x', 'y'])
    writer.writerows((_number(xv, decimal_comma), _number(yv, decimal_comma)) for xv, yv in zip(x, y))
    return output.getvalue()


def peaks_to_text(state, spectra, delimiter=';', decimal_comma=False) -> str:
    """A rectangular peak table retaining full Y precision and provenance."""
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=delimiter, lineterminator='\n')
    writer.writerow(['spectrum', 'x', 'y', 'source', 'label', 'prominence', 'width'])
    for spec in spectra:
        x = np.asarray(spec.x, dtype=float)
        values = state.displayed_y(spec.id)
        if state.peaks_settings.source == 'processed':
            values = state.processed_y.get(spec.id, values)
        y = np.asarray(spec.y if values is None else values, dtype=float)
        if len(x) != len(y) or not len(x):
            raise ValueError(f'Inconsistent peak data in {spec.name}.')
        if x[0] > x[-1]:
            x, y = x[::-1], y[::-1]
        peaks = state.peaks_auto.get(spec.id, []) + state.peaks_manual.get(spec.id, [])
        for peak in sorted(peaks, key=lambda p: p.x):
            peak_y = float(np.interp(peak.x, x, y)) if x[0] <= peak.x <= x[-1] else None
            writer.writerow([
                spec.name, _number(peak.x, decimal_comma), _number(peak_y, decimal_comma),
                'A' if peak.source == 'auto' else 'M', peak.label or '',
                _number(peak.prominence, decimal_comma), _number(peak.width, decimal_comma),
            ])
    return output.getvalue()


def write_spectra_zip(state, spectra, path, delimiter=';', decimal_comma=False, original=False):
    extension = 'csv' if delimiter == ';' else 'tsv'
    # Validate every entry before opening the destination.
    entries = [
        (name, spectrum_to_text(state, spec, delimiter, decimal_comma, original))
        for name, spec in zip(unique_export_names(spectra, extension), spectra)
    ]
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, text in entries:
            archive.writestr(name, text.encode('utf-8'))


class ExportPanel(QWidget):
    """Export settings shared with the rest of the workspace."""

    def __init__(self, state: AppState, get_plot_widget=None, parent=None):
        super().__init__(parent)
        self._state = state
        self._get_plot_widget = get_plot_widget
        self._build_ui()
        state.export_changed.connect(self._sync_from_state)
        self._sync_from_state()

    @staticmethod
    def _button_row(layout, items):
        row = QHBoxLayout()
        for text, callback in items:
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(QLabel('Output name'))
        self._filename = QLineEdit()
        self._filename.setPlaceholderText('Use the spectrum name')
        self._filename.editingFinished.connect(lambda: self._state.set_export(filename=self._filename.text()))
        layout.addWidget(self._filename)
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText('Ask where to save')
        choose = QPushButton('Choose folder…')
        choose.clicked.connect(self._on_choose_folder)
        clear = QPushButton('Reset')
        clear.clicked.connect(lambda: self._state.set_export(folder=''))
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(choose)
        folder_row.addWidget(clear)
        layout.addLayout(folder_row)

        group = QGroupBox('Figure')
        inner = QVBoxLayout(group)
        self._chk_transparent = QCheckBox('Transparent background (PNG / SVG)')
        inner.addWidget(self._chk_transparent)
        self._button_row(inner, [('PNG', lambda: self._export_image('png')),
                                 ('SVG', lambda: self._export_image('svg')),
                                 ('PDF', lambda: self._export_image('pdf'))])
        self._img_info = QLabel('Canvas size is set in Appearance.')
        self._img_info.setWordWrap(True)
        inner.addWidget(self._img_info)
        layout.addWidget(group)

        group = QGroupBox('Spectrum data')
        inner = QVBoxLayout(group)
        self._data_version = QComboBox()
        self._data_version.addItem('Current processed data', False)
        self._data_version.addItem('Imported original data', True)
        inner.addWidget(self._data_version)
        self._chk_decimal_comma = QCheckBox('Decimal comma (CZ)')
        inner.addWidget(self._chk_decimal_comma)
        self._button_row(inner, [('Active CSV', lambda: self._export_data(';')),
                                 ('Active TSV', lambda: self._export_data('\t'))])
        self._button_row(inner, [('All CSV files', lambda: self._export_all_data(';')),
                                 ('All TSV files', lambda: self._export_all_data('\t'))])
        self._button_row(inner, [('All CSV → ZIP', lambda: self._export_zip(';')),
                                 ('All TSV → ZIP', lambda: self._export_zip('\t'))])
        self._data_info = QLabel('Data retain full numeric precision.')
        self._data_info.setWordWrap(True)
        inner.addWidget(self._data_info)
        layout.addWidget(group)

        group = QGroupBox('Peak table')
        inner = QVBoxLayout(group)
        self._peak_scope = QComboBox()
        self._peak_scope.addItem('Active spectrum', 'active')
        self._peak_scope.addItem('All spectra', 'all')
        inner.addWidget(self._peak_scope)
        self._button_row(inner, [('Peaks CSV', lambda: self._export_peaks(';')),
                                 ('Peaks TSV', lambda: self._export_peaks('\t'))])
        layout.addWidget(group)

    def _sync_from_state(self):
        for widget, value in ((self._filename, self._state.export_settings.filename),
                              (self._folder_edit, self._state.export_settings.folder)):
            widget.blockSignals(True)
            widget.setText(value)
            widget.blockSignals(False)

    def _on_choose_folder(self):
        start = self._state.export_settings.folder or self._state.last_folder('image')
        folder = QFileDialog.getExistingDirectory(self, 'Choose export folder', start)
        if folder:
            self._state.set_export(folder=folder)
            self._state.set_last_folder(folder, 'image')

    def _get_base_name(self, fallback='spectrum'):
        spec = self._state.active_spectrum
        return safe_export_name(self._filename.text().strip() or (spec.name if spec else fallback))

    def _output_path(self, base_name, extension, context):
        base = safe_export_name(base_name)
        folder = self._state.export_settings.folder
        if folder and Path(folder).is_dir():
            path = Path(folder) / f'{base}.{extension}'
            suffix = 2
            while path.exists():
                path = Path(folder) / f'{base}_{suffix}.{extension}'
                suffix += 1
            return str(path)
        start = str(Path(self._state.last_folder(context)) / f'{base}.{extension}')
        path, _ = QFileDialog.getSaveFileName(self, f'Save {extension.upper()}', start,
                                             f'{extension.upper()} files (*.{extension})')
        if not path:
            return None
        if Path(path).suffix.lower() != f'.{extension}':
            path += f'.{extension}'
        self._state.set_last_folder(str(Path(path).parent), context)
        return path

    def _export_image(self, fmt):
        wrapper = self._get_plot_widget() if self._get_plot_widget else None
        if wrapper is None:
            self._img_info.setText('Plot is unavailable.')
            return
        hidden = []
        try:
            width, height = int(self._state.graphics.export_width), int(self._state.graphics.export_height)
            if not (300 <= width <= 8000 and 300 <= height <= 8000):
                raise ValueError('Canvas width and height must be between 300 and 8000 pixels.')
            path = self._output_path(self._get_base_name(), fmt, 'image')
            if not path:
                return
            for attr in ('_vline', '_hline'):
                item = getattr(wrapper, attr, None)
                if item is not None:
                    hidden.append((item, item.isVisible()))
                    item.hide()
            transparent = self._chk_transparent.isChecked()
            if fmt == 'png':
                self._export_png(wrapper._plot_item, path, width, height, transparent)
            elif fmt == 'svg':
                self._export_svg(wrapper._plot_item, path, width, height, transparent)
            else:
                self._export_pdf(wrapper._plot_item, path, width, height)
            self._img_info.setText(f'Saved {Path(path).name} · {width} × {height}')
        except (OSError, ValueError, RuntimeError) as exc:
            self._img_info.setText(f'Export failed: {exc}')
        finally:
            for item, visible in hidden:
                item.setVisible(visible)

    @staticmethod
    def _render(plot_item, painter, width, height, transparent=False):
        if not painter.isActive():
            raise OSError('The output painter could not be opened.')
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        target = QRectF(0, 0, width, height)
        if not transparent:
            painter.fillRect(target, QColor('white'))
        bounds = plot_item.sceneBoundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            raise ValueError('The plot has no drawable area.')
        plot_item.scene().render(painter, target, bounds)

    def _export_png(self, plot_item, path, width, height, transparent=False):
        image = QImage(QSize(width, height), QImage.Format.Format_ARGB32)
        if image.isNull():
            raise OSError('The requested image could not be allocated.')
        image.fill(QColor(0, 0, 0, 0) if transparent else QColor('white'))
        painter = QPainter(image)
        try:
            self._render(plot_item, painter, width, height, transparent)
        finally:
            painter.end()
        if not image.save(path, 'PNG'):
            raise OSError('PNG could not be written to the selected path.')

    def _export_svg(self, plot_item, path, width, height, transparent=False):
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(QSize(width, height))
        generator.setViewBox(QRectF(0, 0, width, height))
        generator.setTitle('SpecLab spectrum')
        painter = QPainter(generator)
        try:
            self._render(plot_item, painter, width, height, transparent)
        finally:
            painter.end()
        if not Path(path).is_file() or not Path(path).stat().st_size:
            raise OSError('SVG could not be written.')

    def _export_pdf(self, plot_item, path, width, height):
        writer = QPdfWriter(path)
        writer.setResolution(96)
        writer.setPageSize(QPageSize(QSizeF(width * 72 / 96, height * 72 / 96), QPageSize.Unit.Point))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        painter = QPainter(writer)
        try:
            self._render(plot_item, painter, writer.width(), writer.height())
        finally:
            painter.end()
        if not Path(path).is_file() or not Path(path).stat().st_size:
            raise OSError('PDF could not be written.')

    def _spectrum_to_text(self, spec, delimiter):
        return spectrum_to_text(self._state, spec, delimiter, self._chk_decimal_comma.isChecked(),
                                bool(self._data_version.currentData()))

    def _export_data(self, delimiter):
        spec = self._state.active_spectrum
        if spec is None:
            self._data_info.setText('Select a spectrum first.')
            return
        try:
            text = self._spectrum_to_text(spec, delimiter)
            path = self._output_path(self._get_base_name(), 'csv' if delimiter == ';' else 'tsv', 'data')
            if path:
                Path(path).write_text(text, encoding='utf-8')
                self._data_info.setText(f'Saved {Path(path).name}')
        except (OSError, ValueError) as exc:
            self._data_info.setText(f'Export failed: {exc}')

    def _export_all_data(self, delimiter):
        spectra = self._state.spectra
        if not spectra:
            self._data_info.setText('Load spectra first.')
            return
        folder = self._state.export_settings.folder
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(self, 'Export all spectra', self._state.last_folder('data_all'))
        if not folder:
            return
        self._state.set_last_folder(folder, 'data_all')
        try:
            extension = 'csv' if delimiter == ';' else 'tsv'
            entries = [(name, self._spectrum_to_text(spec, delimiter))
                       for name, spec in zip(unique_export_names(spectra, extension), spectra)]
            for name, text in entries:
                path = Path(folder) / name
                base, suffix = path.stem, 2
                while path.exists():
                    path = Path(folder) / f'{base}_{suffix}.{extension}'
                    suffix += 1
                path.write_text(text, encoding='utf-8')
            self._data_info.setText(f'Saved {len(entries)} spectra to {folder}')
        except (OSError, ValueError) as exc:
            self._data_info.setText(f'Export failed: {exc}')

    def _export_zip(self, delimiter):
        if not self._state.spectra:
            self._data_info.setText('Load spectra first.')
            return
        try:
            path = self._output_path(self._get_base_name('spectra') + '-all', 'zip', 'data_all')
            if path:
                write_spectra_zip(self._state, self._state.spectra, path, delimiter,
                                  self._chk_decimal_comma.isChecked(), bool(self._data_version.currentData()))
                self._data_info.setText(f'Saved {len(self._state.spectra)} spectra in {Path(path).name}')
        except (OSError, ValueError) as exc:
            self._data_info.setText(f'Export failed: {exc}')

    def _export_peaks(self, delimiter):
        spectra = self._state.spectra if self._peak_scope.currentData() == 'all' else [self._state.active_spectrum]
        spectra = [spec for spec in spectra if spec is not None]
        if not any(self._state.peaks_auto.get(s.id) or self._state.peaks_manual.get(s.id) for s in spectra):
            self._data_info.setText('No peaks to export.')
            return
        try:
            text = peaks_to_text(self._state, spectra, delimiter, self._chk_decimal_comma.isChecked())
            path = self._output_path(self._get_base_name('peaks') + '-peaks', 'csv' if delimiter == ';' else 'tsv', 'peaks')
            if path:
                Path(path).write_text(text, encoding='utf-8')
                self._data_info.setText(f'Saved {Path(path).name}')
        except (OSError, ValueError) as exc:
            self._data_info.setText(f'Export failed: {exc}')
