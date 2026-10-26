"""Authenticated HTTP tests on fresh stores, fixed candidates and synthetic patients."""
import copy
import contextlib
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_workbench_http as legacy
from test_care import event, form


class CareHTTPTests(unittest.TestCase):
    setUp = legacy.WorkbenchHTTPTests.setUp
    tearDown = legacy.WorkbenchHTTPTests.tearDown
    new_client = legacy.WorkbenchHTTPTests.new_client
    setup_admin = legacy.WorkbenchHTTPTests.setup_admin

    def attention_payload(self, data, state='reviewed'):
        item = data['attention']['items'][0]
        body = {key: item['review']['body'][key] for key in
                ('state', 'owner', 'due_date', 'note', 'disposition', 'evidence_note', 'evidence_refs')}
        body.update(state=state, owner='Synthetic operator', note='Synthetic review',
                    disposition='confirmed', evidence_note='Synthetic source reviewed')
        return item['signal_key'], {'expected_revision': item['review']['revision'], 'data': body}

    def test_all_routes_require_authentication_and_posts_require_origin(self):
        self.assertEqual(self.client.get('/api/care/demo').status_code, 401)
        self.assertEqual(self.client.get('/api/care/demo/SIM-OV50-001').status_code, 401)
        self.setup_admin()
        data = self.client.get('/api/care/demo/SIM-OV50-001').json()
        key, payload = self.attention_payload(data)
        response = self.client.post('/api/care/demo/SIM-OV50-001/attention/' + key, json=payload,
                                    headers={'origin': 'https://external.invalid'})
        self.assertEqual(response.status_code, 403)

    def test_demo_writes_are_separate_and_persistent_with_server_actor(self):
        self.setup_admin()
        path = '/api/care/demo/SIM-OV50-001'
        data = self.client.get(path).json()
        key, payload = self.attention_payload(data)
        self.assertEqual(self.client.post(path + '/attention/' + key, json=payload).status_code, 200)
        updated = self.client.get(path).json()
        self.assertEqual(updated['attention']['reviewed_count'], 1)
        self.assertEqual(updated['attention']['level'], 'red')
        self.assertEqual(updated['history'][-1]['actor'], 'admin')
        self.assertEqual(self.client.post(path + '/attention/' + key, json=payload).status_code, 409)
        with contextlib.closing(sqlite3.connect(self.root / 'jobs.sqlite')) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM care_records').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT count(*) FROM patient_registry').fetchone()[0], 0)
        self.assertTrue((self.root / 'demo-workflow.sqlite').is_file())
        other = self.client.get('/api/care/demo/SIM-OV50-002').json()
        self.assertEqual(other['attention']['reviewed_count'], 0)

    def test_cross_patient_signal_and_forged_actor_fail(self):
        self.setup_admin()
        path = '/api/care/demo/SIM-OV50-001'
        key, payload = self.attention_payload(self.client.get(path).json())
        self.assertEqual(self.client.post('/api/care/demo/SIM-OV50-002/attention/' + key, json=payload).status_code, 409)
        payload['actor'] = 'forged'
        self.assertEqual(self.client.post(path + '/attention/' + key, json=payload).status_code, 422)
        self.assertEqual(self.client.get('/api/care/unknown').status_code, 404)
        self.assertEqual(self.client.get('/api/care/demo/SIM-NOT-FOUND').status_code, 404)

    def test_form_save_does_not_complete_plan_and_date_validated(self):
        self.setup_admin()
        path = '/api/care/demo/SIM-OV50-020'
        before = self.client.get(path).json()
        self.assertEqual(before['followup']['status'], 'overdue')
        value = form()
        response = self.client.post(path + '/form/F1', json={'expected_revision': 0, 'data': value})
        self.assertEqual(response.status_code, 200, response.text)
        after = self.client.get(path).json()
        self.assertEqual(after['followup'], before['followup'])
        self.assertEqual(after['history'][-1]['body']['template_version'], 'followup-raw-v1')
        value['visit_date'] = '2027-01-01'
        self.assertEqual(self.client.post(path + '/form/F2', json={'expected_revision': 0, 'data': value}).status_code, 422)

    def test_events_revisions_and_source_references_are_patient_bound(self):
        self.setup_admin()
        path = '/api/care/demo/SIM-OV50-001'
        value = event('medication')
        self.assertEqual(self.client.post(path + '/event/M1', json={'expected_revision': 0, 'data': value}).status_code, 200)
        value.update(dose='10 mg', note='Synthetic correction')
        self.assertEqual(self.client.post(path + '/event/M1', json={'expected_revision': 1, 'data': value}).status_code, 200)
        value['evidence_refs'] = ['visit:SIM-VISIT50-002-Y5']
        self.assertEqual(self.client.post(path + '/event/M1', json={'expected_revision': 2, 'data': value}).status_code, 422)
        data = self.client.get(path).json()
        self.assertEqual(len([r for r in data['history'] if r['item_id'] == 'M1']), 2)
        self.assertEqual(len([r for r in data['timeline'] if r['id'] == 'M1']), 1)

    def test_roster_counts_current_work_not_first_followup(self):
        self.setup_admin()
        response = self.client.get('/api/care/demo')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total'], 50)
        self.assertEqual(data['followup_counts'], {'overdue': 10, 'in_window': 10, 'upcoming': 10,
                                                 'completed': 16, 'cancelled': 2, 'unknown': 2})
        self.assertEqual(data['attention_counts']['red'], 5)
        self.assertEqual(self.client.get('/api/demo/patient-overview').json()['summary']['completed'], 50)

    def test_business_records_and_offline_authority_remain_explicit(self):
        self.setup_admin()
        identity = {'patient_id': 'SIM-CARE', 'name': 'Synthetic Care'}
        self.assertEqual(self.client.post('/api/patient-registry', json=identity).status_code, 200)
        path = '/api/care/business/SIM-CARE'
        with patch('server.clinical.tasks', side_effect=RuntimeError('Offline')):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['sync_error'])
            self.assertEqual(self.client.post(path + '/event/E1', json={'expected_revision': 0, 'data': event()}).status_code, 200)
        with contextlib.closing(sqlite3.connect(self.root / 'jobs.sqlite')) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM care_records').fetchone()[0], 1)

    def test_source_navigation_never_accepts_another_jobs_field(self):
        self.setup_admin()
        identity = {'patient_id': 'SIM-CARE', 'name': 'Synthetic Care'}
        self.client.post('/api/patient-registry', json=identity)
        upload = self.client.post('/api/upload', files={'file': ('synthetic.txt', b'Synthetic text only')}, data={'patient_id': identity['patient_id']})
        self.assertEqual(upload.status_code, 200)
        job = upload.json()['id']
        self.assertEqual(self.client.get('/api/jobs/' + job + '/source-map?field_id=other').status_code, 404)
        response = self.client.get('/api/jobs/' + job + '/source-map')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['warnings'], ['logical_page_only'])


if __name__ == '__main__':
    unittest.main()
