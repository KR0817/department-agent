"""Real local-model and FHIR acceptance using explicitly synthetic fixtures."""
import datetime as dt
import hashlib
import json
import pathlib
import time
import uuid
import httpx

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:13002'
run = uuid.uuid4().hex[:12]
report = {'run_id': run, 'data_origin': 'simulated', 'checks': [], 'jobs': [],
          'scope': 'Real local model, OCR/readers, synthetic publication and persistent follow-up; not clinical accuracy qualification'}
client = httpx.Client(base_url=BASE, headers={'Origin': BASE}, timeout=350)


def check(ok, name, **detail):
    report['checks'].append({'name': name, 'passed': bool(ok), **detail})
    print(('PASS ' if ok else 'FAIL ') + name, flush=True)
    if not ok:
        raise RuntimeError(name)


def wait(job):
    last = None
    for _ in range(200):
        r = client.get('/api/jobs/' + job).json()
        if r['state'] != last:
            print('Job ' + job[:8] + ': ' + r['state'], flush=True)
            last = r['state']
        if r['state'] in ('review', 'published', 'failed', 'blocked'):
            return r
        time.sleep(2)
    raise RuntimeError('Job timeout')


def upload(name):
    path = ROOT / 'fixtures' / name
    with path.open('rb') as stream:
        response = client.post('/api/upload', data={'synthetic': 'true'}, files={'file': (name, stream)})
    check(response.status_code == 200, 'upload_' + name)
    job = response.json()['id']
    report['jobs'].append(job)
    return job


try:
    check(client.get('/').status_code == 200, 'workbench_open')
    status = client.get('/api/status').json()
    check(status['model_ready'], 'local_model_ready', model=status['model'], digest=status['model_digest'])
    report['model_digest'] = status['model_digest']
    check(httpx.post(BASE + '/api/upload', headers={'Origin': 'https://example.com'}, timeout=10).status_code in (401, 403), 'unauthenticated_cross_origin_denied')
    first = upload('visit-1.txt')
    a = wait(first)
    check(a['state'] in ('review', 'published'), 'model_extracts_first_visit', error=a.get('error'))
    values = {f['code']: f['value'] for f in a['candidate']['visits'][0]['facts']}
    check(a['candidate']['patient_id'] == 'SIM-SJD-001' and a['candidate']['visits'][0]['date'] == '2026-07-01', 'identity_date_exact')
    check(all(values.get(k) == v for k, v in {'dryness': '3', 'fatigue': '6', 'pain': '9', 'igg': '18.2', 'c3': '0.82'}.items()), 'five_declared_fields_match_source')
    check(client.post('/api/jobs/' + first + '/approve', json={'version': 'stale', 'reviewed': True}).status_code == 409, 'stale_review_denied')
    check(client.post('/api/jobs/' + first + '/approve', json={'version': a['version'], 'reviewed': False}).status_code == 409, 'unreviewed_publication_denied')
    approved = client.post('/api/jobs/' + first + '/approve', json={'version': a['version'], 'reviewed': True, 'followup_days': 90})
    check(approved.status_code == 200, 'reviewed_first_visit_published', result=approved.json())
    receipt = approved.json()
    repeated = client.post('/api/jobs/' + first + '/approve', json={'version': a['version'], 'reviewed': True, 'followup_days': 90})
    check(repeated.status_code == 200 and repeated.json() == receipt, 'publication_retry_same_receipt')
    check(upload('visit-1.txt') == first, 'duplicate_upload_same_job')
    second = upload('visit-2.txt')
    b = wait(second)
    check(b['state'] in ('review', 'published'), 'model_extracts_second_visit', error=b.get('error'))
    approved = client.post('/api/jobs/' + second + '/approve', json={'version': b['version'], 'reviewed': True, 'followup_days': 90})
    check(approved.status_code == 200 and approved.json()['patient'] == receipt['patient'], 'second_visit_same_patient', result=approved.json())
    patients = client.get('/api/patients').json()
    p = next(p for p in patients if p['patient_id'] == 'SIM-SJD-001')
    check([v['date'] for v in p['visits']] == ['2026-07-01', '2026-10-01'], 'two_visit_longitudinal_timeline')
    tasks = client.get('/api/tasks').json()
    check(any(t['id'] == receipt['task'] for t in tasks), 'fhir_followup_obligation_present')
    csv = wait(upload('lab.csv'))
    check(csv['state'] in ('review', 'published') and csv['candidate']['model'] == 'deterministic-csv', 'structured_lis_does_not_call_model')
    scan = wait(upload('scan.png'))
    check(scan['state'] == 'review' and scan['method'] == 'local-ocr', 'scan_local_ocr_and_model', error=scan.get('error'))
    report['passed'] = True
except Exception as exc:
    report['passed'] = False
    report['failure'] = str(exc)
finally:
    report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    path = ROOT / 'evidence' / ('live-' + run + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(path)}), flush=True)
    client.close()
if not report['passed']:
    raise SystemExit(1)
