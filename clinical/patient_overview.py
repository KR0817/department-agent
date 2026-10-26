"""Read-only, explicitly synthetic cohort; never imports clinical or business stores."""
from collections import Counter
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re
from patient_attention import evaluate_attention

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'patient-overview-five-year-demo.json'
COHORT = 'sjd-overview-demo-20-v1'
FIVE_YEAR_COHORT = 'sjd-overview-demo-50-5y-v1'
CONTEXT_CODES = ('medications', 'inpatient_exams', 'infection_status', 'comorbidities', 'baseline_exams')
METRICS = (
    ('dryness', '\u53e3\u5e72\u8bc4\u5206', 'symptoms', '\u5206', 1),
    ('fatigue', '\u75b2\u52b3\u8bc4\u5206', 'symptoms', '\u5206', 1),
    ('pain', '\u75bc\u75db\u8bc4\u5206', 'symptoms', '\u5206', 1),
    ('igg', '\u514d\u75ab\u7403\u86cb\u767dG\uff08IgG\uff09', 'measurements', 'g/L', 2),
    ('c3', '\u8865\u4f53C3', 'measurements', 'g/L', 2),
    ('c4', '\u8865\u4f53C4', 'measurements', 'g/L', 2),
)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid simulation date')
    return date.fromisoformat(value)


def _synthetic_text(value, limit):
    if not isinstance(value, str) or not value.startswith('\u5408\u6210') or len(value) > limit:
        raise ValueError('Description must be explicitly synthetic and bounded')
    return value


def _profile(value):
    if not isinstance(value, dict) or value.get('sex') not in ('female', 'male', 'unknown'):
        raise ValueError('Invalid synthetic profile')
    age = value['age_at_enrollment']
    if age is not None and (type(age) is not int or not 0 <= age <= 130):
        raise ValueError('Invalid age at enrollment')
    return {'sex': value['sex'], 'age_at_enrollment': age,
            'condition_label': _synthetic_text(value['condition_label'], 120)}


def _metrics(value, keys, maximum):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Metric codes must match the fixed schema')
    result = {}
    for code in keys:
        number = value[code]
        if number is not None and (type(number) not in (int, float)
                or not 0 <= number <= maximum or not math.isfinite(number)):
            raise ValueError('Metric values must be finite, numeric and within storage bounds')
        result[code] = number
    return result


def _clinical_context(value, visits):
    """Return only bounded synthetic records tied to this patient's visits."""
    if not isinstance(value, dict) or set(value) != set(CONTEXT_CODES):
        raise ValueError('Clinical context categories must match the fixed schema')
    by_id = {visit['id']: visit for visit in visits}
    result = {}
    for code in CONTEXT_CODES:
        rows = value[code]
        if not isinstance(rows, list) or len(rows) > 20:
            raise ValueError('Clinical context collection exceeds its bound')
        result[code] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid clinical context record')
            visit = by_id.get(row.get('visit_id'))
            if not visit or row.get('date') != visit['date'] or row.get('code') != code:
                raise ValueError('Clinical context must match its patient, visit, date and category')
            value_text = _synthetic_text(row.get('value'), 1200)
            quote = _synthetic_text(row.get('quote'), 1600)
            if value_text not in quote or row.get('unit') != '' or type(row.get('current')) is not bool:
                raise ValueError('Clinical context requires an exact source quote and explicit state')
            result[code].append({'date': visit['date'], 'value': value_text, 'unit': '',
                'quote': quote, 'code': code, 'source_job': None, 'source_label': visit['source_label'],
                'visit_id': visit['id'], 'current': row['current'], 'verification': 'synthetic_demo'})
    return result


def _attention_visits(patient):
    """Adapt only the validated synthetic DTO, without changing the historical fixture."""
    visits = []
    for visit in patient['visits']:
        facts = []
        for code, label, group, unit, _ in METRICS:
            value = visit[group][code]
            if value is not None:
                literal = str(value)
                facts.append({'code': code, 'value': literal, 'unit': unit,
                              'quote': visit['source_label'] + '; ' + label + ': ' + literal + ' ' + unit,
                              'current': True, 'source_job': None})
        for rows in patient.get('clinical_context', {}).values():
            for row in rows:
                if row['visit_id'] == visit['id']:
                    facts.append({key: row[key] for key in ('code', 'value', 'unit', 'quote', 'current', 'source_job')})
        visits.append({'date': visit['date'], 'event_id': visit['id'], 'facts': facts})
    return visits


def build_overview(source):
    """Derive patient-level first-follow-up completion from linked simulated visits."""
    if not isinstance(source, dict) or source.get('synthetic') is not True:
        raise ValueError('An explicit synthetic cohort is required')
    version = source.get('detail_schema_version')
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Unsupported synthetic detail schema')
    cohort, size, patient_prefix = (COHORT, 20, 'SIM-OV20-') if version == 1 else (FIVE_YEAR_COHORT, 50, 'SIM-OV50-')
    if source.get('cohort_id') != cohort:
        raise ValueError('Synthetic cohort and schema version do not match')
    context_version = source.get('clinical_context_version')
    if context_version is not None and (type(context_version) is not int or context_version != 1):
        raise ValueError('Unsupported synthetic clinical context schema')
    as_of = _date(source['as_of'])
    period = {'start': '2021-10-24', 'end': '2026-10-24', 'years': 5}
    if version == 2:
        declared = source.get('observation_period')
        if (not isinstance(declared, dict) or type(declared.get('years')) is not int
                or declared != period or as_of.isoformat() != period['end'] or context_version != 1):
            raise ValueError('The five-year cohort requires its complete frozen period and clinical context')
    records = source['patients']
    if not isinstance(records, list) or len(records) != size:
        raise ValueError('This version requires its complete synthetic cohort')
    patients, identifiers, visit_ids = [], set(), set()
    for record in records:
        profile = _profile(record['profile'])
        patient_id, name = record['id'], record['name']
        if not isinstance(patient_id, str) or not re.fullmatch(patient_prefix + r'\d{3}', patient_id) or patient_id in identifiers:
            raise ValueError('Patient identifier is not unique and synthetic')
        if not isinstance(name, str) or not name.startswith('\u6a21\u62df\u60a3\u8005') or len(name) > 80:
            raise ValueError('Patient name is not explicitly synthetic')
        identifiers.add(patient_id)
        enrolled = _date(record['enrolled_at'])
        due = _date(record['first_followup']['due_date'])
        if enrolled > as_of or due != enrolled + timedelta(days=90):
            raise ValueError('Invalid baseline or first-follow-up plan')
        if version == 2 and enrolled.isoformat() != period['start']:
            raise ValueError('Every five-year patient must have the same complete observation period')
        start, end = due - timedelta(days=14), due + timedelta(days=14)
        prefix = ('SIM-VISIT-' if version == 1 else 'SIM-VISIT50-') + patient_id.rsplit('-', 1)[1]
        schedule = {prefix + '-B': ('baseline', enrolled), prefix + '-F1': ('first_followup', due)}
        if version == 2:
            schedule.update({prefix + '-Y' + str(year): ('annual_followup', date(enrolled.year + year, 10, 24))
                             for year in range(1, 6)})
        visits = []
        bounds = (1, 2) if version == 1 else (7, 7)
        if not isinstance(record['visits'], list) or not bounds[0] <= len(record['visits']) <= bounds[1]:
            raise ValueError('The simulated visit count does not match its schema')
        for visit in record['visits']:
            kind, visit_id, day = visit['kind'], visit['id'], _date(visit['date'])
            expected = schedule.get(visit_id) if isinstance(visit_id, str) else None
            if (expected is None or kind != expected[0] or visit_id in visit_ids
                    or (version == 2 and day != expected[1])):
                raise ValueError('Visit evidence is duplicated or belongs to another patient')
            if day < enrolled or day > as_of:
                raise ValueError('Visit falls outside the simulation observation period')
            label = _synthetic_text(visit['source_label'], 80)
            visit_ids.add(visit_id)
            visits.append({'id': visit_id, 'date': day.isoformat(), 'kind': kind, 'source_label': label,
                'condition_note': _synthetic_text(visit['condition_note'], 500),
                'symptoms': _metrics(visit['symptoms'], ('dryness', 'fatigue', 'pain'), 10),
                'measurements': _metrics(visit['measurements'], ('igg', 'c3', 'c4'), 1000)})
        baseline = [v for v in visits if v['kind'] == 'baseline']
        followups = [v for v in visits if v['kind'] == 'first_followup']
        if len(baseline) != 1 or baseline[0]['date'] != enrolled.isoformat() or len(followups) > 1:
            raise ValueError('Exactly one baseline and at most one first follow-up are required')
        evidence = record['first_followup'].get('evidence_visit_id')
        completed_at = None
        if evidence is not None:
            if len(followups) != 1 or followups[0]['id'] != evidence:
                raise ValueError('Completion requires linked visit evidence')
            completed = _date(followups[0]['date'])
            if not enrolled < completed or not start <= completed <= end:
                raise ValueError('Completion is outside its first-follow-up window')
            completed_at, status = completed.isoformat(), 'completed'
            next_due = completed + timedelta(days=90)
        else:
            if followups:
                raise ValueError('Follow-up evidence must be linked to its plan')
            status = 'overdue' if as_of > end else 'upcoming' if as_of < start else 'in_window'
            next_due = due
        visits.sort(key=lambda v: (v['date'], v['id']))
        if version == 2:
            next_due = _date(visits[-1]['date']) + timedelta(days=90)
        patients.append({'id': patient_id, 'name': name, 'enrolled_at': enrolled.isoformat(), 'profile': profile,
            'last_visit': visits[-1]['date'], 'visit_count': len(visits), 'visits': visits,
            'next_due_date': next_due.isoformat(), 'first_followup': {
                'due_date': due.isoformat(), 'window_start': start.isoformat(), 'window_end': end.isoformat(),
                'status': status, 'completed_at': completed_at, 'evidence_visit_id': evidence}})
        if context_version is not None:
            patients[-1]['clinical_context'] = _clinical_context(record.get('clinical_context'), visits)
            if version == 2 and any(not rows or len({row['visit_id'] for row in rows}) != len(rows)
                                   for rows in patients[-1]['clinical_context'].values()):
                raise ValueError('Five-year clinical categories require unique linked records')
        patients[-1]['attention'] = {**evaluate_attention(_attention_visits(patients[-1]), as_of.isoformat()),
                                    'source': 'synthetic_demo'}
    if version == 2:
        if identifiers != {patient_prefix + f'{index:03d}' for index in range(1, size + 1)}:
            raise ValueError('The complete five-year synthetic identifier sequence is required')
        patients.sort(key=lambda patient: patient['id'])
    counts = Counter(p['first_followup']['status'] for p in patients)
    attention_counts = Counter(p['attention']['level'] for p in patients)
    return {'synthetic': True, 'cohort_id': cohort,
        'cohort_label': '\u0032\u0030\u4eba\u5408\u6210\u6f14\u793a\u961f\u5217' if version == 1 else '\u0035\u0030\u4eba\u00b7\u0035\u5e74\u5408\u6210\u6f14\u793a\u961f\u5217',
        'as_of': as_of.isoformat(), 'completion_basis': 'first_followup_encounter', 'delivery_enabled': False,
        'detail_schema_version': version,
        **({'observation_period': dict(period)} if version == 2 else {}),
        **({'clinical_context_version': context_version} if context_version is not None else {}),
        'metric_definitions': [{'code': code, 'label': label, 'group': group, 'unit': unit, 'precision': precision}
                               for code, label, group, unit, precision in METRICS],
        'summary': {'enrolled': len(patients), 'completed': counts['completed'],
            'pending': len(patients) - counts['completed'], 'completion_percent': round(100 * counts['completed'] / len(patients)),
            'overdue': counts['overdue'], 'in_window': counts['in_window'], 'upcoming': counts['upcoming'],
            'visits': sum(p['visit_count'] for p in patients),
            **({'attention_counts': {level: attention_counts[level] for level in ('red', 'orange', 'yellow', 'gray')}}
               if version == 2 else {})}, 'patients': patients}


def load_demo_overview():
    """Load the versioned fixture; IO or schema failures remain visible to the caller."""
    return build_overview(json.loads(FIXTURE.read_text(encoding='utf-8')))
