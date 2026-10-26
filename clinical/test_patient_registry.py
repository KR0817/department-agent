"""Patient registration and document binding use isolated synthetic stores only."""
import contextlib
import datetime as dt
import hashlib
import importlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
import accounts
import outbox
import patient_registry
import recovery


class PatientRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.previous_accounts, self.previous_outbox = accounts.DATABASE, outbox.DATABASE
        self.previous_server = sys.modules.get('server')
        self.previous_namespace = dict(self.previous_server.__dict__) if self.previous_server else None
        self.environment = patch.dict(os.environ, {'AGENT_DATA': str(self.root), 'AGENT_DEMO': '0',
                                                   'AGENT_DOCUMENT_MODE': 'local', 'AGENT_PORT': '13042'})
        self.environment.start()
        self.server = importlib.reload(self.previous_server) if self.previous_server else importlib.import_module('server')
        self.client = TestClient(self.server.app, base_url='http://localhost:13042',
                                 headers={'origin': 'http://localhost:13042'})
        self.password = 'Synthetic-registry-password'
        response = self.client.post('/api/auth/setup', json={'username': 'synthetic-admin', 'password': self.password})
        self.assertEqual(response.status_code, 200)
        self.identity = {'patient_id': 'SIM-REGISTRY', 'name': 'Synthetic Registry', 'sex': 'unknown', 'birth_date': None}

    def tearDown(self):
        self.client.close()
        accounts.DATABASE, outbox.DATABASE = self.previous_accounts, self.previous_outbox
        self.environment.stop()
        if self.previous_namespace is not None:
            self.server.__dict__.clear()
            self.server.__dict__.update(self.previous_namespace)
        else:
            sys.modules.pop('server', None)
        self.temp.cleanup()

    def register(self, **changes):
        response = self.client.post('/api/patient-registry', json={**self.identity, **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self, content=b'Synthetic registry source', patient_id='SIM-REGISTRY', filename='synthetic.txt'):
        return self.client.post('/api/upload', files={'file': (filename, content)},
                                data={'patient_id': patient_id} if patient_id is not None else {})

    def record(self, job):
        return self.client.get('/api/jobs/' + job).json()

    def source(self, code='pain', value='3', patient_id='SIM-REGISTRY', name='Synthetic Registry', note=None):
        return ('# SJD-SYNTHETIC\npatient_id,name,visit_date,event_id,code,value,unit,source_note\n'
                f'{patient_id},{name},2026-10-24,am,{code},{value},,{note or (code + ": " + value)}\n').encode()

    def wait_job(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            record = self.record(job)
            if record['state'] not in ('queued', 'reading', 'extracting'):
                return record
            time.sleep(0.02)
        self.fail('Synthetic worker did not finish within the bounded wait')

    def candidate(self, **changes):
        return {'patient_id': self.identity['patient_id'], 'name': self.identity['name'],
                'visits': [{'date': '2026-10-24', 'event_id': 'am',
                            'facts': [{'code': 'pain', 'value': '3', 'unit': '', 'quote': 'pain: 3'}]}], **changes}

    def review_candidate(self, job, candidate=None):
        candidate = candidate or self.candidate()
        version = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        self.server.update(job, state='review', candidate=json.dumps(candidate), version=version,
                           text='2026-10-24 am\npain: 3')
        return self.record(job)

    def approve(self, record):
        return self.client.post('/api/jobs/' + record['id'] + '/approve', json={
            'version': record['version'], 'review_revision': record['review_revision'],
            'reviewed': True, 'accept_defaults': True})

    def archived(self, patient_id='SIM-REGISTRY', name='Synthetic Registry', *, legacy=False,
                 code='medications', value='Synthetic medication statement', date='2026-10-24',
                 observation=None, correction_of=None, state='archived'):
        job = str(uuid.uuid4())
        fact = {'code': code, 'value': value, 'unit': '', 'quote': code + ': ' + value,
                'field_id': job[:8], 'revision': 1}
        if correction_of:
            fact['correction_of'] = correction_of
        candidate = {'patient_id': patient_id, 'name': name, 'visits': [{'date': date, 'event_id': 'am', 'facts': [fact]}]}
        receipt = {'patient': 'synthetic-fhir-patient'}
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,text,candidate,version,receipt,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (job, job, 'synthetic-archive.csv', '.csv', 'published' if legacy else 'partial',
                         fact['quote'], json.dumps(candidate), job, json.dumps(receipt) if legacy else None, date))
            if not legacy:
                progress = {'patient': receipt['patient'], 'fields': {fact['field_id']: {'state': state,
                    'observation': observation or 'observation-' + job, 'revision': 1}}}
                con.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?)',
                            (job, 1, json.dumps({'candidate': candidate, 'followup_days': 90}), json.dumps(progress),
                             json.dumps(receipt), 'partial', None))
        return job

    def test_registry_starts_empty_and_does_not_enroll_the_demo_cohort(self):
        self.assertEqual(self.client.get('/api/patient-registry').json(), {'patients': [], 'total': 0})
        response = self.client.get('/api/demo/patient-overview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['summary']['enrolled'], 50)
        self.assertEqual(response.json()['summary']['completed'], 50)
        self.assertEqual(self.client.get('/api/patient-registry').json()['total'], 0)

    def test_registration_is_idempotent_and_actor_is_server_derived(self):
        first = self.register(name='  Synthetic Registry  ', sex='female', birth_date='1980-01-02')
        again = self.register(sex='female', birth_date='1980-01-02')
        self.assertTrue(first['created'])
        self.assertFalse(again['created'])
        self.assertEqual(first['patient'], again['patient'])
        with self.server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM patient_registry').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT actor FROM patient_registry').fetchone()[0], 'synthetic-admin')
        self.assertEqual(set(first['patient']), {'patient_id', 'name', 'sex', 'birth_date', 'source', 'created_at'})

    def test_registration_rejects_invalid_values_unknown_fields_and_conflicts(self):
        future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        changes = ({'patient_id': 'x'}, {'patient_id': 'x' * 65}, {'patient_id': '\u60a3\u8005001'},
                   {'patient_id': '../patient'}, {'name': '   '}, {'name': 'x' * 81}, {'name': 'Hidden\x00Name'},
                   {'name': 'Hidden\u200bName'}, {'sex': 'invalid'}, {'birth_date': future},
                   {'birth_date': '2026-02-30'}, {'birth_date': '20260203'}, {'actor': 'forged'})
        for value in changes:
            response = self.client.post('/api/patient-registry', json={**self.identity, **value})
            self.assertEqual(response.status_code, 422, response.text)
        self.register()
        for value in ({'name': 'Other Name'}, {'sex': 'male'}, {'birth_date': '1980-01-01'}):
            self.assertEqual(self.client.post('/api/patient-registry', json={**self.identity, **value}).status_code, 409)

    def test_registration_audit_failure_rolls_back_the_registration(self):
        with self.server.db() as con:
            con.execute("CREATE TRIGGER synthetic_registration_audit_failure BEFORE INSERT ON audit WHEN NEW.event='patient_registered' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.register()
        self.assertEqual(self.client.get('/api/patient-registry').json()['total'], 0)

    def test_binding_audit_failure_rolls_back_job_and_selection_before_source_creation(self):
        self.register()
        with self.server.db() as con:
            con.execute("CREATE TRIGGER synthetic_binding_audit_failure BEFORE INSERT ON audit WHEN NEW.event='patient_selected' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.upload()
        self.assertEqual(self.client.get('/api/jobs').json(), [])
        self.assertEqual(list((self.root / 'sources').iterdir()), [])
        with self.server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM job_patient_association').fetchone()[0], 0)

    def test_registered_patient_has_empty_verified_context_and_no_candidate_facts(self):
        self.register()
        job = self.upload().json()['id']
        self.review_candidate(job)
        result = self.client.get('/api/patient-registry/SIM-REGISTRY').json()
        self.assertEqual(result['visits'], [])
        self.assertEqual(result['clinical_context'], {key: [] for key in patient_registry.CONTEXT_CODES})
        self.assertEqual(result['documents'], [{'id': job, 'filename': 'synthetic.txt', 'state': 'review',
                                               'created': self.record(job)['created']}])

    def test_registry_routes_require_authentication_and_same_origin(self):
        with TestClient(self.server.app, base_url='http://localhost:13042') as anonymous:
            self.assertEqual(anonymous.get('/api/patient-registry').status_code, 401)
            self.assertEqual(anonymous.get('/api/patient-registry/SIM-REGISTRY').status_code, 401)
        self.assertEqual(self.client.post('/api/patient-registry', json=self.identity,
                                          headers={'origin': 'https://outside.invalid'}).status_code, 403)
        self.assertEqual(self.client.get('/api/patient-registry', headers={'host': 'outside.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/patient-registry', content=json.dumps(self.identity),
                                          headers={'content-type': 'text/plain'}).status_code, 422)
        response = self.client.get('/api/patient-registry')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/api/patient-registry/unknown').status_code, 404)

    def test_staff_can_register_without_administrator_role(self):
        self.assertEqual(self.client.post('/api/admin/users', json={'username': 'synthetic-staff',
            'password': self.password, 'role': 'staff'}).status_code, 200)
        with TestClient(self.server.app, base_url='http://localhost:13042',
                        headers={'origin': 'http://localhost:13042'}) as staff:
            self.assertEqual(staff.post('/api/auth/login', json={'username': 'synthetic-staff', 'password': self.password}).status_code, 200)
            self.assertEqual(staff.post('/api/patient-registry', json=self.identity).status_code, 200)
            self.assertEqual(staff.get('/api/patient-registry').json()['total'], 1)

    def test_upload_requires_existing_selection_and_does_not_write_failed_sources(self):
        self.assertEqual(self.upload(patient_id=None).status_code, 422)
        self.assertEqual(self.upload(patient_id='SIM-MISSING').status_code, 404)
        self.assertEqual(self.upload(patient_id='SIM-OV20-001').status_code, 404)
        self.assertEqual(self.upload(patient_id='SIM-OV50-001').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs').json(), [])
        self.assertEqual(list((self.root / 'sources').iterdir()), [])

    def test_upload_binds_server_identity_and_duplicate_cannot_rebind(self):
        self.register()
        self.register(patient_id='SIM-OTHER', name='Synthetic Other')
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        job = response.json()['id']
        selected = self.record(job)['patient_context']
        self.assertEqual({key: selected[key] for key in ('patient_id', 'name', 'actor', 'source')},
                         {'patient_id': 'SIM-REGISTRY', 'name': 'Synthetic Registry', 'actor': 'synthetic-admin', 'source': 'operator_selected'})
        self.assertTrue(selected['selected_at'])
        self.assertEqual(self.upload().json(), {'id': job, 'duplicate': True, 'patient_id': 'SIM-REGISTRY'})
        self.assertEqual(self.upload(patient_id='SIM-OTHER').status_code, 409)
        self.assertEqual(self.record(job)['patient_context'], selected)
        self.assertEqual((self.root / 'sources' / job).read_bytes(), b'Synthetic registry source')
        self.assertEqual(len(self.client.get('/api/jobs').json()), 1)

    def test_legacy_duplicate_unknown_identity_is_not_implicitly_bound(self):
        self.register()
        source = b'Unbound legacy synthetic document'
        job = str(uuid.uuid4())
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,state,created) VALUES(?,?,?,?,?)',
                        (job, hashlib.sha256(source).hexdigest(), 'legacy.txt', 'queued', '2026-10-01'))
        self.assertEqual(self.upload(source).status_code, 409)
        self.review_candidate(job)
        self.assertTrue(self.upload(source).json()['duplicate'])
        self.assertIsNone(self.record(job)['patient_context'])
        self.server.update(job, candidate=json.dumps(self.candidate(name='Different Name')))
        self.assertEqual(self.upload(source).status_code, 409)

    def test_worker_passes_binding_and_blocks_mismatched_candidate_before_outbox(self):
        self.register()
        calls = []
        def extract(text, patient_context=None):
            calls.append(patient_context)
            return self.candidate(patient_id='SIM-WRONG')
        with patch.object(self.server, 'extract_csv', side_effect=extract), \
                patch.object(self.server.outbox, 'candidate_ready') as queue, self.client:
            job = self.upload(self.source(), filename='synthetic.csv').json()['id']
            record = self.wait_job(job)
            self.assertEqual(record['state'], 'blocked')
            self.assertEqual(record['error'], 'Selected patient does not match the document identity')
            self.assertIsNone(record['candidate'])
            queue.assert_not_called()
        self.assertEqual(calls[0]['patient_id'], 'SIM-REGISTRY')
        self.assertEqual(calls[0]['name'], 'Synthetic Registry')

    def test_worker_legacy_unbound_call_keeps_the_old_signature(self):
        source = self.source()
        job = str(uuid.uuid4())
        (self.root / 'sources' / job).write_bytes(source)
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,created) VALUES(?,?,?,?,?,?)',
                        (job, hashlib.sha256(source).hexdigest(), 'legacy.csv', '.csv', 'queued', '2026-10-01'))
        with patch.object(self.server, 'extract_csv', side_effect=lambda text: self.candidate()) as extract, self.client:
            self.assertEqual(self.wait_job(job)['state'], 'review')
            self.assertEqual(len(extract.call_args.args), 1)
            self.assertEqual(extract.call_args.kwargs, {})

    def test_publication_rejects_candidate_and_frozen_plan_identity_mismatch(self):
        self.register()
        job = self.upload().json()['id']
        record = self.review_candidate(job, self.candidate(name='Different Name'))
        with patch.object(self.server.clinical, 'publish') as publish:
            self.assertEqual(self.approve(record).status_code, 409)
            publish.assert_not_called()
        record = self.review_candidate(job)
        with self.server.db() as con:
            con.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?)',
                        (job, 0, json.dumps({'candidate': self.candidate(patient_id='SIM-OTHER'), 'followup_days': 90}),
                         json.dumps({'fields': {}}), None, 'partial', None))
        with patch.object(self.server.clinical, 'publish') as publish:
            self.assertEqual(self.approve(record).status_code, 409)
            publish.assert_not_called()

    def legacy_review(self, name='Synthetic Original'):
        job = str(uuid.uuid4())
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,created) VALUES(?,?,?,?,?,?)',
                        (job, job, 'synthetic-legacy.csv', '.csv', 'queued', '2026-10-01'))
        return self.review_candidate(job, self.candidate(name=name))

    def test_unbound_legacy_candidate_cannot_publish_against_new_registered_name(self):
        record = self.legacy_review()
        self.assertIsNone(record['patient_context'])
        self.register()
        with patch.object(self.server.clinical, 'publish') as publish, \
                patch.object(self.server.outbox, 'publication_ready') as followup:
            response = self.approve(record)
            self.assertEqual(response.status_code, 409, response.text)
            publish.assert_not_called()
            followup.assert_not_called()
        current = self.record(record['id'])
        self.assertEqual(current['candidate'], record['candidate'])
        self.assertEqual(current['history'], [])
        self.assertIsNone(current['publication'])
        self.assertIsNone(current['patient_context'])
        self.assertEqual(self.client.get('/api/patient-registry').status_code, 200)

    def test_unbound_frozen_plan_replay_cannot_publish_against_registered_identity(self):
        record = self.legacy_review(name=self.identity['name'])
        self.register()
        # The actual frozen payload must be checked even when the current candidate matches.
        plan = {'candidate': self.candidate(name='Synthetic Original'), 'followup_days': 90,
                'version': record['version'], 'reviewer': 'synthetic-admin',
                'input_review_revision': 0, 'accept_defaults': True}
        with self.server.db() as con:
            con.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?)',
                        (record['id'], 0, json.dumps(plan), json.dumps({'fields': {}}), None, 'partial', None))
        self.server.update(record['id'], state='partial')
        with patch.object(self.server.clinical, 'publish') as publish, \
                patch.object(self.server.outbox, 'publication_ready') as followup:
            self.assertEqual(self.approve(record).status_code, 409)
            publish.assert_not_called()
            followup.assert_not_called()
        current = self.record(record['id'])
        self.assertEqual(current['publication']['plan'], plan)
        self.assertEqual(current['state'], 'partial')
        self.assertIsNone(current['patient_context'])

    def test_five_context_groups_project_archives_only_and_preserve_corrections(self):
        self.register()
        original = self.archived(observation='synthetic-original', date='2026-10-01')
        corrected = self.archived(value='Synthetic corrected medication', date='2026-10-01', correction_of='synthetic-original')
        for code in patient_registry.CONTEXT_CODES[1:]:
            self.archived(code=code, value='Synthetic ' + code)
        self.archived(code='infection_status', value='Synthetic unarchived candidate', state='pending')
        detail = self.client.get('/api/patient-registry/SIM-REGISTRY').json()
        self.assertEqual(set(detail['clinical_context']), set(patient_registry.CONTEXT_CODES))
        medications = detail['clinical_context']['medications']
        self.assertEqual(len(medications), 2)
        self.assertFalse(next(item for item in medications if item['source_job'] == original)['current'])
        self.assertTrue(next(item for item in medications if item['source_job'] == corrected)['current'])
        self.assertTrue(all(item['verification'] == 'reviewed_archive' for item in medications))
        self.assertEqual(len(detail['clinical_context']['infection_status']), 1)
        self.assertEqual(len(detail['documents']), 7)

    def test_legacy_prescription_is_medication_history_without_inferred_status(self):
        job = self.archived(legacy=True, code='prescription', value='Synthetic historical prescription')
        listing = self.client.get('/api/patient-registry').json()
        self.assertEqual(listing['total'], 1)
        self.assertEqual(listing['patients'][0]['source'], 'archived')
        detail = self.client.get('/api/patient-registry/SIM-REGISTRY').json()
        item = detail['clinical_context']['medications'][0]
        self.assertEqual(item['code'], 'prescription')
        self.assertEqual(item['source_job'], job)
        self.assertEqual(item['verification'], 'legacy_archive')
        self.assertEqual(item['value'], 'Synthetic historical prescription')
        self.assertEqual(detail['clinical_context']['infection_status'], [])
        self.assertNotIn('taking', item)

    def test_archived_identity_can_be_enriched_but_name_conflicts_are_explicit(self):
        self.archived()
        self.assertTrue(self.register(sex='female')['created'])
        self.assertEqual(self.client.get('/api/patient-registry').json()['patients'][0]['source'], 'registered')
        self.assertEqual(self.client.post('/api/patient-registry', json={**self.identity, 'name': 'Other'}).status_code, 409)
        self.archived(name='Conflicting Synthetic Name')
        self.assertEqual(self.client.get('/api/patient-registry').status_code, 409)
        self.assertEqual(self.client.get('/api/patients').status_code, 409)

    def test_database_export_and_recovery_allowlist_include_new_business_tables(self):
        self.register()
        job = self.upload().json()['id']
        response = self.client.get('/api/admin/export/database')
        self.assertEqual(response.status_code, 200)
        target_dir = self.root / 'synthetic-export'
        target_dir.mkdir()
        target = target_dir / 'jobs.sqlite'
        target.write_bytes(response.content)
        summary = recovery.database_summary(target)
        self.assertEqual(summary['tables']['patient_registry']['rows'], 1)
        self.assertEqual(summary['tables']['job_patient_association']['rows'], 1)
        self.assertNotIn('users', summary['tables'])
        with contextlib.closing(sqlite3.connect(target)) as con:
            self.assertEqual(con.execute('SELECT job_id,patient_id FROM job_patient_association').fetchone(), (job, 'SIM-REGISTRY'))

    def test_real_csv_binding_reaches_review_archive_and_business_detail(self):
        self.register()
        content = self.source(code='medications', value='Synthetic medication statement')
        with self.client:
            job = self.upload(content, filename='synthetic.csv').json()['id']
            record = self.wait_job(job)
            self.assertEqual(record['state'], 'review', record.get('error'))
            def publish(candidate, source_hash, days, actor, progress, on_progress):
                self.assertEqual(candidate['patient_id'], 'SIM-REGISTRY')
                self.assertEqual(candidate['name'], 'Synthetic Registry')
                progress['patient'] = 'synthetic-fhir-patient'
                for field_id, item in progress['fields'].items():
                    item.update(state='archived', observation='synthetic-' + field_id)
                on_progress(progress)
                return {'patient': 'synthetic-fhir-patient', 'task': 'synthetic-task',
                        'window_start': '2026-12-01', 'window_end': '2027-02-01'}
            with patch.object(self.server.clinical, 'publish', side_effect=publish):
                response = self.approve(record)
                self.assertEqual(response.status_code, 200, response.text)
            detail = self.client.get('/api/patient-registry/SIM-REGISTRY').json()
            self.assertEqual(detail['documents'][0]['state'], 'published')
            self.assertEqual(detail['clinical_context']['medications'][0]['value'], 'Synthetic medication statement')
            self.assertEqual(self.record(job)['text'], content.decode())
            self.assertEqual((self.root / 'sources' / job).read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
