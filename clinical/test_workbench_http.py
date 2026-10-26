"""Authenticated HTTP checks using fresh synthetic stores and no live clinical APIs."""
import asyncio
import contextlib
import hashlib
import importlib
import io
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

import accounts
import outbox
import patient_overview


class WorkbenchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.previous_accounts = accounts.DATABASE
        self.previous_outbox = outbox.DATABASE
        self.previous_server = sys.modules.get('server')
        self.previous_namespace = dict(self.previous_server.__dict__) if self.previous_server else None
        self.environment = patch.dict(os.environ, {'AGENT_DATA': str(self.root), 'AGENT_DEMO': '0',
                                                   'AGENT_DOCUMENT_MODE': 'local', 'AGENT_PORT': '13042'})
        self.environment.start()
        self.server = importlib.reload(self.previous_server) if self.previous_server else importlib.import_module('server')
        self.client = self.new_client()
        self.password = 'Synthetic-http-test-password'

    def tearDown(self):
        self.client.close()
        accounts.DATABASE = self.previous_accounts
        outbox.DATABASE = self.previous_outbox
        self.environment.stop()
        if self.previous_namespace is not None:
            self.server.__dict__.clear()
            self.server.__dict__.update(self.previous_namespace)
        else:
            sys.modules.pop('server', None)
        self.temp.cleanup()

    def new_client(self):
        return TestClient(self.server.app, base_url='http://localhost:13042',
                          headers={'origin': 'http://localhost:13042'})

    def setup_admin(self):
        response = self.client.post('/api/auth/setup', json={'username': 'ADMIN', 'password': self.password})
        self.assertEqual(response.status_code, 200)
        return response

    def test_status_uses_selected_model_pin(self):
        self.setup_admin()
        for model in ('qwen3:4b', 'qwen3:14b'):
            expected = self.server.pinned_model_digest(model)
            for digest, ready in ((expected, True), ('wrong', False)):
                response = io.StringIO(json.dumps({'models': [{'name': model, 'digest': digest}]}))
                with self.subTest(model=model, digest=digest), patch.object(self.server, 'MODEL', model), \
                        patch('server.urllib.request.urlopen', return_value=response):
                    status = self.client.get('/api/status').json()
                    self.assertEqual(status['model'], model)
                    self.assertEqual(status['model_ready'], ready)


    def upload_source(self, content=b'Synthetic source only', name='synthetic.txt'):
        identity = {'patient_id': 'SIM-HTTP', 'name': 'Synthetic Example'}
        if name.endswith('.csv'):
            candidate = self.server.extract_csv(content.decode('utf-8'))
            identity = {key: candidate[key] for key in ('patient_id', 'name')}
        self.assertEqual(self.client.post('/api/patient-registry', json=identity).status_code, 200)
        response = self.client.post('/api/upload', files={'file': (name, content)}, data={'patient_id': identity['patient_id']})
        self.assertEqual(response.status_code, 200)
        return response.json()['id']

    def test_anonymous_routes_and_legacy_cookie_are_denied(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.client.get('/api/auth/state').json(),
                         {'setup_required': True, 'authenticated': False, 'user': None})
        for route in ('/api/jobs', '/api/jobs/unknown/source', '/api/admin/overview',
                      '/api/admin/export/database', '/api/admin/export/archive', '/api/outbox', '/api/demo/patient-overview'):
            self.assertEqual(self.client.get(route).status_code, 401)
        self.client.cookies.set('sjd_agent', 'synthetic-historical-demo-cookie')
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)

    def test_bootstrap_cookie_login_and_logout(self):
        response = self.setup_admin()
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('sjd_workbench_13042=', cookie)
        self.assertIn('httponly', cookie)
        self.assertIn('samesite=strict', cookie)
        self.assertIn('path=/', cookie)
        self.assertIn('max-age=' + str(accounts.TTL_SECONDS), cookie)
        self.assertEqual(response.json()['user']['username'], 'admin')
        self.assertEqual(response.json()['user']['role'], 'admin')
        self.assertEqual(self.client.post('/api/auth/setup', json={'username': 'another', 'password': self.password}).status_code, 409)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)
        self.assertFalse(self.client.get('/api/auth/state').json()['setup_required'])
        response = self.client.post('/api/auth/login', json={'username': 'AdMiN', 'password': self.password})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get('/api/auth/state').json()['authenticated'])

    def test_demo_overview_is_authenticated_and_does_not_write_business_records(self):
        self.setup_admin()
        with self.server.db() as con:
            before = list(con.iterdump())
        with patch('server.clinical.tasks', side_effect=AssertionError('No live clinical query')):
            response = self.client.get('/api/demo/patient-overview')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertEqual(response.json()['summary']['enrolled'], 50)
        self.assertEqual(response.json()['summary']['completed'], 50)
        self.assertEqual(response.json()['summary']['visits'], 350)
        self.assertEqual(response.json()['summary']['attention_counts'], {'red': 6, 'orange': 8, 'yellow': 10, 'gray': 26})
        self.assertEqual(response.json()['detail_schema_version'], 2)
        self.assertEqual(len(response.json()['metric_definitions']), 6)
        self.assertIn('age_at_enrollment', response.json()['patients'][0]['profile'])
        self.assertIsNone(response.json()['patients'][24]['visits'][3]['measurements']['c3'])
        with self.server.db() as con:
            self.assertEqual(list(con.iterdump()), before)

    def test_staff_can_read_the_synthetic_overview(self):
        self.setup_admin()
        self.assertEqual(self.client.post('/api/admin/users', json={'username': 'staff-demo',
            'password': self.password, 'role': 'staff'}).status_code, 200)
        with self.new_client() as staff:
            self.assertEqual(staff.post('/api/auth/login', json={'username': 'staff-demo',
                'password': self.password}).status_code, 200)
            response = staff.get('/api/demo/patient-overview')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['summary']['pending'], 0)
            self.assertEqual(staff.get('/api/admin/overview').status_code, 403)

    def test_demo_fixture_failure_does_not_return_fake_metrics(self):
        self.setup_admin()
        for failure in (FileNotFoundError('internal-path'), ValueError('bad-record')):
            with patch('server.load_demo_overview', side_effect=failure):
                response = self.client.get('/api/demo/patient-overview')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'detail': 'Patient overview demo is unavailable'})

    def test_invalid_detail_fixture_fails_closed_through_http(self):
        self.setup_admin()
        source = json.loads(patient_overview.FIXTURE.read_text(encoding='utf-8'))
        fixture = self.root / 'invalid-synthetic-overview.json'
        for invalid in (True, 'internal-hidden-marker', float('nan'), float('inf'), -1, 1001):
            with self.subTest(value=repr(invalid)):
                source['patients'][0]['visits'][0]['measurements']['igg'] = invalid
                fixture.write_text(json.dumps(source), encoding='utf-8')
                with patch.object(patient_overview, 'FIXTURE', fixture):
                    response = self.client.get('/api/demo/patient-overview')
                self.assertEqual(response.status_code, 503)
                self.assertIn('no-store', response.headers['cache-control'])
                self.assertEqual(response.json(), {'detail': 'Patient overview demo is unavailable'})

    def test_auth_and_business_mutations_require_same_origin(self):
        payload = {'username': 'admin', 'password': self.password}
        for route in ('/api/auth/setup', '/api/auth/login', '/api/auth/logout'):
            self.assertEqual(self.client.post(route, json=payload, headers={'origin': 'https://outside.invalid'}).status_code, 403)
        self.setup_admin()
        self.assertEqual(self.client.post('/api/admin/users', json={**payload, 'role': 'staff'},
                                          headers={'origin': ''}).status_code, 403)
        self.assertEqual(self.client.post('/api/upload', files={'file': ('synthetic.txt', b'example')},
                                          headers={'origin': 'https://outside.invalid'}).status_code, 403)
        self.assertEqual(self.client.get('/api/auth/state', headers={'host': 'outside.invalid'}).status_code, 403)
        self.assertEqual(len(self.client.get('/api/admin/users').json()['users']), 1)

    def test_staff_cannot_access_administration_or_exports(self):
        self.setup_admin()
        response = self.client.post('/api/admin/users', json={'username': 'staff', 'password': self.password, 'role': 'staff'})
        self.assertEqual(response.status_code, 200)
        with self.new_client() as staff:
            self.assertEqual(staff.post('/api/auth/login', json={'username': 'staff', 'password': self.password}).status_code, 200)
            self.assertEqual(staff.get('/api/jobs').status_code, 200)
            for route in ('/api/admin/users', '/api/admin/overview', '/api/admin/export/database', '/api/admin/export/archive'):
                self.assertEqual(staff.get(route).status_code, 403)
            self.assertEqual(staff.post('/api/admin/users', json={'username': 'illegal', 'password': self.password,
                                                                 'role': 'admin'}).status_code, 403)

    def test_default_confirmation_records_authenticated_actor_and_origin(self):
        self.setup_admin()
        response = self.client.post('/api/admin/users', json={'username': 'reviewer', 'password': self.password,
                                                             'role': 'staff'})
        self.assertEqual(response.status_code, 200)
        text = ('# SJD-SYNTHETIC\npatient_id,name,visit_date,event_id,code,value,unit,source_note\n'
                'SIM-DEFAULT-ACTOR,Synthetic Example,2026-10-23,am,pain,3,,pain: 3\n')
        job = self.upload_source(text.encode(), 'synthetic-default-actor.csv')
        candidate = self.server.extract_csv(text)
        version = hashlib.sha256(text.encode()).hexdigest()
        self.server.update(job, state='review', text=text, candidate=json.dumps(candidate), version=version)

        def publish(candidate, source_hash, days, actor, progress, on_progress):
            self.assertEqual(actor, 'reviewer')
            for field in progress['fields'].values():
                field.update(state='archived', observation='synthetic-default-observation')
            on_progress(progress)
            return {'patient': 'synthetic-default-patient', 'task': 'synthetic-default-task',
                    'window_start': '2026-11-08', 'window_end': '2026-12-06'}

        with self.new_client() as staff:
            self.assertEqual(staff.post('/api/auth/login', json={'username': 'reviewer', 'password': self.password}).status_code, 200)
            self.assertEqual(staff.get('/api/jobs/' + job).json()['history'], [])
            body = {'version': version, 'review_revision': 0, 'reviewed': True, 'followup_days': 30,
                    'accept_defaults': True, 'actor': 'forged-admin'}
            with patch.object(self.server.clinical, 'publish', side_effect=publish) as clinical_publish:
                response = staff.post('/api/jobs/' + job + '/approve', json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(staff.post('/api/jobs/' + job + '/approve', json=body).json(), response.json())
                self.assertEqual(clinical_publish.call_count, 1)
        record = self.client.get('/api/jobs/' + job).json()
        self.assertEqual(record['history'][0]['actor'], 'reviewer')
        self.assertEqual(record['history'][0]['origin'], 'batch_default_accept')
        self.assertEqual(record['publication']['plan']['reviewer'], 'reviewer')
        with self.server.db() as con:
            audit = con.execute("SELECT detail FROM audit WHERE job=? AND event='field_reviewed'", (job,)).fetchone()
        self.assertEqual(json.loads(audit[0])['actor'], 'reviewer')
        self.assertEqual(json.loads(audit[0])['origin'], 'batch_default_accept')

    def test_validation_and_authentication_errors_do_not_echo_password(self):
        invalid = self.client.post('/api/auth/setup', json={'username': 'admin', 'password': self.password, 'email': 'extra'})
        self.assertEqual(invalid.status_code, 422)
        self.assertTrue(self.password not in invalid.text, 'Validation response echoed a credential')
        self.setup_admin()
        for username in ('admin', 'not-existing'):
            response = self.client.post('/api/auth/login', json={'username': username, 'password': self.password + '-wrong'})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {'detail': 'Invalid username or password'})
            self.assertTrue(self.password not in response.text, 'Login response echoed a credential')
        response = self.client.post('/api/auth/login', json={'username': 'admin', 'password': 'x' * 129})
        self.assertEqual(response.status_code, 422)
        self.assertTrue('x' * 129 not in response.text, 'Validation response echoed oversized input')

    def test_streamed_multipart_is_bounded_before_parsing(self):
        self.setup_admin()
        header = (b'--synthetic-boundary\r\nContent-Disposition: form-data; name="file"; '
                  b'filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n')
        footer = b'\r\n--synthetic-boundary--\r\n'
        headers = {'content-type': 'multipart/form-data; boundary=synthetic-boundary'}
        # No Content-Length: the limit must count received bytes, not trust headers.
        with patch('starlette.requests.Request.form', side_effect=AssertionError('Oversized multipart reached parsing')) as parse:
            response = self.client.post('/api/upload', content=iter([header, b'x' * 6_000_000,
                                                                    b'x' * 6_000_000, footer]), headers=headers)
        self.assertNotIn('content-length', response.request.headers)
        self.assertEqual(response.status_code, 413)
        self.assertLess(len(response.content), 200)
        parse.assert_not_called()
        self.assertEqual(self.client.get('/api/jobs').json(), [])
        self.assertEqual(list((self.root / 'sources').iterdir()), [])
        self.assertEqual(self.client.post('/api/patient-registry', json={'patient_id': 'SIM-STREAM',
                                                                       'name': 'Synthetic Stream'}).status_code, 200)
        selection = (b'--synthetic-boundary\r\nContent-Disposition: form-data; name="patient_id"\r\n\r\n'
                     b'SIM-STREAM\r\n')
        response = self.client.post('/api/upload', content=iter([selection, header, b'Synthetic small streamed upload', footer]),
                                    headers=headers)
        self.assertNotIn('content-length', response.request.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.client.get('/api/jobs').json()), 1)

    def test_invalid_length_and_unauthenticated_stream_are_rejected(self):
        response = self.client.post('/api/upload', content=iter([b'Synthetic anonymous stream']))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post('/api/upload', content=b'example',
                                          headers={'content-length': 'not-a-number'}).status_code, 400)
        self.setup_admin()
        self.assertEqual(self.client.post('/api/upload', content=b'example',
                                          headers={'content-length': '-1'}).status_code, 413)
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_asgi_limit_accumulates_multiple_receive_messages(self):
        sent, reached = [], []

        async def application(scope, receive, send):
            reached.append(True)

        async def run():
            messages = iter([{'type': 'http.request', 'body': b'a' * 6_000_000, 'more_body': True},
                             {'type': 'http.request', 'body': b'b' * 6_000_000, 'more_body': True}])

            async def receive():
                return next(messages)

            async def send(message):
                sent.append(message)

            await self.server.RequestBodyLimit(application)({'type': 'http'}, receive, send)

        asyncio.run(run())
        self.assertEqual(reached, [])
        self.assertEqual(sent[0]['status'], 413)
        self.assertLess(len(sent[1]['body']), 200)

    def test_sqlite_export_is_business_only_and_audited(self):
        self.setup_admin()
        job = self.upload_source()
        response = self.client.get('/api/admin/export/database')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('attachment;', response.headers['content-disposition'])
        snapshot = self.root / 'downloaded-business.sqlite'
        snapshot.write_bytes(response.content)
        with contextlib.closing(sqlite3.connect(snapshot)) as con:
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'jobs', 'audit', 'followup_outbox', 'outbox_audit', 'patient_registry', 'job_patient_association'} <= tables)
            self.assertTrue(not {'users', 'sessions', 'attempts'} & tables)
            self.assertEqual(con.execute('SELECT id FROM jobs').fetchone()[0], job)
        self.assertTrue(self.password.encode() not in response.content, 'Export included a credential')
        with self.server.db() as con:
            audit = con.execute("SELECT detail FROM audit WHERE event='business_database_export'").fetchone()
        self.assertEqual(json.loads(audit[0])['actor'], 'admin')

    def test_archive_allowlist_hashes_and_integrity_failure(self):
        self.setup_admin()
        content = b'Synthetic source archive test'
        job = self.upload_source(content)
        resources = {kind: [{'resourceType': kind, 'id': 'synthetic-' + kind.lower()}]
                     for kind in ('Patient', 'Encounter', 'Observation', 'Provenance', 'Task', 'Basic')}
        with patch.object(self.server.clinical, 'search', side_effect=lambda kind, params: resources[kind]) as search:
            response = self.client.get('/api/admin/export/archive')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({call.args[0] for call in search.call_args_list}, set(resources))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(set(archive.namelist()), {'jobs.sqlite', 'clinical-resources.json', 'manifest.json', 'sources/' + job})
            manifest = json.loads(archive.read('manifest.json'))
            self.assertIn('accounts', manifest['excluded'])
            self.assertEqual(json.loads(archive.read('clinical-resources.json')), resources)
            self.assertEqual(archive.read('sources/' + job), content)
            for item in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.read(item['path'])).hexdigest(), item['sha256'])
        (self.root / 'sources' / job).write_bytes(b'Changed synthetic source')
        with patch.object(self.server.clinical, 'search', return_value=[]):
            self.assertEqual(self.client.get('/api/admin/export/archive').status_code, 503)
        with patch.object(self.server.clinical, 'search', side_effect=RuntimeError('Synthetic unavailable backend')):
            self.assertEqual(self.client.get('/api/admin/export/archive').status_code, 503)

    def test_overview_reports_actual_counts_and_dependency_failure(self):
        self.setup_admin()
        self.upload_source()
        with patch.object(self.server.clinical, 'tasks', return_value=[]):
            response = self.client.get('/api/admin/overview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['jobs_by_state'], {'queued': 1})
        self.assertEqual(response.json()['patients'], 0)
        with patch.object(self.server.clinical, 'tasks', side_effect=RuntimeError('Synthetic unavailable backend')):
            self.assertEqual(self.client.get('/api/admin/overview').status_code, 503)

    def test_upload_to_reviewed_pending_queue_never_sends(self):
        self.setup_admin()
        text = ('# SJD-SYNTHETIC\npatient_id,name,visit_date,event_id,code,value,unit,source_note\n'
                'SIM-HTTP,Synthetic Example,2026-10-23,am,pain,3,,pain: 3\n')
        with self.client:
            job = self.upload_source(text.encode(), 'synthetic.csv')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                record = self.client.get('/api/jobs/' + job).json()
                if record['state'] not in ('queued', 'reading', 'extracting'):
                    break
                time.sleep(0.05)
            self.assertEqual(record['state'], 'review')
            with patch.object(self.server.clinical, 'tasks', return_value=[]):
                queue = self.client.get('/api/outbox').json()
            self.assertFalse(queue['delivery_enabled'])
            draft = queue['items'][0]
            self.assertEqual(draft['status'], 'draft')
            edit = {'revision': draft['revision'], 'due_date': draft['due_date'], 'message': 'Synthetic follow-up message',
                    'status': 'pending_send', 'reason': 'Synthetic queue test'}
            self.assertEqual(self.client.post('/api/outbox/' + draft['id'], json=edit).status_code, 422)
            response = self.client.post('/api/jobs/' + job + '/review', json={'version': record['version'],
                'review_revision': 0, 'field_id': record['fields'][0]['id'], 'action': 'accept'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['history'][0]['actor'], 'admin')

            def publish(candidate, source_hash, days, actor, progress, on_progress):
                progress['patient'] = 'synthetic-patient'
                for field in progress['fields'].values():
                    field.update(state='archived', observation='synthetic-observation')
                on_progress(progress)
                return {'patient': 'synthetic-patient', 'task': 'synthetic-task', 'visits': 1, 'fields': 1,
                        'window_start': '2026-11-08', 'window_end': '2026-12-06'}

            with patch.object(self.server.clinical, 'publish', side_effect=publish):
                response = self.client.post('/api/jobs/' + job + '/approve', json={'version': record['version'],
                    'review_revision': 1, 'reviewed': True, 'followup_days': 30})
            self.assertEqual(response.status_code, 200)
            with patch.object(self.server.clinical, 'tasks', return_value=[]):
                pending = self.client.get('/api/outbox').json()['items'][0]
            self.assertEqual(pending['status'], 'pending_send')
            self.assertEqual(pending['task_id'], 'synthetic-task')
            self.assertEqual(self.client.post('/api/outbox/' + draft['id'], json=edit).status_code, 409)
            self.assertEqual(self.client.post('/api/outbox/' + draft['id'] + '/send').status_code, 404)
            completed = {'id': 'synthetic-task', 'status': 'completed', 'completion_mode': 'reviewed-visit-only',
                         'evidence': ['Encounter/synthetic-followup']}
            with patch.object(self.server.clinical, 'tasks', return_value=[completed]):
                queue = self.client.get('/api/outbox').json()
            self.assertFalse(queue['delivery_enabled'])
            self.assertEqual(queue['items'][0]['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
