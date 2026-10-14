"""Validated preset recipes and migration of the original SpecLab JSON format."""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
import uuid

from app.models import SPECTRAL_MODES
from core.processing import validate_operations
from core.project_io import SETTINGS, settings_from_dict

PRESETS_FILENAME = 'speclab_presets.json'
_SECTIONS = set(SETTINGS)
_PAYLOAD_KEYS = _SECTIONS | {'spectral_mode', 'pipeline', 'migration'}
_PIPELINE_KEYS = {
    'operations', 'recipe_scope', 'source_spectrum_name', 'from_original',
    'auto_peaks_applied', 'cosmic_applied', 'baseline_applied', 'smoothing_applied', 'raw_only',
}


def _get_presets_path() -> str:
    directory = Path.home() / '.speclab'
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / PRESETS_FILENAME)


def _string(value, label, limit=1024):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{label} musí být text o délce nejvýše {limit} znaků.')
    return value


def _timestamp(value, label):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f'{label} musí být konečná hodnota.')
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f'Neplatná hodnota {label}.') from error
    text = _string(value, label, 100)
    try:
        datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(f'Neplatná hodnota {label}.') from error
    return text


def _snake(key):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()


def _validate_pipeline(pipeline):
    if not isinstance(pipeline, dict) or set(pipeline) - _PIPELINE_KEYS:
        raise ValueError('Preset obsahuje neplatné nebo neznámé pole pipeline.')
    result = copy.deepcopy(pipeline)
    for key in ('from_original', 'auto_peaks_applied', 'cosmic_applied',
                'baseline_applied', 'smoothing_applied', 'raw_only'):
        if key in result and not isinstance(result[key], bool):
            raise ValueError(f'Pipeline {key} musí být logická hodnota.')
    if 'operations' in result:
        operations = result['operations']
        if not isinstance(operations, list):
            raise ValueError('Operace presetu musí být seznam.')
        result['operations'] = validate_operations(operations) if operations else []
    if 'recipe_scope' in result and result['recipe_scope'] not in {'active_spectrum', 'all'}:
        raise ValueError('Neplatný rozsah receptu presetu.')
    if result.get('source_spectrum_name') is not None:
        _string(result['source_spectrum_name'], 'Název zdrojového spektra')
    if result.get('raw_only') and any(result.get(k) for k in
                                      ('operations', 'cosmic_applied', 'baseline_applied', 'smoothing_applied')):
        raise ValueError('Preset pouze s původními daty nemůže obsahovat také kroky zpracování.')
    return result


def _validate_labeling(value):
    """Retain unsupported v1 naming settings for reference, never silently discard."""
    if not isinstance(value, dict):
        raise ValueError('Starší dataLabeling musí být objekt.')
    enums = {'renumberMode': {'index', 'sequence', 'extract'}}
    strings = {'renumberPrefix', 'sequenceStart', 'sequenceStep', 'sequenceSuffix'}
    allowed = set(enums) | strings | {'invertOrder', 'labelExtract'}
    if set(value) - allowed:
        raise ValueError('Neznámé starší nastavení dataLabeling.')
    for key, item in value.items():
        if key in enums:
            if not isinstance(item, str) or item not in enums[key]:
                raise ValueError(f'Neplatná hodnota dataLabeling.{key}.')
        elif key in strings:
            _string(item, f'dataLabeling.{key}')
        elif key == 'invertOrder' and not isinstance(item, bool):
            raise ValueError('dataLabeling.invertOrder musí být logická hodnota.')
        elif key == 'labelExtract':
            if not isinstance(item, dict):
                raise ValueError('labelExtract musí být objekt.')
            text_keys = {'start', 'end', 'prefix', 'suffix', 'regex'}
            bool_keys = {'trimResult', 'numbersOnly'}
            if set(item) - (text_keys | bool_keys | {'mode', 'preset'}):
                raise ValueError('Neznámé starší nastavení labelExtract.')
            for k, v in item.items():
                if k in text_keys:
                    _string(v, f'labelExtract.{k}')
                elif k in bool_keys and not isinstance(v, bool):
                    raise ValueError(f'labelExtract.{k} musí být logická hodnota.')
                elif k == 'mode' and v not in ('none', 'filename'):
                    raise ValueError('Neplatný režim labelExtract.')
                elif k == 'preset' and v not in ('mv', 'firstNumber', 'lastNumber', 'regex', 'slice'):
                    raise ValueError('Neplatný preset labelExtract.')
    return copy.deepcopy(value)


def _region_bound(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} musí být číselná hodnota zadaná jako text.')
    if not value.strip():
        return None
    try:
        number = float(value.replace(',', '.'))
    except ValueError as error:
        raise ValueError(f'Neplatná hodnota {label}.') from error
    if not math.isfinite(number):
        raise ValueError(f'{label} musí být konečná hodnota.')
    return number


def _migrate_v1(payload):
    if not isinstance(payload, dict):
        raise ValueError('Obsah staršího presetu musí být objekt.')
    allowed = {'themeMode', 'plot', 'graphics', 'baseline', 'smoothing',
               'cosmic', 'dataLabeling', 'peaksSettings'}
    if set(payload) - allowed:
        raise ValueError('Neznámé pole původního presetu SpecLab.')
    result, warnings, migration = {}, [], {'source_format': 'SpecLab-v1'}
    for section in ('plot', 'graphics', 'baseline', 'smoothing', 'cosmic', 'peaksSettings'):
        value = payload.get(section, {})
        if not isinstance(value, dict):
            raise ValueError(f'Starší sekce {section} musí být objekt.')
        target = 'peaks' if section == 'peaksSettings' else section
        names = {field.name for field in fields(SETTINGS[target][1])}
        mapped = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('Názvy nastavení presetu musí být textové řetězce.')
            if key == 'uiRevision' and section == 'plot':
                if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                    raise ValueError('Neplatná hodnota staršího plot.uiRevision.')
                continue  # A rendering counter is regenerated by the new canvas.
            if section == 'peaksSettings' and key == 'labelPlacement':
                if item != 'leader':
                    raise ValueError('Umístění popisků píků ve starším formátu není podporováno.')
                continue
            overrides = {'lambda': 'lambda_', 'useRegion': 'region_enabled',
                         'regionXMin': 'x_min', 'regionXMax': 'x_max'}
            name = overrides.get(key, _snake(key))
            if name not in names:
                raise ValueError(f'Starší nastavení {section}.{key} není podporováno.')
            mapped[name] = (_region_bound(item, key) if key in {'regionXMin', 'regionXMax'} else item)
        # Original TypeScript defaults differed from the older Python defaults.
        if target == 'peaks':
            mapped.setdefault('min_prominence', 0.0)
        result[target] = asdict(settings_from_dict(SETTINGS[target][1], mapped))
    if 'themeMode' in payload:
        theme = payload['themeMode']
        if not isinstance(theme, str) or theme not in {'system', 'light', 'dark'}:
            raise ValueError('Neplatné téma rozhraní ve starším formátu.')
        migration['theme_mode'] = theme
        warnings.append('The original interface theme is retained for reference; choose the global theme in Appearance.')
    if 'dataLabeling' in payload:
        migration['legacy_data_labeling'] = _validate_labeling(payload['dataLabeling'])
        warnings.append('Original automatic naming settings are retained for reference; apply naming with the spectrum tools.')
    # v1 never recorded whether cosmic removal or smoothing was applied.
    # Reconstruct only a stage whose activation can be established.
    baseline = result['baseline']
    recipe = []
    if baseline['enabled']:
        recipe.append({'op': 'baseline', 'params': {'lam': baseline['lambda_'],
                       'p': baseline['p'], 'iterations': baseline['iterations']}})
    result['pipeline'] = {'operations': recipe, 'from_original': True,
                          'auto_peaks_applied': False, 'recipe_scope': 'all'}
    warnings.append('V1 did not record the processing history. Only an enabled baseline is recovered; cosmic removal, smoothing and automatic peaks must be applied explicitly.')
    if result['peaks'].get('region_enabled'):
        plot = result['plot']
        if plot.get('x_min') is not None and plot.get('x_max') is not None:
            result['peaks']['x_min'], result['peaks']['x_max'] = plot['x_min'], plot['x_max']
    result['migration'] = migration
    return result, warnings


def normalize_preset_payload(payload, legacy=False):
    """Fully validate before importing or mutating a workspace."""
    if not isinstance(payload, dict):
        raise ValueError('Obsah presetu musí být objekt.')
    warnings = []
    if legacy or any(key in payload for key in ('themeMode', 'dataLabeling', 'peaksSettings')):
        payload, warnings = _migrate_v1(payload)
    if set(payload) - _PAYLOAD_KEYS:
        raise ValueError(f'Neznámá pole presetu: {", ".join(sorted(set(payload) - _PAYLOAD_KEYS))}.')
    result = {}
    for key in _SECTIONS:
        if key in payload:
            result[key] = asdict(settings_from_dict(SETTINGS[key][1], payload[key]))
    if 'spectral_mode' in payload:
        mode = payload['spectral_mode']
        if not isinstance(mode, str) or mode not in SPECTRAL_MODES:
            raise ValueError('Neznámý spektrální režim presetu.')
        result['spectral_mode'] = mode
    if 'pipeline' in payload:
        result['pipeline'] = _validate_pipeline(payload['pipeline'])
    if 'migration' in payload:
        migration = payload['migration']
        if not isinstance(migration, dict):
            raise ValueError('Poznámky k migraci presetu musí být objekt.')
        # Only known inert migration data can pass through export/import.
        if set(migration) - {'source_format', 'theme_mode', 'legacy_data_labeling'}:
            raise ValueError('Neznámé informace o migraci presetu.')
        if 'legacy_data_labeling' in migration:
            _validate_labeling(migration['legacy_data_labeling'])
        if 'source_format' in migration:
            _string(migration['source_format'], 'Zdroj migrace', 100)
        if 'theme_mode' in migration and migration['theme_mode'] not in {'system', 'light', 'dark'}:
            raise ValueError('Neplatné téma při migraci.')
        result['migration'] = copy.deepcopy(migration)
    return result, warnings


class Preset:
    """A validated named snapshot, with visible notices for legacy migration."""

    def __init__(self, name, preset_id=None, created_at=None, updated_at=None,
                 payload=None, warnings=None):
        self.name = _string(name, 'Název presetu', 200).strip()
        if not self.name:
            raise ValueError('Název presetu nesmí být prázdný.')
        self.id = uuid.uuid4().hex if preset_id is None else _string(preset_id, 'ID presetu', 200)
        if not self.id:
            raise ValueError('ID presetu nesmí být prázdné.')
        self.created_at = _timestamp(created_at, 'Čas vytvoření')
        self.updated_at = _timestamp(updated_at, 'Čas aktualizace') if updated_at is not None else self.created_at
        self.payload, migration_warnings = normalize_preset_payload({} if payload is None else payload)
        if warnings is not None and (not isinstance(warnings, list) or
                                     any(not isinstance(w, str) or len(w) > 2000 for w in warnings)):
            raise ValueError('Upozornění presetu musí být seznam krátkých textů.')
        self.warnings = list(dict.fromkeys((warnings or []) + migration_warnings))

    def to_dict(self):
        # Revalidate mutable presets before they are persisted/exported.
        payload, notices = normalize_preset_payload(self.payload)
        return {'id': self.id, 'name': _string(self.name, 'Název presetu', 200),
                'created_at': _timestamp(self.created_at, 'Čas vytvoření'),
                'updated_at': _timestamp(self.updated_at, 'Čas aktualizace'), 'payload': payload,
                'warnings': list(dict.fromkeys(self.warnings + notices))}

    @classmethod
    def from_dict(cls, data, legacy=False):
        if not isinstance(data, dict):
            raise ValueError('Každý preset musí být objekt.')
        allowed = {'id', 'name', 'payload', 'created_at', 'updated_at', 'createdAt', 'updatedAt', 'warnings'}
        if set(data) - allowed or 'name' not in data or 'payload' not in data:
            raise ValueError('Neplatný záznam presetu; název a obsah jsou povinné.')
        payload, notices = normalize_preset_payload(data['payload'], legacy)
        warnings = data.get('warnings', [])
        if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
            raise ValueError('Upozornění presetu musí být textové řetězce.')
        return cls(data['name'], data.get('id'), data.get('created_at', data.get('createdAt')),
                   data.get('updated_at', data.get('updatedAt')), payload, warnings + notices)


def capture_preset_payload(state):
    active = state.active_spectrum
    return {
        'spectral_mode': state.spectral_mode,
        **{key: asdict(getattr(state, attribute)) for key, (attribute, _) in SETTINGS.items()},
        'pipeline': {
            'operations': state.processing_recipe(active.id) if active else [],
            'recipe_scope': 'active_spectrum', 'source_spectrum_name': active.name if active else None,
            'auto_peaks_applied': bool(state.peaks_auto.get(active.id)) if active else False,
            'from_original': True,
        },
    }


def apply_preset_payload(state, payload, apply_recipe=True):
    """Settings-only never changes data; recipe replay is explicit and atomic."""
    payload, _ = normalize_preset_payload(payload)
    settings = {key: payload[key] for key in _SECTIONS if key in payload}
    if 'spectral_mode' in payload:
        settings['spectral_mode'] = payload['spectral_mode']
    recipe, detect_auto = None, False
    if apply_recipe:
        pipeline = payload.get('pipeline', {})
        if 'operations' in pipeline:
            recipe = pipeline['operations']
        elif pipeline:
            recipe = []
            c = settings_from_dict(SETTINGS['cosmic'][1], settings.get('cosmic', {}))
            b = settings_from_dict(SETTINGS['baseline'][1], settings.get('baseline', {}))
            s = settings_from_dict(SETTINGS['smoothing'][1], settings.get('smoothing', {}))
            if pipeline.get('cosmic_applied'):
                recipe.append({'op': 'despike', 'params': {'window': c.window, 'threshold': c.threshold,
                               'max_width': c.max_width, 'positive_only': c.positive_only, 'iterations': c.iterations}})
            if pipeline.get('baseline_applied', b.enabled):
                recipe.append({'op': 'baseline', 'params': {'lam': b.lambda_, 'p': b.p, 'iterations': b.iterations}})
            if pipeline.get('smoothing_applied'):
                recipe.append({'op': 'smooth', 'params': {'window': s.window, 'poly_order': s.poly_order}})
        elif settings.get('baseline', {}).get('enabled'):
            b = settings['baseline']
            recipe = [{'op': 'baseline', 'params': {'lam': b['lambda_'], 'p': b['p'], 'iterations': b['iterations']}}]
        detect_auto = bool(pipeline.get('auto_peaks_applied', False))
    return state.apply_preset(settings, recipe=recipe, detect_auto=detect_auto)


def _read_presets(path):
    target = Path(path)
    if target.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('Soubor presetů překračuje limit 10 MB.')
    with target.open(encoding='utf-8') as handle:
        document = json.load(handle, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nekonečná nebo nečíselná hodnota JSON presetu.')))
    legacy = False
    if isinstance(document, dict):
        version = document.get('schemaVersion')
        if type(version) is not int or version not in {1, 2} or document.get('app') != 'SpecLab':
            raise ValueError('Nepodporované schéma presetů nebo aplikace SpecLab.')
        entries, legacy = document.get('presets'), version == 1
    else:
        entries = document  # Previous Python versions used a plain JSON list.
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError('Soubor presetů musí obsahovat seznam nejvýše 1 000 presetů.')
    presets, ids = [], set()
    for index, item in enumerate(entries):
        try:
            preset = Preset.from_dict(item, legacy=legacy)
        except (ValueError, TypeError) as error:
            raise ValueError(f'Preset č. {index + 1}: {error}') from error
        if preset.id in ids:
            raise ValueError('Soubor presetů obsahuje duplicitní ID.')
        ids.add(preset.id)
        presets.append(preset)
    return presets


def load_presets():
    path = Path(_get_presets_path())
    return _read_presets(path) if path.exists() else []


def _write_presets(presets, filepath):
    entries = [preset.to_dict() for preset in presets]
    document = {'schemaVersion': 2, 'app': 'SpecLab',
                'exportedAt': datetime.now(timezone.utc).isoformat(), 'presets': entries}
    encoded = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False)
    target = Path(filepath)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                         prefix=f'.{target.name}.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_presets(presets):
    _write_presets(presets, _get_presets_path())


def export_presets_to_file(presets, filepath):
    _write_presets(presets, filepath)


def import_presets_from_file(filepath):
    return _read_presets(filepath)
