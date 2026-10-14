import unittest

import numpy as np

from app.models import Peak, Spectrum
from app.state import LABEL_OFFSETS, AppState
from core.presets import apply_preset_payload, capture_preset_payload


def op(name, **params):
    return {'op': name, 'params': params}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = AppState()
        self.spec = Spectrum(name='test', x=list(range(21)), y=[float(i + 1) for i in range(21)],
                             meta={'technique': 'uv_vis', 'y_kind': 'absorbance', 'x_unit': 'nm'})
        self.state.add_spectrum(self.spec)

    def test_ai_then_manual_continuation_and_atomic_undo(self):
        raw = self.state.original_data(self.spec.id)
        self.state.apply_operations([op('shift', y=2)], source='ai', label='AI offset')
        ai_y = list(self.state.active_spectrum.y)
        self.state.apply_operations([op('normalize')])
        np.testing.assert_allclose(self.state.active_spectrum.y, np.array(ai_y) / max(ai_y))
        self.assertEqual(self.state.original_data(self.spec.id), raw)
        self.assertEqual(self.state.history[-2]['source'], 'ai')
        self.assertTrue(self.state.undo())
        self.assertEqual(self.state.active_spectrum.y, ai_y)
        self.assertTrue(self.state.undo())
        self.assertEqual(self.state.active_spectrum.y, raw[1])
        self.assertTrue(self.state.redo())
        self.assertEqual(self.state.active_spectrum.y, ai_y)

    def test_preview_is_nonmutating_stale_and_tamper_guarded(self):
        original = list(self.spec.y)
        undo_depth = len(self.state._undo_stack)
        proposal = self.state.preview_operations([op('shift', y=1)])
        self.assertEqual(self.spec.y, original)
        self.assertEqual(len(self.state._undo_stack), undo_depth)
        proposal['results'][self.spec.id]['y'][0] = 100
        with self.assertRaises(ValueError):
            self.state.apply_preview(proposal)
        proposal = self.state.preview_operations([op('shift', y=1)])
        self.spec.y[0] = 2  # Legacy direct mutations are also detected by the data fingerprint.
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.state.apply_preview(proposal)
        proposal = self.state.preview_operations([op('normalize')])
        self.state.update_spectrum_metadata(self.spec.id, y_kind='intensity')
        with self.assertRaises(ValueError):
            self.state.apply_preview(proposal)

    def test_batch_failure_changes_no_spectrum_or_history(self):
        short = Spectrum(x=[1, 2], y=[1, 2])
        self.state.add_spectrum(short)
        before = [list(spec.y) for spec in self.state.spectra]
        history, undo_depth = self.state.history, len(self.state._undo_stack)
        with self.assertRaises(ValueError):
            self.state.apply_operations([op('smooth', window=5, poly_order=2)],
                                        [self.spec.id, short.id])
        self.assertEqual([s.y for s in self.state.spectra], before)
        self.assertEqual(len(self.state._undo_stack), undo_depth)
        self.assertEqual(self.state.history, history)

    def test_manual_peaks_metadata_and_settings_restored(self):
        self.state.peaks_manual[self.spec.id] = [Peak(x=5, label='marker')]
        self.state.peaks_auto[self.spec.id] = [Peak(x=7)]
        self.state.set_graphics(x_label='Test unit')
        self.state.apply_operations([op('crop', min=3, max=15), op('shift', x=2)])
        manual = self.state.peaks_manual[self.spec.id][0]
        self.assertEqual(manual.x, 7)
        self.assertEqual(self.state.peaks_auto.get(self.spec.id), None)
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.x, list(range(21)))
        self.assertEqual(self.state.peaks_manual[self.spec.id][0].x, 5)
        self.assertEqual(self.state.peaks_auto[self.spec.id][0].x, 7)
        self.assertEqual(self.state.graphics.x_label, 'Test unit')

    def test_reset_is_undoable_and_new_edit_discards_redo(self):
        self.state.apply_operations([op('shift', y=2)])
        edited = list(self.state.active_spectrum.y)
        self.state.reset_processing()
        self.assertEqual(self.state.active_spectrum.y, self.state.original_data(self.spec.id)[1])
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.y, edited)
        self.state.apply_operations([op('shift', y=3)])
        self.assertFalse(self.state.can_redo)

    def test_preset_replays_from_original_once_and_undo_settings(self):
        self.state.apply_operations([op('shift', y=2), op('smooth', window=5, poly_order=2)])
        self.state.set_graphics(x_label='Saved axis')
        payload = capture_preset_payload(self.state)
        expected = list(self.state.active_spectrum.y)
        self.state.set_graphics(x_label='Other axis')
        self.state.apply_operations([op('shift', y=20)])
        before = list(self.state.active_spectrum.y)
        apply_preset_payload(self.state, payload)
        np.testing.assert_allclose(self.state.active_spectrum.y, expected)
        self.assertEqual(self.state.graphics.x_label, 'Saved axis')
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.y, before)
        self.assertEqual(self.state.graphics.x_label, 'Other axis')
        invalid = dict(payload)
        invalid['smoothing'] = {'window': 4}
        with self.assertRaises(ValueError):
            apply_preset_payload(self.state, invalid)
        self.assertEqual(self.state.active_spectrum.y, before)

    def test_peak_edits_have_undo(self):
        peak = Peak(x=5, label='old')
        self.state.peaks_manual[self.spec.id] = [peak]
        self.state.edit_peak_label(self.spec.id, peak.id, 'new')
        self.state.remove_peak(self.spec.id, peak.id)
        self.state.undo()
        self.assertEqual(self.state.peaks_manual[self.spec.id][0].label, 'new')
        self.state.undo()
        self.assertEqual(self.state.peaks_manual[self.spec.id][0].label, 'old')

    def test_label_offsets_follow_peak_and_reset_when_ordinate_rescales(self):
        peak = self.state.add_manual_peak(self.spec.id, 5)
        self.state.set_peak_label_offset(self.spec.id, peak.id, 1, 12)
        self.assertNotIn(LABEL_OFFSETS, self.state.original_metadata(self.spec.id))
        self.state.update_spectrum_metadata(self.spec.id, x_unit='cm^-1')
        self.assertNotIn(LABEL_OFFSETS, self.state.original_metadata(self.spec.id))
        # Offsets are relative to the peak, so a shifted peak keeps its label nearby.
        self.state.apply_operations([op('shift', x=2)])
        self.assertEqual(self.state.peaks_manual[self.spec.id][0].x, 7)
        self.assertEqual(self.state.active_spectrum.meta[LABEL_OFFSETS][peak.id], [1, 12])
        self.state.reset_processing()
        self.assertEqual(self.state.peaks_manual[self.spec.id][0].x, 5)
        self.assertEqual(self.state.active_spectrum.meta[LABEL_OFFSETS][peak.id], [1, 12])
        # A Y offset in old units is meaningless after normalization.
        self.state.apply_operations([op('normalize')])
        self.assertNotIn(LABEL_OFFSETS, self.state.active_spectrum.meta)
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.meta[LABEL_OFFSETS][peak.id], [1, 12])
        self.state.reset_peak_label_positions()
        self.assertNotIn(LABEL_OFFSETS, self.state.active_spectrum.meta)
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.meta[LABEL_OFFSETS][peak.id], [1, 12])
        # Absolute positions from earlier builds are dropped instead of misplaced.
        self.state.update_spectrum_metadata(self.spec.id, peak_label_positions={peak.id: [6, 12]})
        self.assertNotIn('peak_label_positions', self.state.active_spectrum.meta)

    def test_undo_shares_unchanged_arrays_and_restores_values(self):
        x_before = self.state.active_spectrum.x
        self.state.rename_spectrum(self.spec.id, 'renamed')
        entry = self.state._undo_stack[-1]
        self.assertIs(entry['before']['_spectra'][0].x, x_before)
        self.assertIs(entry['after']['_spectra'][0].x, x_before)
        self.state.apply_operations([op('shift', y=1)])
        shifted = list(self.state.active_spectrum.y)
        self.state.rename_spectrum(self.spec.id, 'again')
        self.state.undo()
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.name, 'renamed')
        self.assertEqual(self.state.active_spectrum.y, [float(i + 1) for i in range(21)])
        self.state.redo()
        self.assertEqual(self.state.active_spectrum.y, shifted)

    def test_measurement_type_survives_stage_removal_but_ordinate_does_not(self):
        self.state.apply_operations([op('baseline')])
        self.state.update_spectrum_metadata(self.spec.id, technique='raman', x_unit='cm^-1',
                                            y_kind='intensity')
        self.state.reset_operation('baseline')
        meta = self.state.active_spectrum.meta
        self.assertEqual((meta['technique'], meta['x_unit']), ('raman', 'cm^-1'))
        # The raw ordinate stays as imported; it is not relabelled after processing.
        self.assertEqual(self.state.original_metadata(self.spec.id)['y_kind'], 'absorbance')

    def test_import_remove_and_clear_are_undoable_without_losing_edits(self):
        self.state.apply_operations([op('shift', y=2)])
        shifted = list(self.state.active_spectrum.y)
        other = Spectrum(name='other', x=[1, 2, 3], y=[3, 2, 1])
        self.state.add_spectra([(other, [Peak(x=2, source='manual')])])
        self.state.remove_spectrum(self.spec.id)
        self.assertEqual([s.id for s in self.state.spectra], [other.id])
        self.state.undo()  # removal
        self.assertEqual([s.id for s in self.state.spectra], [self.spec.id, other.id])
        self.assertEqual(self.state.active_spectrum_id, other.id)
        self.state.set_active_spectrum(self.spec.id)
        self.assertEqual(self.state.active_spectrum.y, shifted)
        self.assertEqual(self.state.processing_recipe(self.spec.id)[0]['op'], 'shift')
        self.state.clear_spectra()
        self.assertEqual(self.state.spectra, [])
        self.state.undo()  # clear
        self.assertEqual(len(self.state.spectra), 2)
        self.assertEqual(len(self.state.peaks_manual[other.id]), 1)
        self.state.undo()  # import
        self.assertEqual([s.id for s in self.state.spectra], [self.spec.id])
        self.assertNotIn(other.id, self.state.peaks_manual)
        self.assertIsNone(self.state.original_data(other.id))
        self.state.redo()
        self.assertEqual([s.id for s in self.state.spectra], [self.spec.id, other.id])
        self.assertEqual(self.state.history[-1]['action'], 'redo')
        # The earlier processing step is still undoable after membership changes.
        self.state.undo()
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.y, [float(i + 1) for i in range(21)])

    def test_batch_add_is_atomic(self):
        good = Spectrum(name='good', x=[1, 2, 3], y=[1, 2, 3])
        bad = Spectrum(name='bad', x=[1, 1, 2], y=[1, 2, 3])
        with self.assertRaises(ValueError):
            self.state.add_spectra([(good, None), (bad, None)])
        self.assertEqual(len(self.state.spectra), 1)
        self.state.add_spectra([(good, [Peak(x=2, source='manual')])])
        self.assertEqual(self.state.active_spectrum_id, good.id)
        self.assertTrue(self.state.peaks_settings.enabled)

    def test_undo_bound_and_stage_reset(self):
        for _ in range(45):
            self.state.apply_operations([op('shift', y=1)])
        count = 0
        while self.state.undo():
            count += 1
        self.assertEqual(count, 40)
        self.state.apply_operations([op('smooth', window=5, poly_order=2)])
        self.state.reset_operation('smooth')
        self.assertFalse(any(p['op'] == 'smooth' for p in self.state.processing_recipe(self.spec.id)))

    def test_rename_reorder_and_metadata_are_independent_undo_transactions(self):
        other = Spectrum(name='second', x=[1, 2], y=[1, 2])
        self.state.add_spectrum(other)
        self.state.set_active_spectrum(self.spec.id)
        self.state.apply_operations([op('normalize')])
        normalized = list(self.state.active_spectrum.y)
        self.state.rename_spectra({self.spec.id: 'Renamed', other.id: 'Second renamed'})
        self.state.move_spectrum(self.spec.id, 'down')
        self.state.update_spectrum_metadata(self.spec.id, x_unit='cm^-1')
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.meta['x_unit'], 'nm')
        self.assertEqual(self.state.active_spectrum.name, 'Renamed')
        self.state.undo()
        self.assertEqual(self.state.spectra[0].id, self.spec.id)
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.name, 'test')
        self.assertEqual(self.state.spectra[1].name, 'second')
        self.assertEqual(self.state.active_spectrum.y, normalized)
        self.state.undo()
        self.assertEqual(self.state.active_spectrum.y, self.state.original_data(self.spec.id)[1])

    def test_processing_undo_preserves_later_untouched_settings_and_selection(self):
        other = Spectrum(x=[1, 2], y=[1, 2])
        self.state.add_spectrum(other)
        self.state.set_active_spectrum(self.spec.id)
        self.state.apply_operations([op('normalize')])
        self.state.set_graphics(x_label='Changed after processing', show_grid=True)
        self.state.set_plot(x_min=3, x_max=19)
        self.state.set_smoothing(window=7, poly_order=2)
        self.state.set_baseline(lambda_=10000)
        self.state.set_cosmic(threshold=8)
        self.state.set_active_spectrum(other.id)
        self.state.undo()
        self.assertEqual(self.state.graphics.x_label, 'Changed after processing')
        self.assertTrue(self.state.graphics.show_grid)
        self.assertEqual(self.state.plot.x_min, 3)
        self.assertEqual(self.state.smoothing.window, 7)
        self.assertEqual(self.state.baseline.lambda_, 10000)
        self.assertEqual(self.state.cosmic.threshold, 8)
        self.assertEqual(self.state.active_spectrum_id, other.id)
        self.state.redo()
        self.assertEqual(self.state.graphics.x_label, 'Changed after processing')
        self.assertEqual(self.state.smoothing.window, 7)

    def test_mixed_peak_scope_uses_safe_polarity_and_scale_and_region(self):
        self.state.clear_spectra()
        absorbance = Spectrum(x=[0, 1, 2, 3, 4], y=[0, 0.1, 0, 0.2, 0], meta={'y_kind': 'absorbance'})
        transmit = Spectrum(x=[0, 1, 2, 3, 4], y=[100, 80, 100, 60, 100], meta={'y_kind': 'transmittance_percent'})
        self.state.add_spectrum(absorbance)
        self.state.add_spectrum(transmit)
        self.state.set_peaks(min_prominence=5, min_distance=0, polarity='min',
                             region_enabled=True, x_min=0.5, x_max=1.5)
        self.assertEqual(self.state.detect_spectrum_peaks([absorbance.id, transmit.id]), 2)
        self.assertEqual(self.state.peaks_auto[absorbance.id][0].kind, 'max')
        self.assertEqual(self.state.peaks_auto[transmit.id][0].kind, 'min')
        self.assertTrue(all(p.x == 1 for peaks in self.state.peaks_auto.values() for p in peaks))
        self.state.set_peaks(polarity='both')
        self.assertEqual(self.state._peak_parameters(self.state.peaks_settings, absorbance.meta, True)[1], 'both')
        self.state.set_peaks(polarity='min', min_prominence=1, mixed_defaults=False)
        self.assertEqual(self.state._peak_parameters(self.state.peaks_settings, transmit.meta, True), (1, 'min'))


if __name__ == '__main__':
    unittest.main()
