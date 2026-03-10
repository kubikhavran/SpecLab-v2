"""
Export panel — save plot images (PNG / SVG) and spectrum data (CSV / TSV).
Thoroughly tested version with proper canvas size, transparency, and folder memory.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState


class ExportPanel(QWidget):
    """Controls for exporting plot images and spectrum data."""

    def __init__(
        self,
        state: AppState,
        get_plot_widget=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._get_plot_widget = get_plot_widget
        self._export_folder: str = ""
        self._build_ui()
        self._connect_signals()

    # ── Folder helpers ───────────────────────────────────

    def _start_dir(self, context: str) -> str:
        return self._state.last_folder(context)

    def _remember(self, path: str, context: str) -> None:
        if path:
            self._state.set_last_folder(path, context)

    def _on_choose_folder(self) -> None:
        start = self._export_folder or self._start_dir("image")
        folder = QFileDialog.getExistingDirectory(self, "Choose export folder", start)
        if folder and os.path.isdir(folder):
            self._export_folder = folder
            self._folder_edit.setText(folder)

    def _direct_path(self, base_name: str, ext: str) -> str | None:
        """Return a direct save path if export folder is set, else None."""
        if self._export_folder and os.path.isdir(self._export_folder):
            return os.path.join(self._export_folder, f"{base_name}.{ext}")
        return None

    # ── UI ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Filename
        self._filename = QLineEdit()
        self._filename.setPlaceholderText("e.g. EC-SERS_2026-02-09")
        layout.addWidget(QLabel("Filename:"))
        layout.addWidget(self._filename)

        # Export folder
        layout.addWidget(QLabel("Export folder:"))
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("(not set — save dialogs will open)")
        folder_row.addWidget(self._folder_edit, stretch=1)
        self._btn_choose_folder = QPushButton("Choose folder…")
        folder_row.addWidget(self._btn_choose_folder)
        layout.addLayout(folder_row)

        # ── Image export ──
        img_group = QGroupBox("Image export")
        img_layout = QVBoxLayout(img_group)
        img_layout.setContentsMargins(4, 6, 4, 6)

        self._chk_transparent = QCheckBox("Transparent background")
        img_layout.addWidget(self._chk_transparent)

        img_btn_row = QHBoxLayout()
        self._btn_png = QPushButton("Export PNG")
        self._btn_svg = QPushButton("Export SVG")
        img_btn_row.addWidget(self._btn_png)
        img_btn_row.addWidget(self._btn_svg)
        img_layout.addLayout(img_btn_row)

        self._img_info = QLabel("")
        self._img_info.setStyleSheet("color: #64748b; font-size: 11px;")
        img_layout.addWidget(self._img_info)

        layout.addWidget(img_group)

        # ── Data export ──
        data_group = QGroupBox("Data export")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(4, 6, 4, 6)

        self._chk_decimal_comma = QCheckBox("Decimal comma (CZ)")
        data_layout.addWidget(self._chk_decimal_comma)

        row1 = QHBoxLayout()
        self._btn_csv = QPushButton("Export CSV (;)")
        self._btn_tsv = QPushButton("Export TSV")
        row1.addWidget(self._btn_csv)
        row1.addWidget(self._btn_tsv)
        data_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn_csv_all = QPushButton("Export ALL CSV")
        self._btn_tsv_all = QPushButton("Export ALL TSV")
        row2.addWidget(self._btn_csv_all)
        row2.addWidget(self._btn_tsv_all)
        data_layout.addLayout(row2)

        self._data_info = QLabel("")
        self._data_info.setStyleSheet("color: #64748b; font-size: 11px;")
        data_layout.addWidget(self._data_info)

        layout.addWidget(data_group)

        # ── Peak table export ──
        peak_group = QGroupBox("Peak table export")
        peak_layout = QVBoxLayout(peak_group)
        peak_layout.setContentsMargins(4, 6, 4, 6)

        peak_row = QHBoxLayout()
        self._btn_peaks_csv = QPushButton("Peaks CSV")
        self._btn_peaks_tsv = QPushButton("Peaks TSV")
        peak_row.addWidget(self._btn_peaks_csv)
        peak_row.addWidget(self._btn_peaks_tsv)
        peak_layout.addLayout(peak_row)

        layout.addWidget(peak_group)

    def _connect_signals(self) -> None:
        self._filename.editingFinished.connect(
            lambda: self._state.set_export(filename=self._filename.text())
        )
        self._btn_choose_folder.clicked.connect(self._on_choose_folder)
        self._btn_png.clicked.connect(lambda: self._export_image("png"))
        self._btn_svg.clicked.connect(lambda: self._export_image("svg"))
        self._btn_csv.clicked.connect(lambda: self._export_data(";"))
        self._btn_tsv.clicked.connect(lambda: self._export_data("\t"))
        self._btn_csv_all.clicked.connect(lambda: self._export_all_data(";"))
        self._btn_tsv_all.clicked.connect(lambda: self._export_all_data("\t"))
        self._btn_peaks_csv.clicked.connect(lambda: self._export_peaks(";"))
        self._btn_peaks_tsv.clicked.connect(lambda: self._export_peaks("\t"))

    # ── Helpers ──────────────────────────────────────────

    def _get_base_name(self, fallback: str = "spectrum") -> str:
        name = self._filename.text().strip()
        if not name:
            spec = self._state.active_spectrum
            name = spec.name if spec else fallback
        for ch in r'\/:*?"<>|':
            name = name.replace(ch, "_")
        return name[:80].strip().rstrip(". ")

    def _format_number(self, value: float) -> str:
        text = f"{value}"
        if self._chk_decimal_comma.isChecked():
            text = text.replace(".", ",")
        return text

    # ── Image export ────────────────────────────────────

    def _export_image(self, fmt: str) -> None:
        """Export plot as PNG or SVG with correct canvas size and transparency."""
        if self._get_plot_widget is None:
            self._img_info.setText("Plot widget not available")
            return
        plot_widget = self._get_plot_widget()
        if plot_widget is None:
            self._img_info.setText("Plot widget not available")
            return

        g = self._state.graphics
        base_name = self._get_base_name()
        ext = "png" if fmt == "png" else "svg"
        w, h = g.export_width, g.export_height

        path = self._direct_path(base_name, ext)
        if path is None:
            start = os.path.join(self._start_dir("image"), f"{base_name}.{ext}")
            path, _ = QFileDialog.getSaveFileName(
                self, f"Save {ext.upper()} image", start,
                f"{ext.upper()} files (*.{ext})",
            )
            if not path:
                return
            self._remember(path, "image")

        try:
            plot_item = plot_widget._plot_item
            transparent = self._chk_transparent.isChecked()

            if fmt == "png":
                self._export_png(plot_item, path, w, h, transparent)
            else:
                self._export_svg(plot_item, path, w, h)

            self._img_info.setText(f"Saved: {os.path.basename(path)} ({w}×{h})")
        except Exception as e:
            self._img_info.setText(f"Error: {e}")

    def _export_png(self, plot_item, path: str, w: int, h: int, transparent: bool) -> None:
        """Render the plot to a PNG file at exact pixel dimensions."""
        if transparent:
            bg_color = QColor(0, 0, 0, 0)
            img_format = QImage.Format.Format_ARGB32
        else:
            bg_color = QColor(255, 255, 255, 255)
            img_format = QImage.Format.Format_RGB32

        image = QImage(QSize(w, h), img_format)
        image.fill(bg_color)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        source_rect = plot_item.sceneBoundingRect()
        target_rect = QRectF(0, 0, w, h)
        plot_item.scene().render(painter, target_rect, source_rect)

        painter.end()
        image.save(path, "PNG")

    def _export_svg(self, plot_item, path: str, w: int, h: int) -> None:
        """Render the plot to an SVG file."""
        from PySide6.QtSvg import QSvgGenerator

        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(QSize(w, h))
        generator.setViewBox(QRectF(0, 0, w, h))
        generator.setTitle("SpecLab Export")

        painter = QPainter(generator)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        source_rect = plot_item.sceneBoundingRect()
        target_rect = QRectF(0, 0, w, h)
        plot_item.scene().render(painter, target_rect, source_rect)

        painter.end()

    # ── Data export ─────────────────────────────────────

    def _spectrum_to_text(self, spec, delimiter: str) -> str:
        lines = [
            f"# name: {spec.name}",
            f"# points: {min(len(spec.x), len(spec.y))}",
            f"# exportedAt: {datetime.now().isoformat()}",
            f"x{delimiter}y",
        ]
        y_disp = self._state.displayed_y(spec.id)
        if y_disp is None:
            y_disp = spec.y
        n = min(len(spec.x), len(y_disp))
        for i in range(n):
            xv, yv = spec.x[i], y_disp[i]
            lines.append(f"{self._format_number(xv)}{delimiter}{self._format_number(yv)}")
        return "\n".join(lines)

    def _export_data(self, delimiter: str) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            self._data_info.setText("No spectrum selected")
            return

        ext = "csv" if delimiter == ";" else "tsv"
        base_name = self._get_base_name(spec.name)
        path = self._direct_path(base_name, ext)
        if path is None:
            start = os.path.join(self._start_dir("data"), f"{base_name}.{ext}")
            path, _ = QFileDialog.getSaveFileName(
                self, f"Save {ext.upper()}", start,
                f"{ext.upper()} files (*.{ext})",
            )
            if not path:
                return
            self._remember(path, "data")

        text = self._spectrum_to_text(spec, delimiter)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self._data_info.setText(f"Saved: {os.path.basename(path)}")
        except OSError as e:
            self._data_info.setText(f"Error: {e}")

    def _export_all_data(self, delimiter: str) -> None:
        spectra = self._state.spectra
        if not spectra:
            self._data_info.setText("No spectra loaded")
            return

        ext = "csv" if delimiter == ";" else "tsv"
        if self._export_folder and os.path.isdir(self._export_folder):
            folder = self._export_folder
        else:
            folder = QFileDialog.getExistingDirectory(
                self, "Select export folder", self._start_dir("data_all")
            )
            if not folder:
                return
            self._state.set_last_folder(folder, "data_all")

        used_names: set = set()
        count = 0
        for spec in spectra:
            safe_name = spec.name.strip().replace(" ", "_")
            for ch in r'\/:*?"<>|':
                safe_name = safe_name.replace(ch, "")
            if not safe_name:
                safe_name = "spectrum"
            fname = f"{safe_name}.{ext}"
            suffix_num = 2
            while fname in used_names:
                fname = f"{safe_name}_{suffix_num}.{ext}"
                suffix_num += 1
            used_names.add(fname)

            text = self._spectrum_to_text(spec, delimiter)
            full_path = os.path.join(folder, fname)
            try:
                with open(full_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                count += 1
            except OSError as e:
                self._data_info.setText(f"Error writing {fname}: {e}")
                return

        self._data_info.setText(f"Saved {count} files to {os.path.basename(folder)}/")

    # ── Peak table export ───────────────────────────────

    def _export_peaks(self, delimiter: str) -> None:
        spectra = self._state.spectra
        if not spectra:
            return

        ext = "csv" if delimiter == ";" else "tsv"
        base_name = self._get_base_name("peaks")
        path = self._direct_path(f"{base_name}-peaks", ext)
        if path is None:
            start = os.path.join(self._start_dir("peaks"), f"{base_name}-peaks.{ext}")
            path, _ = QFileDialog.getSaveFileName(
                self, f"Save peaks {ext.upper()}", start,
                f"{ext.upper()} files (*.{ext})",
            )
            if not path:
                return
            self._remember(path, "peaks")

        decimals = self._state.peaks_settings.decimals
        sections = []

        for spec in spectra:
            y_disp = self._state.displayed_y(spec.id)
            if y_disp is None:
                y_disp = spec.y
            xa = np.array(spec.x, dtype=np.float64)

            rows = []
            for source_name, store in [("auto", self._state.peaks_auto), ("manual", self._state.peaks_manual)]:
                peaks = store.get(spec.id, [])
                for peak in peaks:
                    idx = int(np.argmin(np.abs(xa - peak.x)))
                    py = y_disp[idx] if idx < len(y_disp) else 0.0
                    tag = "A" if source_name == "auto" else "M"
                    rows.append((peak.x, py, tag))

            if not rows:
                continue

            rows.sort(key=lambda r: r[0])

            section_lines = [
                f"# Spectrum: {spec.name}",
                f"# Peaks: {len(rows)}",
                f"x{delimiter}y{delimiter}source",
            ]
            for px, py, tag in rows:
                section_lines.append(
                    f"{px:.{decimals}f}{delimiter}{py:.{decimals}f}{delimiter}{tag}"
                )
            sections.append("\n".join(section_lines))

        if not sections:
            self._data_info.setText("No peaks to export")
            return

        header = [
            f"# SpecLab — Peak Table Export",
            f"# Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Spectra: {len(sections)}",
            f"#",
        ]
        full_text = "\n".join(header) + "\n\n" + "\n\n".join(sections) + "\n"

        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(full_text)
            self._data_info.setText(f"Peaks saved: {os.path.basename(path)}")
        except OSError as e:
            self._data_info.setText(f"Error: {e}")
