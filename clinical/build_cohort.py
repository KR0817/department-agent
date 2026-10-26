"""Build a deterministic synthetic demonstration without accessing business data."""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

AGENT = Path(__file__).resolve().parent
OUTPUT = AGENT.parent / 'work' / 'cohort-demo'
sys.path.insert(0, str(AGENT))
from patient_overview import build_overview

START = date(2021, 10, 24)
END = date(2026, 10, 24)
EXPECTED_COUNTS = {'red': 6, 'orange': 8, 'yellow': 10, 'gray': 26}
CONTEXT_CODES = ('medications', 'inpatient_exams', 'infection_status', 'comorbidities', 'baseline_exams')


def build_source():
    """Construct literal records; priority labels are calculated only by the engine."""
    patients = []
    schedule = [('B', 'baseline', START), ('F1', 'first_followup', START + timedelta(days=90))]
    schedule += [('Y' + str(year), 'annual_followup', date(2021 + year, 10, 24)) for year in range(1, 6)]
    for index in range(1, 51):
        suffix = f'{index:03d}'
        identifier = 'SIM-OV50-' + suffix
        prefix = 'SIM-VISIT50-' + suffix
        dryness, fatigue, pain = 2 + index % 4, 2 + (index + 1) % 4, 1 + index % 4
        igg = round(12 + (index % 5) * 0.6, 2)
        visits = []
        context = {code: [] for code in CONTEXT_CODES}
        for sequence, (ending, kind, day) in enumerate(schedule):
            visit_id = prefix + '-' + ending
            symptoms = {'dryness': dryness, 'fatigue': fatigue, 'pain': pain}
            measurements = {'igg': round(igg + [2, 1, 1.5, 0.5, 0, 0, 0][sequence], 2),
                            'c3': round(0.85 + (index % 4) * 0.05 + (sequence % 3) * 0.02, 2),
                            'c4': round(0.16 + (index % 3) * 0.02 + (sequence % 2) * 0.01, 2)}
            if 7 <= index <= 10 and sequence >= 4:
                measurements['igg'] = round(igg + (sequence - 4) * 2, 2)
            if 15 <= index <= 19 and sequence == 6:
                symptoms['dryness'] += 1
            if index == 25 and sequence == 3:
                measurements['c3'] = None
            if index == 26:
                measurements['c4'] = None
            if index == 27 and sequence == 6:
                symptoms['pain'] = None
            if index == 28 and sequence == 5:
                measurements['igg'] = None
            if index == 29 and sequence == 0:
                symptoms['dryness'] = None
            if index == 30 and sequence == 6:
                symptoms['fatigue'] = None
            if index == 31 and sequence == 6:
                measurements['c3'] = None
            if index == 32:
                symptoms['pain'] = 0
            visits.append({'id': visit_id, 'kind': kind, 'date': day.isoformat(),
                'source_label': '\u5408\u6210\u4e94\u5e74\u8bbf\u89c6\u8d44\u6599 ' + suffix + '-' + ending,
                'condition_note': '\u5408\u6210\u968f\u8bbf\u8bb0\u5f55\uff1a\u672c\u6b21\u8bbf\u89c6\u4fdd\u7559\u5355\u9879\u8bc4\u5206\u3001\u68c0\u67e5\u539f\u503c\u548c\u4e94\u7c7b\u4e34\u5e8a\u8d44\u6599\uff0c\u4ec5\u7528\u4e8e\u754c\u9762\u6f14\u793a\u3002',
                'symptoms': symptoms, 'measurements': measurements})
            texts = {
                'medications': '\u5408\u6210\u7528\u836f\u8bb0\u5f55\uff1a\u793a\u4f8b\u7528\u836f\u7532\uff0c\u8bb0\u5f55\u5242\u91cf5 mg\uff0c\u6bcf\u65e51\u6b21\uff0c\u4ec5\u7528\u4e8e\u754c\u9762\u6f14\u793a\u3002',
                'inpatient_exams': '\u5408\u6210\u4f4f\u9662\u4e3b\u8981\u68c0\u67e5\u8bb0\u5f55\uff1a\u80f8\u90e8\u5f71\u50cf\u53ca\u8840\u5e38\u89c4\u62a5\u544a\u5df2\u5f52\u6863\uff0c\u4fdd\u7559\u539f\u62a5\u544a\u8bb0\u5f55\u3002',
                'infection_status': '\u5408\u6210\u611f\u67d3\u8bb0\u5f55\uff1a\u672c\u6b21\u8d44\u6599\u4ec5\u8bb0\u5f55\u547c\u5438\u9053\u75c7\u72b6\u6838\u5bf9\u60c5\u51b5\uff0c\u611f\u67d3\u6b21\u6570\u672a\u8bb0\u5f55\u3002',
                'comorbidities': '\u5408\u6210\u57fa\u7840\u75c5\u8bb0\u5f55\uff1a\u793a\u4f8b\u9ad8\u8840\u538b\u75c5\u53f2\uff0c\u4ec5\u7528\u4e8e\u4e34\u5e8a\u8d44\u6599\u5c55\u793a\u3002',
                'baseline_exams': '\u5408\u6210\u91cd\u8981\u57fa\u7840\u68c0\u67e5\u8bb0\u5f55\uff1a\u6cea\u6db2\u8bd5\u9a8c\u3001\u553e\u6db2\u6d41\u7387\u53ca\u80be\u529f\u80fd\u62a5\u544a\u5df2\u5f52\u6863\uff0c\u8be6\u60c5\u89c1\u5408\u6210\u539f\u6587\u3002',
            }
            if index % 3 == 0:
                texts['comorbidities'] = '\u5408\u6210\u57fa\u7840\u75c5\u8bb0\u5f55\uff1a\u672c\u6b21\u8d44\u6599\u672a\u8bb0\u5f55\u57fa\u7840\u75c5\u4fe1\u606f\u3002'
            if 1 <= index <= 6 and sequence == (6 if index <= 3 else 4):
                texts['inpatient_exams'] = '\u5408\u6210\u68c0\u67e5\u62a5\u544a\uff1a\u8840\u94be6.8 mmol/L\uff0c\u62a5\u544a\u6807\u8bb0\u5371\u6025\u503c\uff0c\u9700\u7acb\u5373\u5904\u7406\u3002'
            if 11 <= index <= 14 and sequence == 6:
                texts['infection_status'] = '\u5408\u6210\u611f\u67d3\u8bb0\u5f55\uff1a\u8fd190\u5929\u611f\u67d33\u6b21\uff0c\u524d90\u5929\u611f\u67d31\u6b21\u3002'
            if 20 <= index <= 24 and sequence == 6:
                texts['medications'] = '\u5408\u6210\u7528\u836f\u8bb0\u5f55\uff1a\u793a\u4f8b\u7528\u836f\u4e59\uff0c\u8bb0\u5f55\u5242\u91cf10 mg\uff0c\u6bcf\u65e51\u6b21\uff0c\u4ec5\u7528\u4e8e\u754c\u9762\u6f14\u793a\u3002'
            for code, text in texts.items():
                context[code].append({'visit_id': visit_id, 'date': day.isoformat(), 'code': code,
                                      'value': text, 'quote': text, 'unit': '', 'current': True})
        patients.append({'id': identifier, 'name': '\u6a21\u62df\u60a3\u8005' + suffix,
            'enrolled_at': START.isoformat(),
            'profile': {'sex': 'male' if index % 5 == 0 else 'female',
                        'age_at_enrollment': 30 + index % 36,
                        'condition_label': '\u5408\u6210\u5e72\u71e5\u7efc\u5408\u5f81\u968f\u8bbf\u6f14\u793a'},
            'first_followup': {'due_date': (START + timedelta(days=90)).isoformat(),
                               'evidence_visit_id': prefix + '-F1'},
            'visits': visits, 'clinical_context': context})
    return {'synthetic': True, 'cohort_id': 'sjd-overview-demo-50-5y-v1', 'detail_schema_version': 2,
            'clinical_context_version': 1, 'as_of': END.isoformat(),
            'observation_period': {'start': START.isoformat(), 'end': END.isoformat(), 'years': 5},
            'patients': patients}


def encode(value):
    return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + '\n').encode('ascii')


def preserve_or_create(path, content):
    """Never replace a previously generated, different artifact."""
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError('Existing artifact differs: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify existing deterministic artifacts without writing')
    args = parser.parse_args()
    source = build_source()
    result = build_overview(source)
    counts = Counter(patient['attention']['level'] for patient in result['patients'])
    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError('Calculated attention counts differ from the demonstration design')
    fixture = AGENT / 'fixtures' / 'patient-overview-five-year-demo.json'
    artifacts = {fixture: encode(source), OUTPUT / 'demo-overview.json': encode(result)}
    for path, content in artifacts.items():
        if args.check:
            if path.read_bytes() != content:
                raise ValueError('Deterministic artifact mismatch: ' + str(path))
        else:
            preserve_or_create(path, content)
    report = {'status': 'PASS', 'input_kind': 'synthetic_development', 'clinical_validation': False,
              'summary': result['summary'], 'observation_period': result['observation_period'],
              'calculated_attention_counts': dict(counts),
              'attention_patient_ids': {level: [patient['id'] for patient in result['patients']
                                                if patient['attention']['level'] == level]
                                        for level in EXPECTED_COUNTS},
              'missing_measurements': [{'patient_id': patient['id'], 'date': visit['date'], 'code': code}
                  for patient in result['patients'] for visit in patient['visits']
                  for group in ('symptoms', 'measurements') for code, value in visit[group].items() if value is None],
              'source_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (Path(__file__), AGENT / 'patient_overview.py', AGENT / 'patient_attention.py', fixture)},
              'patients': [{'id': patient['id'], 'visits': patient['visit_count'],
                            'first_followup': patient['first_followup']['status'],
                            'next_due_date': patient['next_due_date'], 'attention': patient['attention']['level'],
                            'kinds': [item['kind'] for item in patient['attention']['items']]}
                           for patient in result['patients']]}
    report_path = OUTPUT / 'cohort-verification.json'
    if args.check:
        if report_path.read_bytes() != encode(report):
            raise ValueError('Verification metadata no longer matches the input, code and derived overview')
    else:
        preserve_or_create(report_path, encode(report))
    print(json.dumps({'status': 'PASS', 'check_only': args.check, 'summary': result['summary'],
                      'source_sha256': report['source_sha256']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
