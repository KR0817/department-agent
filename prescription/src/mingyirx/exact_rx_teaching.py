"""Local exact-prescription selection and explicitly fictional teaching overlays."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'mingyirx-exact-rx-teaching-v1'
FIELDS = ('item_name', 'quantity', 'days', 'frequency', 'dose', 'unit')
COLUMNS = (11, 12, 13, 14, 15, 16)
HEADER = ('   ', 'NAME', 'CLINIC_CODE', 'PHYSICAL_CARDNO', 'BEGIN_TIME',
          'BIRTHDAY', 'SEX_CODE', 'BEGIN_TIME', 'DIAG', 'RELA_PHONE',
          'DEPT_NAME', 'ITEM_NAME', 'QTY', 'DAYS', 'FREQUENCY_CODE',
          'ONCE_DOSE', 'ONCE_UNIT')
PATTERNS = {'RA': r'类风湿(?:性)?关节炎|rheumatoid\s*arthritis',
            'SJD': r'干燥综合(?:征|症)|舍格伦|斯耶格伦|sj[oö]gren',
            'AS': r'强直性脊柱炎|ankylosing\s*spondylitis'}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def _date(value):
    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y/%m/%d'):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            pass
    return None


def read_source(path: Path, expected_hash: str, encoding='gb18030'):
    """Return transient source-key groups; never serialize the keys or dates.

    Select only linkage, coarse-label, and prescription fields. A malformed date
    invalidates the entire source-key sequence, so later selection cannot bridge
    an unresolved visit. Source grouping is not independent identity validation.
    """
    if digest(path).lower() != expected_hash.lower():
        raise ValueError('SOURCE_HASH_MISMATCH')
    groups = defaultdict(dict)
    blocked = set()
    unresolved_clinics = set()
    stats = Counter()
    with path.open('r', encoding=encoding, newline='') as stream:
        reader = csv.reader(stream)
        if tuple(next(reader, [])) != HEADER:
            raise ValueError('SOURCE_HEADER_MISMATCH')
        for number, row in enumerate(reader, 2):
            stats['source_rows'] += 1
            if len(row) != len(HEADER):
                raise ValueError('SOURCE_ROW_WIDTH_INVALID')
            key, timestamp = row[3], _date(row[4])
            if not key.strip():
                stats['missing_key_rows'] += 1
                if row[2].strip():
                    unresolved_clinics.add(row[2])
                else:
                    raise ValueError('UNLINKABLE_PRESCRIPTION_ROW')
                continue
            if timestamp is None:
                blocked.add(key)
                stats['invalid_date_rows'] += 1
                continue
            visit = groups[key].setdefault(timestamp, {'rows': [], 'references': [],
                                                      'conditions': set(), 'clinic_keys': set()})
            visit['clinic_keys'].add(row[2])
            visit['rows'].append(dict(zip(FIELDS, (row[i] for i in COLUMNS))))
            visit['references'].append(number)
            visit['conditions'].update(code for code, pattern in PATTERNS.items()
                                       if re.search(pattern, row[8], re.I))
    for key in blocked:
        groups.pop(key, None)
    for visits in groups.values():
        for visit in visits.values():
            if visit['clinic_keys'] & unresolved_clinics:
                visit['unresolved_rows'] = True
    stats['invalid_date_sequences'] = len(blocked)
    stats['source_key_sequences'] = len(groups)
    stats['ambiguous_timestamp_groups'] = sum(len(v['clinic_keys']) != 1
        for visits in groups.values() for v in visits.values())
    if digest(path).lower() != expected_hash.lower():
        raise ValueError('SOURCE_CHANGED_DURING_READ')
    return groups, dict(stats)


def _eligible(visit, exclusion_pattern):
    rows = visit['rows']
    return (5 <= len(rows) <= 60 and len(visit['clinic_keys']) == 1
        and all(k.strip() for k in visit['clinic_keys']) and not visit.get('unresolved_rows')
        and all(r['item_name'].strip() and r['unit'].strip() == 'g'
                and not re.search(exclusion_pattern, r['item_name'])
                and all(len(v) <= 120 and not re.search(r'[\x00-\x1f]', v) for v in r.values())
                for r in rows))


def _cue_names(name):
    # Matching aliases never change any displayed or frozen source string.
    return re.sub(r'[\s\d.*()\[\]（）]', '', name)


def simulate(rows: list[dict], rules: dict) -> dict:
    """Choose a fictional writing prompt; this is not clinical classification."""
    names = [r['item_name'] for r in rows]
    scored = []
    for index, rule in enumerate(rules['profiles']):
        matched = [name for name in names if any(
            _cue_names(name) == alias for alias in rule['cues'])]
        scored.append((len(set(matched)), -index, rule, sorted(set(matched))))
    hits, _, profile, cues = max(scored, key=lambda r: (r[0], r[1]))
    if not hits:
        profile = rules['fallback']
    return {'origin': 'SIMULATED_FROM_PRESCRIPTION_NOT_OBSERVED',
            'profile_id': profile['id'], 'matched_cues': cues,
            'cue_groups': [{'profile_id': p['id'], 'count': n, 'items': items}
                           for n, _, p, items in scored if n],
            **{key: profile[key] for key in ('inspection', 'listening', 'inquiry',
                                            'palpation', 'syndrome', 'principle')}}


def select_episodes(groups, rules: dict, exclusion_pattern: str, limit=10):
    """Pick varied teaching windows; selection is deliberately nonrepresentative."""
    candidates = defaultdict(list)
    for key_index, visits in enumerate(groups.values()):
        ordered = sorted(visits)
        day_counts = Counter(t.date() for t in ordered)
        for start in range(len(ordered) - 2):
            times = ordered[start:start + 3]
            window = [visits[t] for t in times]
            if (not all(day_counts[t.date()] == 1 for t in times)
                or not all(0 < (b.date() - a.date()).days <= 180 for a, b in zip(times, times[1:]))
                or not all(_eligible(v, exclusion_pattern) for v in window)):
                continue
            conditions = sorted(set.union(*(v['conditions'] for v in window)))
            category = '+'.join(conditions) or 'OTHER'
            raw = [v['rows'] for v in window]
            memberships = [set(r['item_name'] for r in rows) for rows in raw]
            changes = sum(len(a ^ b) for a, b in zip(memberships, memberships[1:]))
            if changes == 0:
                continue
            overlays = [simulate(rows, rules) for rows in raw]
            profile_changes = sum(a['profile_id'] != b['profile_id']
                                  for a, b in zip(overlays, overlays[1:]))
            # Prefer illustrative change without presenting a prevalence sample.
            score = (-profile_changes, -min(changes, 12), key_index, start)
            candidates[category].append((score, key_index, times, window, overlays))
    selected, used = [], set()
    categories = sorted(candidates, key=lambda c: (c not in ('RA+SJD', 'AS', 'SJD', 'RA'), c))
    for _ in range(2):
        for category in categories:
            available = [x for x in candidates[category] if x[1] not in used]
            if not available or len(selected) >= limit:
                continue
            _, key_index, times, window, overlays = min(available, key=lambda x: x[0])
            used.add(key_index)
            selected.append({'case_id': f'RX-{len(selected)+1:03d}',
                'recorded_label_category': category, 'physician_attribution': 'UNKNOWN',
                'visits': [{'ordinal': i + 1, 'offset_days': (t.date()-times[0].date()).days,
                            'raw_rows': v['rows'], 'simulation': sim,
                            'private_source_rows': v['references']}
                           for i, (t, v, sim) in enumerate(zip(times, window, overlays))]})
    return selected


def verify_exact(path: Path, episodes: list, expected_hash: str, encoding='gb18030'):
    """Independently reread selected source positions and compare all six fields."""
    expected = {}
    for episode in episodes:
        for visit in episode['visits']:
            if len(visit['raw_rows']) != len(visit['private_source_rows']):
                raise ValueError('ROW_REFERENCE_COUNT_MISMATCH')
            for position, row in zip(visit['private_source_rows'], visit['raw_rows']):
                if position in expected:
                    raise ValueError('SELECTED_SOURCE_ROW_REUSED')
                expected[position] = row
    matched = 0
    with path.open('r', encoding=encoding, newline='') as stream:
        reader = csv.reader(stream)
        if tuple(next(reader, [])) != HEADER:
            raise ValueError('SOURCE_HEADER_MISMATCH')
        for number, row in enumerate(reader, 2):
            if number in expected:
                if len(row) != len(HEADER) or dict(zip(FIELDS, (row[i] for i in COLUMNS))) != expected[number]:
                    raise ValueError('EXACT_PRESCRIPTION_MISMATCH')
                matched += 1
    if matched != len(expected) or digest(path).lower() != expected_hash.lower():
        raise ValueError('SOURCE_RECHECK_FAILED')
    return {'gate': 'PASS', 'verified_rows': matched, 'verified_raw_fields': matched * len(FIELDS),
            'source_hash_verified': True, 'clinical_validation': False}


def presentable(bundle: dict) -> dict:
    """Private provenance stays outside HTML; medication content remains restricted."""
    result = json.loads(canonical(bundle))
    for case in result['episodes']:
        for visit in case['visits']:
            visit.pop('private_source_rows', None)
    return result
