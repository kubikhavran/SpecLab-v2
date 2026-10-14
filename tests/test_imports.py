"""Import regressions: preserve measured values and reject unsafe interpretations."""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src_python'))
from core.spectrum_parser import SpectrumParseError, parse_spectrum_file, parse_spectrum_files


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def file(self, suffix, contents):
        path = Path(self.temp.name) / ('sample' + suffix)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding='utf-8')
        return str(path)

    def test_european_csv_preserves_all_columns_and_pairs(self):
        path = self.file('.csv', '\ufeffWavenumber (cm^-1);Absorbance A;Absorbance B\n3000,0;0,1;0,2\n1000,0;0,3;0,4\n2000,0;0,5;0,6\n')
        spectra = parse_spectrum_files(path)
        self.assertEqual(len(spectra), 2)
        self.assertEqual(spectra[0].x, [1000, 2000, 3000])
        self.assertEqual(spectra[0].y, [0.3, 0.5, 0.1])
        self.assertEqual(spectra[1].y, [0.4, 0.6, 0.2])
        self.assertEqual(spectra[0].metadata['x_unit'], 'cm^-1')
        self.assertEqual(spectra[0].metadata['y_kind'], 'absorbance')
        with self.assertRaisesRegex(SpectrumParseError, 'několik spekter'):
            parse_spectrum_file(path)

    def test_csv_quoted_headers_and_values(self):
        path = self.file('.csv', '"Wavelength (nm)","Absorbance, sample"\n"250","0.1"\n"251","0.2"\n')
        item = parse_spectrum_file(path)
        self.assertEqual(item.y, [0.1, 0.2])
        self.assertEqual(item.metadata['name'], 'Absorbance, sample')

    def test_whitespace_decimal_comma_and_metadata(self):
        item = parse_spectrum_file(self.file('.txt', '# technique=raman x_unit=cm^-1 y_kind=intensity\n100,0 10,5\n200,0 20,5\n'))
        self.assertEqual(item.y, [10.5, 20.5])
        self.assertEqual(item.metadata['technique'], 'raman')

    def test_text_does_not_drop_invalid_rows(self):
        for row in ['2,NaN', '2,Inf', '2,', '2,3,4', '2,broken']:
            with self.subTest(row=row), self.assertRaises(SpectrumParseError):
                parse_spectrum_files(self.file('.csv', '1,2\n' + row + '\n3,4\n'))

    def test_duplicate_x_rejected(self):
        with self.assertRaisesRegex(SpectrumParseError, 'Duplicitní souřadnice X'):
            parse_spectrum_file(self.file('.txt', '1 2\n1 3\n2 4\n'))

    @staticmethod
    def annotations(*records):
        """OMNIC block 104: u32 count, then u16 flags, f32 x, f32 label x, f32 y, text NUL."""
        raw = struct.pack('<I', len(records))
        for x, text in records:
            raw += struct.pack('<Hfff', 8, x, x, 50.0) + text.encode('latin-1') + b'\x00'
        return raw

    @classmethod
    def spa(cls, payload_count=3, declared_count=3, x_unit=1, peaks=True):
        entries = [(2, 512, 208), (3, 720, payload_count * 4)]
        # Real files also carry free text (history, comments) that must not become peaks.
        peak_text = cls.annotations((2000.0, 'Carbonyl'), (3000.0, '3000'))
        history = b'Automatic Baseline Correct\n Corrected from 3000.0000 to 1000.0000.\n'
        if peaks:
            entries += [(104, 740, len(peak_text)), (27, 900, len(history))]
        blob = bytearray(1000)
        blob[:18] = b'Spectral Data File'
        struct.pack_into('<H', blob, 294, len(entries))
        for index, (key, offset, length) in enumerate(entries):
            position = 304 + index * 16
            blob[position] = key
            struct.pack_into('<II', blob, position + 2, offset, length)
        struct.pack_into('<I', blob, 516, declared_count)
        blob[520], blob[524] = x_unit, 17
        struct.pack_into('<ff', blob, 528, 3000, 1000)
        struct.pack_into('<' + 'f' * payload_count, blob, 720, *range(1, payload_count + 1))
        if peaks:
            blob[740:740 + len(peak_text)] = peak_text
            blob[900:900 + len(history)] = history
        return bytes(blob)

    def test_spa_preserves_direction_and_embedded_peaks(self):
        item = parse_spectrum_file(self.file('.spa', self.spa()))
        self.assertEqual(item.x, [1000, 2000, 3000])
        self.assertEqual(item.y, [3, 2, 1])
        self.assertEqual(item.metadata['y_kind'], 'absorbance')
        # OMNIC labels: custom text kept, numeric labels left to SpecLab formatting.
        self.assertEqual([(p.x, p.label) for p in item.imported_peaks], [(2000, 'Carbonyl'), (3000, '')])
        self.assertEqual(item.metadata['imported_peaks_source'], 'omnic_annotations')

    def test_spa_ignores_free_text_and_reads_find_peaks_table(self):
        blob = bytearray(self.spa(peaks=False))
        report = b'PEAKTABLE\nFIND PEAKS:\n Peak list:\n  Position:  1500  Intensity:  34.762\n'
        status = b'Instrument Status\tPass\tDate Tested: 2026\n Corrected from 3000 to 1000.\n'
        struct.pack_into('<H', blob, 294, 4)
        for index, (key, offset, length) in enumerate([(130, 740, len(report)), (27, 900, len(status))], 2):
            position = 304 + index * 16
            blob[position] = key
            struct.pack_into('<II', blob, position + 2, offset, length)
        blob += bytes(200)
        blob[740:740 + len(report)] = report
        blob[900:900 + len(status)] = status
        item = parse_spectrum_file(self.file('.spa', bytes(blob)))
        self.assertEqual([p.x for p in item.imported_peaks], [1500])
        self.assertEqual(item.metadata['imported_peaks_source'], 'omnic_peak_table')
        bad = bytearray(self.spa())
        struct.pack_into('<I', bad, 740, 99)   # record count larger than the block
        self.assertEqual(parse_spectrum_file(self.file('.spa', bytes(bad))).imported_peaks, [])

    def test_spa_blanked_regions_become_recorded_gaps(self):
        blob = bytearray(self.spa(payload_count=5, declared_count=5, peaks=False))
        struct.pack_into('<f', blob, 720 + 2 * 4, float('nan'))
        item = parse_spectrum_file(self.file('.spa', bytes(blob)))
        self.assertEqual(item.x, [1000, 1500, 2500, 3000])
        self.assertEqual(item.y, [5, 4, 2, 1])
        self.assertEqual(item.metadata['blanked_regions'], [[2000.0, 2000.0]])
        struct.pack_into('<f', blob, 720, float('inf'))
        with self.assertRaisesRegex(SpectrumParseError, 'nekonečné'):
            parse_spectrum_files(self.file('.spa', bytes(blob)))

    def test_spa_truncated_payload_not_stretched(self):
        with self.assertRaisesRegex(SpectrumParseError, 'počtu bodů'):
            parse_spectrum_files(self.file('.spa', self.spa(payload_count=2, declared_count=3)))

    def test_spa_bad_table_does_not_use_legacy_guess(self):
        blob = bytearray(self.spa())
        struct.pack_into('<H', blob, 294, 1000)
        with self.assertRaisesRegex(SpectrumParseError, 'tabulka záznamů'):
            parse_spectrum_files(self.file('.spa', bytes(blob)))

    def test_spa_rejects_interferogram(self):
        with self.assertRaisesRegex(SpectrumParseError, 'interferogram'):
            parse_spectrum_files(self.file('.spa', self.spa(x_unit=2)))

    @staticmethod
    def wdf(capacity=3, collected=2, flags=0):
        header = bytearray(512)
        struct.pack_into('<4sIQQ', header, 0, b'WDF1', 1, 512, flags)
        struct.pack_into('<III', header, 52, 0, 0, 3)
        struct.pack_into('<QQ', header, 64, capacity, collected)
        struct.pack_into('<III', header, 84, 1, 3, 0)
        struct.pack_into('<II', header, 128, 1, 2)
        struct.pack_into('<If', header, 152, 6, 18797)
        def block(tag, payload):
            return struct.pack('<4sIQ', tag, 0, 16 + len(payload)) + payload
        x = block(b'XLST', struct.pack('<II3f', 1, 1, 300, 200, 100))
        y = block(b'DATA', struct.pack('<6f', 1, 2, 3, 4, 5, 6))
        return bytes(header) + x + y

    def test_wdf_imports_collected_count_not_capacity(self):
        items = parse_spectrum_files(self.file('.wdf', self.wdf()))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].x, [100, 200, 300])
        self.assertEqual(items[1].y, [6, 5, 4])
        self.assertEqual(items[0].metadata['capacity'], 3)

    def test_wdf_rejects_truncated_blocks_and_multitrack(self):
        with self.assertRaisesRegex(SpectrumParseError, 'zkrácen'):
            parse_spectrum_files(self.file('.wdf', self.wdf()[:-1]))
        with self.assertRaisesRegex(SpectrumParseError, 'multitrack'):
            parse_spectrum_files(self.file('.wdf', self.wdf(flags=8)))

    def test_real_vendor_wdf_map_and_independent_reference_values(self):
        fixture = Path(__file__).parent / 'fixtures' / 'renishaw-si-map.wdf'
        items = parse_spectrum_files(str(fixture))
        self.assertEqual((len(items), len(items[0].x)), (88, 575))
        self.assertEqual(items[0].metadata['map_definition']['shape'], [8, 11, 0])
        self.assertAlmostEqual(items[0].metadata['stage_x'], -7.09, places=4)
        self.assertEqual(items[0].metadata['time'], '2005-10-27T13:54:51+00:00')
        # These integer values are independently asserted by Renishaw's upstream tests.
        # The native axis descends; normalized import reverses X and Y together.
        self.assertEqual([int(v) for v in items[0].y[-4:][::-1]], [1595, 1565, 1590, 1580])
        self.assertEqual([int(v) for v in items[-1].y[-4:][::-1]], [1612, 1615, 1514, 1553])
        self.assertTrue(np.all(np.diff(items[0].x) > 0))

    @staticmethod
    def jcamp(data='10+1+2\n12+3', count=3):
        return f'##TITLE=IR example\n##JCAMP-DX=5.01\n##DATA TYPE=INFRARED SPECTRUM\n##XUNITS=1/CM\n##YUNITS=ABSORBANCE\n##XFACTOR=100\n##YFACTOR=0.1\n##FIRSTX=1000\n##LASTX=1200\n##NPOINTS={count}\n##XYDATA=(X++(Y..Y))\n{data}\n##END=\n'

    def test_jcamp_factors_packed_affn_and_multi_blocks(self):
        item = parse_spectrum_file(self.file('.jdx', self.jcamp()))
        self.assertEqual(item.x, [1000, 1100, 1200])
        np.testing.assert_allclose(item.y, [0.1, 0.2, 0.3])
        self.assertEqual(item.metadata['technique'], 'infrared')
        items = parse_spectrum_files(self.file('.dx', self.jcamp() + self.jcamp()))
        self.assertEqual(len(items), 2)

    def test_jcamp_bad_checkpoint_compression_length_rejected(self):
        for data in ['10+1+2\n11+3', '10ABC\n12+3', '10+1\n12+3']:
            with self.subTest(data=data), self.assertRaises(SpectrumParseError):
                parse_spectrum_files(self.file('.jdx', self.jcamp(data)))

    @staticmethod
    def spc(explicit=False, endian='<', exponent=-128, subfiles=1):
        header = bytearray(512)
        header[0], header[1], header[2] = 128 if explicit else 0, 0x4B if endian == '<' else 0x4C, 7
        struct.pack_into('b', header, 3, exponent)
        struct.pack_into(endian + 'IddI', header, 4, 3, 400, 600, subfiles)
        header[28], header[29] = 3, 2
        subheader = bytearray(32)
        struct.pack_into(endian + 'I', subheader, 16, 3)
        x = struct.pack(endian + '3f', 400, 450, 600) if explicit else b''
        return bytes(header) + x + bytes(subheader) + struct.pack(endian + '3f', 0.1, 0.2, 0.3)

    def test_spc_uniform_explicit_axis_and_byte_orders(self):
        for endian in ['<', '>']:
            for explicit in [False, True]:
                with self.subTest(endian=endian, explicit=explicit):
                    item = parse_spectrum_file(self.file('.spc', self.spc(explicit, endian)))
                    self.assertEqual(item.x, [400, 450, 600] if explicit else [400, 500, 600])
                    np.testing.assert_allclose(item.y, [0.1, 0.2, 0.3])
                    self.assertEqual(item.metadata['technique'], 'uv_vis')

    def test_spc_integer_multifile_and_truncation_rejected(self):
        for blob in [self.spc(exponent=10), self.spc(subfiles=2), self.spc()[:-3]]:
            with self.assertRaises(SpectrumParseError):
                parse_spectrum_files(self.file('.spc', blob))

    def test_unknown_binary_not_imported_as_text(self):
        with self.assertRaises(SpectrumParseError):
            parse_spectrum_files(self.file('.txt', b'1\x00 2\n3 4'))


if __name__ == '__main__':
    unittest.main()
