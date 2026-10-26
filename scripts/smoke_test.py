"""Exercise the complete workbench over loopback HTTP with invented fixtures only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

from start import CLINICAL, PRESCRIPTION, ROOT, environment, prepare_site, run_lock

RX = '/api/department/mingyirx'
KNOWLEDGE = '/api/department/knowledge'
ANALYSIS_PAGES = {'aggregate.html', 'inheritance.html', 'exact-rx.html',
                  'supplement.html', 'research-report.html'}


class SmokeFailure(Exception):
    """Carry only a fixed check name, never an HTTP response or submitted data."""


class Checks:
    def __init__(self):
        self.results = []
        self.counts = {}
        self.completed = False

    def check(self, name, passed):
        row = {'check': name, 'passed': bool(passed)}
        self.results.append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise SmokeFailure(name)

    def response(self, name, response, status=200):
        self.check(name, response.status_code == status)
        return response

    def report(self):
        return {'synthetic': True, 'clinical_validation': False, 'completed': self.completed,
                'passed': self.completed and bool(self.results) and all(row['passed'] for row in self.results),
                'checks': self.results, 'counts': self.counts}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def html_policy_valid(response):
    """Independently compare executable inline scripts with the delivered CSP."""
    csp = response.headers.get('content-security-policy', '')
    executable = set()
    for attrs, body in re.findall(rb'<script\b([^>]*)>(.*?)</script>', response.content, re.S):
        if b'application/json' in attrs or re.search(rb'\bsrc\s*=', attrs):
            continue
        normalized = body.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        executable.add(base64.b64encode(hashlib.sha256(normalized).digest()).decode('ascii'))
    return ("frame-ancestors 'self'" in csp and "connect-src 'self'" in csp
            and "object-src 'none'" in csp and "script-src 'unsafe-inline'" not in csp
            and executable == set(re.findall(r"'sha256-([^']+)'", csp)))


def clinical_flow(client, checks):
    from extract import extract_csv

    raw = (CLINICAL / 'fixtures/lab.csv').read_bytes()
    checks.check('clinical_fixture_explicitly_synthetic', raw.startswith(b'# SJD-SYNTHETIC'))
    candidate = extract_csv(raw.decode('utf-8'))
    identity = {key: candidate[key] for key in ('patient_id', 'name')}
    checks.response('clinical_patient_registration', client.post('/api/patient-registry', json=identity))
    uploaded = checks.response('clinical_marked_csv_upload', client.post('/api/upload',
        files={'file': ('synthetic-lab.csv', raw, 'text/csv')},
        data={'synthetic': 'true', 'patient_id': identity['patient_id']})).json()
    job_path = '/api/jobs/' + uploaded['id']
    deadline = time.monotonic() + 30
    record = None
    while time.monotonic() < deadline:
        response = client.get(job_path)
        if response.status_code != 200:
            break
        record = response.json()
        if record['state'] in {'review', 'blocked', 'failed'}:
            break
        time.sleep(0.1)
    checks.check('clinical_csv_reaches_review_without_model', record is not None
                 and record['state'] == 'review' and record['candidate']['model'] == 'deterministic-csv')
    checks.check('clinical_source_bytes_preserved', checks.response('clinical_source_download',
                 client.get(job_path + '/source')).content == raw)
    fields = record['fields']
    checks.check('clinical_all_fixture_fields_extracted', len(fields) == 3)
    approval = {'version': record['version'], 'review_revision': 0, 'reviewed': True,
                'followup_days': 30, 'accept_defaults': False}
    checks.response('clinical_unreviewed_archive_rejected', client.post(job_path + '/approve', json=approval), 409)
    checks.response('clinical_stale_version_rejected', client.post(job_path + '/review', json={
        'version': '0' * 64, 'review_revision': 0, 'field_id': fields[0]['id'], 'action': 'accept'}), 409)
    for number, field in enumerate(fields, 1):
        record = checks.response('clinical_field_review_' + str(number), client.post(job_path + '/review', json={
            'version': record['version'], 'review_revision': record['review_revision'],
            'field_id': field['id'], 'action': 'accept'})).json()
    approval['review_revision'] = record['review_revision']
    receipt = checks.response('clinical_explicit_archive', client.post(job_path + '/approve', json=approval)).json()
    record = checks.response('clinical_archived_job', client.get(job_path)).json()
    checks.check('clinical_each_review_archived', record['state'] == 'published'
                 and len(record['history']) == len(fields)
                 and all(field['decision']['action'] == 'accept'
                         and field['archive']['state'] == 'archived' for field in record['fields']))
    checks.counts['clinical_reviewed_fields'] = len(fields)
    return {'path': job_path, 'record': record, 'approval': approval, 'receipt': receipt,
            'patient_path': '/api/patient-registry/' + identity['patient_id']}


def knowledge_flow(client, checks):
    catalog = checks.response('knowledge_catalog', client.get(KNOWLEDGE + '/catalog')).json()
    checks.check('knowledge_explicit_synthetic_catalog', catalog['data_origin'] == 'synthetic'
                 and catalog['model'] == 'not_connected' and catalog['model_status'] == 'not_run')
    payload = {'question': catalog['example_question'], 'disease': 'all', 'source_id': 'all',
               'index_sha256': catalog['index_sha256']}
    answer = checks.response('knowledge_fixed_example', client.post(KNOWLEDGE + '/extract', json=payload)).json()
    checks.check('knowledge_no_model_or_clinical_approval', answer['status'] == 'extracts'
                 and answer['data_origin'] == 'synthetic' and answer['model_called'] is False
                 and answer['translation_model_called'] is False and answer['clinical_approval'] is None)
    item = answer['extracts'][0]
    checks.check('knowledge_quote_binding', digest(item['quote'].encode('utf-8')) == item['quote_sha256']
                 and item['answer_zh'] == item['quote'] and item['pmid'] is None and item['doi'] is None)
    checks.check('knowledge_same_origin_locator', re.fullmatch(
        KNOWLEDGE + r'/section/ft_[a-f0-9]{24}', item['page_url']) is not None)
    source = checks.response('knowledge_source_section', client.get(item['page_url']))
    checks.check('knowledge_source_explicit_synthetic', b'SYNTHETIC SOFTWARE FIXTURE' in source.content
                 and item['quote'].encode('utf-8') in source.content)
    refused = checks.response('knowledge_nonexample_request', client.post(KNOWLEDGE + '/extract',
        json={**payload, 'question': 'Which medication should this patient receive?'})).json()
    checks.check('knowledge_nonexample_refusal_without_model', refused['status'] == 'insufficient'
                 and refused['extracts'] == [] and refused['model_called'] is False)
    checks.response('knowledge_stale_index_rejected', client.post(KNOWLEDGE + '/extract',
        json={**payload, 'index_sha256': '0' * 64}), 409)
    checks.counts['knowledge_fixture_sources'] = len(catalog['sources'])


def prescription_flow(client, site, checks):
    from mingyirx.clinical_server import STATIC_NAMES
    from department_rx_workspace import _scoped_index

    status = checks.response('prescription_workspace_status', client.get(RX + '/status')).json()
    checks.check('prescription_complete_static_inventory', set(status['static_assets']) == STATIC_NAMES
                 and len(STATIC_NAMES) == 14 and ANALYSIS_PAGES.issubset(STATIC_NAMES))
    pages = 0
    for name in sorted(STATIC_NAMES):
        response = checks.response('prescription_asset_' + name, client.get(RX + '/site/' + name))
        expected = (site / name).read_bytes()
        if name == 'index.html':
            expected = _scoped_index(expected)
        checks.check('prescription_bytes_' + name, response.content == expected)
        if name.endswith('.html'):
            checks.check('prescription_csp_' + name, html_policy_valid(response))
        if name in ANALYSIS_PAGES:
            pages += 1
    checks.counts.update(prescription_static_assets=len(STATIC_NAMES), prescription_analysis_pages=pages)
    example = checks.response('analysis_synthetic_example', client.get('/api/department/analysis/example')).json()
    checks.check('analysis_example_origin', example['data_origin'] == 'synthetic')
    recognized = checks.response('analysis_readonly_recognize', client.post('/api/department/analysis/recognize',
        json={'text': example['text'], 'data_origin': 'synthetic'})).json()
    checks.response('analysis_review_required', client.post('/api/department/analysis/preview', json={
        'records': recognized['records'], 'data_origin': 'synthetic', 'review_confirmed': False}), 422)
    preview = checks.response('analysis_readonly_preview', client.post('/api/department/analysis/preview', json={
        'records': recognized['records'], 'data_origin': 'synthetic', 'review_confirmed': True})).json()
    checks.check('analysis_preview_does_not_persist', preview['gate'] != 'BLOCK' and preview['persisted'] is False)
    initial = checks.response('prescription_initial_state', client.get(RX + '/api/state')).json()
    checks.check('prescription_fresh_collection', initial['records'] == [] and initial['revision'] == 0)
    headers = {'x-mingyirx-nonce': initial['nonce']}
    upload = {'filename': 'synthetic-visits.txt',
              'data_base64': base64.b64encode(example['text'].encode('utf-8')).decode('ascii')}
    checks.response('prescription_missing_nonce_rejected', client.post(RX + '/api/recognize', json=upload), 403)
    checks.response('prescription_wrong_nonce_rejected', client.post(RX + '/api/recognize', json=upload,
                    headers={'x-mingyirx-nonce': 'x' * 43}), 403)
    proposal = checks.response('prescription_recognize', client.post(RX + '/api/recognize',
                              json=upload, headers=headers)).json()
    records = proposal['records']
    checks.check('prescription_upload_source_binding', proposal['source_sha256'] == digest(example['text'].encode('utf-8')))
    preview = checks.response('prescription_preview', client.post(RX + '/api/preview',
        json={'records': records, 'synthetic': True}, headers=headers)).json()
    checks.check('prescription_preview_pairs', preview['gate'] != 'BLOCK' and len(preview['pairs']) == 2)
    commit = {'records': records, 'synthetic': True, 'confirmed': True, 'deidentified': True, 'revision': 0}
    for flag in ('confirmed', 'deidentified'):
        checks.response('prescription_' + flag + '_required', client.post(RX + '/api/commit',
            json={**commit, flag: False}, headers=headers), 400)
    result = checks.response('prescription_commit', client.post(RX + '/api/commit', json=commit, headers=headers)).json()
    checks.check('prescription_first_revision', result.get('revision') == 1)
    checks.response('prescription_stale_revision_rejected', client.post(RX + '/api/commit',
                    json=commit, headers=headers), 409)
    checks.response('prescription_unavailable_revision_rejected', client.get(RX + '/imported.html?revision=2'), 404)
    page = checks.response('prescription_committed_view', client.get(RX + '/imported.html?revision=1'))
    checks.check('prescription_committed_csp', html_policy_valid(page))
    checks.counts['prescription_committed_records'] = len(records)
    return {'records': records, 'nonce': initial['nonce'], 'page_hash': digest(page.content), 'commit': commit}


def restored_flow(client, clinical, prescription, checks):
    record = checks.response('restart_clinical_job', client.get(clinical['path'])).json()
    checks.check('restart_clinical_archive_and_review_preserved', record['state'] == 'published'
                 and all(record[key] == clinical['record'][key] for key in
                         ('review_revision', 'version', 'history', 'fields', 'receipt', 'publication')))
    detail = checks.response('restart_clinical_patient', client.get(clinical['patient_path'])).json()
    checks.check('restart_clinical_patient_visits_preserved', bool(detail['visits']))
    replay = checks.response('restart_clinical_approval_replay', client.post(clinical['path'] + '/approve',
                             json=clinical['approval'])).json()
    checks.check('restart_clinical_receipt_idempotent', replay == clinical['receipt'])
    snapshot = checks.response('restart_prescription_state', client.get(RX + '/api/state')).json()
    checks.check('restart_prescription_records_and_revision_preserved', snapshot['records'] == prescription['records']
                 and snapshot['revision'] == 1 and snapshot['synthetic'] is True)
    checks.check('restart_prescription_nonce_rotated', snapshot['nonce'] != prescription['nonce'])
    checks.response('restart_old_nonce_rejected', client.post(RX + '/api/preview',
        json={'records': prescription['records'], 'synthetic': True},
        headers={'x-mingyirx-nonce': prescription['nonce']}), 403)
    page = checks.response('restart_prescription_saved_view', client.get(RX + '/imported.html?revision=1'))
    checks.check('restart_prescription_view_bytes_preserved', digest(page.content) == prescription['page_hash'])
    headers = {'x-mingyirx-nonce': snapshot['nonce']}
    result = checks.response('restart_prescription_append_revision', client.post(RX + '/api/commit',
        json={**prescription['commit'], 'revision': 1}, headers=headers)).json()
    checks.check('restart_prescription_revision_chain_continues', result.get('revision') == 2)
    checks.counts['prescription_final_revision'] = 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18896)
    parser.add_argument('--fhir-port', type=int, default=18897)
    args = parser.parse_args()
    if args.port == args.fhir_port or not all(1024 <= p <= 65535 for p in (args.port, args.fhir_port)):
        parser.error('Choose two distinct unprivileged loopback ports')
    sys.path.insert(0, str(CLINICAL))
    import demo

    checks = Checks()
    name = 'smoke-' + uuid.uuid4().hex
    run = ROOT / 'work' / name
    run.mkdir(parents=True, exist_ok=False)
    processes = []
    previous_environment = {}
    try:
        with run_lock(run / 'instance.lock'):
            demo.available(args.port)
            demo.available(args.fhir_port)
            with run_lock(ROOT / 'work/prepare.lock'):
                site = prepare_site()
            settings = environment(site, name, ROOT / 'knowledge', 'synthetic-demo')
            # A model endpoint is intentionally unusable in this deterministic smoke.
            settings['MODEL_URL'] = 'http://127.0.0.1:0'
            previous_environment = {key: os.environ.get(key) for key in settings}
            os.environ.update(settings)
            processes = demo.start(run / 'data', run / 'logs', args.port, args.fhir_port)
            checks.check('owned_synthetic_services_started', all(p.poll() is None for p in processes))
            base_url = f'http://127.0.0.1:{args.port}'
            with httpx.Client(base_url=base_url, headers={'origin': base_url}, timeout=30,
                              trust_env=False, follow_redirects=False) as client:
                for route, label in (('/api/jobs', 'clinical'), (KNOWLEDGE + '/catalog', 'knowledge'),
                                     (RX + '/api/state', 'prescription')):
                    checks.response('anonymous_' + label + '_rejected', client.get(route), 401)
                home = checks.response('current_homepage', client.get('/'))
                checks.check('current_homepage_bytes', home.content == (CLINICAL / 'static/index.html').read_bytes())
                csp = home.headers.get('content-security-policy', '')
                checks.check('current_homepage_csp', "script-src 'self'" in csp and "object-src 'none'" in csp
                             and "frame-ancestors 'none'" in csp and 'unsafe-inline' not in csp)
                static_files = sorted(p for p in (CLINICAL / 'static').rglob('*') if p.is_file())
                for path in static_files:
                    relative = path.relative_to(CLINICAL / 'static').as_posix()
                    response = checks.response('clinical_static_' + relative, client.get('/static/' + relative))
                    checks.check('clinical_static_bytes_' + relative, response.content == path.read_bytes())
                checks.counts['clinical_static_files'] = len(static_files)
                clinical = clinical_flow(client, checks)
                knowledge_flow(client, checks)
                prescription = prescription_flow(client, site, checks)
            demo.stop(processes)
            checks.check('owned_services_stopped_for_restart', all(p.poll() is not None for p in processes))
            processes = []
            processes = demo.start(run / 'data', run / 'logs', args.port, args.fhir_port)
            with httpx.Client(base_url=base_url, headers={'origin': base_url}, timeout=30,
                              trust_env=False, follow_redirects=False) as client:
                checks.response('restart_new_session_required', client.get('/api/jobs'), 401)
                checks.response('restart_demo_session', client.get('/'))
                restored_flow(client, clinical, prescription, checks)
            checks.completed = True
    except Exception:
        # Deliberately suppress request bodies, nonce values, identities and exception details.
        if not checks.results or checks.results[-1]['passed']:
            checks.results.append({'check': 'smoke_runtime_completed', 'passed': False})
            print(json.dumps(checks.results[-1]), flush=True)
    finally:
        try:
            demo.stop(processes)
            checks.check('owned_services_finally_stopped', all(p.poll() is not None for p in processes))
        except Exception:
            checks.results.append({'check': 'owned_services_finally_stopped', 'passed': False})
            print(json.dumps(checks.results[-1]), flush=True)
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        report = checks.report()
        (run / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'check_count': len(checks.results),
                          'counts': checks.counts}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
