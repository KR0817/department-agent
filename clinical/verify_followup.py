"""Verify automatic visit-based follow-up using fresh synthetic CSV records."""
import json
import pathlib
import time
import uuid
import httpx

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:13002'
run = uuid.uuid4().hex[:8]
report = {'run_id': run, 'data_origin': 'simulated', 'checks': []}
c = httpx.Client(base_url=BASE, headers={'Origin': BASE}, timeout=350, trust_env=False)


def check(ok, name):
    report['checks'].append({'name': name, 'passed': bool(ok)})
    if not ok:
        raise RuntimeError(name)


def publish(day, value):
    body = '# SJD-SYNTHETIC\npatient_id,name,visit_date,code,value,unit\nSIM-AUTO-' + run + ',Synthetic Followup,' + day + ',igg,' + value + ',g/L'
    r = c.post('/api/upload', data={'synthetic': 'true'}, files={'file': ('auto-' + day + '.csv', body.encode())})
    r.raise_for_status()
    job = r.json()['id']
    for _ in range(30):
        j = c.get('/api/jobs/' + job).json()
        if j['state'] == 'review':
            break
        time.sleep(1)
    r = c.post('/api/jobs/' + job + '/approve', json={'version': j['version'], 'reviewed': True, 'followup_days': 90})
    check(r.status_code == 200, 'publish_' + day)
    report.setdefault('receipts', []).append(r.json())
    return r.json()


try:
    c.get('/').raise_for_status()
    first, second = publish('2026-07-01', '18.2'), publish('2026-10-01', '16.1')
    check(first['patient'] == second['patient'], 'same_patient_reused')
    check(first['task'] in second['matched_followups'], 'uploaded_followup_matches_prior_window')
    tasks = c.get('/api/tasks').json()
    check(next(t for t in tasks if t['id'] == first['task'])['status'] == 'completed', 'prior_visit_based_task_completed')
    check(next(t for t in tasks if t['id'] == second['task'])['status'] == 'requested', 'next_followup_scheduled')
    report['passed'] = True
except Exception as exc:
    report.update(passed=False, error=str(exc))
finally:
    path = ROOT / 'evidence' / ('auto-followup-' + run + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report.get('passed'), 'report': str(path)}))
    c.close()
if not report.get('passed'):
    raise SystemExit(1)
