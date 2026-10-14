"""Regression coverage for lossless exports, archives and image output."""

import csv
import io
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src_python'))

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QImage, QPen
from PySide6.QtWidgets import QApplication, QGraphicsScene

from app.models import Peak, Spectrum
from app.state import AppState
from core.spectrum_parser import parse_spectrum_files, parse_spectrum_text
from ui.export_panel import (
    ExportPanel, peaks_to_text, safe_export_name, spectrum_to_text, write_spectra_zip,
)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state = AppState()

    def add_spectrum(self, name='sample', x=None, y=None, **metadata):
        spec = Spectrum(name=name, x=x or [1.0, 2.0, 3.0],
                        y=y or [0.1234567890123456, 0.7654321098765432, 0.00123456789],
                        meta=metadata)
        self.state.add_spectrum(spec)
        return spec

    def test_csv_tsv_roundtrip_decimal_modes_and_current_data(self):
        spec = self.add_spectrum(x=[1000.25, 1001.5, 1003.75], x_unit='nm',
                                 technique='uv_vis', y_kind='absorbance')
        # The export resolves displayed data, never the untouched imported array.
        self.state.smoothed_y[spec.id] = [0.0001234567890123456, 0.9876543210123456, 1.234567890123]
        self.state.set_plot(stack_offset=100)
        for delimiter in (';', '\t'):
            for decimal_comma in (False, True):
                with self.subTest(delimiter=delimiter, decimal_comma=decimal_comma):
                    text = spectrum_to_text(self.state, spec, delimiter, decimal_comma)
                    x, y = parse_spectrum_text(text)
                    self.assertEqual(x, spec.x)
                    self.assertEqual(y, self.state.smoothed_y[spec.id])
                    with tempfile.TemporaryDirectory() as directory:
                        file = Path(directory) / 'sample.csv'
                        file.write_text(text)
                        parsed = parse_spectrum_files(str(file))[0]
                        self.assertEqual(parsed.metadata['x_unit'], 'nm')
                        self.assertEqual(parsed.metadata['y_kind'], 'absorbance')

    def test_imported_export_keeps_original_units_after_conversion(self):
        spec = self.add_spectrum(y=[100.0, 50.0, 25.0], x_unit='cm^-1',
                                 technique='infrared', y_kind='transmittance_percent')
        self.state.apply_operations([{'op': 'convert_y', 'params': {'target': 'absorbance'}}])
        current = spectrum_to_text(self.state, spec)
        original = spectrum_to_text(self.state, spec, original=True)
        self.assertIn('# y_kind=absorbance', current)
        self.assertIn('# y_kind=transmittance_percent', original)
        self.assertEqual(parse_spectrum_text(original)[1], [100.0, 50.0, 25.0])
        self.assertAlmostEqual(parse_spectrum_text(current)[1][1], math.log10(2))
        self.assertEqual(self.state.original_data(spec.id)[1], [100.0, 50.0, 25.0])

    def test_peak_table_quoting_precision_and_descending_interpolation(self):
        spec = self.add_spectrum(name='Sample; "A"\nreplicate', x=[3.0, 2.0, 1.0],
                                 y=[0.1, 0.1234567890123456, 0.2])
        self.state.set_peaks(decimals=0)
        self.state.peaks_auto[spec.id] = [
            Peak(x=2.0, source='auto', label='C=O; "sharp"\nnext', prominence=0.12345, width=0.45678),
        ]
        self.state.peaks_manual[spec.id] = [Peak(x=1.5, source='manual')]
        for delimiter in (';', '\t'):
            for decimal_comma in (False, True):
                text = peaks_to_text(self.state, [spec], delimiter, decimal_comma)
                rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1]['spectrum'], spec.name)
                self.assertEqual(rows[1]['label'], 'C=O; "sharp"\nnext')
                self.assertEqual(rows[1]['source'], 'A')
                parse_number = lambda value: float(value.replace(',', '.'))
                self.assertEqual(parse_number(rows[1]['y']), spec.y[1])
                self.assertAlmostEqual(parse_number(rows[0]['y']), (spec.y[1] + spec.y[2]) / 2)
                self.assertEqual(parse_number(rows[1]['prominence']), 0.12345)
                self.assertEqual(parse_number(rows[1]['width']), 0.45678)

    def test_derived_ordinate_unit_is_written_and_reimported(self):
        spec = self.add_spectrum(x=[400.0, 401.0, 402.0], y=[0.1, 0.2, 0.4],
                                 x_unit='nm', y_kind='absorbance', y_unit='absorbance',
                                 technique='uv_vis')
        self.state.apply_operations([{'op': 'derivative',
                                      'params': {'order': 1, 'window': 3, 'poly_order': 2}}])
        text = spectrum_to_text(self.state, spec)
        self.assertIn(f'# y_unit={spec.meta["y_unit"]}', text)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'derivative.csv'
            file.write_text(text)
            imported = parse_spectrum_files(str(file))[0]
            self.assertEqual(imported.metadata['y_unit'], spec.meta['y_unit'])

    def test_zip_duplicate_names_path_safety_and_contents(self):
        for name in ('Sample', 'sample', '../sample', '.', '..', 'CON', 'CON.txt', 'sample.csv'):
            self.add_spectrum(name=name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spectra.zip'
            write_spectra_zip(self.state, self.state.spectra, path, decimal_comma=True)
            with ZipFile(path) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), len(self.state.spectra))
                self.assertEqual(len({name.casefold() for name in names}), len(names))
                for name in names:
                    self.assertEqual(Path(name).name, name)
                    self.assertNotIn('\\', name)
                    self.assertEqual(parse_spectrum_text(archive.read(name).decode())[1],
                                     self.state.spectra[0].y)

    def test_export_folder_never_escapes_or_overwrites(self):
        self.add_spectrum()
        with tempfile.TemporaryDirectory() as directory:
            panel = ExportPanel(self.state)
            self.state.set_export(folder=directory)
            panel._filename.setText('../figure.csv')
            panel._export_data(';')
            first = next(Path(directory).iterdir())
            original_bytes = first.read_bytes()
            panel._export_data(';')
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 2)
            self.assertEqual(first.read_bytes(), original_bytes)
            self.assertFalse(any(file.name.endswith('.csv.csv') for file in files))
            panel.deleteLater()
        for name in ('.', '..', '', 'foo/', 'CON', 'CON.txt'):
            value = safe_export_name(name)
            self.assertTrue(value)
            self.assertNotIn('/', value)
            self.assertNotIn('\\', value)
            self.assertNotIn(value, ('.', '..', 'CON'))
            self.assertFalse(value.startswith('CON'))

    def test_image_outputs_size_transparency_pdf_svg_and_save_failure(self):
        # A Qt scene exercises the real rendering path without a platform window.
        scene = QGraphicsScene()
        no_pen = QPen(Qt.PenStyle.NoPen)
        frame = scene.addRect(0, 0, 640, 480, no_pen, QBrush(Qt.BrushStyle.NoBrush))
        scene.addRect(100, 100, 50, 50, no_pen, QBrush(Qt.GlobalColor.red))
        panel = ExportPanel(self.state)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            png = folder / 'figure.png'
            panel._export_png(frame, str(png), 800, 600, True)
            image = QImage(str(png))
            self.assertEqual((image.width(), image.height()), (800, 600))
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            panel._export_png(frame, str(png), 800, 600, False)
            self.assertEqual(QImage(str(png)).pixelColor(0, 0).alpha(), 255)
            svg = folder / 'figure.svg'
            panel._export_svg(frame, str(svg), 800, 600, True)
            self.assertIn('<svg', svg.read_text())
            pdf = folder / 'figure.pdf'
            panel._export_pdf(frame, str(pdf), 800, 600)
            self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
            with self.assertRaises(OSError):
                panel._export_png(frame, str(folder / 'missing' / 'figure.png'), 800, 600)
        panel.deleteLater()


if __name__ == '__main__':
    unittest.main()
