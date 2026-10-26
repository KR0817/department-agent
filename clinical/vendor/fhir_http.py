"""Exercise synthetic projects via normal authentication; never read credentials."""
import base64
import datetime
import hashlib
import json
import os
import pathlib
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent
BASE = os.environ.get('SJD_BASE_URL', 'http://127.0.0.1:18103').rstrip('/')  # override for restore/upgrade copies
FHIR = '/fhir/R4/'
SYSTEM = 'https://example.invalid/sjd-sim/source'
LAST_AUTH_ATTEMPT = 0.0


def call(method, path, payload=None, token=None, extra=None, form=False):
    global LAST_AUTH_ATTEMPT
    if path in ('/auth/newuser', '/auth/newproject', '/auth/login'):
        # Preserve the upstream five-per-minute limit; pace the test instead.
        wait = max(0, 13 - (time.monotonic() - LAST_AUTH_ATTEMPT))
        time.sleep(wait)
        LAST_AUTH_ATTEMPT = time.monotonic()
    headers = {'Accept': 'application/fhir+json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    headers.update(extra or {})
    if isinstance(payload, bytes):
        data = payload
        headers.setdefault('Content-Type', 'application/octet-stream')
    elif form:
        data = urllib.parse.urlencode(payload).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/fhir+json' if path.startswith(FHIR) else 'application/json'
    else:
        data = None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    for attempt in range(3):
        if path in ('/auth/newuser', '/auth/newproject', '/auth/login'):
            LAST_AUTH_ATTEMPT = time.monotonic()
        try:
            response = urllib.request.urlopen(request, timeout=25)
        except urllib.error.HTTPError as exc:
            response = exc
        if response.status != 429 or attempt == 2:
            break
        response.close()
        print('Rate limit observed; waiting before retry.', flush=True)
        time.sleep(30)
    with response:
        raw = response.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        return response.status, body, dict(response.headers)


def require(condition, name, checks, **evidence):
    checks.append({'name': name, 'passed': bool(condition), **evidence})
    if not condition:
        raise RuntimeError('Check failed: ' + name)
    print('PASS ' + name, flush=True)


def authenticate(label, run_id, checks):
    password = secrets.token_hex(24)
    email = f'{label}-{run_id}@sjd.invalid'
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    status, login, _ = call('POST', '/auth/newuser', {
        'firstName': 'Synthetic', 'lastName': label, 'email': email, 'password': password,
        'projectId': 'new', 'codeChallenge': challenge, 'codeChallengeMethod': 'S256',
    })
    require(status == 200 and bool(login.get('login')), f'{label}_offline_registration', checks, http=status)
    status, project_login, _ = call('POST', '/auth/newproject', {
        'login': login['login'], 'projectName': 'SJD Simulation ' + label + ' ' + run_id,
    })
    require(status == 200 and bool(project_login.get('code')), f'{label}_project_creation', checks, http=status)
    status, tokens, _ = call('POST', '/oauth2/token', {
        'grant_type': 'authorization_code', 'code': project_login['code'], 'code_verifier': verifier,
    }, form=True)
    require(status == 200 and bool(tokens.get('access_token')), f'{label}_pkce_exchange', checks, http=status)
    # Check the normal login path as well; new registration alone is insufficient.
    status, relogin, _ = call('POST', '/auth/login', {
        'email': email, 'password': password, 'codeChallenge': challenge, 'codeChallengeMethod': 'S256',
    })
    require(status == 200 and bool(relogin.get('code')), f'{label}_password_login', checks, http=status)
    status, tokens, _ = call('POST', '/oauth2/token', {
        'grant_type': 'authorization_code', 'code': relogin['code'], 'code_verifier': verifier,
    }, form=True)
    require(status == 200 and bool(tokens.get('access_token')), f'{label}_login_token', checks, http=status)
    return tokens['access_token']


def create(resource, token, checks, label, identifier=None):
    headers = None
    if identifier:
        headers = {'If-None-Exist': urllib.parse.urlencode({'identifier': SYSTEM + '|' + identifier})}
    status, body, _ = call('POST', FHIR + resource['resourceType'], resource, token, headers)
    require(status in (200, 201) and bool(body.get('id')), label, checks, http=status)
    return body


def main():
    run_id = uuid.uuid4().hex[:12]
    report = {'run_id': run_id, 'data_origin': 'simulated',
              'started_at': datetime.datetime.now().astimezone().isoformat(), 'checks': [],
              'scope': 'Native API probes; not complete Stage A or clinical validation'}
    checks = report['checks']
    try:
        for label, password in [('short', 'too-short'), ('common', '12345678901234567890')]:
            status, _, _ = call('POST', '/auth/newuser', {
                'firstName': 'Synthetic', 'lastName': 'Rejected',
                'email': f'{label}-{run_id}@sjd.invalid', 'password': password,
            })
            require(status == 400, label + '_password_rejected', checks, http=status)
        first = authenticate('alpha', run_id, checks)
        second = authenticate('beta', run_id, checks)
        source_id = run_id + '-patient'
        patient_input = {'resourceType': 'Patient', 'active': True,
                         'identifier': [{'system': SYSTEM, 'value': source_id}],
                         'name': [{'text': '\u6a21\u62df\u60a3\u8005\u7532'}]}
        patient = create(patient_input, first, checks, 'patient_create', source_id)
        repeated = create(patient_input, first, checks, 'patient_repeat', source_id)
        require(patient['id'] == repeated['id'], 'patient_import_idempotency', checks)
        reference = 'Patient/' + patient['id']
        # Project membership is represented by the authenticated session; do not
        # assume the server exposes its non-standard project field in FHIR meta.
        report['project_labels'] = ['alpha', 'beta']
        report['resource_ids'] = {'patient': patient['id']}
        encounters = []
        for number, date in enumerate(['2026-10-01', '2026-10-13'], start=1):
            visit_id = f'{run_id}-visit-{number}'
            visit = {'resourceType': 'Encounter', 'status': 'finished',
                     'class': {'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode', 'code': 'AMB'},
                     'identifier': [{'system': SYSTEM, 'value': visit_id}], 'subject': {'reference': reference},
                     'period': {'start': date + 'T09:00:00+08:00', 'end': date + 'T09:20:00+08:00'}}
            item = create(visit, first, checks, f'visit_{number}_create', visit_id)
            duplicate = create(visit, first, checks, f'visit_{number}_repeat', visit_id)
            require(item['id'] == duplicate['id'], f'visit_{number}_idempotency', checks)
            encounters.append(item['id'])
        status, visits, _ = call('GET', FHIR + 'Encounter?' + urllib.parse.urlencode({'subject': reference, '_count': 10}), token=first)
        require(status == 200 and len(visits.get('entry', [])) == 2, 'two_visits_one_patient', checks)
        report['resource_ids']['encounters'] = encounters
        obligation = run_id + '-followup-v1'
        task_input = {'resourceType': 'Task', 'status': 'requested', 'intent': 'order',
                      'identifier': [{'system': SYSTEM, 'value': obligation}],
                      'for': {'reference': reference}, 'description': 'Synthetic follow-up; no outbound contact',
                      'restriction': {'period': {'start': '2026-10-27T00:00:00+08:00', 'end': '2026-11-03T23:59:59+08:00'}}}
        task = create(task_input, first, checks, 'followup_create', obligation)
        duplicate = create(task_input, first, checks, 'followup_repeat', obligation)
        require(task['id'] == duplicate['id'], 'followup_idempotency', checks)
        report['resource_ids']['task'] = task['id']
        original_version = task['meta']['versionId']
        task['status'] = 'in-progress'
        status, task, _ = call('PUT', FHIR + 'Task/' + task['id'], task, first, {'If-Match': f'W/"{original_version}"'})
        require(status == 200 and task['status'] == 'in-progress', 'followup_transition', checks)
        status, _, _ = call('PUT', FHIR + 'Task/' + task['id'], task, first, {'If-Match': f'W/"{original_version}"'})
        require(status == 412, 'stale_followup_update_rejected', checks, http=status)
        status, queue, _ = call('GET', FHIR + 'Task?' + urllib.parse.urlencode({'identifier': SYSTEM + '|' + obligation}), token=first)
        require(status == 200 and len(queue.get('entry', [])) == 1 and queue['entry'][0]['resource']['status'] == 'in-progress', 'queue_rebuilt_from_persistent_task', checks)
        blob = b'SYNTHETIC_ATTACHMENT_ONLY\n'
        binary = create({'resourceType': 'Binary', 'contentType': 'text/plain',
                         'securityContext': {'reference': reference}, 'data': base64.b64encode(blob).decode()},
                        first, checks, 'binary_create')
        report['resource_ids']['binary'] = binary['id']
        status, fetched, _ = call('GET', FHIR + 'Binary/' + binary['id'], token=first)
        require(status == 200 and base64.b64decode(fetched.get('data', '')) == blob, 'binary_roundtrip', checks)
        status, raw_binary, _ = call('POST', FHIR + 'Binary', blob, first,
                                    {'Content-Type': 'text/plain', 'X-Security-Context': reference})
        require(status == 201 and bool(raw_binary.get('id')), 'raw_attachment_upload', checks, http=status)
        raw_id = raw_binary['id']
        report['resource_ids']['raw_binary'] = raw_id
        status, content, _ = call('GET', FHIR + 'Binary/' + raw_id, token=first, extra={'Accept': 'text/plain'})
        require(status == 200 and content == blob, 'raw_attachment_download', checks, http=status)
        status, _, _ = call('GET', FHIR + 'Binary/' + raw_id, token=second, extra={'Accept': 'text/plain'})
        require(status in (403, 404), 'cross_project_raw_attachment_denied', checks, http=status)
        denied = {}
        for name, path in [('patient_read', reference), ('patient_history', reference + '/_history'),
                           ('task_read', 'Task/' + task['id']), ('binary_read', 'Binary/' + binary['id'])]:
            status, _, _ = call('GET', FHIR + path, token=second)
            denied[name] = status
            require(status in (403, 404), 'cross_project_' + name, checks, http=status)
        status, leaked, _ = call('GET', FHIR + 'Patient?' + urllib.parse.urlencode({'_id': patient['id']}), token=second)
        require(status == 200 and not leaked.get('entry'), 'cross_project_search_empty', checks)
        status, _, _ = call('PUT', FHIR + reference, patient, second)
        require(status in (403, 404), 'cross_project_update_denied', checks, http=status)
        status, batch, _ = call('POST', FHIR, {'resourceType': 'Bundle', 'type': 'batch',
                                             'entry': [{'request': {'method': 'GET', 'url': reference}}]}, second)
        require(status == 200 and batch['entry'][0]['response']['status'].split()[0] in ('403', '404'), 'cross_project_batch_denied', checks)
        # Confirm the permitted history path, not only forbidden operations.
        status, history, _ = call('GET', FHIR + 'Task/' + task['id'] + '/_history', token=first)
        require(status == 200 and len(history.get('entry', [])) >= 2, 'task_history_retained', checks)
        status, own, _ = call('GET', FHIR + reference, token=first)
        require(status == 200 and own['name'] == patient_input['name'], 'chinese_patient_roundtrip', checks)
        report['snapshot'] = {'scope': 'synthetic functional snapshot; not approved research export',
                              'patients': 1, 'encounters': 2, 'followup_tasks': 1,
                              'attachment_sha256': hashlib.sha256(blob).hexdigest()}
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        # Avoid arbitrary exception content or raw HTTP responses containing credentials.
        report['failure'] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    report['finished_at'] = datetime.datetime.now().astimezone().isoformat()
    path = ROOT / ('workflow-verification-' + run_id + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'report': path.name,
                      'failure': report.get('failure')}))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
