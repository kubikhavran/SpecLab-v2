"""Validated, local spectrum operations shared by manual controls and AI plans.

Plans are plain data; no generated code is evaluated. Each operation consumes
the previous operation's result. Smoothing, baseline and despiking work on
neighbouring points and accept gently varying sampling (recorded in details);
derivatives need a physical step, so nonuniform data must be resampled first.
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


# Language models sometimes write integers as 11.0; accept exactly integral floats.
_INTEGER_PARAMS = {'iterations', 'window', 'poly_order', 'order', 'max_width'}


def _number(value, name, low=-1e12, high=1e12, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessingError(f'{name} musí být konečné číslo.')
    if integer and (not isinstance(value, int)):
        raise ProcessingError(f'{name} musí být celé číslo.')
    if not low <= value <= high:
        raise ProcessingError(f'{name} musí být v rozmezí {low:g} až {high:g}.')
    if not math.isfinite(value):
        raise ProcessingError(f'{name} musí být konečné číslo.')
    return value


def validate_operations(operations) -> list[dict]:
    """Validate the whitelist and parameters without executing the plan."""
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ProcessingError('Zadej 1 až 100 operací zpracování.')
    validated = []
    for item in operations:
        if not isinstance(item, dict) or set(item) - {'op', 'params'}:
            raise ProcessingError('Každá operace smí obsahovat pouze op a params.')
        op = item.get('op')
        if not isinstance(op, str) or op not in DEFAULTS:
            raise ProcessingError(f'Neznámá operace zpracování: {op!r}.')
        given = item.get('params', {})
        if not isinstance(given, dict) or set(given) - set(DEFAULTS[op]):
            raise ProcessingError(f'Neznámé nebo neplatné parametry operace {op}.')
        p = copy.deepcopy({**DEFAULTS[op], **given})
        for key in _INTEGER_PARAMS & set(p):
            value = p[key]
            if isinstance(value, float) and math.isfinite(value) and value.is_integer():
                p[key] = int(value)
        if op == 'baseline':
            _number(p['lam'], 'lam', 1, 1e12)
            _number(p['p'], 'p', 1e-6, 1 - 1e-6)
            _number(p['iterations'], 'iterations', 1, 100, integer=True)
        if op in {'smooth', 'derivative', 'despike'}:
            _number(p['window'], 'window', 5 if op == 'despike' else 3, 1001, integer=True)
            if p['window'] % 2 == 0:
                raise ProcessingError('Okno filtru musí být liché.')
        if op in {'smooth', 'derivative'}:
            _number(p['poly_order'], 'poly_order', 0, 9, integer=True)
            if p['poly_order'] >= p['window']:
                raise ProcessingError('Řád polynomu musí být menší než okno.')
        if op == 'derivative':
            _number(p['order'], 'order', 1, 2, integer=True)
            if p['poly_order'] < p['order']:
                raise ProcessingError('Řád polynomu musí být alespoň tak vysoký jako řád derivace.')
        if op == 'despike':
            _number(p['threshold'], 'threshold', 0.1, 100)
            _number(p['max_width'], 'max_width', 1, 100, integer=True)
            _number(p['iterations'], 'iterations', 1, 100, integer=True)
            if not isinstance(p['positive_only'], bool):
                raise ProcessingError('positive_only musí být logická hodnota.')
        if op == 'normalize' and (not isinstance(p['method'], str) or p['method'] not in {'max', 'vector', 'area', 'minmax'}):
            raise ProcessingError('Neznámá metoda normalizace.')
        if op == 'convert_y' and (not isinstance(p['target'], str) or p['target'] not in {'absorbance', 'transmittance_percent', 'transmittance_fraction'}):
            raise ProcessingError('Neznámý cíl převodu.')
        if op in {'crop', 'interpolate'}:
            _number(p['min'], 'min')
            _number(p['max'], 'max')
            if p['min'] >= p['max']:
                raise ProcessingError('Minimum rozsahu musí být menší než maximum.')
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
        raise ProcessingError('Spektrum musí obsahovat číselná pole.') from error
    if xa.ndim != 1 or ya.ndim != 1 or len(xa) != len(ya) or not 2 <= len(xa) <= MAX_POINTS:
        raise ProcessingError('Spektrum musí mít stejně dlouhá pole X/Y s 2 až 1 000 000 body.')
    if not np.all(np.isfinite(xa)) or not np.all(np.isfinite(ya)):
        raise ProcessingError('Hodnoty spektra musí být konečné.')
    dx = np.diff(xa)
    if not (np.all(dx > 0) or np.all(dx < 0)):
        raise ProcessingError('Hodnoty X musí být přísně vzestupné nebo sestupné.')
    return xa.copy(), ya.copy()


# Detector-based axes (e.g. Raman CCD pixels converted to cm⁻¹) are monotonic but
# not exactly equidistant. Point-domain filters are acceptable there, but not across
# real gaps where neighbouring samples are far apart in X.
MAX_INDEX_STEP_RATIO = 3.0


def _is_uniform(x) -> bool:
    dx = np.diff(x)
    return bool(np.allclose(dx, dx[0], rtol=1e-4, atol=abs(dx[0]) * 1e-8))


def _uniform_step(x):
    if not _is_uniform(x):
        raise ProcessingError('Tato operace vyžaduje rovnoměrně rozložené hodnoty X. Nejprve spektrum převzorkuj.')
    return float(np.diff(x)[0])


def _point_domain_ready(x, detail):
    """Allow point-domain filters on gently varying sampling; reject gaps."""
    if _is_uniform(x):
        detail['sampling'] = 'uniform'
        return
    step = np.abs(np.diff(x))
    # The median of two steps is their mean, which would hide a gap.
    typical = np.median(step) if len(step) >= 3 else np.min(step)
    ratio = float(np.max(step) / typical)
    if ratio > MAX_INDEX_STEP_RATIO:
        raise ProcessingError(
            f'V rozložení hodnot X je mezera ({ratio:.1f}× obvyklý krok). '
            'Mezeru ořízni nebo spektrum nejprve převzorkuj.')
    detail['sampling'] = 'point_index'
    detail['max_step_ratio'] = ratio


def _filter_ready(x, window, detail=None):
    if detail is None:
        delta = _uniform_step(x)
    else:
        _point_domain_ready(x, detail)
        delta = None
    if window > len(x):
        raise ProcessingError(f'Okno {window} přesahuje {len(x)} dostupných bodů; zvol menší liché okno.')
    return delta


def _derived(meta, op, unit='a.u.'):
    meta['previous_y_kind'] = meta.get('y_kind', 'intensity')
    meta['previous_y_unit'] = meta.get('y_unit', '')
    meta['y_kind'], meta['y_unit'] = 'intensity', unit
    meta['ordinate_processing'] = op


def _interpolate(x, y, mask):
    good = ~mask
    if np.count_nonzero(good) < 2:
        raise ProcessingError('Po interpolaci musí zůstat alespoň dva nezměněné body.')
    # Both ends must be supported; silently extrapolating an edge spike is unsafe.
    if mask[0] or mask[-1]:
        raise ProcessingError('Rozsah interpolace musí mít z obou stran nezměněného souseda.')
    ascending = x[-1] > x[0]
    xp, yp = (x[good], y[good]) if ascending else (x[good][::-1], y[good][::-1])
    result = y.copy()
    result[mask] = np.interp(x[mask], xp, yp)
    return result


def _despike(x, y, params, detail):
    _filter_ready(x, params['window'], detail)
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
        raise ProcessingError('Metadata spektra musí být objekt.')
    meta = copy.deepcopy(meta)
    details = []
    for item in operations:
        op, p = item['op'], item['params']
        detail = copy.deepcopy(item)
        if op == 'baseline':
            # AsLS penalises second differences between neighbouring points.
            _point_domain_ready(x, detail)
            if len(x) < 3:
                raise ProcessingError('Korekce baseline vyžaduje alespoň tři body.')
            baseline = asls_baseline(y, lam=p['lam'], p=p['p'], n_iter=p['iterations'])
            y = y - baseline
            detail['baseline'] = baseline.tolist()
            if meta.get('y_kind') == 'absorbance':
                # Subtracting an absorbance background preserves the logarithmic unit.
                meta['ordinate_processing'] = 'baseline'
            else:
                _derived(meta, 'baseline', meta.get('y_unit', 'a.u.'))
        elif op == 'smooth':
            _filter_ready(x, p['window'], detail)
            y = savgol_filter(y, window_length=p['window'], polyorder=p['poly_order'])
        elif op == 'despike':
            y, detail['removed_count'] = _despike(x, y, p, detail)
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
                raise ProcessingError('Normalizace vyžaduje konečný, nenulový dělitel.')
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
                raise ProcessingError('Před převodem nastav známý typ ordináty: absorbanci nebo transmitanci.')
            if source.startswith('transmittance') and np.any(y <= 0):
                raise ProcessingError('Transmitance musí být pro logaritmický převod přísně kladná.')
            with np.errstate(over='ignore', under='ignore', invalid='ignore', divide='ignore'):
                if source == target:
                    converted = y.copy()
                else:
                    fraction = np.power(10.0, -y) if source == 'absorbance' else (
                        y / 100.0 if source == 'transmittance_percent' else y)
                    converted = -np.log10(fraction) if target == 'absorbance' else (
                        fraction * 100.0 if target == 'transmittance_percent' else fraction)
                if not np.all(np.isfinite(converted)) or (target.startswith('transmittance') and np.any(converted <= 0)):
                    raise ProcessingError('Výsledek převodu překračuje konečné kladné hodnoty transmitance.')
            y = converted
            meta['y_kind'] = target
            meta['y_unit'] = '%' if target == 'transmittance_percent' else ('fraction' if target == 'transmittance_fraction' else 'AU')
        elif op == 'crop':
            mask = (x >= p['min']) & (x <= p['max'])
            if np.count_nonzero(mask) < 2:
                raise ProcessingError('Po oříznutí musí zůstat alespoň dva body.')
            x, y = x[mask], y[mask]
        elif op == 'resample':
            span = abs(float(x[-1] - x[0]))
            ratio = span / p['step']
            if not np.isfinite(ratio) or ratio + 1 > MAX_POINTS:
                raise ProcessingError('Převzorkování překračuje limit 1 000 000 bodů.')
            count = int(np.floor(ratio + min(1e-10, ratio * 1e-12))) + 1
            if count < 2:
                raise ProcessingError('Krok převzorkování musí zachovat alespoň dva body.')
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
                raise ProcessingError('Rozsah interpolace neobsahuje žádné body.')
            y = _interpolate(x, y, mask)
            detail['removed_count'] = int(np.count_nonzero(mask))
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ProcessingError(f'Operace {op} vytvořila nekonečná nebo nečíselná data.')
        x, y = _arrays(x, y)
        details.append(detail)
    return {'x': x.tolist(), 'y': y.tolist(), 'meta': meta, 'details': details}
