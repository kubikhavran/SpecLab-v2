import unittest

import numpy as np

from core.peak_detection import detect_peaks, detected_to_peaks
from core.processing import ProcessingError, run_operations, validate_operations


def operation(name, **params):
    return {'op': name, 'params': params}


class ProcessingTests(unittest.TestCase):
    def test_conversion_round_trip_and_units(self):
        x, y = [1, 2, 3], [10, 50, 105]
        result = run_operations(x, y, {'y_kind': 'transmittance_percent'}, [
            operation('convert_y', target='absorbance'),
            operation('convert_y', target='transmittance_fraction'),
            operation('convert_y', target='transmittance_percent'),
        ])
        np.testing.assert_allclose(result['y'], y)
        self.assertEqual(result['meta']['y_kind'], 'transmittance_percent')
        self.assertEqual(result['meta']['y_unit'], '%')

    def test_conversion_requires_known_positive_ordinate(self):
        for meta, y in [({'y_kind': 'intensity'}, [1, 2]),
                        ({'y_kind': 'transmittance_fraction'}, [0, 0.5])]:
            with self.assertRaises(ProcessingError):
                run_operations([1, 2], y, meta, [operation('convert_y', target='absorbance')])
        with self.assertRaises(ProcessingError):
            run_operations([1, 2], [1000, 1], {'y_kind': 'absorbance'},
                           [operation('convert_y', target='transmittance_fraction')])

    def test_derivative_sign_and_scale_descending(self):
        x = np.arange(10, -1, -0.5)
        y = x * x
        result = run_operations(x, y, {'x_unit': 'nm', 'y_kind': 'absorbance'},
                                [operation('derivative', order=1, window=5, poly_order=2)])
        np.testing.assert_allclose(result['y'], 2 * x, atol=1e-10)
        self.assertEqual(result['meta']['y_kind'], 'intensity')
        second = run_operations(x, y, {}, [operation('derivative', order=2, window=5, poly_order=2)])
        np.testing.assert_allclose(second['y'], 2, atol=1e-10)

    def test_sequence_uses_previous_result_and_does_not_mutate_input(self):
        x, y, meta = [1, 2, 3], [1, 2, 4], {'y_kind': 'absorbance'}
        result = run_operations(x, y, meta, [operation('shift', y=2), operation('normalize', method='max')])
        np.testing.assert_allclose(result['y'], [0.5, 2 / 3, 1])
        self.assertEqual(y, [1, 2, 4])
        self.assertEqual(meta, {'y_kind': 'absorbance'})
        with self.assertRaises(ProcessingError):
            run_operations(x, y, meta, [operation('normalize'), operation('convert_y', target='transmittance_percent')])

    def test_nonuniform_requires_resampling_and_grid_preserves_step(self):
        x = [0, 1, 2.1, 3, 4, 5]
        with self.assertRaisesRegex(ProcessingError, 'Resample'):
            run_operations(x, x, {}, [operation('derivative', window=5, poly_order=2)])
        result = run_operations(x, x, {}, [operation('resample', step=0.7),
                                         operation('smooth', window=5, poly_order=2)])
        np.testing.assert_allclose(np.diff(result['x']), 0.7)
        np.testing.assert_allclose(result['x'], result['y'], atol=1e-10)
        descending = run_operations(x[::-1], x[::-1], {}, [operation('resample', step=0.7)])
        np.testing.assert_allclose(np.diff(descending['x']), -0.7)

    def test_detector_axis_allows_point_filters_but_not_gaps(self):
        # Raman CCD axes are monotonic with a slowly changing step.
        x = np.cumsum(np.linspace(1.49, 1.68, 200))
        y = np.sin(x / 20) + 0.01 * np.cos(x * 7)
        y[100] += 50
        for op in [operation('smooth', window=11, poly_order=3), operation('baseline'),
                   operation('despike', window=11)]:
            with self.subTest(op=op['op']):
                result = run_operations(x, y, {}, [op])
                self.assertEqual(result['details'][0]['sampling'], 'point_index')
                self.assertTrue(np.all(np.isfinite(result['y'])))
        uniform = run_operations(np.arange(20.0), np.ones(20), {}, [operation('smooth', window=5)])
        self.assertEqual(uniform['details'][0]['sampling'], 'uniform')
        gap = np.r_[np.arange(0, 20.0), np.arange(100, 120.0)]
        for op in [operation('smooth', window=5), operation('baseline'), operation('despike', window=5)]:
            with self.subTest(gap=op['op']), self.assertRaisesRegex(ProcessingError, 'gap'):
                run_operations(gap, np.ones(40), {}, [op])
        with self.assertRaisesRegex(ProcessingError, 'Resample'):
            run_operations(x, y, {}, [operation('derivative', window=11, poly_order=3)])
        with self.assertRaisesRegex(ProcessingError, 'gap'):
            run_operations([100.0, 101.0, 100000.0], [1.0, 2.0, 3.0], {},
                           [operation('smooth', window=3, poly_order=1)])

    def test_invalid_parameters_and_data_are_rejected(self):
        invalid = [operation('exec'), operation('smooth', window=4),
                   operation('smooth', window=1003), operation('smooth', poly_order=10),
                   operation('baseline', p=1), operation('baseline', iterations=0),
                   operation('resample', step=0), operation('normalize', typo=1),
                   operation('shift', x=float('inf')), operation('despike', positive_only='yes')]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ProcessingError):
                validate_operations([item])
        for x, y in [([1, 2], [1, float('nan')]), ([1, 1], [1, 2]),
                     ([1, 2, 3], [1, 2]), ([[1, 2]], [[1, 2]])]:
            with self.subTest(x=x), self.assertRaises(ProcessingError):
                run_operations(x, y, {}, [operation('normalize')])
        with self.assertRaises(ProcessingError):
            run_operations([1, 2], [1, 2], {}, [operation('smooth')])

    def test_normalization_and_baseline(self):
        for method in ['max', 'vector', 'area', 'minmax']:
            result = run_operations([0, 1, 2], [1, 2, 3], {}, [operation('normalize', method=method)])
            self.assertTrue(np.all(np.isfinite(result['y'])))
        with self.assertRaises(ProcessingError):
            run_operations([0, 1], [0, 0], {}, [operation('normalize')])
        x = np.arange(101)
        y = 10 + 0.02 * x + 20 * np.exp(-((x - 50) / 4) ** 2)
        result = run_operations(x, y, {}, [operation('baseline', lam=1e5)])
        self.assertLess(abs(np.median(result['y'][:20])), 0.5)
        self.assertGreater(max(result['y']), 15)
        absorbance = run_operations(x, y, {'y_kind': 'absorbance'}, [operation('baseline')])
        self.assertEqual(absorbance['meta']['y_kind'], 'absorbance')
        transmittance = run_operations(x, y, {'y_kind': 'transmittance_percent'}, [operation('baseline')])
        self.assertEqual(transmittance['meta']['y_kind'], 'intensity')

    def test_manual_interpolation_and_zero_mad_spike(self):
        x, y = np.arange(21), np.ones(21)
        y[10] = 100
        result = run_operations(x, y, {}, [operation('despike', window=5)])
        np.testing.assert_allclose(result['y'], 1)
        self.assertEqual(result['details'][0]['removed_count'], 1)
        result = run_operations(x[::-1], y[::-1], {}, [operation('interpolate', min=9.5, max=10.5)])
        np.testing.assert_allclose(result['y'], 1)
        with self.assertRaises(ProcessingError):
            run_operations(x, y, {}, [operation('interpolate', min=0, max=2)])

    def test_peaks_distance_in_real_x_and_minimum_polarity(self):
        x = [0, 1, 1.1, 1.2, 2, 8, 9, 10, 11]
        y = [0, 5, 0, 4, 0, 0, 3, 0, 0]
        detected = detect_peaks(x, y, min_prominence=0.1, min_distance_x=0.5)
        self.assertEqual([p.x for p in detected], [1.0, 9.0])
        minima = detected_to_peaks(detect_peaks([0, 1, 2, 3, 4], [1, 0, 1, 0.5, 1],
                                               min_distance_x=0, polarity='min'))
        self.assertTrue(minima)
        self.assertTrue(all(p.kind == 'min' and p.prominence > 0 for p in minima))


if __name__ == '__main__':
    unittest.main()
