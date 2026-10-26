"""Deterministic clinical tools. The model cannot invoke these or access credentials."""
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import threading
import urllib.parse
import uuid
from vendor import fhir_http as http
from extract import LABELS

SYSTEM = 'https://example.invalid/sjd-agent'
http.BASE = os.environ.get('FHIR_URL', 'http://server:8103')
LOCK = threading.RLock()
TOKEN = None


def request(method, path, body=None, extra=None):
    global TOKEN
    with LOCK:
        if os.environ.get('AGENT_DEMO') == '1':
            base = urllib.parse.urlsplit(http.BASE)
            if base.scheme != 'http' or base.hostname not in ('127.0.0.1', 'localhost', '::1') or base.username or base.path not in ('', '/'):
                raise ValueError('Synthetic FHIR requires an explicit loopback HTTP URL')
            status, result, _ = http.call(method, path, body, None, extra)
            if status >= 300:
                raise RuntimeError('Synthetic clinical API rejected request: HTTP ' + str(status))
            return result
        if not TOKEN:
            authenticate()
        status, result, _ = http.call(method, path, body, TOKEN, extra)
        if status == 401:
            TOKEN = None
            authenticate()
            status, result, _ = http.call(method, path, body, TOKEN, extra)
        if status >= 300:
            raise RuntimeError('Clinical API rejected request: HTTP ' + str(status))
        return result


def authenticate():
    """Normal service runtime uses only its own newly generated identity, never existing user secrets."""
    global TOKEN
    path = pathlib.Path(os.environ.get('AGENT_DATA', '/data')) / 'service-identity.json'
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    if path.exists():
        identity = json.loads(path.read_text())
        status, login, _ = http.call('POST', '/auth/login', {**identity, 'codeChallenge': challenge, 'codeChallengeMethod': 'S256'})
        if status != 200 or not login.get('code'):
            raise RuntimeError('Dedicated simulation identity unavailable')
    else:
        identity = {'email': 'agent-' + uuid.uuid4().hex[:12] + '@sjd.invalid', 'password': secrets.token_urlsafe(32)}
        status, login, _ = http.call('POST', '/auth/newuser', {**identity, 'firstName': 'Synthetic', 'lastName': 'Agent service',
            'projectId': 'new', 'codeChallenge': challenge, 'codeChallengeMethod': 'S256'})
        if status != 200:
            raise RuntimeError('Dedicated simulation registration failed')
        status, login, _ = http.call('POST', '/auth/newproject', {'login': login['login'], 'projectName': 'SjD Upload Agent Synthetic'})
        if status != 200 or not login.get('code'):
            raise RuntimeError('Dedicated simulation project creation failed')
        with path.open('x') as stream:
            json.dump(identity, stream)
        path.chmod(0o600)
    status, result, _ = http.call('POST', '/oauth2/token', {'grant_type': 'authorization_code', 'code': login['code'],
        'code_verifier': verifier}, form=True)
    if status != 200:
        raise RuntimeError('Dedicated simulation token exchange failed')
    TOKEN = result['access_token']


def search(kind, params):
    """Read all pages without forwarding authentication to untrusted next URLs."""
    path = '/fhir/R4/' + kind + '?' + urllib.parse.urlencode(params)
    rows, seen = [], set()
    base = urllib.parse.urlsplit(http.BASE)
    while path:
        if path in seen or len(seen) >= 1000:
            raise ValueError('Clinical pagination repeated or exceeded the safety bound')
        seen.add(path)
        current_url = http.BASE + path
        page = request('GET', path)
        rows.extend(e['resource'] for e in page.get('entry', []) if 'resource' in e)
        next_urls = [link.get('url', '') for link in page.get('link', []) if link.get('relation') == 'next']
        if len(next_urls) > 1:
            raise ValueError('Clinical pagination has multiple next links')
        path = None
        if next_urls:
            next_url = urllib.parse.urlsplit(urllib.parse.urljoin(current_url, next_urls[0]))
            if ((next_url.scheme, next_url.netloc) != (base.scheme, base.netloc) or
                    next_url.path != '/fhir/R4/' + kind or next_url.fragment or next_url.username):
                raise ValueError('Clinical pagination URL is outside the configured resource boundary')
            path = next_url.path + ('?' + next_url.query if next_url.query else '')
    return rows


def existing(kind, key):
    found = search(kind, {'identifier': SYSTEM + '|' + key})
    if len(found) > 1:
        raise ValueError('Identity conflict: multiple clinical resources')
    return found[0] if found else None


def create(resource, key):
    return request('POST', '/fhir/R4/' + resource['resourceType'],
        {**resource, 'identifier': [{'system': SYSTEM, 'value': key}]},
        {'If-None-Exist': urllib.parse.urlencode({'identifier': SYSTEM + '|' + key})})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _checkpoint(progress, callback):
    if callback:
        callback(copy.deepcopy(progress))


def _field_archive(fact, visit, event_key, patient_ref, encounter, source_hash, reviewer):
    """A receipt reconciles a committed transaction even if its response was lost."""
    value = fact['value'] + (' ' + fact['unit'] if fact['unit'] else '')
    correction = fact.get('correction_of')
    revision = fact.get('revision', 0)
    fact_key = event_key + ':' + fact['code']
    if correction:
        fact_key += ':revision:' + str(revision) + ':' + _digest([source_hash, fact.get('field_id'), correction])
    review = fact.get('review', {'actor': reviewer, 'action': 'accept'})
    receipt_key = 'receipt:' + _digest([source_hash, fact_key, revision, review, fact['quote'], value])
    encounter_ref = 'Encounter/' + encounter['id']

    def reconciled():
        receipt = existing('Basic', receipt_key)
        if not receipt:
            return None
        obs = existing('Observation', fact_key)
        if (not obs or obs.get('valueString') != value or obs.get('subject', {}).get('reference') != patient_ref or
                obs.get('encounter', {}).get('reference') != encounter_ref):
            raise ValueError('Archive receipt does not match the reviewed fact')
        return {'state': 'archived', 'observation': obs['id'], 'key': fact_key, 'receipt': receipt['id'],
                'revision': revision, 'correction_of': correction}

    result = reconciled()
    if result:
        return result
    prior = existing('Observation', fact_key)
    if prior:
        if prior.get('valueString') != value:
            raise ValueError('Existing event has a conflicting value; explicit correction workflow required')
        if (prior.get('subject', {}).get('reference') != patient_ref or
                prior.get('encounter', {}).get('reference') != encounter_ref or not any(
                    c.get('system') == SYSTEM + '/field' and c.get('code') == fact['code']
                    for c in prior.get('code', {}).get('coding', []))):
            raise ValueError('Existing observation has inconsistent identity bindings')
    if correction:
        target = request('GET', '/fhir/R4/Observation/' + str(uuid.UUID(correction)))
        if (target.get('subject', {}).get('reference') != patient_ref or
                target.get('encounter', {}).get('reference') != encounter_ref or not any(
                    c.get('system') == SYSTEM + '/field' and c.get('code') == fact['code']
                    for c in target.get('code', {}).get('coding', []))):
            raise ValueError('Correction target does not match the patient, event and field')
        target_ref = 'Observation/' + correction
        successors = [o for o in search('Observation', {'encounter': encounter_ref})
                      if any(r.get('reference') == target_ref for r in o.get('derivedFrom', []))]
        if any(not prior or item['id'] != prior['id'] for item in successors):
            raise ValueError('Correction target was already superseded; reload current history')
    url = 'urn:uuid:' + str(uuid.uuid4())
    obs = {'resourceType': 'Observation', 'identifier': [{'system': SYSTEM, 'value': fact_key}],
        'status': 'amended' if correction else 'final',
        'code': {'coding': [{'system': SYSTEM + '/field', 'code': fact['code']}], 'text': LABELS[fact['code']]},
        'subject': {'reference': patient_ref}, 'encounter': {'reference': encounter_ref},
        'effectiveDateTime': visit['date'], 'valueString': value, 'note': [{'text': fact['quote']}],
        'extension': [{'url': SYSTEM + '/source-sha256', 'valueString': source_hash},
                      {'url': SYSTEM + '/field-id', 'valueString': fact.get('field_id', fact_key)},
                      {'url': SYSTEM + '/review-revision', 'valueInteger': revision}]}
    entities = [{'role': 'source', 'what': {'identifier': {'system': SYSTEM + '/sha256', 'value': source_hash}}}]
    if correction:
        obs['derivedFrom'] = [{'reference': 'Observation/' + correction}]
        entities.append({'role': 'revision', 'what': {'reference': 'Observation/' + correction}})
    provenance = {'resourceType': 'Provenance', 'target': [{'reference': url}],
        'recorded': dt.datetime.now(dt.timezone.utc).isoformat(),
        'agent': [{'who': {'display': review.get('actor', reviewer)}}], 'entity': entities,
        'extension': [{'url': SYSTEM + '/review-decision', 'valueString': json.dumps(review, sort_keys=True)}]}
    receipt = {'resourceType': 'Basic', 'identifier': [{'system': SYSTEM, 'value': receipt_key}],
        'code': {'text': 'Synthetic reviewed source receipt'}, 'subject': {'reference': patient_ref},
        'extension': [{'url': SYSTEM + '/observation', 'valueReference': {'reference': url}}]}
    entries = [
        {'fullUrl': url, 'resource': obs, 'request': {'method': 'POST', 'url': 'Observation',
            'ifNoneExist': urllib.parse.urlencode({'identifier': SYSTEM + '|' + fact_key})}},
        {'resource': provenance, 'request': {'method': 'POST', 'url': 'Provenance'}},
        {'resource': receipt, 'request': {'method': 'POST', 'url': 'Basic',
            'ifNoneExist': urllib.parse.urlencode({'identifier': SYSTEM + '|' + receipt_key})}},
    ]
    try:
        bundle = request('POST', '/fhir/R4/', {'resourceType': 'Bundle', 'type': 'transaction', 'entry': entries})
        if (bundle.get('type') != 'transaction-response' or len(bundle.get('entry', [])) != len(entries) or
                any(not e.get('response', {}).get('status', '').startswith('2') for e in bundle['entry'])):
            raise RuntimeError('Clinical transaction incomplete')
    except Exception:
        result = reconciled()
        if result:
            return result
        raise
    result = reconciled()
    if not result:
        raise RuntimeError('Clinical transaction has no durable receipt')
    return result


def _supported_task(task):
    return any(c.get('system') == SYSTEM and c.get('code') == 'visit-based-followup-v1'
               for c in task.get('code', {}).get('coding', []))


def _followup_window(index_day, followup_days):
    due = dt.date.fromisoformat(index_day) + dt.timedelta(days=followup_days)
    return {'start': (due - dt.timedelta(days=14)).isoformat(), 'end': (due + dt.timedelta(days=14)).isoformat()}


def publish(candidate, source_hash, followup_days, reviewer, progress=None, on_progress=None):
    """Resume a frozen review plan, retaining completed field and Task receipts."""
    # ponytail: one local publisher lock; use a durable lease before multi-worker deployment.
    with LOCK:
        state = copy.deepcopy(progress or {})
        state.setdefault('fields', {})
        state.setdefault('matched_followups', [])
        if 'transaction-bundles' not in request('GET', '/auth/me')['project'].get('features', []):
            raise ValueError('Atomic transaction feature required')
        patient_key = 'patient:' + candidate['patient_id']
        index_days = [visit['date'] for visit in candidate['visits']
                      if any(not fact.get('correction_of') for fact in visit['facts'])]
        if index_days:
            index_day = max(index_days)
            prior_task = existing('Task', patient_key + ':followup:' + index_day)
            if prior_task and prior_task.get('restriction', {}).get('period') != _followup_window(index_day, followup_days):
                raise ValueError('Existing follow-up window differs; explicit rescheduling required')
        patient = existing('Patient', patient_key)
        if patient and patient.get('name', [{}])[0].get('text') != candidate['name']:
            raise ValueError('Patient identifier has a different name; manual identity review required')
        if not patient:
            patient = create({'resourceType': 'Patient', 'active': True, 'name': [{'text': candidate['name']}]}, patient_key)
        patient_ref = 'Patient/' + patient['id']
        state['patient'] = patient['id']
        visits, eligible = [], []
        for visit in candidate['visits']:
            event_id = visit.get('event_id') or 'source-' + source_hash
            event_key = patient_key + ':' + visit['date'] + ':event:' + event_id
            encounter = create({'resourceType': 'Encounter', 'status': 'finished', 'class': {'code': 'AMB'},
                'subject': {'reference': patient_ref}, 'period': {'start': visit['date']}}, event_key)
            visit_receipt = {'encounter': encounter['id'], 'date': visit['date'], 'event_id': event_id, 'key': event_key}
            visits.append(visit_receipt)
            for fact in visit['facts']:
                field_id = fact.get('field_id') or _digest([event_key, fact['code']])
                completed = state['fields'].get(field_id, {})
                if completed.get('state') == 'archived' and completed.get('revision') == fact.get('revision', 0):
                    # A durable checkpoint is authoritative for this frozen revision.
                    # Only ambiguous commits without it need remote reconciliation.
                    continue
                field_state = {'state': 'pending', 'revision': fact.get('revision', 0), 'event_id': event_id,
                               'encounter': encounter['id'], 'date': visit['date'], 'code': fact['code']}
                state['fields'][field_id] = field_state
                state['visits'] = visits
                _checkpoint(state, on_progress)
                try:
                    field_state.update(_field_archive(fact, visit, event_key, patient_ref, encounter, source_hash, reviewer))
                except Exception as exc:
                    field_state.update(state='failed', error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
                    _checkpoint(state, on_progress)
                    raise
                _checkpoint(state, on_progress)
            if any(not f.get('correction_of') for f in visit['facts']):
                eligible.append(visit_receipt)
        state['visits'] = visits
        state['task_phase'] = 'pending'
        _checkpoint(state, on_progress)
        try:
            # A correction changes a fact, not the occurrence of a new reviewed visit.
            for pending in search('Task', {'patient': patient_ref, '_count': '200'}) if eligible else []:
                if pending.get('for', {}).get('reference') != patient_ref or not _supported_task(pending):
                    continue
                index_day = next((i.get('valueDate') for i in pending.get('input', []) if i.get('type', {}).get('text') == 'Index visit date'), None)
                period = pending.get('restriction', {}).get('period', {})
                visit = next((v for v in eligible if index_day and v['date'] > index_day and
                              period.get('start', '') <= v['date'] <= period.get('end', '')), None)
                if not visit:
                    continue
                target_ref = 'Encounter/' + visit['encounter']
                if pending['status'] == 'requested':
                    pending['status'] = 'completed'
                    pending['output'] = [{'type': {'text': 'Reviewed follow-up visit'},
                                          'valueReference': {'reference': target_ref}}]
                    request('PUT', '/fhir/R4/Task/' + pending['id'], pending,
                            {'If-Match': 'W/"' + pending['meta']['versionId'] + '"'})
                elif pending['status'] != 'completed' or not any(
                        item.get('type', {}).get('text') == 'Reviewed follow-up visit' and
                        item.get('valueReference', {}).get('reference') == target_ref for item in pending.get('output', [])):
                    continue
                if pending['id'] not in state['matched_followups']:
                    state['matched_followups'].append(pending['id'])
                _checkpoint(state, on_progress)
            index_visit = max(eligible or visits, key=lambda item: (item['date'], item['event_id']))
            # Distinct examinations on one day share one follow-up obligation.
            task_key = patient_key + ':followup:' + index_visit['date']
            task = existing('Task', task_key)
            window = _followup_window(index_visit['date'], followup_days)
            if eligible and task and task.get('restriction', {}).get('period') != window:
                raise ValueError('Existing follow-up window differs; explicit rescheduling required')
            if eligible and not task:
                task = create({'resourceType': 'Task', 'status': 'requested', 'intent': 'plan',
                    'code': {'coding': [{'system': SYSTEM, 'code': 'visit-based-followup-v1'}],
                             'text': 'Synthetic visit-based follow-up; no message delivery'}, 'for': {'reference': patient_ref},
                    'input': [{'type': {'text': 'Index visit date'}, 'valueDate': index_visit['date']},
                              {'type': {'text': 'Index event'}, 'valueReference': {'reference': 'Encounter/' + index_visit['encounter']}},
                              {'type': {'text': 'Selected interval days'}, 'valueInteger': followup_days}],
                    'restriction': {'period': window}}, task_key)
            state.update(task=task['id'] if task else None, task_phase='complete',
                         window_start=task['restriction']['period']['start'] if task else None,
                         window_end=task['restriction']['period']['end'] if task else None)
            state.pop('task_error', None)
            _checkpoint(state, on_progress)
        except Exception as exc:
            state.update(task_phase='failed', task_error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
            _checkpoint(state, on_progress)
            raise
        return state


def tasks():
    rows = search('Task', {'_count': '200', '_sort': '-_lastUpdated'})
    result = []
    for task in rows:
        evidence = [reference for item in task.get('output', [])
                    if isinstance(reference := item.get('valueReference', {}).get('reference'), str)
                    and re.fullmatch(r'Encounter/[A-Za-z0-9.-]{1,64}', reference)]
        supported = _supported_task(task)
        mode = 'reviewed-visit-only' if supported else 'unsupported'
        if task['status'] == 'completed' and not evidence:
            mode = 'legacy-unverified'
        result.append({'id': task['id'], 'status': task['status'], 'patient': task.get('for', {}).get('reference'),
                       'window': task.get('restriction', {}).get('period'), 'version': task['meta']['versionId'],
                       'completion_mode': mode, 'evidence': evidence})
    return result


def complete_task(task_id, version):
    """Keep the historical route closed; only reviewed visit evidence may complete Tasks."""
    raise ValueError('Follow-up completion requires a confirmed, in-window reviewed visit; manual completion is disabled')
