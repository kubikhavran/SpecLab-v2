import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import Peak, Spectrum
from app.state import AppState
from core.project_io import load_project, save_project


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'project.speclab'
        self.state = AppState()
        self.spec = Spectrum(name='Sample', x=[1, 2, 3], y=[1, 2, 3],
                             meta={'y_kind': 'absorbance', 'technique': 'uv_vis',
                                   'api_key': 'PRIVATE', 'vendor': {'token': 'PRIVATE', 'instrument': 'test'}})
        self.state.add_spectrum(self.spec)
        self.state.peaks_manual[self.spec.id] = [Peak(x=2, label='Sample label', source='manual')]
        self.state.set_peak_label_offset(self.spec.id, self.state.peaks_manual[self.spec.id][0].id, 0.2, 5)
        self.state.apply_operations([{'op': 'shift', 'params': {'y': 1}}], source='ai')
        self.state.set_graphics(x_label='Wavelength (nm)', palette='viridis')

    def test_roundtrip_original_current_metadata_peaks_style_and_provenance(self):
        save_project(self.state, self.path)
        encoded = self.path.read_text()
        self.assertNotIn('PRIVATE', encoded)
        document = json.loads(encoded)
        self.assertFalse(document['undo_persisted'])
        other = AppState()
        load_project(other, self.path)
        self.assertEqual(other.active_spectrum.y, [2, 3, 4])
        self.assertEqual(other.original_data(self.spec.id), ([1, 2, 3], [1, 2, 3]))
        self.assertEqual(other.peaks_manual[self.spec.id][0].label, 'Sample label')
        self.assertEqual(other.active_spectrum.meta['peak_label_offsets'][other.peaks_manual[self.spec.id][0].id], [0.2, 5])
        self.assertEqual(other.graphics.x_label, 'Wavelength (nm)')
        self.assertEqual(other.history[-1]['source'], 'ai')
        self.assertFalse(other.can_undo)
        self.assertEqual(other.processing_recipe(self.spec.id)[0]['op'], 'shift')
        other.apply_operations([{'op': 'normalize'}])
        self.assertTrue(other.can_undo)

    def test_invalid_project_load_is_transactional(self):
        save_project(self.state, self.path)
        original = json.loads(self.path.read_text())
        for section in ['schema', 'version', 'data', 'settings', 'peak', 'duplicate']:
            with self.subTest(section=section):
                bad = json.loads(json.dumps(original))
                if section == 'schema':
                    bad['schema'] = 'other'
                elif section == 'version':
                    bad['version'] = 999
                elif section == 'data':
                    bad['spectra'][0]['current']['x'] = [1, 1, 3]
                elif section == 'settings':
                    bad['settings']['smoothing']['window'] = 4
                elif section == 'peak':
                    bad['spectra'][0]['peaks_manual'][0]['x'] = None
                else:
                    bad['spectra'].append(bad['spectra'][0])
                self.path.write_text(json.dumps(bad))
                revision = self.state.revision
                with self.assertRaises(ValueError):
                    load_project(self.state, self.path)
                self.assertEqual(self.state.active_spectrum.y, [2, 3, 4])
                self.assertEqual(self.state.revision, revision)
                self.assertTrue(self.state.can_undo)

    def test_invalid_save_does_not_replace_existing_file(self):
        save_project(self.state, self.path)
        previous = self.path.read_text()
        self.state.active_spectrum.meta['invalid'] = float('nan')
        with self.assertRaises(ValueError):
            save_project(self.state, self.path)
        self.assertEqual(self.path.read_text(), previous)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_save_and_load_enforce_the_same_limits_transactionally(self):
        save_project(self.state, self.path)
        original = self.path.read_text()
        for constant, limit in [('MAX_SPECTRA', 0), ('MAX_TOTAL_POINTS', 5), ('MAX_PROJECT_BYTES', 10)]:
            with self.subTest(constant=constant), patch(f'core.project_io.{constant}', limit):
                with self.assertRaises(ValueError):
                    save_project(self.state, self.path)
                self.assertEqual(self.path.read_text(), original)
                before = self.state.revision
                with self.assertRaises(ValueError):
                    load_project(self.state, self.path)
                self.assertEqual(self.state.revision, before)
                self.assertEqual(self.state.active_spectrum.y, [2, 3, 4])


if __name__ == '__main__':
    unittest.main()
