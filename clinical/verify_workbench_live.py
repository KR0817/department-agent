"""Exercise only a fresh, task-owned workbench with known synthetic inputs."""
import argparse
import contextlib
import hashlib
import io
import json
import pathlib
import secrets
import sqlite3
import time
import zipfile
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://localhost:13042')
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
assert args.base == 'http://localhost:13042', 'Live verifier is restricted to its owned QA port'
assert not args.output.exists(), 'Preserve prior evidence'
args.output.mkdir(parents=True)
root = pathlib.Path(__file__).resolve().parent
report = {'scope': 'Synthetic development only; actual local AI/OCR and Medplum runtime',
          'checks': [], 'started_at': time.time(), 'inputs': [], 'external_messages_sent': 0}


def check(name, value):
    report['checks'].append({'name': name, 'passed': bool(value)})
    assert value, name


def require(response, status=200):
    assert response.status_code == status, 'Unexpected HTTP status: ' + str(response.status_code)
    return response.json()


client = httpx.Client(base_url=args.base, headers={'origin': args.base}, timeout=360, trust_env=False)
try:
    check('fresh_first_admin_setup', require(client.get('/api/auth/state'))['setup_required'])
    check('anonymous_export_denied', client.get('/api/admin/export/database').status_code == 401)
    password = secrets.token_urlsafe(24)
    require(client.post('/api/auth/setup', json={'username': 'qa-admin', 'password': password}))
    status = require(client.get('/api/status'))
    check('pinned_model_and_ocr_ready', status['model_ready'] and status['ocr_ready'] and status['document_mode'] == 'local')
    report['model'] = {k: status[k] for k in ('model', 'model_digest', 'ocr_ready', 'document_mode')}
    jobs = []
    for name in ('visit-1.txt', 'scan.png'):
        raw = (root / 'fixtures' / name).read_bytes()
        report['inputs'].append({'fixture': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'origin': 'simulated'})
        result = require(client.post('/api/upload', files={'file': (name, raw)}, data={'synthetic': 'true'}))
        deadline = time.monotonic() + 720
        started = time.monotonic()
        while time.monotonic() < deadline:
            record = require(client.get('/api/jobs/' + result['id']))
            if record['state'] in ('review', 'failed', 'blocked'):
                break
            time.sleep(2)
        report.setdefault('extractions', []).append({'fixture': name, 'state': record['state'],
            'method': record['method'], 'fields': len(record['fields']), 'seconds': round(time.monotonic() - started, 2),
            'error': record.get('error')})
        print(json.dumps({'fixture': name, 'state': record['state'], 'fields': len(record['fields'])}), flush=True)
        check(name + '_candidate_ready', record['state'] == 'review' and len(record['fields']) > 0)
        check(name + '_source_quotes', all(f['original']['quote'] in record['text'] for f in record['fields']))
        if name.endswith('.png'):
            check('actual_image_ocr_used', record['method'] == 'local-ocr')
        check(name + '_duplicate_upload_reuses_job', require(client.post('/api/upload', files={'file': (name, raw)},
              data={'synthetic': 'true'})) == {'id': result['id'], 'duplicate': True})
        jobs.append(record)
    check('automatic_followup_drafts', len(require(client.get('/api/outbox'))['items']) >= 1)
    record = jobs[0]
    check('unreviewed_publication_rejected', client.post('/api/jobs/' + record['id'] + '/approve', json={
        'version': record['version'], 'review_revision': 0, 'reviewed': True, 'followup_days': 30}).status_code == 409)
    for field in record['fields']:
        record = require(client.post('/api/jobs/' + record['id'] + '/review', json={
            'version': record['version'], 'review_revision': record['review_revision'],
            'field_id': field['id'], 'action': 'accept'}))
    approval = {'version': record['version'], 'review_revision': record['review_revision'], 'reviewed': True, 'followup_days': 30}
    receipt = require(client.post('/api/jobs/' + record['id'] + '/approve', json=approval))
    check('real_medplum_archive_and_task', bool(receipt.get('patient') and receipt.get('task')))
    check('archive_retry_same_receipt', require(client.post('/api/jobs/' + record['id'] + '/approve', json=approval)) == receipt)
    queue = require(client.get('/api/outbox'))
    linked = [r for r in queue['items'] if r['task_id'] == receipt['task']]
    check('one_pending_send_entry_for_task', len(linked) == 1 and linked[0]['status'] == 'pending_send' and not queue['delivery_enabled'])
    item = linked[0]
    body = {k: item[k] for k in ('revision', 'due_date', 'message', 'status')}
    body.update(reason='Synthetic QA message review', message='Synthetic follow-up reminder, not sent.')
    require(client.post('/api/outbox/' + item['id'], json=body))
    check('stale_outbox_edit_rejected', client.post('/api/outbox/' + item['id'], json=body).status_code == 409)
    overview = require(client.get('/api/admin/overview'))
    check('admin_overview_matches_jobs', sum(overview['jobs_by_state'].values()) == 2 and overview['patients'] == 1)
    response = client.get('/api/admin/export/database')
    check('database_download', response.status_code == 200 and response.content.startswith(b'SQLite format 3'))
    database = args.output / 'synthetic-business.sqlite'
    database.write_bytes(response.content)
    with contextlib.closing(sqlite3.connect(database)) as con:
        check('export_database_integrity', con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        check('no_authentication_tables_in_export', not tables.intersection({'users', 'sessions', 'attempts'}))
    response = client.get('/api/admin/export/archive')
    check('archive_download', response.status_code == 200)
    (args.output / 'synthetic-business.zip').write_bytes(response.content)
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        check('all_archive_hashes_match', all(hashlib.sha256(bundle.read(f['path'])).hexdigest() == f['sha256'] for f in manifest['files']))
        check('no_runtime_identity_in_archive', all(not any(word in name for word in ('accounts', 'identity', 'secret', '.env')) for name in bundle.namelist()))
    require(client.post('/api/admin/users', json={'username': 'qa-staff', 'password': secrets.token_urlsafe(24), 'role': 'staff'}))
    require(client.post('/api/auth/logout', json={}))
    check('logout_revokes_api_access', client.get('/api/jobs').status_code == 401)
    report['passed'] = True
except Exception as exc:
    report['passed'] = False
    report['failure'] = type(exc).__name__ + ': ' + str(exc)
    raise
finally:
    client.close()
    report['elapsed_seconds'] = round(time.time() - report['started_at'], 2)
    (args.output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'output': str(args.output)}), flush=True)
