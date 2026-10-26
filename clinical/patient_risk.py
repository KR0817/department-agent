"""Synthetic-only Cox demonstration; business patients have no clinical model."""
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import re

MODEL_PATH = Path(__file__).resolve().parent / 'fixtures' / 'risk-models-v1.json'
MODEL_SHA256 = '91c0a6fda21e4a88c2ac2b41001e6aa216d7bd3540aa05a0ad3aa3023d99f45d'
MODEL_VERSION = 'synthetic-cox-v1-20261025'
CODES = ('igg', 'c3', 'dryness', 'fatigue')
ENDPOINTS = ('activity_worsening', 'infection')
HORIZONS = (90, 180, 365)


def _base(status, mode):
    return {'schema_version': 1, 'status': status, 'mode': mode, 'model_version': MODEL_VERSION,
            'model_sha256': None, 'index_date': None, 'index_basis': 'first_baseline_visit',
            'horizon_days': 365, 'clinical_validated': False, 'features': [], 'models': [], 'reasons': []}


def business_risk():
    """Never infer clinical eligibility from a patient identifier or model fixture."""
    result = _base('clinical_unavailable', 'clinical')
    result['reasons'] = [
        '\u5df2\u90e8\u7f72\u5408\u6210\u6f14\u793a\u6a21\u578b\uff1b\u4e1a\u52a1\u60a3\u8005\u5c1a\u672a\u542f\u7528\u4e34\u5e8a\u98ce\u9669\u9884\u6d4b\u3002',
        '\u9700\u786e\u8ba4\u611f\u67d3\u548c\u75c5\u60c5\u6d3b\u52a8\u52a0\u91cd\u5b9a\u4e49\uff0c\u5b8c\u6210\u7ed3\u5c40\u6807\u6ce8\u3001\u5220\u5931\u4e0e\u7ade\u4e89\u4e8b\u4ef6\u8bb0\u5f55\u3002',
        '\u9700\u5b8c\u6210\u6837\u672c\u91cf\u89c4\u5212\u3001\u65f6\u95f4\u6216\u5916\u90e8\u9a8c\u8bc1\u3001\u6821\u51c6\u4e0e\u533b\u751f\u5ba1\u6838\u3002',
    ]
    return result


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid date')
    return date.fromisoformat(value)


def _load_model():
    raw = MODEL_PATH.read_bytes()
    if len(raw) > 100000 or hashlib.sha256(raw).hexdigest() != MODEL_SHA256:
        raise ValueError('Model checksum mismatch')
    model = json.loads(raw)
    if (model['schema_version'] != 1 or model['model_version'] != MODEL_VERSION
            or model['training_source'] != 'synthetic_generator' or model['clinical_validated'] is not False
            or model['horizon_days'] != 365 or model['index_basis'] != 'first_baseline_visit'):
        raise ValueError('Unsupported model')
    definitions = model['feature_definitions']
    if tuple(row['code'] for row in definitions) != CODES:
        raise ValueError('Invalid feature order')
    for item in definitions:
        if not (_number(item['min']) and _number(item['max']) and item['min'] < item['max']):
            raise ValueError('Invalid feature domain')
    if tuple(item['id'] for item in model['models']) != ENDPOINTS:
        raise ValueError('Invalid endpoints')
    for item in model['models']:
        if tuple(item['feature_codes']) != CODES or len(item['coefficients']) != 4 or len(item['center']) != 4:
            raise ValueError('Invalid coefficient shape')
        if not all(_number(v) for v in item['coefficients'] + item['center']):
            raise ValueError('Invalid coefficients')
        hazard = item['baseline_cumulative_hazard']
        if tuple(row['days'] for row in hazard) != HORIZONS:
            raise ValueError('Unsupported horizons')
        values = [row['value'] for row in hazard]
        if not all(_number(v) and v >= 0 for v in values) or values != sorted(values):
            raise ValueError('Invalid cumulative hazard')
    return model


def _predict(model, values, index_date):
    """Use the same centering and baseline-hazard horizons as the fitted model."""
    log_hazard = sum(beta * (value - center) for beta, value, center in
                     zip(model['coefficients'], values, model['center']))
    relative_hazard = math.exp(log_hazard)
    return [{'days': item['days'], 'risk': -math.expm1(-item['value'] * relative_hazard),
             'date': (index_date + timedelta(days=item['days'])).isoformat()}
            for item in model['baseline_cumulative_hazard']]


def demo_risk(patient, metric_definitions):
    """Called only with server-selected demo fixtures; never with business records."""
    result = _base('model_unavailable', 'synthetic_demo')
    result['training_source'] = 'synthetic_generator'
    try:
        artifact = _load_model()
        result['model_sha256'] = MODEL_SHA256
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['reasons'] = ['\u6f14\u793a\u6a21\u578b\u6682\u4e0d\u53ef\u7528\uff0c\u672a\u751f\u6210\u98ce\u9669\u503c\u3002']
        return result
    result['status'] = 'input_unavailable'
    input_reason = None
    try:
        visits = patient['visits']
        baseline = [v for v in visits if v['kind'] == 'baseline']
        if len(baseline) != 1 or not visits:
            raise ValueError('Exactly one baseline required')
        visit = baseline[0]
        index_date = _day(visit['date'])
        if index_date != _day(patient['enrolled_at']) or any(_day(v['date']) < index_date for v in visits):
            raise ValueError('Baseline must be the first visit')
        if not isinstance(visit['id'], str) or not visit['id']:
            raise ValueError('Missing visit provenance')
        result['index_date'] = index_date.isoformat()
        values = []
        for feature in artifact['feature_definitions']:
            definitions = [m for m in metric_definitions if m['code'] == feature['code']]
            if len(definitions) != 1 or definitions[0]['unit'] != feature['unit'] or definitions[0]['group'] != feature['group']:
                input_reason = feature['label'] + '\uff1a\u6307\u6807\u5b9a\u4e49\u6216\u5355\u4f4d\u4e0d\u5339\u914d\uff08\u9700\u8981 ' + feature['unit'] + '\uff09\u3002'
                raise ValueError('Conflicting units or metric definition')
            value = visit.get(feature['group'], {}).get(feature['code'])
            if not _number(value) or not feature['min'] <= value <= feature['max']:
                input_reason = feature['label'] + ('\uff1a\u9996\u6b21\u8bbf\u89c6\u7f3a\u5c11\u8bb0\u5f55\u3002' if value is None else
                    '\uff1a\u503c\u65e0\u6548\u6216\u8d85\u51fa\u5408\u6210\u751f\u6210\u5668\u8303\u56f4 ' + str(feature['min']) + '\u2013' + str(feature['max']) + ' ' + feature['unit'] + '\u3002')
                raise ValueError('Missing, invalid or out-of-domain input')
            values.append(float(value))
            result['features'].append({**{k: feature[k] for k in ('code', 'label', 'unit')},
                'value': value, 'source_date': visit['date'], 'source_ref': visit['id']})
        models = [{**{k: model[k] for k in ('id', 'label', 'endpoint_version', 'training_n', 'training_events')},
                   'estimates': _predict(model, values, index_date)} for model in artifact['models']]
        result.update(status='available', models=models)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        result['features'] = []
        result['reasons'] = [input_reason or '\u9996\u6b21\u5165\u7ec4\u8bbf\u89c6\u8bb0\u5f55\u4e0d\u5b8c\u6574\u6216\u51b2\u7a81\uff0c\u672a\u751f\u6210\u98ce\u9669\u503c\u3002',
            '\u6a21\u578b\u4fdd\u7559\u539f\u5165\u7ec4\u65e5\u671f\uff0c\u4e0d\u7528\u540e\u7eed\u968f\u8bbf\u503c\u8865\u5165\u57fa\u7ebf\u3002']
        return result
