"""Real HTTP synthetic workflow, owned-process restart and application restore."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import sys
import time
import traceback
import uuid
import httpx
from demo import start, stop, ROOT
from extract import extract_csv
from recovery import backup, restore, validate_backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--runtime', type=pathlib.Path, required=True)
    parser.add_argument('--agent-port', type=int, default=13022)
    parser.add_argument('--fhir-port', type=int, default=18123)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    args.runtime.mkdir(parents=True, exist_ok=False)
    data, restored = args.runtime / 'data', args.runtime / 'restored'
    checks, processes = [], []
    report = {'data_origin': 'simulated', 'scope': 'current HTTP double and application recovery; no Medplum/model/clinical accuracy test',
              'date': '2026-10-22', 'checks': checks, 'passed': False}
    client = None

    def check(name, condition, detail=None):
        checks.append({'name': name, 'passed': bool(condition), 'detail': detail})
        if not condition:
            raise AssertionError(name)

    def connect():
        c = httpx.Client(base_url=f'http://127.0.0.1:{args.agent_port}',
                         headers={'origin': f'http://127.0.0.1:{args.agent_port}'}, timeout=30)
        c.get('/').raise_for_status()
        return c

    def job(job_id):
        return client.get('/api/jobs/' + job_id).json()

    def wait_review(job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = job(job_id)
            if current['state'] == 'review':
                return current
            if current['state'] in ('blocked', 'failed'):
                raise AssertionError(current['error'])
            time.sleep(0.1)
        raise AssertionError('Extraction did not reach review')

    def upload(name):
        response = client.post('/api/upload', data={'synthetic': 'true'},
            files={'file': (name, (ROOT / 'fixtures' / name).read_bytes(), 'text/csv')})
        response.raise_for_status()
        return response.json()['id']

    def decide(job_id, field, action='accept', endpoint='review', **values):
        current = job(job_id)
        response = client.post('/api/jobs/' + job_id + '/' + endpoint, json={'version': current['version'],
            'review_revision': current['review_revision'], 'field_id': field['id'], 'action': action, **values})
        response.raise_for_status()
        return response.json()

    def approve(job_id):
        current = job(job_id)
        return client.post('/api/jobs/' + job_id + '/approve', json={'version': current['version'],
            'review_revision': current['review_revision'], 'reviewed': True, 'followup_days': 30})

    def resources(kind):
        response = httpx.get(f'http://127.0.0.1:{args.fhir_port}/fhir/R4/{kind}', timeout=10)
        response.raise_for_status()
        return [e['resource'] for e in response.json().get('entry', [])]

    try:
        processes = start(data, args.runtime / 'logs', args.agent_port, args.fhir_port)
        client = connect()
        check('demo_status_disables_model', client.get('/api/status').json()['mode'] == 'synthetic-demo')
        initial_id = upload('review-demo.csv')
        initial = wait_review(initial_id)
        check('unreviewed_submission_rejected', approve(initial_id).status_code == 409)
        for field in initial['fields']:
            code = field['original']['code']
            if code == 'pain':
                decide(initial_id, field, 'modify', value='8', unit='', quote=field['original']['quote'], reason='Source note check')
            elif code == 'ssa':
                decide(initial_id, field, 'reject', reason='Deliberately excluded synthetic reading')
            elif code == 'c3':
                decide(initial_id, field, 'defer', reason='Synthetic reviewer needs a second look')
            else:
                decide(initial_id, field)
        selected = [f for f in job(initial_id)['fields'] if f['decision']['action'] in ('accept', 'modify')]
        client.post('/api/demo/fault', json={'mode': 'before_commit', 'field_id': selected[1]['id']}).raise_for_status()
        response = approve(initial_id)
        partial = job(initial_id)
        (args.output / 'partial-job.json').write_text(json.dumps(partial, indent=2), encoding='utf-8')
        check('second_field_failure_retains_first_receipt', response.status_code == 409 and partial['state'] == 'partial'
              and sum(f.get('state') == 'archived' for f in partial['publication']['progress']['fields'].values()) == 1)
        source_hash = hashlib.sha256((data / 'sources' / initial_id).read_bytes()).hexdigest()
        client.close()
        stop(processes)
        processes = start(data, args.runtime / 'restart-logs', args.agent_port, args.fhir_port)
        client = connect()
        check('owned_process_restart_retains_partial_plan', job(initial_id)['publication']['progress'] == partial['publication']['progress'])
        response = approve(initial_id)
        check('partial_retry_completes', response.status_code == 200, response.status_code)
        observations = resources('Observation')
        check('only_three_reviewed_fields_archived', len(observations) == 3, len(observations))
        check('same_day_events_independent', len(resources('Encounter')) == 2)
        before = {kind: len(resources(kind)) for kind in ('Patient', 'Encounter', 'Observation', 'Provenance', 'Basic', 'Task')}
        check('duplicate_upload_same_job', upload('review-demo.csv') == initial_id)
        check('duplicate_approve_same_receipt', approve(initial_id).json() == response.json())
        check('duplicate_does_not_create_resources', before == {kind: len(resources(kind)) for kind in before})
        pending_task = client.get('/api/tasks').json()[0]
        manual = client.post('/api/tasks/' + pending_task['id'] + '/complete', json={'version': pending_task['version']})
        check('status_only_followup_completion_rejected', manual.status_code == 409
              and next(t for t in resources('Task') if t['id'] == pending_task['id'])['status'] == 'requested')

        follow_id = upload('followup-demo.csv')
        follow = wait_review(follow_id)
        decide(follow_id, follow['fields'][0])
        client.post('/api/demo/fault', json={'mode': 'after_commit', 'field_id': follow['fields'][0]['id']}).raise_for_status()
        lost = approve(follow_id)
        if lost.status_code != 200:
            check('lost_response_is_retryable', lost.status_code == 409 and job(follow_id)['state'] == 'partial')
        completed = approve(follow_id)
        check('commit_response_loss_reconciled', completed.status_code == 200 and len(resources('Observation')) == 4)
        check('reviewed_followup_completes_supported_task', any(t['status'] == 'completed' and t.get('output') for t in resources('Task')))
        pain = next(f for f in job(initial_id)['fields'] if f['original']['code'] == 'pain')
        old_observation = pain['archive']['observation']
        decide(initial_id, pain, 'modify', endpoint='correction', value='5', unit='', quote=pain['original']['quote'], reason='Corrected synthetic report')
        response = approve(initial_id)
        check('correction_archive_succeeds', response.status_code == 200, response.text if response.status_code != 200 else None)
        observations = resources('Observation')
        check('old_value_retained_new_amended_resource', len(observations) == 5
              and any(o['id'] == old_observation and o['valueString'] == '8' for o in observations)
              and any(o.get('status') == 'amended' and o['valueString'] == '5' for o in observations))
        timeline = client.get('/api/patients').json()
        facts = [f for p in timeline for v in p['visits'] for f in v['facts']]
        check('timeline_marks_old_correction_superseded', any(f.get('observation') == old_observation and not f['current'] for f in facts))
        check('rejected_and_deferred_absent_from_timeline', not any(f['code'] in ('ssa', 'c3') for f in facts))
        deferred = next(f for f in job(initial_id)['fields'] if f['original']['code'] == 'c3')
        decide(initial_id, deferred)
        check('deferred_field_can_be_reviewed_later', approve(initial_id).status_code == 200 and len(resources('Observation')) == 6)
        check('source_bytes_immutable', hashlib.sha256((data / 'sources' / initial_id).read_bytes()).hexdigest() == source_hash)
        final_job = job(initial_id)
        (args.output / 'reviewed-job.json').write_text(json.dumps(final_job, indent=2), encoding='utf-8')
        (args.output / 'timeline.json').write_text(json.dumps(client.get('/api/patients').json(), indent=2), encoding='utf-8')
        before_fhir = {kind: resources(kind) for kind in ('Patient', 'Encounter', 'Observation', 'Provenance', 'Basic', 'Task')}
        client.close()
        stop(processes)
        processes = []

        # Queue a new declared synthetic source while owned writers are stopped.
        queued_id = str(uuid.uuid4())
        queued = (ROOT / 'fixtures' / 'followup-demo.csv').read_text(encoding='utf-8') + '\n# queued-restore-' + queued_id
        (data / 'sources' / queued_id).write_text(queued, encoding='utf-8')
        con = sqlite3.connect(data / 'jobs.sqlite')
        with con:
            con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,created) VALUES(?,?,?,?,?,?)',
                        (queued_id, hashlib.sha256(queued.encode()).hexdigest(), 'restore-queue.csv', '.csv', 'queued', dt.datetime.now(dt.timezone.utc).isoformat()))
        con.close()
        snapshot = args.runtime / 'snapshot'
        manifest = backup(data, snapshot, writers_stopped=True)
        validate_backup(snapshot)
        restore(snapshot, restored)
        check('snapshot_restored_source_hash', hashlib.sha256((restored / 'sources' / initial_id).read_bytes()).hexdigest() == source_hash)
        report['recovery_manifest'] = manifest
        processes = start(restored, args.runtime / 'restored-logs', args.agent_port, args.fhir_port)
        client = connect()
        check('restored_review_history_and_receipts_equal', job(initial_id)['history'] == final_job['history']
              and job(initial_id)['publication_history'] == final_job['publication_history'])
        check('restored_queue_resumes', wait_review(queued_id)['state'] == 'review')
        check('restored_archive_and_tasks_equal', all(resources(kind) == values for kind, values in before_fhir.items()))
        refs = [item['observation'] for item in job(initial_id)['publication']['progress']['fields'].values() if item['state'] == 'archived']
        check('restored_receipts_resolve', all(httpx.get(f'http://127.0.0.1:{args.fhir_port}/fhir/R4/Observation/{ref}').status_code == 200 for ref in refs))
        report['identity_recovery'] = 'NOT_RUN: no identity material in this synthetic double; sessions regenerated'
        report['resource_counts'] = {kind: len(resources(kind)) for kind in before_fhir}
        report['passed'] = True
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
    finally:
        if client:
            client.close()
        stop(processes)
        report['checks_passed'] = sum(c['passed'] for c in checks)
        report['runtime'] = str(args.runtime.resolve())
        (args.output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': report['checks_passed'], 'report': str(args.output / 'verification.json')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
