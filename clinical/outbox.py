"""Durable follow-up drafts and pending items; this module never sends messages."""
import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import re
import sqlite3

DATABASE = pathlib.Path('jobs.sqlite')
PUBLIC_FIELDS = ('id', 'patient_id', 'name', 'job_id', 'task_id', 'status', 'due_date',
                 'window_start', 'window_end', 'message', 'revision', 'updated_at')
DEFAULT_MESSAGE = '\u60a8\u597d\uff0c\u8bf7\u8054\u7cfb\u79d1\u5ba4\u786e\u8ba4\u672c\u6b21\u968f\u8bbf\u5b89\u6392\u3002'


class OutboxError(ValueError):
    """A safe error that the HTTP layer may expose with its status code."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def initialize(database_path='jobs.sqlite'):
    """Add only the outbox tables to an existing or fresh business database."""
    global DATABASE
    DATABASE = pathlib.Path(database_path)
    with _db(write=True) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS followup_outbox (
            id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, name TEXT NOT NULL,
            index_date TEXT NOT NULL, job_id TEXT NOT NULL, job_ids TEXT NOT NULL,
            task_id TEXT UNIQUE, status TEXT NOT NULL
                CHECK(status IN ('draft','pending_send','completed','cancelled')),
            due_date TEXT NOT NULL, window_start TEXT, window_end TEXT,
            message TEXT NOT NULL, due_edited INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(patient_id,index_date))''')
        con.execute('''CREATE TABLE IF NOT EXISTS outbox_audit (
            id INTEGER PRIMARY KEY, at TEXT NOT NULL, outbox_id TEXT NOT NULL,
            revision INTEGER NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL,
            detail TEXT NOT NULL)''')


@contextlib.contextmanager
def _db(write=False):
    con = sqlite3.connect(DATABASE, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if write:
            con.execute('BEGIN IMMEDIATE')
        with con:
            yield con
    finally:
        con.close()


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise OutboxError(422, label + ' is missing or invalid')
    return value.strip()


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise OutboxError(422, 'Date must use YYYY-MM-DD')
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise OutboxError(422, 'Date is invalid') from exc


def _candidate(candidate):
    if not isinstance(candidate, dict):
        raise OutboxError(422, 'Candidate is invalid')
    patient = _text(candidate.get('patient_id'), 'Patient identifier', 64)
    name = _text(candidate.get('name'), 'Patient name', 120)
    visits = candidate.get('visits')
    if not isinstance(visits, list):
        raise OutboxError(422, 'Candidate visits are invalid')
    dates = []
    for visit in visits:
        if not isinstance(visit, dict) or not isinstance(visit.get('facts'), list):
            raise OutboxError(422, 'Candidate visit is invalid')
        day = _date(visit.get('date'))
        if any(isinstance(fact, dict) and not fact.get('correction_of') for fact in visit['facts']):
            dates.append(day)
    return (patient, name, max(dates).isoformat()) if dates else None


def _public(row):
    return {key: row[key] for key in PUBLIC_FIELDS}


def _audit(con, row, actor, action, detail):
    con.execute('INSERT INTO outbox_audit(at,outbox_id,revision,actor,event,detail) VALUES(?,?,?,?,?,?)',
                (row['updated_at'], row['id'], row['revision'], actor, action,
                 json.dumps(detail, ensure_ascii=False, sort_keys=True)))


def _save(con, row, actor, action, detail, new=False):
    row['revision'] = 1 if new else row['revision'] + 1
    row['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    if new:
        keys = tuple(row)
        con.execute('INSERT INTO followup_outbox(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')',
                    [row[key] for key in keys])
    else:
        con.execute('''UPDATE followup_outbox SET job_ids=?,task_id=?,status=?,due_date=?,
                    window_start=?,window_end=?,message=?,due_edited=?,revision=?,updated_at=? WHERE id=?''',
                    [row[key] for key in ('job_ids', 'task_id', 'status', 'due_date', 'window_start',
                     'window_end', 'message', 'due_edited', 'revision', 'updated_at', 'id')])
    _audit(con, row, actor, action, detail)


def _draft(con, job_id, candidate, followup_days=90):
    patient, name, index_date = candidate
    prior = con.execute('SELECT * FROM followup_outbox WHERE patient_id=? AND index_date=?',
                        (patient, index_date)).fetchone()
    if prior:
        row = dict(prior)
        if row['name'] != name:
            raise OutboxError(409, 'Patient identifier has a different name; identity review required')
        jobs = json.loads(row['job_ids'])
        if job_id not in jobs:
            row['job_ids'] = json.dumps(sorted([*jobs, job_id]))
            _save(con, row, 'system:extraction', 'source_linked', {'job_id': job_id})
        return row
    try:
        due = _date(index_date) + dt.timedelta(days=followup_days)
    except OverflowError as exc:
        raise OutboxError(422, 'Follow-up date is outside the supported range') from exc
    row = {'id': hashlib.sha256((patient + '\x00' + index_date).encode()).hexdigest()[:32],
           'patient_id': patient, 'name': name, 'index_date': index_date, 'job_id': job_id,
           'job_ids': json.dumps([job_id]), 'task_id': None, 'status': 'draft',
           'due_date': due.isoformat(), 'window_start': None, 'window_end': None,
           'message': DEFAULT_MESSAGE, 'due_edited': 0}
    _save(con, row, 'system:extraction', 'draft_created', {'job_id': job_id}, new=True)
    return row


def candidate_ready(job_id, candidate, followup_days=90):
    """Create one draft per patient and latest eligible visit date, retaining sources."""
    job_id = _text(job_id, 'Job identifier', 128)
    if type(followup_days) is not int or not 1 <= followup_days <= 730:
        raise OutboxError(422, 'Follow-up interval must be 1-730 days')
    selected = _candidate(candidate)
    if not selected:
        return None
    with _db(write=True) as con:
        return _public(_draft(con, job_id, selected, followup_days))


def publication_ready(job_id, candidate, receipt):
    """Link a successful clinical Task once; retries preserve edits and cancellation."""
    job_id = _text(job_id, 'Job identifier', 128)
    selected = _candidate(candidate)
    if not isinstance(receipt, dict):
        raise OutboxError(422, 'Publication receipt is invalid')
    if not selected or not receipt.get('task'):
        return None
    task = receipt['task']
    if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,64}', task):
        raise OutboxError(422, 'Clinical Task identifier is invalid')
    start, end = (_date(receipt.get(key)) for key in ('window_start', 'window_end'))
    if start > end:
        raise OutboxError(422, 'Clinical Task window is reversed')
    with _db(write=True) as con:
        linked = con.execute('SELECT patient_id,index_date FROM followup_outbox WHERE task_id=?', (task,)).fetchone()
        if linked and (linked['patient_id'], linked['index_date']) != (selected[0], selected[2]):
            raise OutboxError(409, 'Clinical Task already belongs to another follow-up obligation')
        row = _draft(con, job_id, selected)
        if row['task_id'] and row['task_id'] != task:
            raise OutboxError(409, 'Follow-up obligation is already linked to a different clinical Task')
        if row['task_id']:
            if (row['window_start'], row['window_end']) != (start.isoformat(), end.isoformat()):
                raise OutboxError(409, 'Clinical Task window changed; explicit reconciliation required')
            return _public(row)
        row.update(task_id=task, window_start=start.isoformat(), window_end=end.isoformat())
        if not row['due_edited']:
            row['due_date'] = (start + (end - start) // 2).isoformat()
        if row['status'] == 'draft':
            row['status'] = 'pending_send'
        _save(con, row, 'system:clinical', 'task_linked', {'job_id': job_id, 'task_id': task})
        return _public(row)


def rows():
    """Return the declared public queue fields, never authentication or source text."""
    with _db() as con:
        return [_public(row) for row in con.execute('SELECT * FROM followup_outbox ORDER BY due_date,id')]


def edit(item_id, payload, actor):
    """Apply a reasoned, optimistic edit; no caller may claim message delivery."""
    actor = _text(actor, 'Actor', 128)
    fields = {'revision', 'due_date', 'message', 'status', 'reason'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise OutboxError(422, 'Expected revision, due_date, message, status and reason')
    if type(payload['revision']) is not int or payload['revision'] < 1:
        raise OutboxError(422, 'Revision is invalid')
    due = _date(payload['due_date']).isoformat()
    message = _text(payload['message'], 'Message', 2000)
    reason = _text(payload['reason'], 'Reason', 500)
    status = payload['status']
    if status not in ('draft', 'pending_send', 'cancelled'):
        raise OutboxError(422, 'Status must be draft, pending_send or cancelled')
    with _db(write=True) as con:
        prior = con.execute('SELECT * FROM followup_outbox WHERE id=?', (item_id,)).fetchone()
        if not prior:
            raise OutboxError(404, 'Follow-up item not found')
        row = dict(prior)
        if row['revision'] != payload['revision']:
            raise OutboxError(409, 'Follow-up item changed; reload before editing')
        if row['status'] == 'completed':
            raise OutboxError(409, 'Completed follow-up items are read-only')
        if status == 'pending_send' and not row['task_id']:
            raise OutboxError(422, 'A reviewed clinical Task is required before pending_send')
        before = {key: row[key] for key in ('due_date', 'message', 'status')}
        if due != row['due_date']:
            row['due_edited'] = 1
        row.update(due_date=due, message=message, status=status)
        _save(con, row, actor, 'edited', {'reason': reason, 'before': before,
                                        'after': {key: row[key] for key in before}})
        return _public(row)


def sync_tasks(tasks):
    """Close linked pending entries from clinical evidence, never from delivery claims."""
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise OutboxError(422, 'Clinical task list is invalid')
    with _db(write=True) as con:
        for task in tasks:
            state = task.get('status')
            if state == 'completed':
                evidence = task.get('evidence', [])
                if (task.get('completion_mode') != 'reviewed-visit-only' or not isinstance(evidence, list) or
                        not any(isinstance(ref, str) and re.fullmatch(r'Encounter/[A-Za-z0-9.-]{1,64}', ref)
                                for ref in evidence)):
                    continue
                new_state = 'completed'
            elif state in ('cancelled', 'entered-in-error'):
                new_state = 'cancelled'
            else:
                continue
            prior = con.execute('SELECT * FROM followup_outbox WHERE task_id=?', (task.get('id'),)).fetchone()
            if not prior or prior['status'] in ('completed', 'cancelled'):
                continue
            row = dict(prior)
            row['status'] = new_state
            _save(con, row, 'system:clinical', 'task_' + new_state,
                  {'task_id': task['id'], 'clinical_status': state,
                   'evidence': task.get('evidence', []) if new_state == 'completed' else []})
    return rows()
