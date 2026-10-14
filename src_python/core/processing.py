"""Validated, local spectrum operations shared by manual controls and AI plans.

Plans are plain data; no generated code is evaluated. Each operation consumes
the previous operation's result. Nonuniform data must be explicitly resampled
before algorithms defined on equally spaced points.
"""
from __future__ import annotations

import copy
import math

import numpy as np
from scipy.integrate import trapezoid
from scipy.ndimage import median_filter
from scipy.signal import savgol_filter

from core.baseline import asls_baseline


class ProcessingError(ValueError):
    """An operation or spectrum is invalid for local processing."""


MAX_POINTS = 1_000_000
DEFAULTS = {
    'baseline': {'lam': 1e6, 'p': 0.01, 'iterations': 10},
    'smooth': {'window': 11, 'poly_order': 3},
    'despike': {'window': 11, 'threshold': 6.0, 'max_width': 3,
                'positive_only': True, 'iterations': 1},
    'normalize': {'method': 'max'},
    'derivative': {'order': 1, 'window': 11, 'poly_order': 3},
    'convert_y': {'target': None},
    'crop': {'min': None, 'max': None},
    'resample': {'step': None},
    'shift': {'x': 0.0, 'y': 0.0},
    'interpolate': {'min': None, 'max': None},
}


def _number(value, name, low=-1e12, high=1e12, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessingError(f'{name} must be a finite number.')
    if integer and (not isinstance(value, int)):
        raise ProcessingError(f'{name} must be an integer.')
    if not low <= value <= high:
        raise ProcessingError(f'{name} must be between {low:g} and {high:g}.')
    if not math.isfinite(value):
        raise ProcessingError(f'{name} must be a finite number.')
    return value


def validate_operations(operations) -> list[dict]:
    """Validate the whitelist and parameters without executing the plan."""
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ProcessingError('Provide between 1 and 100 processing operations.')
    validated = []
    for item in operations:
        if not isinstance(item, dict) or set(item) - {'op', 'params'}:
            raise ProcessingError('Each operation must contain only op and params.')
        op = item.get('op')
        if not isinstance(op, str) or op not in DEFAULTS:
            raise ProcessingError(f'Unknown processing operation: {op!r}.')
        given = item.get('params', {})
        if not isinstance(given, dict) or set(given) - set(DEFAULTS[op]):
            raise ProcessingError(f'Unknown or invalid parameters for {op}.')
        p = copy.deepcopy({**DEFAULTS[op], **given})
        if op == 'baseline':
            _number(p['lam'], 'lam', 1, 1e12)
            _number(p['p'], 'p', 1e-6, 1 - 1e-6)
            _number(p['iterations'], 'iterations', 1, 100, integer=True)
        if op in {'smooth', 'derivative', 'despike'}:
            _number(p['window'], 'window', 5 if op == 'despike' else 3, 1001, integer=True)
            if p['window'] % 2 == 0:
                raise ProcessingError('Filter window must be odd.')
        if op in {'smooth', 'derivative'}:
            _number(p['poly_order'], 'poly_order', 0, 9, integer=True)
            if p['poly_order'] >= p['window']:
                raise ProcessingError('Polynomial order must be smaller than the window.')
        if op == 'derivative':
            _number(p['order'], 'order', 1, 2, integer=True)
            if p['poly_order'] < p['order']:
                raise ProcessingError('Polynomial order must be at least the derivative order.')
        if op == 'despike':
            _number(p['threshold'], 'threshold', 0.1, 100)
            _number(p['max_width'], 'max_width', 1, 100, integer=True)
            _number(p['iterations'], 'iterations', 1, 100, integer=True)
            if not isinstance(p['positive_only'], bool):
                raise ProcessingError('positive_only must be a boolean.')
        if op == 'normalize' and (not isinstance(p['method'], str) or p['method'] not in {'max', 'vector', 'area', 'minmax'}):
            raise ProcessingError('Unknown normalization method.')
        if op == 'convert_y' and (not isinstance(p['target'], str) or p['target'] not in {'absorbance', 'transmittance_percent', 'transmittance_fraction'}):
            raise ProcessingError('Unknown conversion target.')
        if op in {'crop', 'interpolate'}:
            _number(p['min'], 'min')
            _number(p['max'], 'max')
            if p['min'] >= p['max']:
                raise ProcessingError('Range minimum must be smaller than maximum.')
        if op == 'resample':
            _number(p['step'], 'step', 1e-12, 1e12)
        if op == 'shift':
            _number(p['x'], 'x')
            _number(p['y'], 'y')
        validated.append({'op': op, 'params': p})
    return validated


def _arrays(x, y):
    try:
        xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    except (TypeError, ValueError) as error:
        raise ProcessingError('Spectrum must contain numeric arrays.') from error
    if xa.ndim != 1 or ya.ndim != 1 or len(xa) != len(ya) or not 2 <= len(xa) <= MAX_POINTS:
        raise ProcessingError('Spectrum requires equally sized X/Y arrays with 2–1,000,000 points.')
    if not np.all(np.isfinite(xa)) or not np.all(np.isfinite(ya)):
        raise ProcessingError('Spectrum values must be finite.')
    dx = np.diff(xa)
    if not (np.all(dx > 0) or np.all(dx < 0)):
        raise ProcessingError('X values must be strictly increasing or decreasing.')
    return xa.copy(), ya.copy()


def _uniform_step(x):
    dx = np.diff(x)
    if not np.allclose(dx, dx[0], rtol=1e-4, atol=abs(dx[0]) * 1e-8):
        raise ProcessingError('This operation requires equally spaced X values. Resample the spectrum first.')
    return float(dx[0])


def _filter_ready(x, window):
    delta = _uniform_step(x)
    if window > len(x):
        raise ProcessingError(f'Window {window} exceeds the {len(x)} available points; choose a smaller odd window.')
    return delta


def _derived(meta, op, unit='a.u.'):
    meta['previous_y_kind'] = meta.get('y_kind', 'intensity')
    meta['previous_y_unit'] = meta.get('y_unit', '')
    meta['y_kind'], meta['y_unit'] = 'intensity', unit
    meta['ordinate_processing'] = op


def _interpolate(x, y, mask):
    good = ~mask
    if np.count_nonzero(good) < 2:
        raise ProcessingError('Interpolation must leave at least two unmodified points.')
    # Both ends must be supported; silently extrapolating an edge spike is unsafe.
    if mask[0] or mask[-1]:
        raise ProcessingError('Interpolation range must have an unmodified neighbour on both sides.')
    ascending = x[-1] > x[0]
    xp, yp = (x[good], y[good]) if ascending else (x[good][::-1], y[good][::-1])
    result = y.copy()
    result[mask] = np.interp(x[mask], xp, yp)
    return result


def _despike(x, y, params):
    _filter_ready(x, params['window'])
    output = y.copy()
    removed = np.zeros(len(y), dtype=bool)
    for _ in range(params['iterations']):
        reference = median_filter(output, size=params['window'], mode='nearest')
        residual = output - reference
        centre = np.median(residual)
        sigma = 1.4826 * np.median(np.abs(residual - centre))
        # A flat trace with a single cosmic spike has zero MAD; retain a numerical floor.
        floor = np.finfo(float).eps * max(1.0, float(np.max(np.abs(output)))) * 32
        cut = params['threshold'] * max(float(sigma), floor)
        candidates = ((residual - centre) > cut if params['positive_only']
                      else np.abs(residual - centre) > cut)
        mask = np.zeros(len(y), dtype=bool)
        starts = np.flatnonzero(np.diff(np.r_[False, candidates, False].astype(int)) == 1)
        ends = np.flatnonzero(np.diff(np.r_[False, candidates, False].astype(int)) == -1)
        for start, end in zip(starts, ends):
            if end - start <= params['max_width'] and start > 0 and end < len(y):
                mask[start:end] = True
        if not np.any(mask):
            break
        output = _interpolate(x, output, mask)
        removed |= mask
    return output, int(np.sum(removed))


def run_operations(x, y, meta, operations) -> dict:
    """Run a fully validated sequential recipe without mutating the inputs."""
    operations = validate_operations(operations)
    x, y = _arrays(x, y)
    if not isinstance(meta, dict):
        raise ProcessingError('Spectrum metadata must be an object.')
    meta = copy.deepcopy(meta)
    details = []
    for item in operations:
        op, p = item['op'], item['params']
        detail = copy.deepcopy(item)
        if op == 'baseline':
            _uniform_step(x)
            if len(x) < 3:
                raise ProcessingError('Baseline correction needs at least three points.')
            baseline = asls_baseline(y, lam=p['lam'], p=p['p'], n_iter=p['iterations'])
            y = y - baseline
            detail['baseline'] = baseline.tolist()
            if meta.get('y_kind') == 'absorbance':
                # Subtracting an absorbance background preserves the logarithmic unit.
                meta['ordinate_processing'] = 'baseline'
            else:
                _derived(meta, 'baseline', meta.get('y_unit', 'a.u.'))
        elif op == 'smooth':
            _filter_ready(x, p['window'])
            y = savgol_filter(y, window_length=p['window'], polyorder=p['poly_order'])
        elif op == 'despike':
            y, detail['removed_count'] = _despike(x, y, p)
        elif op == 'normalize':
            method = p['method']
            if method == 'minmax':
                y = y - np.min(y)
                divisor = float(np.max(y))
            elif method == 'vector':
                divisor = float(np.linalg.norm(y))
            elif method == 'area':
                divisor = abs(float(trapezoid(y, x)))
            else:
                divisor = float(np.max(np.abs(y)))
            if not np.isfinite(divisor) or divisor <= 0:
                raise ProcessingError('Normalization requires a finite, nonzero divisor.')
            y = y / divisor
            detail['divisor'] = divisor
            _derived(meta, f'normalize:{method}')
        elif op == 'derivative':
            delta = _filter_ready(x, p['window'])
            unit = f"({meta.get('y_unit', meta.get('y_kind', 'a.u.'))})/({meta.get('x_unit', 'X')})^{p['order']}"
            y = savgol_filter(y, window_length=p['window'], polyorder=p['poly_order'],
                              deriv=p['order'], delta=delta)
            _derived(meta, f"derivative:{p['order']}", unit)
        elif op == 'convert_y':
            source, target = meta.get('y_kind'), p['target']
            known = {'absorbance', 'transmittance_percent', 'transmittance_fraction'}
            if not isinstance(source, str) or source not in known:
                raise ProcessingError('Set a known absorbance or transmittance ordinate type before conversion.')
            if source.startswith('transmittance') and np.any(y <= 0):
                raise ProcessingError('Transmittance must be strictly positive for logarithmic conversion.')
            with np.errstate(over='ignore', under='ignore', invalid='ignore', divide='ignore'):
                if source == target:
                    converted = y.copy()
                else:
                    fraction = np.power(10.0, -y) if source == 'absorbance' else (
                        y / 100.0 if source == 'transmittance_percent' else y)
                    converted = -np.log10(fraction) if target == 'absorbance' else (
                        fraction * 100.0 if target == 'transmittance_percent' else fraction)
                if not np.all(np.isfinite(converted)) or (target.startswith('transmittance') and np.any(converted <= 0)):
                    raise ProcessingError('Conversion exceeds finite positive transmittance limits.')
            y = converted
            meta['y_kind'] = target
            meta['y_unit'] = '%' if target == 'transmittance_percent' else ('fraction' if target == 'transmittance_fraction' else 'AU')
        elif op == 'crop':
            mask = (x >= p['min']) & (x <= p['max'])
            if np.count_nonzero(mask) < 2:
                raise ProcessingError('Crop must retain at least two points.')
            x, y = x[mask], y[mask]
        elif op == 'resample':
            span = abs(float(x[-1] - x[0]))
            ratio = span / p['step']
            if not np.isfinite(ratio) or ratio + 1 > MAX_POINTS:
                raise ProcessingError('Resampling exceeds the 1,000,000-point limit.')
            count = int(np.floor(ratio + min(1e-10, ratio * 1e-12))) + 1
            if count < 2:
                raise ProcessingError('Resampling step must retain at least two points.')
            direction = 1 if x[-1] > x[0] else -1
            sampled = x[0] + direction * p['step'] * np.arange(count)
            # Floating arithmetic can put the final grid point barely outside its source.
            if direction > 0:
                new_y = np.interp(sampled, x, y)
            else:
                new_y = np.interp(sampled, x[::-1], y[::-1])
            x, y = sampled, new_y
        elif op == 'shift':
            x, y = x + p['x'], y + p['y']
            if p['y'] != 0:
                _derived(meta, 'offset', meta.get('y_unit', 'a.u.'))
        elif op == 'interpolate':
            mask = (x >= p['min']) & (x <= p['max'])
            if not np.any(mask):
                raise ProcessingError('Interpolation range contains no points.')
            y = _interpolate(x, y, mask)
            detail['removed_count'] = int(np.count_nonzero(mask))
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ProcessingError(f'{op} produced nonfinite data.')
        x, y = _arrays(x, y)
        details.append(detail)
    return {'x': x.tolist(), 'y': y.tolist(), 'meta': meta, 'details': details}
