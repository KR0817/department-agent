"""Authenticated local upload workbench. No external inference or messaging."""
import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
import threading
import time
import uuid
import urllib.request
import zipfile
from functools import lru_cache
from typing import Literal
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, StrictBool
import clinical
import accounts
import account_recovery
import patient_registry
from patient_attention import evaluate_attention
import outbox
import care
import care_demo
import source_map
import patient_risk
from patient_overview import load_demo_overview, _attention_visits
from extract import read_document, extract_text, extract_csv, validate_result, LABELS, OCR, pinned_model_digest

DATA = pathlib.Path(os.environ.get('AGENT_DATA', '/data'))
ROOT = pathlib.Path(__file__).resolve().parent
DEMO = os.environ.get('AGENT_DEMO') == '1'
DOCUMENT_MODE = 'synthetic' if DEMO else os.environ.get('AGENT_DOCUMENT_MODE', 'synthetic')
if DOCUMENT_MODE not in ('synthetic', 'local'):
    raise RuntimeError('Invalid document mode')
PORT = int(os.environ.get('AGENT_PORT', '13002'))
COOKIE = 'sjd_agent' if DEMO else 'sjd_workbench_' + str(PORT)
RECOVERY_COOKIE = 'sjd_recovery_' + str(PORT)
RECOVERY_PATH = '/api/auth/recovery'
HOSTS = (f'localhost:{PORT}', f'127.0.0.1:{PORT}', 'testserver')
ORIGINS = (f'http://localhost:{PORT}', f'http://127.0.0.1:{PORT}')
DATA.mkdir(parents=True, exist_ok=True)
(DATA / 'sources').mkdir(exist_ok=True)
if DEMO:
    marker = DATA / 'SYNTHETIC_ONLY'
    if not marker.exists() or marker.read_bytes() != b'simulated\n':
        raise RuntimeError('Demo requires a newly provisioned synthetic data directory')
MODEL_URL = os.environ.get('MODEL_URL', 'http://model:11434')
MODEL = os.environ.get('AGENT_MODEL', 'qwen3:4b')
pinned_model_digest(MODEL)
SESSIONS = {}
WRITE_LOCK = threading.Lock()
SOURCE_MAP_LOCK = threading.Lock()


@contextlib.contextmanager
def db():
    con = sqlite3.connect(DATA / 'jobs.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


with db() as con:
    con.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, sha TEXT UNIQUE, filename TEXT, suffix TEXT, state TEXT, text TEXT, method TEXT, candidate TEXT, version TEXT, error TEXT, receipt TEXT, created TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT, job TEXT, event TEXT, detail TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS reviews (job TEXT, revision INTEGER, field_id TEXT, decision TEXT, PRIMARY KEY(job,revision))')
    con.execute('CREATE TABLE IF NOT EXISTS publications (job TEXT, revision INTEGER, plan TEXT, progress TEXT, receipt TEXT, state TEXT, error TEXT, PRIMARY KEY(job,revision))')
    patient_registry.initialize(con)
    care.initialize(con)
    con.execute("UPDATE jobs SET state='queued' WHERE state IN ('reading','extracting')")
    # Publication is idempotent; explicit review retry is required after a process interruption.
    con.execute("UPDATE jobs SET state='partial', error='Publication interrupted; retry the frozen review' WHERE state='publishing'")
    con.execute("UPDATE publications SET state='partial', error='Publication interrupted; retry the frozen review' WHERE state='publishing'")

if not DEMO:
    accounts.initialize(DATA / 'accounts.sqlite')
outbox.initialize(DATA / 'jobs.sqlite')


@contextlib.contextmanager
def care_db(scope):
    if scope not in ('business', 'demo'):
        raise care.CareError(404, 'Care scope not found')
    con = sqlite3.connect(DATA / ('demo-workflow.sqlite' if scope == 'demo' else 'jobs.sqlite'), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            care.initialize(con)
            yield con
    finally:
        con.close()


def event(job, action, detail=''):
    with db() as con:
        con.execute('INSERT INTO audit(at,job,event,detail) VALUES(?,?,?,?)', (dt.datetime.now(dt.timezone.utc).isoformat(), job, action, detail))


def update(job, **values):
    with db() as con:
        con.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', [*values.values(), job])


def job_record(job):
    with db() as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
        selected = patient_registry.context(con, job)
    if not row:
        raise HTTPException(404, 'Job not found')
    value = dict(row)
    value['patient_context'] = selected
    for key in ('candidate', 'receipt'):
        value[key] = json.loads(value[key]) if value[key] else None
    with db() as con:
        reviews = con.execute('SELECT * FROM reviews WHERE job=? ORDER BY revision', (job,)).fetchall()
        publications = con.execute('SELECT * FROM publications WHERE job=? ORDER BY revision', (job,)).fetchall()
    value['history'] = [{**json.loads(r['decision']), 'field_id': r['field_id'], 'revision': r['revision']} for r in reviews]
    value['review_revision'] = reviews[-1]['revision'] if reviews else 0
    value['publication_history'] = []
    archived = {}
    for row in publications:
        pub = dict(row)
        for key in ('plan', 'progress', 'receipt'):
            pub[key] = json.loads(pub[key]) if pub[key] else None
        pub['followup_days'] = pub['plan']['followup_days']
        for field_id, item in (pub['progress'] or {}).get('fields', {}).items():
            if item.get('state') == 'archived':
                archived[field_id] = item
        value['publication_history'].append(pub)
    value['publication'] = value['publication_history'][-1] if publications else None
    decisions = {r['field_id']: r for r in value['history']}
    value['fields'] = []
    if value['candidate']:
        for visit in value['candidate']['visits']:
            event_id = visit.get('event_id') or 'source-' + value['sha']
            for fact in visit['facts']:
                field_id = hashlib.sha256((visit['date'] + '|' + event_id + '|' + fact['code']).encode()).hexdigest()[:24]
                value['fields'].append({'id': field_id, 'event_id': event_id, 'date': visit['date'],
                    'original': fact, 'decision': decisions.get(field_id), 'archive': archived.get(field_id)})
    value['legacy_read_only'] = value['state'] == 'published' and not publications
    return value


def worker(stop=None):
    stop = stop or threading.Event()
    while not stop.is_set():
        with db() as con:
            row = con.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        if not row:
            stop.wait(0.25)
            continue
        job = row['id']
        try:
            update(job, state='reading', error=None)
            event(job, 'read_source')
            text, method = read_document(DATA / 'sources' / job, row['suffix'], require_synthetic=DOCUMENT_MODE == 'synthetic')
            update(job, text=text, method=method, state='extracting')
            event(job, 'extract_local', 'deterministic-csv' if row['suffix'] == '.csv' else MODEL)
            if DEMO and row['suffix'] != '.csv':
                raise ValueError('Synthetic demo uses deterministic CSV only; model calls are disabled')
            with db() as con:
                selected = patient_registry.context(con, job)
            if selected:
                candidate = (extract_csv(text, patient_context=selected) if row['suffix'] == '.csv'
                             else extract_text(text, MODEL_URL, MODEL, patient_context=selected))
            else:
                candidate = extract_csv(text) if row['suffix'] == '.csv' else extract_text(text, MODEL_URL, MODEL)
            patient_registry.validate_candidate(candidate, selected)
            serialized = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
            version = hashlib.sha256((row['sha'] + serialized).encode()).hexdigest()
            update(job, candidate=serialized, version=version, state='review')
            outbox.candidate_ready(job, candidate)
            event(job, 'candidate_ready', version)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, patient_registry.RegistryError)) else 'Local extraction unavailable: ' + type(exc).__name__
            update(job, state='blocked' if isinstance(exc, (ValueError, patient_registry.RegistryError)) else 'failed', error=message)
            event(job, 'extraction_failed', type(exc).__name__)


@contextlib.asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=5)


class RequestBodyLimit:
    """Bound the full body before multipart parsing, including chunked requests."""

    def __init__(self, app, limit=11_000_000):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        full_rx = scope.get('path', '').startswith('/api/department/mingyirx/api/')
        limit = 12 * 1024 * 1024 if full_rx else self.limit
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > limit:
                response = JSONResponse({'error': 'REQUEST_TOO_LARGE'} if full_rx else {'detail': 'Request body exceeds 11 MB'}, status_code=413)
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        payload = bytes(body)
        del body
        pending = True

        async def bounded_receive():
            nonlocal pending
            if pending:
                pending = False
                return {'type': 'http.request', 'body': payload, 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
# The authentication/Origin middleware below stays outside this bounded buffer.
app.add_middleware(RequestBodyLimit)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Validation details can echo password/form values; never return raw input.
    return JSONResponse({'detail': 'Invalid request fields or value limits'}, status_code=422)


@app.exception_handler(accounts.AccountError)
async def account_error(request, exc):
    return JSONResponse({'detail': exc.message}, status_code=exc.status)


@app.exception_handler(outbox.OutboxError)
async def outbox_error(request, exc):
    return JSONResponse({'detail': exc.message}, status_code=exc.status)


@app.exception_handler(patient_registry.RegistryError)
async def registry_error(request, exc):
    return JSONResponse({'detail': exc.message}, status_code=exc.status)


@app.exception_handler(care.CareError)
async def care_error(request, exc):
    return JSONResponse({'detail': exc.message}, status_code=exc.status)


def actor(request):
    return request.state.user['username']


@app.middleware('http')
async def boundary(request: Request, call_next):
    host = request.headers.get('host', '')
    if host not in HOSTS:
        return JSONResponse({'detail': 'Local host required'}, status_code=403, headers={'Cache-Control': 'no-store'})
    try:
        length = int(request.headers.get('content-length', '0'))
    except ValueError:
        return JSONResponse({'detail': 'Invalid content length'}, status_code=400, headers={'Cache-Control': 'no-store'})
    full_rx = request.url.path.startswith('/api/department/mingyirx/')
    if full_rx and (request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none')
                    or request.headers.get('origin') not in (None, *ORIGINS)):
        return JSONResponse({'error': 'SAME_ORIGIN_REQUIRED'}, status_code=403, headers={'Cache-Control': 'no-store'})
    body_limit = 12 * 1024 * 1024 if request.url.path.startswith('/api/department/mingyirx/api/') else 11_000_000
    if length < 0 or length > body_limit:
        return JSONResponse({'error': 'REQUEST_TOO_LARGE'} if full_rx else {'detail': 'Upload exceeds 10 MB'}, status_code=413, headers={'Cache-Control': 'no-store'})
    if request.url.path.startswith('/api/'):
        if request.method != 'GET' and request.headers.get('origin') not in ORIGINS:
            return JSONResponse({'error': 'SAME_ORIGIN_REQUIRED'} if full_rx else {'detail': 'Same-origin action required'}, status_code=403, headers={'Cache-Control': 'no-store'})
        if request.url.path.startswith(RECOVERY_PATH + '/') and request.method == 'POST' and request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return JSONResponse({'detail': 'Invalid request fields or value limits'}, status_code=422,
                                headers={'Cache-Control': 'no-store'})
        token = request.cookies.get(COOKIE, '')
        user = ({'id': 'demo', 'username': SESSIONS[token], 'role': 'admin', 'active': True}
                if DEMO and token in SESSIONS else None) if DEMO else accounts.session(token)
        request.state.user = user
        public = ('/api/auth/state', '/api/auth/setup', '/api/auth/login', '/api/auth/logout',
                  '/api/auth/recovery/request', '/api/auth/recovery/state', '/api/auth/recovery/complete')
        if not user and request.url.path not in public:
            return JSONResponse({'error': 'AUTHENTICATION_REQUIRED'} if full_rx else {'detail': 'Sign in with your username and password'}, status_code=401, headers={'Cache-Control': 'no-store'})
        if request.url.path == '/api/patient-registry' and request.method == 'POST' and request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return JSONResponse({'detail': 'Invalid request fields or value limits'}, status_code=422,
                                headers={'Cache-Control': 'no-store'})
        if request.url.path.startswith('/api/admin/') and (not user or user['role'] != 'admin'):
            return JSONResponse({'detail': 'Administrator access required'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    framed_rx = (full_rx and response.status_code == 200
                 and response.headers.get('content-type', '').startswith('text/html')
                 and (request.url.path.startswith('/api/department/mingyirx/site/')
                      or request.url.path == '/api/department/mingyirx/imported.html')
                 and 'Content-Security-Policy' in response.headers)
    if not framed_rx:
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.get('/')
def home():
    response = FileResponse(ROOT / 'static' / 'index.html')
    if DEMO:
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = 'synthetic-operator-' + uuid.uuid4().hex[:10]
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict')
    return response


class Credentials(BaseModel):
    model_config = {'extra': 'forbid'}
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class NewUser(Credentials):
    role: Literal['admin', 'staff'] = 'staff'


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class RecoveryRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    username: str = Field(min_length=1, max_length=64)


class RecoveryComplete(BaseModel):
    model_config = {'extra': 'forbid'}
    request_id: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=128)


def recovery_enabled():
    if DEMO:
        raise HTTPException(409, 'Password recovery is unavailable in deterministic demo mode')


@app.post('/api/auth/recovery/request')
def recovery_request(value: RecoveryRequest, request: Request):
    recovery_enabled()
    result, token = account_recovery.request_recovery(value.username, request.cookies.get(RECOVERY_COOKIE, ''),
                                                     request.client.host if request.client else 'local')
    response = JSONResponse(result)
    response.set_cookie(RECOVERY_COOKIE, token, httponly=True, samesite='strict', path=RECOVERY_PATH,
                        max_age=max(0, int(result['expires_at'] - time.time())))
    return response


@app.get('/api/auth/recovery/state')
def recovery_state(request: Request):
    recovery_enabled()
    return account_recovery.state(request.cookies.get(RECOVERY_COOKIE, ''))


@app.post('/api/auth/recovery/complete')
def recovery_complete(value: RecoveryComplete, request: Request):
    recovery_enabled()
    result = account_recovery.complete(request.cookies.get(RECOVERY_COOKIE, ''), value.request_id,
                                       value.new_password, value.confirmation)
    response = JSONResponse(result)
    response.delete_cookie(RECOVERY_COOKIE, path=RECOVERY_PATH, httponly=True, samesite='strict')
    response.delete_cookie(COOKIE, path='/')
    return response


def signed_in(result):
    user, token = result
    response = JSONResponse({'user': user})
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/', max_age=accounts.TTL_SECONDS)
    return response


@app.get('/api/auth/state')
def auth_state(request: Request):
    return {'setup_required': False if DEMO else accounts.setup_required(),
            'authenticated': bool(request.state.user), 'user': request.state.user}


@app.post('/api/auth/setup')
def setup(value: Credentials):
    if DEMO:
        raise HTTPException(409, 'Account setup is unavailable in deterministic demo mode')
    result = accounts.setup(value.username, value.password)
    event('', 'account_initialized', result[0]['username'])
    return signed_in(result)


@app.post('/api/auth/login')
def login(value: Credentials, request: Request):
    if DEMO:
        raise HTTPException(409, 'Account login is unavailable in deterministic demo mode')
    result = accounts.login(value.username, value.password, request.client.host if request.client else 'local')
    event('', 'signed_in', result[0]['username'])
    return signed_in(result)


@app.post('/api/auth/logout')
def logout(request: Request):
    token = request.cookies.get(COOKIE, '')
    if DEMO:
        SESSIONS.pop(token, None)
    else:
        accounts.logout(token)
    response = JSONResponse({'signed_out': True})
    response.delete_cookie(COOKIE, path='/')
    return response


@app.post('/api/auth/password')
def password(value: PasswordChange, request: Request):
    if DEMO:
        raise HTTPException(409, 'Demo has no password')
    result = accounts.change_password(request.cookies.get(COOKIE, ''), value.current_password, value.new_password)
    event('', 'password_changed', actor(request))
    return signed_in(result)


@app.get('/api/admin/users')
def users():
    return {'users': [] if DEMO else accounts.list_users()}


@app.post('/api/admin/users')
def create_user(value: NewUser, request: Request):
    if DEMO:
        raise HTTPException(409, 'Demo has no persistent accounts')
    user = accounts.create_user(value.username, value.password, value.role)
    event('', 'account_created', json.dumps({'actor': actor(request), 'username': user['username'], 'role': user['role']}))
    return user


@app.get('/api/status')
def status(request: Request):
    if DEMO:
        return {'model': 'deterministic-csv', 'model_ready': True, 'mode': 'synthetic-demo',
                'scope': 'synthetic-only', 'fields': LABELS, 'notifications_enabled': False,
                'operator': actor(request), 'user': request.state.user, 'document_mode': DOCUMENT_MODE,
                'ocr_ready': False, 'outbound_mode': 'pending_only'}
    try:
        with urllib.request.urlopen(MODEL_URL + '/api/tags', timeout=4) as response:
            models = json.load(response).get('models', [])
        ready = any(m['name'] == MODEL and m.get('digest') == pinned_model_digest(MODEL) for m in models)
    except Exception:
        ready, models = False, []
    return {'model': MODEL, 'model_ready': ready, 'model_digest': next((m.get('digest') for m in models if m['name'] == MODEL), None),
            'scope': 'local-development', 'fields': LABELS, 'notifications_enabled': False,
            'operator': actor(request), 'user': request.state.user, 'document_mode': DOCUMENT_MODE,
            'ocr_ready': OCR.executable.is_file(), 'outbound_mode': 'pending_only'}


@app.get('/api/jobs')
def jobs():
    with db() as con:
        rows = con.execute('SELECT id,filename,state,error,created FROM jobs ORDER BY created DESC LIMIT 100').fetchall()
    return [dict(r) for r in rows]


@app.get('/api/jobs/{job}')
def get_job(job: str):
    return job_record(job)


@app.get('/api/jobs/{job}/source')
def source(job: str):
    record = job_record(job)
    return FileResponse(DATA / 'sources' / record['id'], filename=record['filename'])


@lru_cache(maxsize=16)
def source_mapping(job, sha, suffix, fallback):
    with SOURCE_MAP_LOCK:
        return source_map.build(DATA / 'sources' / job, suffix, fallback, OCR)


@app.get('/api/jobs/{job}/source-map')
def get_source_map(job: str, field_id: str = ''):
    record = job_record(job)
    field = next((f for f in record['fields'] if f['id'] == field_id), None)
    if field_id and field is None:
        raise HTTPException(404, 'Source field not found')
    try:
        mapping = source_mapping(job, record['sha'], record['suffix'], record['text'] or '')
        return {**mapping, 'source_sha': record['sha'], 'field_id': field_id,
                'quote': field['original']['quote'] if field else '',
                'matches': source_map.locate(mapping, field['original']['quote']) if field else []}
    except Exception:
        raise HTTPException(503, 'Source map unavailable; download the original') from None


@app.get('/api/jobs/{job}/page/{number}')
def source_page(job: str, number: int):
    record = job_record(job)
    try:
        data, media_type = source_map.page_image(DATA / 'sources' / job, record['suffix'], number)
        return Response(data, media_type=media_type)
    except Exception:
        raise HTTPException(404, 'Source page unavailable; download the original') from None


@app.post('/api/upload')
async def upload(request: Request, file: UploadFile = File(...), synthetic: bool = Form(False),
                 patient_id: str | None = Form(None)):
    if DOCUMENT_MODE == 'synthetic' and not synthetic:
        raise HTTPException(400, 'Synthetic-only acknowledgement required')
    if not DEMO and not patient_id:
        raise HTTPException(422, 'Select or register a patient before uploading')
    suffix = pathlib.Path(file.filename or '').suffix.lower()
    if suffix not in ('.txt', '.md', '.csv', '.docx', '.pdf', '.png', '.jpg', '.jpeg'):
        raise HTTPException(400, 'Unsupported document format')
    data = await file.read(10_000_001)
    if not data or len(data) > 10_000_000:
        raise HTTPException(413, 'Upload must contain 1 byte to 10 MB')
    digest = hashlib.sha256(data).hexdigest()
    with WRITE_LOCK, db() as con:
        con.execute('BEGIN IMMEDIATE')
        selected = patient_registry.lookup(con, patients(), patient_id) if patient_id else None
        prior = con.execute('SELECT id,candidate FROM jobs WHERE sha=?', (digest,)).fetchone()
        if prior:
            patient_registry.duplicate(con, prior, selected)
            return {'id': prior['id'], 'duplicate': True, **({'patient_id': selected['patient_id']} if selected else {})}
        job = str(uuid.uuid4())
        con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,created) VALUES(?,?,?,?,?,?)',
            (job, digest, pathlib.Path(file.filename).name[:120], suffix, 'queued', dt.datetime.now(dt.timezone.utc).isoformat()))
        if selected:
            binding = patient_registry.associate(con, job, selected, actor(request))
            con.execute('INSERT INTO audit(at,job,event,detail) VALUES(?,?,?,?)',
                        (binding['selected_at'], job, 'patient_selected',
                         json.dumps({'actor': binding['actor'], 'patient_id': binding['patient_id']})))
        # Keep original files immutable even if an unexpected filename collision occurs.
        with (DATA / 'sources' / job).open('xb') as source:
            source.write(data)
    event(job, 'source_uploaded', digest)
    return {'id': job, 'duplicate': False, **({'patient_id': selected['patient_id']} if selected else {})}


class Approval(BaseModel):
    version: str
    reviewed: bool
    review_revision: int = Field(ge=0)
    followup_days: int = Field(default=90, ge=1, le=730)
    accept_defaults: StrictBool = False


class Review(BaseModel):
    model_config = {'extra': 'forbid'}
    version: str
    review_revision: int = Field(ge=0)
    field_id: str
    action: Literal['accept', 'modify', 'reject', 'defer'] = 'modify'
    value: str | None = Field(default=None, max_length=4000)
    unit: str | None = Field(default=None, max_length=100)
    quote: str | None = Field(default=None, max_length=6000)
    reason: str = Field(default='', max_length=1000)


def save_review(job, review, request, correction=False):
    with WRITE_LOCK:
        record = job_record(job)
        if record['version'] != review.version or record['review_revision'] != review.review_revision:
            raise HTTPException(409, 'Review changed; reload before saving')
        if record['state'] not in ('review', 'published') or record['legacy_read_only']:
            raise HTTPException(409, 'Review is unavailable or publication is frozen')
        field = next((f for f in record['fields'] if f['id'] == review.field_id), None)
        if not field:
            raise HTTPException(422, 'Unknown field')
        archived = field['archive']
        if correction:
            if not archived or review.action != 'modify':
                raise HTTPException(409, 'Correction requires an archived field and modify action')
            if field['decision'] and field['decision']['revision'] > archived.get('revision', 0):
                raise HTTPException(409, 'A correction is already pending')
        elif archived:
            raise HTTPException(409, 'Archived fields require an explicit correction')
        if review.action != 'accept' and not review.reason.strip():
            raise HTTPException(422, 'A reason is required')
        fact = dict(field['original'])
        if review.action == 'modify':
            if review.value is None or review.quote is None or review.unit is None:
                raise HTTPException(422, 'Modified value, unit and source quote are required')
            fact.update(value=review.value.strip(), unit=review.unit.strip(), quote=review.quote)
            try:
                # The date/event remain immutable; validation checks edited lexical evidence.
                validate_result({'visits': [{'date': field['date'], 'date_quote': field['date'], 'facts': [fact]}]}, record['text'])
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        decision = {**fact, 'action': review.action, 'reason': review.reason.strip(),
                    'actor': actor(request),
                    'at': dt.datetime.now(dt.timezone.utc).isoformat()}
        if correction:
            if fact['value'] == field['decision']['value'] and fact['unit'] == field['decision']['unit']:
                raise HTTPException(422, 'Correction must change the archived value or unit')
            decision['correction_of'] = archived['observation']
        revision = record['review_revision'] + 1
        with db() as con:
            con.execute('INSERT INTO reviews VALUES(?,?,?,?)', (job, revision, review.field_id, json.dumps(decision)))
            con.execute('INSERT INTO audit(at,job,event,detail) VALUES(?,?,?,?)',
                        (decision['at'], job, 'correction_reviewed' if correction else 'field_reviewed',
                         json.dumps({**decision, 'field_id': review.field_id, 'revision': revision})))
            con.execute("UPDATE jobs SET state='review', error=NULL WHERE id=?", (job,))
        return job_record(job)


@app.post('/api/jobs/{job}/review')
def review_field(job: str, review: Review, request: Request):
    return save_review(job, review, request)


@app.post('/api/jobs/{job}/correction')
def correction(job: str, review: Review, request: Request):
    return save_review(job, review, request, correction=True)


@app.post('/api/jobs/{job}/approve')
def approve(job: str, approval: Approval, request: Request):
    with WRITE_LOCK:
        record = job_record(job)
        patient_registry.validate_candidate(record['candidate'], record['patient_context'])
        if record['publication']:
            patient_registry.validate_candidate(record['publication']['plan']['candidate'], record['patient_context'])
        with db() as con:
            patient_registry.validate_registered_identity(con, record['candidate'])
            if record['publication']:
                patient_registry.validate_registered_identity(con, record['publication']['plan']['candidate'])
        if not approval.reviewed or record['version'] != approval.version:
            raise HTTPException(409, 'Current source-backed candidates require explicit review')
        if record['legacy_read_only'] or record['state'] not in ('review', 'published', 'partial', 'publishing'):
            raise HTTPException(409, 'Job is not ready for review')
        publication = record['publication']
        current_revision = record['review_revision']
        # A lost response may replay the pre-default revision, but never a plan
        # invalidated by subsequent edits. Current-revision legacy retries stay valid.
        replay = bool(publication and publication['revision'] == current_revision
            and publication['plan']['version'] == approval.version
            and (approval.review_revision == current_revision
                 or (approval.accept_defaults == publication['plan'].get('accept_defaults', False)
                     and approval.review_revision == publication['plan'].get('input_review_revision'))))
        if approval.review_revision != current_revision and not replay:
            raise HTTPException(409, 'Current source-backed candidates require explicit review')
        if publication and publication['followup_days'] != approval.followup_days:
            raise HTTPException(409, 'Follow-up interval is frozen for this job; explicit rescheduling is separate')
        if replay:
            publication_revision = publication['revision']
            if publication['state'] == 'published':
                outbox.publication_ready(job, publication['plan']['candidate'], publication['receipt'])
                return publication['receipt']
            plan, progress = publication['plan'], publication['progress']
        elif record['state'] == 'review':
            if not approval.accept_defaults and any(not f['decision'] for f in record['fields']):
                raise HTTPException(409, 'Every field needs an explicit decision')
            reviewer = actor(request)
            publication_revision = current_revision
            defaults = []
            visits = {}
            for field in record['fields']:
                decision = field['decision']
                if not decision:
                    if field['archive']:
                        continue
                    publication_revision += 1
                    decision = {**field['original'], 'action': 'accept', 'reason': '',
                        'actor': reviewer, 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'origin': 'batch_default_accept'}
                    defaults.append((publication_revision, field['id'], decision))
                    decision = {**decision, 'field_id': field['id'], 'revision': publication_revision}
                if decision['action'] not in ('accept', 'modify'):
                    continue
                if field['archive'] and field['archive'].get('revision', 0) >= decision['revision']:
                    continue
                key = (field['date'], field['event_id'])
                visit = visits.setdefault(key, {'date': field['date'], 'event_id': field['event_id'], 'facts': []})
                visit['facts'].append({**{k: decision[k] for k in ('code', 'value', 'unit', 'quote')},
                    'field_id': field['id'], 'revision': decision['revision'], 'review': decision,
                    **({'correction_of': decision['correction_of']} if decision.get('correction_of') else {})})
            if not visits:
                raise HTTPException(409, 'No accepted or modified fields to archive')
            plan = {'candidate': {**record['candidate'], 'visits': list(visits.values())},
                    'followup_days': approval.followup_days,
                    'reviewer': reviewer, 'version': approval.version,
                    'input_review_revision': approval.review_revision, 'accept_defaults': approval.accept_defaults}
            progress = {'fields': {fact['field_id']: {'state': 'pending', 'revision': fact['revision']}
                                   for visit in plan['candidate']['visits'] for fact in visit['facts']}}
            with db() as con:
                # Default decisions are the document-level confirmation, committed
                # with its frozen publication plan so retries cannot duplicate them.
                for revision, field_id, decision in defaults:
                    con.execute('INSERT INTO reviews VALUES(?,?,?,?)', (job, revision, field_id, json.dumps(decision)))
                    con.execute('INSERT INTO audit(at,job,event,detail) VALUES(?,?,?,?)',
                        (decision['at'], job, 'field_reviewed',
                         json.dumps({**decision, 'field_id': field_id, 'revision': revision})))
                con.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?)',
                    (job, publication_revision, json.dumps(plan), json.dumps(progress), None, 'publishing', None))
                con.execute("UPDATE jobs SET state='publishing' WHERE id=?", (job,))
        else:
            raise HTTPException(409, 'Job is not ready for review')
        update(job, state='publishing')
        with db() as con:
            con.execute("UPDATE publications SET state='publishing', error=NULL WHERE job=? AND revision=?",
                        (job, publication_revision))
        event(job, 'human_reviewed', approval.version)
        def checkpoint(value):
            with db() as con:
                con.execute('UPDATE publications SET progress=? WHERE job=? AND revision=?',
                            (json.dumps(value), job, publication_revision))
        try:
            receipt = clinical.publish(plan['candidate'], record['sha'], plan['followup_days'], plan['reviewer'],
                                       progress=progress, on_progress=checkpoint)
            with db() as con:
                con.execute("UPDATE publications SET state='published', receipt=?, error=NULL WHERE job=? AND revision=?",
                            (json.dumps(receipt), job, publication_revision))
            update(job, state='published', receipt=json.dumps(receipt), error=None)
            event(job, 'published', json.dumps(receipt))
            outbox.publication_ready(job, plan['candidate'], receipt)
            return receipt
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Publication interrupted; retry available'
            with db() as con:
                con.execute("UPDATE publications SET state='partial', error=? WHERE job=? AND revision=?",
                            (message, job, publication_revision))
            update(job, state='partial', error=message)
            event(job, 'publication_failed', type(exc).__name__)
            raise HTTPException(409, message) from None


@app.post('/api/jobs/{job}/retry')
def retry(job: str):
    record = job_record(job)
    if record['state'] not in ('failed', 'blocked'):
        raise HTTPException(409, 'Only failed/blocked jobs can retry')
    update(job, state='queued', error=None)
    event(job, 'retry_requested')
    return {'queued': True}


@app.get('/api/patients')
def patients():
    """Project the small local queue; larger histories need pagination or a stored projection."""
    with db() as con:
        rows = con.execute('SELECT id FROM jobs WHERE candidate IS NOT NULL ORDER BY created').fetchall()
    result = {}
    for row in rows:
        record = job_record(row['id'])
        c = record['candidate']
        patient_registry.validate_candidate(c, record['patient_context'])
        for publication in record['publication_history']:
            progress = publication['progress'] or {}
            if not any(f.get('state') == 'archived' for f in progress.get('fields', {}).values()):
                continue
            patient_id = (publication['receipt'] or {}).get('patient') or progress.get('patient')
            if c['patient_id'] in result and result[c['patient_id']]['name'] != c['name']:
                raise patient_registry.RegistryError(409, 'Patient identifier has conflicting names; identity review is required')
            patient = result.setdefault(c['patient_id'], {'patient_id': c['patient_id'], 'name': c['name'], 'fhir_id': patient_id,
                                                         'created_at': record['created'], 'visits': []})
            patient_registry.validate_candidate(publication['plan']['candidate'], c)
            for visit in publication['plan']['candidate']['visits']:
                key = (visit['date'], visit['event_id'])
                entry = next((v for v in patient['visits'] if (v['date'], v['event_id']) == key), None)
                if entry is None:
                    entry = {**visit, 'facts': [], 'source_job': row['id']}
                    patient['visits'].append(entry)
                for fact in visit['facts']:
                    archived = progress.get('fields', {}).get(fact['field_id'], {})
                    if archived.get('state') != 'archived':
                        continue
                    observation = archived.get('observation')
                    if any(f.get('observation') == observation for f in entry['facts']):
                        continue
                    entry['facts'].append({**fact, 'observation': observation, 'source_job': row['id'], 'current': True})
        if record['legacy_read_only'] and record['receipt']:
            if c['patient_id'] in result and result[c['patient_id']]['name'] != c['name']:
                raise patient_registry.RegistryError(409, 'Patient identifier has conflicting names; identity review is required')
            patient = result.setdefault(c['patient_id'], {'patient_id': c['patient_id'], 'name': c['name'], 'fhir_id': record['receipt']['patient'],
                                                         'created_at': record['created'], 'visits': []})
            patient['visits'].extend([{**v, 'event_id': v.get('event_id') or 'source-' + record['sha'],
                                      'source_job': row['id'], 'legacy': True} for v in c['visits']])
    for patient in result.values():
        replaced = {f['correction_of'] for v in patient['visits'] for f in v['facts'] if f.get('correction_of')}
        for visit in patient['visits']:
            for fact in visit['facts']:
                fact['current'] = fact.get('observation') not in replaced
        patient['visits'].sort(key=lambda v: v['date'])
    return list(result.values())


class PatientRegistration(BaseModel):
    model_config = {'extra': 'forbid'}
    patient_id: str = Field(min_length=3, max_length=64)
    name: str
    sex: Literal['female', 'male', 'unknown'] = 'unknown'
    birth_date: str | None = Field(default=None, max_length=10)


@app.get('/api/patient-registry')
def registered_patients():
    archived = patients()
    by_id = {patient['patient_id']: patient for patient in archived}
    as_of = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    with db() as con:
        result = patient_registry.patients(con, archived)
    for patient in result:
        patient['attention'] = evaluate_attention(by_id.get(patient['patient_id'], {}).get('visits', []), as_of)
    return {'patients': result, 'total': len(result)}


@app.post('/api/patient-registry')
def register_patient(value: PatientRegistration, request: Request):
    with WRITE_LOCK, db() as con:
        con.execute('BEGIN IMMEDIATE')
        result = patient_registry.register(con, patients(), value.model_dump(), actor(request))
        if result['created']:
            con.execute('INSERT INTO audit(at,job,event,detail) VALUES(?,?,?,?)',
                        (result['patient']['created_at'], '', 'patient_registered',
                         json.dumps({'actor': actor(request), 'patient_id': result['patient']['patient_id']})))
        return result


@app.get('/api/patient-registry/{patient_id}')
def registered_patient(patient_id: str):
    archived = patients()
    with db() as con:
        patient = patient_registry.lookup(con, archived, patient_id)
        result = patient_registry.detail(con, patient, archived)
    as_of = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    result['attention'] = evaluate_attention(result['visits'], as_of)
    result['risk'] = patient_risk.business_risk()
    return result


@app.get('/api/demo/patient-overview')
def demo_patient_overview():
    try:
        overview = load_demo_overview()
        for patient in overview['patients']:
            patient['risk'] = patient_risk.demo_risk(patient, overview['metric_definitions'])
        return overview
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(503, 'Patient overview demo is unavailable') from None


def care_context(scope, patient_id, roster=None, task_state=None):
    if scope == 'demo':
        overview = roster or load_demo_overview()
        patient = next((p for p in overview['patients'] if p['id'] == patient_id), None)
        if patient is None:
            raise care.CareError(404, 'Care patient not found')
        plans, seed = care_demo.scenarios(patient, overview['as_of'])
        return {'patient_id': patient_id, 'name': patient['name'], 'as_of': overview['as_of'],
                'attention': patient['attention'], 'visits': _attention_visits(patient), 'plans': plans,
                'seed_history': seed, 'evidence_refs': ['visit:' + v['id'] for v in patient['visits']]}
    if scope != 'business':
        raise care.CareError(404, 'Care scope not found')
    archived = patients() if roster is None else roster
    with db() as con:
        patient = patient_registry.lookup(con, archived, patient_id)
        detail = patient_registry.detail(con, patient, archived)
    as_of = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    projection = next((p for p in archived if p['patient_id'] == patient_id), {})
    task_rows, sync_error = care_task_state() if task_state is None else task_state
    return {'patient_id': patient_id, 'name': patient['name'], 'as_of': as_of,
            'attention': evaluate_attention(detail['visits'], as_of), 'visits': detail['visits'],
            'plans': care.business_plans(patient_id, outbox.rows(), task_rows, as_of,
                                         projection.get('fhir_id'), sync_error),
            'seed_history': [], 'sync_error': sync_error,
            'evidence_refs': sorted({'job:' + f['source_job'] for v in detail['visits'] for f in v['facts']
                                    if f.get('source_job')})}


def care_task_state():
    try:
        return clinical.tasks(), None
    except Exception:
        return [], 'Clinical task status unavailable'


def care_projection(scope, context, con):
    history = context['seed_history'] + care.records(con, context['patient_id'])
    return {'scope': scope, 'patient_id': context['patient_id'], 'name': context['name'],
            'as_of': context['as_of'], 'synthetic': scope == 'demo', 'form_version': care.FORM_VERSION,
            'attention': care.decorate(context['attention'], history), 'history': history,
            'followup': context['plans'], 'sync_error': context.get('sync_error'),
            'timeline': care.timeline(context['visits'], history), 'evidence_refs': context['evidence_refs']}


@app.get('/api/care/{scope}')
def care_roster(scope: str):
    if scope not in ('business', 'demo'):
        raise care.CareError(404, 'Care scope not found')
    roster = load_demo_overview() if scope == 'demo' else patients()
    if scope == 'demo':
        identities = [p['id'] for p in roster['patients']]
    else:
        with db() as con:
            identities = [p['patient_id'] for p in patient_registry.patients(con, roster)]
    task_state = care_task_state() if scope == 'business' else ([], None)
    summaries = []
    with care_db(scope) as con:
        for identity in identities:
            context = care_context(scope, identity, roster, task_state)
            projected = care_projection(scope, context, con)
            attention, followup = projected['attention'], projected['followup']
            summaries.append({'patient_id': identity, 'name': context['name'], 'as_of': context['as_of'],
                              'open_count': attention['open_count'], 'reviewed_count': attention['reviewed_count'],
                              'open_level': attention['open_level'], 'followup_status': followup['status'],
                              'selected_plan': followup['selected'], 'overdue_count': followup['overdue_count']})
    return {'scope': scope, 'patients': summaries, 'total': len(summaries), 'sync_error': task_state[1],
            'followup_counts': {s: sum(p['followup_status'] == s for p in summaries) for s in care.PLAN_STATES},
            'attention_counts': {s: sum(p['open_level'] == s and p['open_count'] > 0 for p in summaries) for s in care.LEVELS}}


@app.get('/api/care/{scope}/{patient_id}')
def get_care(scope: str, patient_id: str):
    context = care_context(scope, patient_id)
    with care_db(scope) as con:
        return care_projection(scope, context, con)


@app.post('/api/care/{scope}/{patient_id}/{kind}/{item_id}')
def save_care(scope: str, patient_id: str, kind: str, item_id: str, value: dict, request: Request):
    with WRITE_LOCK:
        context = care_context(scope, patient_id)
        with care_db(scope) as con:
            con.execute('BEGIN IMMEDIATE')
            return care.save(con, patient_id, kind, item_id, value, actor(request), context)


@app.get('/api/tasks')
def tasks():
    try:
        return clinical.tasks()
    except Exception:
        raise HTTPException(503, 'Follow-up authority unavailable') from None


@app.get('/api/outbox')
def followup_outbox():
    try:
        outbox.sync_tasks(clinical.tasks())
    except Exception:
        return {'delivery_enabled': False, 'items': outbox.rows(),
                'sync_error': 'Clinical task status unavailable; showing saved queue'}
    return {'delivery_enabled': False, 'items': outbox.rows()}


class OutboxEdit(BaseModel):
    model_config = {'extra': 'forbid'}
    revision: int = Field(ge=1)
    due_date: str = Field(max_length=10)
    message: str = Field(min_length=1, max_length=2000)
    status: Literal['draft', 'pending_send', 'cancelled']
    reason: str = Field(min_length=1, max_length=500)


@app.post('/api/outbox/{item_id}')
def edit_outbox(item_id: str, value: OutboxEdit, request: Request):
    return outbox.edit(item_id, value.model_dump(), actor(request))


@app.get('/api/admin/overview')
def overview():
    patients_list = patients()
    task_list = tasks()
    outbox.sync_tasks(task_list)
    with db() as con:
        job_counts = {r[0]: r[1] for r in con.execute('SELECT state,COUNT(*) FROM jobs GROUP BY state')}
        recent = [dict(r) for r in con.execute('SELECT at,event FROM audit ORDER BY id DESC LIMIT 15')]
    def counts(values, key):
        result = {}
        for value in values:
            result[value[key]] = result.get(value[key], 0) + 1
        return result
    return {'jobs_by_state': job_counts, 'patients': len(patients_list),
            'events': sum(len(p['visits']) for p in patients_list),
            'fields': sum(sum(f.get('current', True) for f in v['facts']) for p in patients_list for v in p['visits']),
            'tasks_by_status': counts(task_list, 'status'), 'outbox_by_status': counts(outbox.rows(), 'status'),
            'recent_audit': recent, 'scope': 'Local workbench business data; no clinical performance claim'}


def business_snapshot():
    directory = DATA / 'exports' / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / 'jobs.sqlite'
    with db() as con, contextlib.closing(sqlite3.connect(path)) as target:
        con.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise HTTPException(503, 'Database snapshot failed integrity validation')
    return directory, path


@app.get('/api/admin/export/database')
def export_database(request: Request):
    directory, path = business_snapshot()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    event('', 'business_database_export', json.dumps({'actor': actor(request), 'sha256': digest}))
    return FileResponse(path, media_type='application/vnd.sqlite3', filename='sjd-workbench-' + directory.name[:8] + '.sqlite')


@app.get('/api/admin/export/archive')
def export_archive(request: Request):
    directory, path = business_snapshot()
    try:
        resources = {kind: clinical.search(kind, {'_count': 100}) for kind in
                     ('Patient', 'Encounter', 'Observation', 'Provenance', 'Task', 'Basic')}
    except Exception:
        raise HTTPException(503, 'Clinical resource export unavailable; no partial archive is offered') from None
    snapshot = directory / 'clinical-resources.json'
    snapshot.write_text(json.dumps(resources, ensure_ascii=False), encoding='utf-8')
    archive = directory / 'business-archive.zip'
    manifest = {'scope': 'Workflow SQLite snapshot, immutable originals and allowlisted clinical resources',
                'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'document_mode': DOCUMENT_MODE,
                'excluded': ['accounts', 'sessions', 'service identity', 'infrastructure secrets', 'Redis', 'full PostgreSQL'],
                'consistency': 'SQLite online snapshot; FHIR resources read sequentially, not an atomic full-system backup',
                'files': []}
    with contextlib.closing(sqlite3.connect(path)) as snapshot_db:
        source_rows = snapshot_db.execute('SELECT id,sha FROM jobs').fetchall()
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for source, name in [(path, 'jobs.sqlite'), (snapshot, 'clinical-resources.json')]:
            bundle.write(source, name)
            manifest['files'].append({'path': name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        for source_id, digest in source_rows:
            if str(uuid.UUID(source_id)) != source_id:
                raise HTTPException(503, 'Unexpected source identifier; archive refused')
            source = DATA / 'sources' / source_id
            if not source.is_file() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise HTTPException(503, 'Source integrity mismatch; archive refused')
            name = 'sources/' + source_id
            bundle.write(source, name)
            manifest['files'].append({'path': name, 'sha256': digest})
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    event('', 'business_archive_export', json.dumps({'actor': actor(request), 'files': len(manifest['files']),
                                                   'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))
    return FileResponse(archive, media_type='application/zip', filename='sjd-business-' + directory.name[:8] + '.zip')


class Completion(BaseModel):
    version: str


class DemoFault(BaseModel):
    mode: Literal['before_commit', 'after_commit'] = 'before_commit'
    field_id: str = Field(default='*', max_length=64)


@app.post('/api/demo/fault')
def demo_fault(value: DemoFault):
    if not DEMO:
        raise HTTPException(404)
    clinical.request('POST', '/__synthetic__/fault', {**value.model_dump(), 'remaining': 1})
    return {'armed': True, 'scope': 'synthetic-only'}


@app.post('/api/tasks/{task}/complete')
def complete(task: str, value: Completion):
    try:
        result = clinical.complete_task(task, value.version)
        event(task, 'followup_completed')
        return {'status': result['status']}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/fixtures/{name}')
def fixture(name: str):
    if name not in ('visit-1.txt', 'visit-2.txt', 'lab.csv', 'scan.png', 'review-demo.csv', 'followup-demo.csv',
                    'review-demo-zh.csv', 'followup-demo-zh.csv'):
        raise HTTPException(404)
    return FileResponse(ROOT / 'fixtures' / name, filename=name)


from department import router as department_router
app.include_router(department_router)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
