"""Versioned, atomic project files; credentials and runtime undo stacks are excluded."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from app.models import (BaselineSettings, CosmicSettings, GraphicsSettings, Peak,
                        PeaksSettings, PlotSettings, SPECTRAL_MODES, SmoothingSettings,
                        Spectrum)

SCHEMA = 'speclab.project'
VERSION = 1
MAX_SPECTRA = 1000
MAX_TOTAL_POINTS = 10_000_000
MAX_PROJECT_BYTES = 256 * 1024 * 1024
SETTINGS = {
    'plot': ('_plot', PlotSettings), 'graphics': ('_graphics', GraphicsSettings),
    'baseline': ('_baseline', BaselineSettings), 'smoothing': ('_smoothing', SmoothingSettings),
    'cosmic': ('_cosmic', CosmicSettings), 'peaks': ('_peaks', PeaksSettings),
}


def _safe_json(value):
    """Project metadata can hold vendor fields, but never credential fields."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('Klíče metadat projektu musí být textové řetězce.')
            normalized = key.lower().replace('-', '_')
            if any(part in normalized for part in ('password', 'secret', 'token', 'authorization', 'api_key', 'apikey')):
                continue
            result[key] = _safe_json(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError('Projekt obsahuje metadata, která nelze uložit jako konečný JSON.')


def settings_from_dict(cls, data: dict):
    """Validate project and preset settings before touching application state."""
    if not isinstance(data, dict):
        raise ValueError('Nastavení musí být objekt.')
    instance = cls()
    allowed = {field.name for field in fields(cls)}
    if set(data) - allowed:
        raise ValueError(f'Neznámé položky nastavení {cls.__name__}: {", ".join(sorted(set(data) - allowed))}')
    for key, value in data.items():
        default = getattr(instance, key)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, float) or default is None:
            valid = value is None if default is None and value is None else (
                isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            )
        else:
            valid = isinstance(value, str) and len(value) <= 1024
        if not valid:
            raise ValueError(f'Neplatná hodnota pro {cls.__name__}.{key}.')
        if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) > 1e12:
            raise ValueError(f'Nastavení {key} překračuje povolený rozsah.')
        setattr(instance, key, value)
    for key in ('axis_line_color','grid_color','label_color','leader_color'):
        if hasattr(instance,key) and not re.fullmatch(r'#[0-9a-fA-F]{6}',getattr(instance,key)):
            raise ValueError(f'Barva {key} musí mít tvar #RRGGBB.')
    enums = {
        'mode': {'active', 'all'}, 'source': {'displayed', 'processed'},
        'polarity': {'max', 'min', 'both'}, 'label_color_mode': {'trace', 'custom'},
        'leader_color_mode': {'trace', 'custom'}, 'frame_mode': {'open', 'box'},
        'plot_canvas': {'auto', 'white', 'dark'},
        'scale_mode': {'common', 'full'},
    }
    for key, options in enums.items():
        if hasattr(instance, key) and getattr(instance, key) not in options:
            raise ValueError(f'Neplatné nastavení {key}.')
    ranges = {
        'lambda_': (1, 1e12), 'p': (1e-6, 1 - 1e-6), 'iterations': (1, 100),
        'window': (3, 1001), 'poly_order': (0, 9), 'threshold': (0.1, 100),
        'max_width': (1, 100), 'min_prominence': (0, 1e12), 'min_distance': (0, 1e12),
        'max_peaks': (1, 10000), 'decimals': (0, 10), 'label_font_size': (1, 300),
        'base_font_size': (1, 300), 'tick_font_size': (1, 300), 'trace_line_width': (1, 100),
        'grid_width': (1, 100), 'axis_line_width': (1, 100), 'leader_line_width': (1, 100),
        'export_width': (100, 20000), 'export_height': (100, 20000),
    }
    for key, (low, high) in ranges.items():
        if hasattr(instance, key) and not low <= getattr(instance, key) <= high:
            raise ValueError(f'Nastavení {key} musí být v rozmezí {low} až {high}.')
    if isinstance(instance, SmoothingSettings) and instance.poly_order >= instance.window:
        raise ValueError('Řád polynomu musí být menší než okno vyhlazení.')
    if hasattr(instance, 'window') and instance.window % 2 == 0:
        raise ValueError('Okna filtrů musí být lichá.')
    if isinstance(instance, (PlotSettings, PeaksSettings)):
        pairs = [(instance.x_min, instance.x_max)]
        if isinstance(instance, PlotSettings):
            pairs.append((instance.y_min, instance.y_max))
        for lower, upper in pairs:
            if lower is not None and upper is not None and lower >= upper:
                raise ValueError('Meze grafu musí být vzestupné.')
    return instance


def _peak_from_dict(data: dict) -> Peak:
    if not isinstance(data, dict) or set(data) - {f.name for f in fields(Peak)}:
        raise ValueError('Neplatný záznam píku.')
    peak = Peak(**data)
    if not isinstance(peak.id, str) or not peak.id or len(peak.id) > 200:
        raise ValueError('Neplatné ID píku.')
    if not isinstance(peak.source, str) or not isinstance(peak.kind, str) or peak.source not in {'auto', 'manual'} or peak.kind not in {'max', 'min'}:
        raise ValueError('Neplatný zdroj nebo polarita píku.')
    for name in ('x', 'prominence', 'width'):
        value = getattr(peak, name)
        if value is None and name != 'x':
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Souřadnice a vlastnosti píku musí být konečné.')
    if peak.i is not None and (not isinstance(peak.i, int) or isinstance(peak.i, bool) or peak.i < 0):
        raise ValueError('Neplatný index píku.')
    if peak.label is not None and (not isinstance(peak.label, str) or len(peak.label) > 1000):
        raise ValueError('Neplatný popisek píku.')
    return peak


def save_project(state, path) -> None:
    if len(state.spectra) > MAX_SPECTRA:
        raise ValueError('Projekt podporuje nejvýše 1 000 spekter.')
    settings = {key: asdict(getattr(state, attr)) for key, (attr, _) in SETTINGS.items()}
    for key, (_, cls) in SETTINGS.items():
        settings_from_dict(cls, settings[key])
    spectra = []
    total = 0
    for spec in state.spectra:
        state._validate_data(spec.x, state.displayed_y(spec.id))
        state._validate_data(state._original[spec.id]['x'], state._original[spec.id]['y'])
        state._validated_metadata(spec.meta)
        state._validated_metadata(state._original[spec.id]['meta'])
        total += len(spec.x) + len(state._original[spec.id]['x'])
        if total > MAX_TOTAL_POINTS:
            raise ValueError('Projekt obsahuje příliš mnoho spektrálních bodů.')
        spectra.append({
            'id': spec.id, 'name': spec.name,
            'current': {'x': list(spec.x), 'y': list(state.displayed_y(spec.id)), 'meta': _safe_json(spec.meta)},
            'original': _safe_json(state._original[spec.id]),
            'recipe': state.processing_recipe(spec.id),
            'peaks_auto': [asdict(p) for p in state.peaks_auto.get(spec.id, [])],
            'peaks_manual': [asdict(p) for p in state.peaks_manual.get(spec.id, [])],
            'baseline_overlay': list(state.baseline_y.get(spec.id, [])),
        })
    document = {
        'schema': SCHEMA, 'version': VERSION, 'spectra': spectra,
        'active_spectrum_id': state.active_spectrum_id, 'spectral_mode': state.spectral_mode,
        'settings': settings,
        'provenance': _safe_json(state.history),
        'undo_persisted': False,
    }
    target = Path(path)
    # Serialize before opening a temporary file so invalid metadata never replaces a project.
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_PROJECT_BYTES:
        raise ValueError('Projekt překračuje limit 256 MB.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                         prefix=f'.{target.name}.', suffix='.tmp', delete=False) as output:
            temporary = output.name
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_project(state, path) -> None:
    from core.processing import validate_operations

    target = Path(path)
    if target.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError('Projekt překračuje limit 256 MB.')
    try:
        with target.open(encoding='utf-8') as handle:
            document = json.load(handle, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nekonečná nebo nečíselná hodnota JSON.')))
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Neplatný JSON projektu SpecLab.') from error
    if not isinstance(document, dict) or document.get('schema') != SCHEMA or document.get('version') != VERSION:
        raise ValueError('Nepodporované schéma nebo verze projektu SpecLab.')
    if document.get('undo_persisted') is not False:
        raise ValueError('Nepodporovaný formát historie změn projektu.')
    entries = document.get('spectra')
    if not isinstance(entries, list) or len(entries) > MAX_SPECTRA:
        raise ValueError('Neplatný seznam spekter projektu.')
    spectra, original, recipes, auto, manual, overlays = [], {}, {}, {}, {}, {}
    ids = set()
    total = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError('Neplatné spektrum projektu.')
        sid, name = item.get('id'), item.get('name')
        if not isinstance(sid, str) or not sid or len(sid) > 200 or sid in ids:
            raise ValueError('Duplicitní nebo neplatné ID spektra.')
        if not isinstance(name, str) or len(name) > 1000:
            raise ValueError('Neplatný název spektra.')
        ids.add(sid)
        current, raw = item.get('current'), item.get('original')
        for data in (current, raw):
            if not isinstance(data, dict) or not isinstance(data.get('x'), list) or not isinstance(data.get('y'), list):
                raise ValueError('Neplatná pole spektra projektu.')
            state._validate_data(data['x'], data['y'])
            total += len(data['x'])
            if total > MAX_TOTAL_POINTS:
                raise ValueError('Projekt obsahuje příliš mnoho spektrálních bodů.')
            data['meta'] = state._validated_metadata(_safe_json(data.get('meta', {})))
        spectra.append(Spectrum(id=sid, name=name, x=list(current['x']), y=list(current['y']), meta=current['meta']))
        original[sid] = raw
        recipe = item.get('recipe', [])
        recipes[sid] = validate_operations(recipe) if recipe else []
        overlay = item.get('baseline_overlay', [])
        if not isinstance(overlay, list):
            raise ValueError('Neplatné překrytí baseline.')
        if overlay:
            state._validate_data(current['x'], overlay)
            overlays[sid] = overlay
        for key, store in (('peaks_auto', auto), ('peaks_manual', manual)):
            peak_data = item.get(key, [])
            if not isinstance(peak_data, list) or len(peak_data) > 10000:
                raise ValueError('Neplatný seznam píků projektu.')
            parsed = [_peak_from_dict(p) for p in peak_data]
            if any(p.source != ('auto' if key == 'peaks_auto' else 'manual') for p in parsed):
                raise ValueError('Zdroj píku neodpovídá jeho kolekci v projektu.')
            if any(p.i is not None and p.i >= len(current['x']) for p in parsed):
                raise ValueError('Index píku překračuje délku aktuálního spektra.')
            store[sid] = parsed
    active = document.get('active_spectrum_id')
    if active is not None and active not in ids:
        raise ValueError('Výběr projektu odkazuje na chybějící spektrum.')
    mode = document.get('spectral_mode', 'custom')
    if mode not in SPECTRAL_MODES:
        raise ValueError('Neznámý spektrální režim projektu.')
    settings = document.get('settings', {})
    if not isinstance(settings, dict) or set(settings) - set(SETTINGS):
        raise ValueError('Neplatné nastavení projektu.')
    parsed_settings = {attr: settings_from_dict(cls, settings.get(key, {}))
                       for key, (attr, cls) in SETTINGS.items()}
    provenance = document.get('provenance', [])
    if not isinstance(provenance, list) or len(provenance) > 10000 or any(not isinstance(p, dict) for p in provenance):
        raise ValueError('Neplatné záznamy historie projektu.')
    provenance = _safe_json(provenance)[-200:]
    # No signals or mutations happen above this point. Commit the fully validated file once.
    state._spectra, state._original, state._recipes = spectra, original, recipes
    state._active_spectrum_id, state._spectral_mode = active, mode
    state.peaks_auto, state.peaks_manual = auto, manual
    for attr, setting in parsed_settings.items():
        setattr(state, attr, setting)
    for cache in (state.cosmic_clean_y, state.processed_y, state.baseline_y, state.smoothed_y):
        cache.clear()
    state.baseline_y.update(overlays)
    state._history = copy.deepcopy(provenance)
    state._undo_stack.clear()
    state._redo_stack.clear()
    state._invalidate()
    state._emit_workspace_changed()
