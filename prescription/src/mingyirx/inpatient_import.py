"""Legacy-named workbook adapter; actual care setting must be provided explicitly."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

EXPECTED_SHA = 'f5d1cdcd1823d457faadc51f0e9e7a05a7019b7118d1f9c6a82e134cd1672721'
HEADERS = ['唯一号', '住院号/门诊号', '姓名', '年龄', '性别', '出生日期', '入院时间',
           '出院时间', '处方内容', '药味数', '医嘱组号', '开始时间', '结束时间', '入院日期', '出院诊断']
TOKEN = re.compile(r'(.+?)\s+(\d+(?:\.\d+)?)\s*(g)(?:\s+.*)?')

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def parse_prescription(text: str, stated_count: int) -> list[tuple[str, float, str]]:
    tokens = [t.strip() for t in re.split(r'[;；\r\n]+', text) if t.strip()]
    if len(tokens) != stated_count:
        raise ValueError('Prescription item count mismatch; identifying values withheld')
    result = []
    for token in tokens:
        m = TOKEN.fullmatch(token)
        if not m or float(m[2]) <= 0:
            raise ValueError('Unsupported prescription token or dose; value withheld')
        result.append((m[1].strip(), float(m[2]), m[3]))
    return result

def identity(row: tuple) -> tuple:
    return (str(row[2]).strip(), row[5].date().isoformat(), str(row[4]).strip())

def validate_identities(persons: dict) -> None:
    if any(len(v) != 1 for v in persons.values()):
        raise ValueError('A stable patient identifier has contradictory identity fields')


def candidate_status(pid: str, key: tuple, old_id_keys: dict, old_key_ids: dict) -> str:
    if pid in old_id_keys and old_id_keys[pid] == {key}:
        return 'EXACT_ID_AND_IDENTITY'
    candidates = old_key_ids.get(key, set())
    if len(candidates) == 1:
        return 'UNIQUE_DEMOGRAPHIC_CANDIDATE'
    return 'AMBIGUOUS_DEMOGRAPHIC_CANDIDATE' if candidates else 'NO_EXACT_IDENTITY_CANDIDATE'


def prepare(source: Path, base_config: Path, private: Path, canonical_dir: Path, *,
            expected_sha: str | None = None, source_setting: str = 'unknown',
            physician_id: str = 'unknown') -> dict:
    try:
        import openpyxl
    except ImportError as error:
        raise RuntimeError('Excel import requires the mingyirx[excel] optional dependency') from error
    if expected_sha is None:
        raise ValueError('Provide the previously verified source SHA-256')
    if source_setting not in {'outpatient', 'inpatient', 'unknown'}:
        raise ValueError('Unsupported care setting')
    if digest(source) != expected_sha:
        raise ValueError('Workbook hash differs from the frozen contract')
    private.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    if len(workbook.worksheets) != 1:
        raise ValueError('Unexpected sheet count')
    values = list(workbook.worksheets[0].values)
    if list(values[0]) != HEADERS:
        raise ValueError('Unexpected source header')
    rows = [r for r in values[1:] if any(v is not None for v in r)]
    persons, tuple_ids = defaultdict(set), defaultdict(set)
    rx_ids, group_ids = set(), set()
    parsed = []
    for r in rows:
        if not all(r[j] is not None for j in [0, 1, 2, 4, 5, 8, 9, 10, 11, 14]):
            raise ValueError('Missing required source field')
        if not isinstance(r[5], datetime) or not isinstance(r[11], datetime):
            raise ValueError('Invalid birth or prescription date type')
        if r[0] in rx_ids or r[10] in group_ids:
            raise ValueError('Duplicate prescription or order-group identifier')
        rx_ids.add(r[0]); group_ids.add(r[10])
        key = identity(r); persons[str(r[1])].add(key); tuple_ids[key].add(str(r[1]))
        parsed.append(parse_prescription(r[8], r[9]))
    validate_identities(persons)
    config = json.loads(base_config.read_text(encoding='utf-8'))
    dictionary_path = Path(config['item_normalization']['dictionary_path'])
    if digest(dictionary_path) != config['item_normalization']['expected_sha256']:
        raise ValueError('Dictionary hash mismatch')
    with dictionary_path.open(encoding='utf-8-sig', newline='') as f:
        dictionary = {r['source_item_name']: r['canonical_item_name'] for r in csv.DictReader(f)}
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical = canonical_dir / 'inpatient_lines.csv'
    fields = ['patient_key', 'prescription_key', 'prescription_time', 'birth_time', 'sex',
              'discharge_labels', 'item', 'dose', 'unit', 'physician']
    item_patients = defaultdict(set)
    with canonical.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f); writer.writerow(fields)
        for r, items in zip(rows, parsed):
            for name, dose, unit in items:
                item_patients[name].add(str(r[1]))
                writer.writerow(['IP:' + str(r[1]), 'IPRX:' + str(r[0]), r[11].strftime('%Y-%m-%d %H:%M:%S'),
                    r[5].strftime('%Y-%m-%d'), {'男': 'M', '女': 'F'}[r[4]], r[14], name, dose, unit, physician_id])
    config.update(dataset_id='RX_WORKBOOK_'+expected_sha[:12], cohort_version='workbook-v1',
                  encoding='utf-8', date_formats=['%Y-%m-%d %H:%M:%S', '%Y-%m-%d'],
                  expected_input_sha256={canonical.name: digest(canonical)},
                  columns=dict(zip(['patient_id','visit_id','visit_date','birth_date','sex','diagnosis_text','item_name','dose','unit','physician_id'], range(10))))
    (private / 'config.json').write_text(json.dumps(config, ensure_ascii=True, indent=2), encoding='utf-8')
    audit = {'source_sha256': expected_sha, 'source_rows': len(rows), 'patient_identifiers': len(persons),
        'identity_tuple_count': len(tuple_ids), 'same_identity_multiple_ids': sum(len(v)>1 for v in tuple_ids.values()),
        'prescription_rows': len(rx_ids), 'parsed_item_lines': sum(map(len, parsed)),
        'count_mismatches': 0, 'unparsed_tokens': 0, 'identity_conflicts_within_id': 0,
        'all_admission_discharge_fields_identical': all(r[6] == r[7] == r[13] for r in rows),
        'same_calendar_date_multiple_rx_patients': sum(any(n>1 for n in Counter(r[11].date() for r in rows if str(r[1])==p).values()) for p in persons),
        'year_counts': dict(sorted(Counter(r[11].year for r in rows).items())),
        'distinct_source_items': len(item_patients),
        'unmapped_item_names': sorted(n for n in item_patients if n not in dictionary),
        'unmapped_item_lines': sum(1 for items in parsed for name,_,_ in items if name not in dictionary),
        'terminology_patients': {n: len(ps) for n,ps in item_patients.items()},
        'canonical_sha256': digest(canonical), 'dictionary_sha256': digest(dictionary_path),
        'source_path': str(source.resolve()), 'gate': 'PASS_WITH_WARNINGS',
        'caller_supplied_metadata': {'physician': physician_id, 'setting':source_setting,'id_semantics':'unverified'},
        'blocked': ['length_of_stay','admission_episodes','cross_setting_causal_effects','efficacy','syndrome_inference'],
        'warnings': ['Discharge labels are retrospective', 'Same-day transitions use existing positive-day-gap exclusion',
                     'Distinct stable IDs retained despite matching demographics', 'Unmapped names retain source spelling']}
    (private / 'intake.json').write_text(json.dumps(audit, ensure_ascii=True, indent=2), encoding='utf-8')
    if digest(source) != expected_sha:
        raise ValueError('Workbook changed during intake')
    return {k: v for k,v in audit.items() if k not in ['source_path','unmapped_item_names','terminology_patients']}
