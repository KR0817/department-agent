"""Local task drafts and bounded retrieval; never a clinical publication path."""
import copy
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from department import full_workspace, invoke, payload

router = APIRouter(prefix='/api/department/assistant')
TASKS = ('auto', 'intake', 'knowledge', 'cases', 'prescriptions')
FIELDS = ('symptoms', 'tongue', 'pulse', 'syndrome', 'principle', 'prescription')
ORIGINS = ('patient', 'clinician', 'history', 'operator', 'unknown')
CATEGORIES = ('literature', 'classics', 'formula', 'synthetic', 'unclassified')
PATTERNS = {
    'intake': r'\u6574\u7406|\u8865\u5145|\u8865\u9f50|\u7f3a\u9879|\u4e0a\u4f20|\u56db\u8bca|\bintake\b',
    'knowledge': r'\u77e5\u8bc6|\u6587\u732e|\u53e4\u7c4d|\u6307\u5357|\u6761\u6587|\u65b9\u836f|\bliterature\b',
    'cases': r'\u533b\u6848|\u76f8\u4f3c|\bcases?\b',
    'prescriptions': r'\u5904\u65b9|\u65b9\u5242|\u52a0\u51cf|\u5242\u91cf|\bprescriptions?\b',
}


def invalid(detail='Invalid assistant request'):
    raise HTTPException(422, detail)


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        invalid()


def text(value, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        invalid()
    try:
        value.encode('utf-8')
    except UnicodeError:
        invalid()
    if '\x00' in value:
        invalid()
    return value


def choice(value, options):
    if not isinstance(value, str) or value not in options:
        invalid()
    return value


def validate_draft(value):
    if isinstance(value, dict) and 'context' not in value:
        value = {**value, 'context': {'case_query': '', 'collection_revision': None,
                                    'knowledge_source_id': '', 'knowledge_category': 'all'}}
    exact(value, 'schema instruction task data_origin text supplements context')
    if value['schema'] != 'department-task-v1':
        invalid()
    text(value['instruction'], 1000)
    choice(value['task'], TASKS)
    choice(value['data_origin'], ('synthetic', 'deidentified'))
    text(value['text'], 40000)
    context = value['context']
    exact(context, 'case_query collection_revision knowledge_source_id knowledge_category')
    text(context['case_query'], 200)
    text(context['knowledge_source_id'], 200)
    choice(context['knowledge_category'], ('all', *CATEGORIES))
    if context['collection_revision'] is not None and (type(context['collection_revision']) is not int or not 0 <= context['collection_revision'] <= 1000000):
        invalid()
    supplements = value['supplements']
    if not isinstance(supplements, list) or len(supplements) > 600:
        invalid()
    seen = set()
    for item in supplements:
        exact(item, 'record_id field value status origin')
        if not re.fullmatch(r'REC-[a-f0-9]{24}', text(item['record_id'], 28)):
            invalid()
        choice(item['field'], FIELDS)
        choice(item['status'], ('recorded', 'not_asked', 'unavailable'))
        choice(item['origin'], ORIGINS)
        text(item['value'], 2000, required=item['status'] == 'recorded')
        if item['status'] != 'recorded' and item['value']:
            invalid()
        key = (item['record_id'], item['field'])
        if key in seen:
            invalid()
        seen.add(key)
    return value


def plan(value):
    exact(value, 'instruction task')
    instruction = text(value['instruction'], 1000)
    task = choice(value['task'], TASKS)
    matches = [key for key, pattern in PATTERNS.items() if re.search(pattern, instruction, re.I)]
    selected = task if task != 'auto' else matches[0] if len(matches) == 1 else None
    return {'task': selected, 'candidates': matches, 'needs_selection': selected is None,
            'method': 'bounded_keyword_routing', 'model_called': False,
            'steps': {'intake': ['recognize', 'supplement', 'review', 'preview'],
                      'knowledge': ['choose_public_source', 'ask', 'read_evidence'],
                      'cases': ['search_saved_collection', 'read_matches', 'open_comparison'],
                      'prescriptions': ['open_complete_workspace', 'review', 'explicit_save']}.get(selected, [])}


def apply_supplements(recognized, draft):
    """Keep original records unchanged; additions are distinct unapproved observations."""
    records = copy.deepcopy(recognized['records'])
    by_id = {row['record_id']: row for row in records}
    for item in draft['supplements']:
        if item['record_id'] not in by_id:
            raise HTTPException(409, 'Assistant source changed; recognize again')
        by_id[item['record_id']][item['field']] = item['value'] if item['status'] == 'recorded' else ''
    missing = []
    supplements = {(s['record_id'], s['field']): s for s in draft['supplements']}
    unknown = {'', 'unknown', 'not recorded', 'n/a', '\u672a\u8bb0\u5f55', '\u4e0d\u8be6', '\u672a\u77e5'}
    for row in records:
        for field in FIELDS:
            item = supplements.get((row['record_id'], field))
            if item or row[field].strip().casefold() in unknown:
                missing.append({'record_id': row['record_id'], 'field': field,
                                'status': item['status'] if item else 'not_asked',
                                'origin': item['origin'] if item else 'unknown',
                                'value': item['value'] if item else ''})
    return {**recognized, 'original_records': recognized['records'], 'records': records,
            'missing': missing, 'supplements': draft['supplements'],
            'review_confirmed': False, 'clinical_approval': None}


@contextmanager
def connection(path):
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize(path):
    with connection(path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS assistant_drafts (
            owner TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
            saved_at TEXT NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(owner,id,revision))''')


def draft_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9-]{36}', value):
        raise HTTPException(404, 'Assistant draft not found')
    return value


def public_draft(row, summary=False):
    body = json.loads(row['body'])
    result = {'id': row['id'], 'revision': row['revision'], 'saved_at': row['saved_at'],
              'instruction': body['instruction'][:80], 'task': body['task'], 'data_origin': body['data_origin']}
    if not summary:
        result['draft'] = body
    return result


def drafts(path, owner, identity=None):
    with connection(path) as con:
        if identity:
            row = con.execute('SELECT * FROM assistant_drafts WHERE owner=? AND id=? ORDER BY revision DESC LIMIT 1',
                              (owner, draft_id(identity))).fetchone()
            if not row:
                raise HTTPException(404, 'Assistant draft not found')
            return public_draft(row)
        rows = con.execute('''SELECT d.* FROM assistant_drafts d JOIN
            (SELECT id,MAX(revision) revision FROM assistant_drafts WHERE owner=? GROUP BY id) latest
            ON d.id=latest.id AND d.revision=latest.revision WHERE d.owner=?
            ORDER BY d.saved_at DESC,d.id LIMIT 100''', (owner, owner)).fetchall()
        return {'drafts': [public_draft(row, True) for row in rows]}


def save_draft(path, owner, identity, value):
    draft_id(identity)
    exact(value, 'expected_revision draft')
    revision = value['expected_revision']
    if type(revision) is not int or not 0 <= revision <= 1000000:
        invalid()
    body = json.dumps(validate_draft(value['draft']), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    with connection(path) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM assistant_drafts WHERE owner=? AND id=? ORDER BY revision DESC LIMIT 1',
                          (owner, identity)).fetchone()
        current = row['revision'] if row else 0
        if row and current == revision + 1 and row['body'] == body:
            return public_draft(row)
        if current != revision:
            raise HTTPException(409, 'Assistant draft changed; reload before saving')
        if not row and con.execute('SELECT COUNT(DISTINCT id) FROM assistant_drafts WHERE owner=?', (owner,)).fetchone()[0] >= 100:
            raise HTTPException(429, 'Assistant draft limit reached')
        saved_at = datetime.now(timezone.utc).isoformat()
        con.execute('INSERT INTO assistant_drafts VALUES(?,?,?,?,?)', (owner, identity, current + 1, saved_at, body))
        return public_draft({'id': identity, 'revision': current + 1, 'saved_at': saved_at, 'body': body})


def draft_history(path, owner, identity, before=1000002):
    """Keyset pagination keeps recovery bounded without changing saved versions."""
    draft_id(identity)
    with connection(path) as con:
        if not con.execute('SELECT 1 FROM assistant_drafts WHERE owner=? AND id=? LIMIT 1',
                           (owner, identity)).fetchone():
            raise HTTPException(404, 'Assistant draft not found')
        rows = con.execute('''SELECT * FROM assistant_drafts WHERE owner=? AND id=? AND revision<?
            ORDER BY revision DESC LIMIT 21''', (owner, identity, before)).fetchall()
        return {'versions': [public_draft(row, True) for row in rows[:20]],
                'next_before': rows[19]['revision'] if len(rows) > 20 else None}


def draft_revision(path, owner, identity, revision):
    with connection(path) as con:
        row = con.execute('SELECT * FROM assistant_drafts WHERE owner=? AND id=? AND revision=?',
                          (owner, draft_id(identity), revision)).fetchone()
        if not row:
            raise HTTPException(404, 'Assistant draft version not found')
        return public_draft(row)


def search_cases(snapshot, query):
    query = text(query, 200, required=True).casefold()
    terms = list(dict.fromkeys(re.findall(r'[\w-]+', query)))
    if not terms or len(terms) > 12:
        invalid()
    matches = []
    # ponytail: bounded lexical search over at most 1000 saved records; add an index only after measurement.
    for record in snapshot['records']:
        fields = {key: [term for term in terms if term in record.get(key, '').casefold()]
                  for key in ('condition', *FIELDS)}
        fields = {key: values for key, values in fields.items() if values}
        if fields:
            matches.append({'record': {key: record[key] for key in ('record_id', 'subject_code', 'episode_code',
                'visit_code', 'date', 'condition', *FIELDS, 'source_sha256', 'evidence')},
                'matched_fields': fields, 'matched_terms': sorted({term for values in fields.values() for term in values})})
    matches.sort(key=lambda item: (-len(item['matched_terms']), item['record']['record_id']))
    revision = snapshot['revision']
    return {'matches': matches[:10], 'total': len(matches), 'revision': revision,
            'data_origin': 'synthetic' if snapshot['synthetic'] else 'deidentified',
            'method': 'lexical_saved_collection', 'clinical_approval': None,
            'collection_url': f'/api/department/mingyirx/imported.html?revision={revision}' if revision else None}


def library(value):
    result = copy.deepcopy(value)
    for source in result['sources']:
        category = source.get('knowledge_category')
        if category not in CATEGORIES:
            category = 'synthetic' if (source.get('data_origin') == 'synthetic' or value.get('data_origin') == 'synthetic') else 'literature'
        source['knowledge_category'] = category
    result['categories'] = [{'id': key, 'count': sum(s['knowledge_category'] == key for s in result['sources'])} for key in CATEGORIES]
    return result


def owner(request):
    user = getattr(request.state, 'user', None)
    if not user or not isinstance(user.get('id'), str):
        raise HTTPException(401, 'Sign in with your username and password')
    return user['id']


@router.post('/plan')
async def task_plan(request: Request):
    owner(request)
    return plan(await payload(request, 8192))


@router.post('/prepare')
async def prepare(request: Request):
    owner(request)
    draft = validate_draft(await payload(request, 524288))
    recognized = await invoke('mingyirx', 'recognize', {'text': draft['text'], 'data_origin': draft['data_origin']})
    return apply_supplements(recognized, draft)


@router.get('/drafts')
async def list_drafts(request: Request):
    return await run_in_threadpool(drafts, request.app.state.assistant_db, owner(request))


@router.get('/drafts/{identity}')
async def get_draft(identity: str, request: Request):
    return await run_in_threadpool(drafts, request.app.state.assistant_db, owner(request), identity)


@router.get('/drafts/{identity}/history')
async def get_history(identity: str, request: Request, before: int = Query(1000002, ge=1, le=1000002)):
    return await run_in_threadpool(draft_history, request.app.state.assistant_db, owner(request), identity, before)


@router.get('/drafts/{identity}/revisions/{revision}')
async def get_revision(identity: str, revision: int, request: Request):
    if not 1 <= revision <= 1000001:
        invalid()
    return await run_in_threadpool(draft_revision, request.app.state.assistant_db, owner(request), identity, revision)


@router.post('/drafts/{identity}')
async def store_draft(identity: str, request: Request):
    account = owner(request)
    value = await payload(request, 524288)
    return await run_in_threadpool(save_draft, request.app.state.assistant_db, account, identity, value)


@router.get('/library')
async def get_library(request: Request):
    owner(request)
    return library(await invoke('knowledge', 'library'))


@router.post('/cases')
async def get_cases(request: Request):
    owner(request)
    value = await payload(request, 4096)
    exact(value, 'query')
    text(value['query'], 200, required=True)
    from department_rx_workspace import FullError
    try:
        workspace = await run_in_threadpool(full_workspace, request)
        snapshot = await run_in_threadpool(workspace.snapshot)
        return search_cases(snapshot, value['query'])
    except FullError:
        raise HTTPException(503, 'Assistant saved collection unavailable') from None
