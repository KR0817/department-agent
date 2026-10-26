"""Source-bound review history and explicit follow-up projections; no clinical inference."""
import datetime as dt
import hashlib
import json
import re
import unicodedata

FORM_VERSION = 'followup-raw-v1'
STATES = ('unreviewed', 'acknowledged', 'in_progress', 'reviewed')
PLAN_STATES = ('overdue', 'in_window', 'upcoming', 'completed', 'cancelled', 'unknown')
LEVELS = {'gray': 0, 'yellow': 1, 'orange': 2, 'red': 3}


class CareError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def initialize(con):
    con.execute('''CREATE TABLE IF NOT EXISTS care_records (
        patient_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
        revision INTEGER NOT NULL, body TEXT NOT NULL, actor TEXT NOT NULL,
        recorded_at TEXT NOT NULL, PRIMARY KEY(patient_id,kind,item_id,revision))''')


def text(value, limit=1000, required=False):
    if (not isinstance(value, str) or len(value) > limit or
            any(unicodedata.category(c).startswith('C') and c not in '\n\t' for c in value)):
        raise CareError(422, 'Care text is invalid')
    value = value.strip()
    if required and not value:
        raise CareError(422, 'Care reason and required fields must be completed')
    return value


def day(value, optional=False):
    if optional and value is None:
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise CareError(422, 'Care date is invalid') from None


def signal_key(attention, item):
    # Include full evidence identity: a corrected source must not inherit a prior disposition.
    raw = json.dumps([attention['rules_version'], item['id'], item['evidence']],
                     ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def records(con, patient_id):
    rows = con.execute('SELECT * FROM care_records WHERE patient_id=? ORDER BY recorded_at,revision',
                       (patient_id,)).fetchall()
    return [{**dict(row), 'body': json.loads(row['body'])} for row in rows]


def latest(history, kind, item_id):
    return max((r for r in history if r['kind'] == kind and r['item_id'] == item_id),
               key=lambda r: r['revision'], default=None)


def decorate(attention, history):
    result = {**attention, 'items': []}
    for item in attention['items']:
        key = signal_key(attention, item)
        record = latest(history, 'attention', key)
        result['items'].append({**item, 'signal_key': key, 'review': record or {
            'revision': 0, 'body': {'state': 'unreviewed', 'owner': '', 'due_date': None,
                                  'note': '', 'disposition': '', 'evidence_note': '', 'evidence_refs': []}}})
    active = [i for i in result['items'] if i['review']['body']['state'] != 'reviewed']
    result.update(open_count=len(active), reviewed_count=len(result['items']) - len(active),
                  open_level=max((i['level'] for i in active), key=LEVELS.get, default='gray'))
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise CareError(422, 'Care fields are invalid')


def _refs(value, allowed):
    if (not isinstance(value, list) or len(value) > 12 or any(not isinstance(x, str) for x in value)
            or len(value) != len(set(value)) or not set(value) <= set(allowed)):
        raise CareError(422, 'Care evidence must belong to this patient')
    return value


def validate(kind, value, context, history, item_id):
    if kind == 'attention':
        _keys(value, ('state', 'owner', 'due_date', 'note', 'disposition', 'evidence_note', 'evidence_refs'))
        found = next((i for i in context['attention']['items'] if signal_key(context['attention'], i) == item_id), None)
        if not found:
            raise CareError(409, 'Care source changed; reload before editing')
        if value['state'] not in STATES or value['disposition'] not in ('', 'confirmed', 'already_managed', 'not_applicable', 'needs_followup'):
            raise CareError(422, 'Care state is invalid')
        result = {**value, 'owner': text(value['owner'], 128, required=value['state'] != 'unreviewed'),
                  'due_date': day(value['due_date'], True), 'note': text(value['note'], required=True),
                  'evidence_note': text(value['evidence_note'])}
        if value['state'] == 'reviewed' and (not result['evidence_note'] or not value['disposition']):
            raise CareError(422, 'Care completion requires disposition and evidence')
        if value['disposition'] == 'needs_followup' and (value['state'] != 'in_progress' or not result['due_date']):
            raise CareError(422, 'Care follow-up requires an in-progress state and next date')
        result['source_snapshot'] = found
    elif kind == 'event':
        _keys(value, ('category', 'date', 'end_date', 'title', 'details', 'source_type', 'drug_name',
                      'dose', 'frequency', 'route', 'status', 'site', 'merged_into', 'note', 'evidence_refs'))
        if (value['category'] not in ('medication', 'infection', 'hospital', 'other') or
                value['source_type'] not in ('clinician_record', 'patient_report', 'unknown') or
                value['status'] not in ('unknown', 'current', 'stopped', 'active', 'resolved')):
            raise CareError(422, 'Care event type is invalid')
        result = {**value, 'date': day(value['date']), 'end_date': day(value['end_date'], True)}
        if result['date'] > context['as_of'] or (result['end_date'] and (result['end_date'] < result['date'] or result['end_date'] > context['as_of'])):
            raise CareError(422, 'Care event date is outside the observed period')
        for key in ('title', 'details', 'drug_name', 'dose', 'frequency', 'route', 'site', 'note'):
            result[key] = text(value[key], 1000 if key in ('details', 'note') else 200, key in ('title', 'note'))
        if value['category'] == 'medication' and not result['drug_name']:
            raise CareError(422, 'Care medication name is required')
        target = value['merged_into']
        if target is not None:
            if not isinstance(target, str):
                raise CareError(422, 'Care merge target is invalid')
            prior = latest(history, 'event', target)
            if (value['category'] != 'infection' or target == item_id or not prior or
                    prior['body']['category'] != 'infection' or prior['body']['merged_into'] is not None or
                    any(r['body'].get('merged_into') == item_id and latest(history, 'event', r['item_id']) == r
                        for r in history if r['kind'] == 'event')):
                raise CareError(422, 'Care merge target must be an independent infection event for this patient')
    elif kind == 'form':
        _keys(value, ('template_version', 'visit_date', 'responses', 'medications', 'infection_status',
                     'comorbidities', 'note', 'evidence_refs'))
        if value['template_version'] != FORM_VERSION:
            raise CareError(409, 'Care form version is unsupported')
        result = {**value, 'visit_date': day(value['visit_date']), 'responses': {}}
        if result['visit_date'] > context['as_of']:
            raise CareError(422, 'Care event date is outside the observed period')
        _keys(value['responses'], ('dryness', 'fatigue', 'pain'))
        for key, response in value['responses'].items():
            _keys(response, ('value', 'missing_reason'))
            number, reason = response['value'], text(response['missing_reason'], 300)
            if number is None:
                if not reason:
                    raise CareError(422, 'Care missing response requires a reason')
            elif type(number) not in (int, float) or not 0 <= number <= 10 or reason:
                raise CareError(422, 'Care symptom value must be 0-10 with no missing reason')
            result['responses'][key] = {'value': number, 'missing_reason': reason}
        for key in ('medications', 'infection_status', 'comorbidities', 'note'):
            result[key] = text(value[key], 1000, True)
    else:
        raise CareError(422, 'Care record type is invalid')
    result['evidence_refs'] = _refs(value['evidence_refs'], context['evidence_refs'])
    return result


def save(con, patient_id, kind, item_id, payload, actor, context):
    """Caller owns one write transaction; actor and patient context are server-derived."""
    _keys(payload, ('expected_revision', 'data'))
    revision = payload['expected_revision']
    if type(revision) is not int or revision < 0 or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', item_id):
        raise CareError(422, 'Care revision or identifier is invalid')
    history = records(con, patient_id)
    previous = latest(history, kind, item_id)
    if revision != (previous['revision'] if previous else 0):
        raise CareError(409, 'Care record changed; reload before editing')
    if len(history) >= 10000:
        raise CareError(409, 'Care history limit requires maintenance')
    body = validate(kind, payload['data'], context, history, item_id)
    if previous and kind in ('event', 'form'):
        fixed = 'category' if kind == 'event' else 'template_version'
        if previous['body'][fixed] != body[fixed]:
            raise CareError(409, 'Care record identity cannot change')
    result = {'patient_id': patient_id, 'kind': kind, 'item_id': item_id, 'revision': revision + 1,
              'body': body, 'actor': actor, 'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    con.execute('INSERT INTO care_records VALUES(?,?,?,?,?,?,?)',
                (patient_id, kind, item_id, result['revision'], json.dumps(body, ensure_ascii=True, sort_keys=True),
                 actor, result['recorded_at']))
    return result


def plan_status(plan, as_of):
    """Calendar classification never treats a saved form or message state as a clinical visit."""
    as_of = day(as_of)
    if plan.get('cancelled'):
        return 'cancelled'
    if plan.get('sync_error'):
        return 'unknown'
    if plan.get('completed') and plan.get('evidence'):
        return 'completed'
    start, end = plan.get('window_start'), plan.get('window_end')
    if not start or not end:
        return 'unknown'
    if day(start) > day(end):
        return 'unknown'
    return 'overdue' if as_of > end else 'upcoming' if as_of < start else 'in_window'


def summarize_plans(plans, as_of):
    rows = [{**plan, 'status': plan_status(plan, as_of)} for plan in plans]
    pending = [p for p in rows if p['status'] in ('overdue', 'in_window', 'upcoming', 'unknown')]
    selected = (min(pending, key=lambda p: (PLAN_STATES.index(p['status']), p.get('due_date') or '9999', p['id']))
                if pending else max(rows, key=lambda p: (p.get('due_date') or '', p['id']), default=None))
    return {'as_of': as_of, 'status': selected['status'] if selected else 'unknown', 'selected': selected,
            'plans': sorted(rows, key=lambda p: (p.get('due_date') or '', p['id'])),
            'open_count': len(pending), 'overdue_count': sum(p['status'] == 'overdue' for p in rows)}


def business_plans(patient_id, queue, tasks, as_of, fhir_id=None, sync_error=None):
    authority = {task['id']: task for task in tasks}
    plans = []
    for row in queue:
        if row['patient_id'] != patient_id:
            continue
        task = authority.get(row['task_id'])
        compatible = task and fhir_id and task.get('patient') == 'Patient/' + fhir_id
        window = task.get('window') or {} if compatible else {}
        evidence = task.get('evidence', []) if compatible and task.get('completion_mode') == 'reviewed-visit-only' else []
        plans.append({'id': row['id'], 'task_id': row['task_id'], 'due_date': row['due_date'],
                      'window_start': window.get('start', row['window_start']),
                      'window_end': window.get('end', row['window_end']),
                      'completed': bool(compatible and task['status'] == 'completed' and evidence),
                      'evidence': evidence, 'cancelled': row['status'] == 'cancelled' or bool(compatible and task['status'] in ('cancelled', 'entered-in-error')),
                      'sync_error': sync_error or (None if compatible else 'Clinical plan not verified'),
                      'queue_status': row['status']})
    return summarize_plans(plans, as_of)


def timeline(visits, history):
    events = []
    for visit in visits:
        events.append({'id': visit.get('event_id') or visit.get('id'), 'date': visit['date'],
                       'kind': 'visit', 'facts': [f for f in visit.get('facts', []) if f.get('current') is not False],
                       'source_job': visit.get('source_job'), 'label': visit.get('condition_note', '')})
    for row in history:
        if row['kind'] in ('event', 'form') and row == latest(history, row['kind'], row['item_id']):
            body = row['body']
            events.append({'id': row['item_id'], 'date': body.get('date') or body.get('visit_date'),
                           'kind': row['kind'], 'record': row})
    return sorted(events, key=lambda item: (item['date'], item['kind'], item['id'] or ''))
