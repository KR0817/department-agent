"""Synthetic-only fault injection against the dedicated agent containers."""
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import time
import uuid
import httpx

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:13002'
report = {'run_id': uuid.uuid4().hex[:12], 'data_origin': 'simulated', 'checks': []}
c = httpx.Client(base_url=BASE, headers={'Origin': BASE}, timeout=350, trust_env=False)


def check(ok, name, **detail):
    report['checks'].append({'name': name, 'passed': bool(ok), **detail})
    print(('PASS ' if ok else 'FAIL ') + name, flush=True)
    if not ok:
        raise RuntimeError(name)


def upload(name, data):
    r = c.post('/api/upload', data={'synthetic': 'true'}, files={'file': (name, data)})
    r.raise_for_status()
    return r.json()['id']


def wait(job):
    for _ in range(200):
        j = c.get('/api/jobs/' + job).json()
        if j['state'] in ('review', 'failed', 'blocked', 'published'):
            return j
        time.sleep(2)
    raise RuntimeError('Timed out waiting for extraction')


try:
    c.get('/').raise_for_status()
    check(c.post('/api/upload', headers={'Origin': 'https://example.com'}).status_code == 403, 'authenticated_cross_origin_write_denied')
    check(c.post('/api/upload', data={'synthetic': 'false'}, files={'file': ('x.txt', b'x')}).status_code == 400, 'synthetic_ack_required')
    before = c.get('/api/patients').json()
    task_before = c.get('/api/tasks').json()
    conflict = '# SJD-SYNTHETIC\npatient_id,name,visit_date,code,value,unit\nSIM-SJD-001,' + before[0]['name'] + ',2026-07-01,igg,99.9,g/L'
    job = upload('conflicting-visit.csv', conflict.encode())
    candidate = wait(job)
    check(candidate['state'] == 'review', 'conflicting_source_staged')
    rejected = c.post('/api/jobs/' + job + '/approve', json={'version': candidate['version'], 'reviewed': True})
    check(rejected.status_code == 409 and 'conflicting value' in rejected.json()['detail'], 'conflicting_existing_visit_not_overwritten')
    check(c.get('/api/patients').json() == before, 'conflict_does_not_change_timeline')
    body = (ROOT / 'fixtures' / 'visit-1.txt').read_bytes() + ('\nSynthetic resilience run: ' + report['run_id']).encode()
    subprocess.run(['docker', 'stop', 'sjd-agent-model-1'], check=True, capture_output=True)
    job = upload('model-offline-' + report['run_id'] + '.txt', body)
    failed = wait(job)
    check(failed['state'] == 'failed' and failed['candidate'] is None, 'model_offline_does_not_fabricate_candidate')
    downloaded = c.get('/api/jobs/' + job + '/source').content
    check(hashlib.sha256(downloaded).digest() == hashlib.sha256(body).digest(), 'model_failure_preserves_original_bytes')
    subprocess.run(['docker', 'start', 'sjd-agent-model-1'], check=True, capture_output=True)
    for _ in range(30):
        if c.get('/api/status').json()['model_ready']:
            break
        time.sleep(1)
    check(c.post('/api/jobs/' + job + '/retry', json={}).status_code == 200, 'failed_job_retry_accepted')
    recovered = wait(job)
    check(recovered['state'] == 'review', 'real_model_recovers_same_job', error=recovered.get('error'))
    report['fresh_model_candidate'] = recovered['candidate']
    before_jobs = c.get('/api/jobs').json()
    subprocess.run(['docker', 'restart', 'sjd-agent-workbench-1'], check=True, capture_output=True)
    for _ in range(30):
        try:
            if c.get('/').status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(1)
    check(c.get('/api/jobs').json() == before_jobs, 'restart_preserves_jobs_and_review_states')
    check(c.get('/api/patients').json() == before, 'restart_preserves_longitudinal_archive')
    check(c.get('/api/tasks').json() == task_before, 'restart_preserves_fhir_followup_states')
    task = next(t for t in task_before if t['status'] == 'requested')
    check(c.post('/api/tasks/' + task['id'] + '/complete', json={'version': 'stale'}).status_code == 409, 'stale_followup_update_denied')
    report['passed'] = True
except Exception as exc:
    report.update(passed=False, failure=str(exc))
finally:
    subprocess.run(['docker', 'start', 'sjd-agent-model-1'], capture_output=True)
    report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    path = ROOT / 'evidence' / ('resilience-' + report['run_id'] + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(path), flush=True)
    c.close()
if not report.get('passed'):
    raise SystemExit(1)
