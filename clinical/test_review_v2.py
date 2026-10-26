"""Synthetic HTTP boundary tests; no live model, identity or shared service."""
import hashlib
import importlib
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from extract import extract_csv


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.temp.name)
        (root / 'SYNTHETIC_ONLY').write_bytes(b'simulated\n')
        cls.environment = patch.dict(os.environ, {'AGENT_DATA': str(root), 'AGENT_DEMO': '1', 'AGENT_PORT': '13012'})
        cls.environment.start()
        cls.server = importlib.import_module('server')

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.client = TestClient(self.server.app, headers={'origin': 'http://127.0.0.1:13012'})
        self.client.get('/')
        self.job = str(uuid.uuid4())
        self.patient = 'SIM-' + self.job[:12]
        text = ('# SJD-SYNTHETIC ' + self.job + '\n'
                'patient_id,name,visit_date,event_id,code,value,unit,source_note\n'
                'SIM-TEST,Example,2026-10-22,am,pain,3,,pain: 8; pain: 5\n'
                'SIM-TEST,Example,2026-10-22,pm,igg,18.20,g/L,IgG: 18.20 g/L\n')
        text = text.replace('SIM-TEST', self.patient)
        digest = hashlib.sha256(text.encode()).hexdigest()
        candidate = extract_csv(text)
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,suffix,state,text,candidate,version,created) VALUES(?,?,?,?,?,?,?,?,?)',
                        (self.job, digest, 'synthetic.csv', '.csv', 'review', text, json.dumps(candidate), digest, self.job))
        self.record = self.get()
        self.version = self.record['version']

    def tearDown(self):
        self.client.close()

    def get(self):
        return self.client.get('/api/jobs/' + self.job).json()

    def decide(self, field, action='accept', revision=None, **extra):
        return self.client.post('/api/jobs/' + self.job + '/review', json={
            'version': self.version, 'review_revision': self.get()['review_revision'] if revision is None else revision,
            'field_id': field['id'], 'action': action, **extra})

    def approve(self, **extra):
        return self.client.post('/api/jobs/' + self.job + '/approve', json={'version': self.version,
            'review_revision': self.get()['review_revision'], 'reviewed': True, 'followup_days': 30, **extra})

    def fake_publish(self, candidate, source_hash, days, actor, progress, on_progress):
        progress['patient'] = 'synthetic-patient'
        for visit in candidate['visits']:
            for fact in visit['facts']:
                progress['fields'][fact['field_id']] = {'state': 'archived',
                    'observation': fact['field_id'] + '-' + str(fact['revision']), 'revision': fact['revision']}
                on_progress(progress)
        return {'patient': 'synthetic-patient', 'fields': progress['fields'], 'task': 'task-' + self.job,
                'visits': [], 'window_start': '2026-11-07', 'window_end': '2026-12-05'}

    def test_pending_and_stale_versions_fail_before_clinical_write(self):
        with patch.object(self.server.clinical, 'publish') as publish:
            self.assertEqual(self.approve().status_code, 409)
            field = self.record['fields'][0]
            self.assertEqual(self.decide(field).status_code, 200)
            self.assertEqual(self.decide(field, revision=0).status_code, 409)
            self.assertEqual(self.approve(version='old').status_code, 409)
            publish.assert_not_called()

    def test_default_accept_is_materialized_only_at_document_confirmation(self):
        self.assertEqual(self.get()['history'], [])
        self.assertTrue(all(field['decision'] is None for field in self.get()['fields']))
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            response = self.approve(accept_defaults=True)
        self.assertEqual(response.status_code, 200, response.text)
        current = self.get()
        self.assertEqual(current['candidate'], self.record['candidate'])
        self.assertEqual(current['text'], self.record['text'])
        self.assertEqual(current['review_revision'], 2)
        self.assertEqual([item['revision'] for item in current['history']], [1, 2])
        for field in current['fields']:
            decision = field['decision']
            self.assertEqual(decision['action'], 'accept')
            self.assertEqual(decision['origin'], 'batch_default_accept')
            self.assertTrue(decision['actor'].startswith('synthetic-operator-'))
            self.assertTrue(decision['at'])
            for key in ('code', 'value', 'unit', 'quote'):
                self.assertEqual(decision[key], field['original'][key])
            self.assertEqual(field['archive']['revision'], decision['revision'])
        self.assertEqual(current['publication']['revision'], 2)
        self.assertEqual(current['publication']['plan']['input_review_revision'], 0)
        self.assertTrue(current['publication']['plan']['accept_defaults'])
        self.assertEqual([visit['event_id'] for visit in publish.call_args.args[0]['visits']], ['am', 'pm'])
        with self.server.db() as con:
            audits = con.execute("SELECT detail FROM audit WHERE job=? AND event='field_reviewed'", (self.job,)).fetchall()
        self.assertEqual([json.loads(row[0]) for row in audits], current['history'])

    def test_pre_default_request_replay_returns_same_receipt_without_new_reviews(self):
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            first = self.approve(accept_defaults=True, review_revision=0)
            self.assertEqual(first.status_code, 200, first.text)
            before = self.get()
            repeated = self.approve(accept_defaults=True, review_revision=0)
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json(), first.json())
            self.assertEqual(self.approve(accept_defaults=False, review_revision=0).status_code, 409)
            self.assertEqual(publish.call_count, 1)
        after = self.get()
        self.assertEqual(after['history'], before['history'])
        self.assertEqual(after['publication_history'], before['publication_history'])

    def test_accept_defaults_requires_actual_boolean(self):
        with patch.object(self.server.clinical, 'publish') as publish:
            for invalid in ('true', 'false', 1, 0, None, {}, []):
                with self.subTest(value=invalid):
                    self.assertEqual(self.approve(accept_defaults=invalid).status_code, 422)
            publish.assert_not_called()
        self.assertEqual(self.get()['history'], [])
        self.assertIsNone(self.get()['publication'])

    def test_default_accept_gates_fail_without_materializing_reviews(self):
        with patch.object(self.server.clinical, 'publish') as publish:
            for changes in ({'version': 'stale'}, {'review_revision': 1}, {'reviewed': False}):
                with self.subTest(changes=changes):
                    self.assertEqual(self.approve(accept_defaults=True, **changes).status_code, 409)
            for state in ('queued', 'extracting', 'failed', 'blocked', 'published'):
                with self.subTest(state=state):
                    self.server.update(self.job, state=state)
                    self.assertEqual(self.approve(accept_defaults=True).status_code, 409)
            publish.assert_not_called()
        self.assertEqual(self.get()['history'], [])
        self.assertIsNone(self.get()['publication'])
        with self.server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM audit WHERE job=?', (self.job,)).fetchone()[0], 0)

    def test_default_accept_preserves_rejection(self):
        self.assertEqual(self.decide(self.record['fields'][0], 'reject', reason='Synthetic source problem').status_code, 200)
        before = self.get()['history'][0]
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            self.assertEqual(self.approve(accept_defaults=True).status_code, 200)
        current = self.get()
        self.assertEqual(current['history'][0], before)
        self.assertIsNone(current['fields'][0]['archive'])
        self.assertEqual(current['fields'][1]['decision']['origin'], 'batch_default_accept')
        self.assertEqual([fact['code'] for visit in publish.call_args.args[0]['visits'] for fact in visit['facts']], ['igg'])

    def test_default_accept_preserves_defer_and_explicit_modification(self):
        field = self.record['fields'][0]
        self.decide(field, 'modify', value='8', unit='', quote=field['original']['quote'], reason='Source check')
        self.decide(self.record['fields'][1], 'defer', reason='Need source check')
        before = self.get()['history']
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            self.assertEqual(self.approve(accept_defaults=True).status_code, 200)
        current = self.get()
        self.assertEqual(current['history'], before)
        self.assertEqual(current['publication']['revision'], 2)
        self.assertEqual(current['publication']['plan']['input_review_revision'], 2)
        self.assertIsNone(current['fields'][1]['archive'])
        self.assertEqual(publish.call_args.args[0]['visits'][0]['facts'][0]['value'], '8')

    def test_default_accept_with_only_reject_and_defer_has_no_publication(self):
        self.decide(self.record['fields'][0], 'reject', reason='Source problem')
        self.decide(self.record['fields'][1], 'defer', reason='Later review')
        before = self.get()['history']
        with patch.object(self.server.clinical, 'publish') as publish:
            self.assertEqual(self.approve(accept_defaults=True).status_code, 409)
            publish.assert_not_called()
        self.assertEqual(self.get()['history'], before)
        self.assertIsNone(self.get()['publication'])

    def test_default_accept_partial_retry_reuses_frozen_revision_and_interval(self):
        def partial(candidate, source_hash, days, actor, progress, on_progress):
            fact = candidate['visits'][0]['facts'][0]
            progress['fields'][fact['field_id']] = {'state': 'archived', 'observation': 'first', 'revision': fact['revision']}
            on_progress(progress)
            raise RuntimeError('Synthetic second-field failure')

        with patch.object(self.server.clinical, 'publish', side_effect=partial):
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0).status_code, 409)
        before = self.get()
        self.assertEqual(before['review_revision'], 2)
        self.assertEqual(before['publication']['revision'], 2)
        self.assertEqual(before['state'], 'partial')
        self.assertEqual(sum(item['state'] == 'archived' for item in before['publication']['progress']['fields'].values()), 1)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0, followup_days=31).status_code, 409)
            self.assertEqual(self.approve(accept_defaults=False, review_revision=0).status_code, 409)
            publish.assert_not_called()
            response = self.approve(accept_defaults=True, review_revision=0)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(publish.call_args.args[0], before['publication']['plan']['candidate'])
            self.assertEqual(publish.call_args.args[2], 30)
        after = self.get()
        self.assertEqual(after['history'], before['history'])
        self.assertEqual(len(after['publication_history']), 1)
        self.assertEqual(after['publication']['state'], 'published')
        self.assertTrue(all(field['archive'] for field in after['fields']))

    def test_current_revision_retry_accepts_legacy_plan_without_default_flag(self):
        for field in self.record['fields']:
            self.decide(field)
        with patch.object(self.server.clinical, 'publish', side_effect=RuntimeError('Synthetic interrupted request')):
            self.assertEqual(self.approve().status_code, 409)
        record = self.get()
        plan = record['publication']['plan']
        plan.pop('input_review_revision')
        plan.pop('accept_defaults')
        with self.server.db() as con:
            con.execute('UPDATE publications SET plan=? WHERE job=?', (json.dumps(plan), self.job))
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            response = self.approve(accept_defaults=True)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(publish.call_args.args[0], plan['candidate'])
        current = self.get()
        self.assertEqual(current['history'], record['history'])
        self.assertEqual(current['publication']['plan'], plan)
        self.assertEqual(len(current['publication_history']), 1)

    def test_correction_invalidates_pre_default_replay_and_keeps_prior_history(self):
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0).status_code, 200)
        before = self.get()
        field = before['fields'][0]
        response = self.client.post('/api/jobs/' + self.job + '/correction', json={
            'version': self.version, 'review_revision': 2, 'field_id': field['id'], 'action': 'modify',
            'value': '5', 'unit': '', 'quote': field['original']['quote'], 'reason': 'Synthetic corrected report'})
        self.assertEqual(response.status_code, 200, response.text)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0).status_code, 409)
            publish.assert_not_called()
            self.assertEqual(self.approve(accept_defaults=True).status_code, 200)
            self.assertEqual(sum(len(visit['facts']) for visit in publish.call_args.args[0]['visits']), 1)
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0).status_code, 409)
        current = self.get()
        self.assertEqual(current['candidate'], before['candidate'])
        self.assertEqual(current['history'][:2], before['history'])
        self.assertEqual(current['history'][2]['correction_of'], field['archive']['observation'])
        self.assertEqual(current['publication_history'][0], before['publication_history'][0])
        self.assertEqual(len(current['publication_history']), 2)

    def test_publication_insert_failure_rolls_back_default_reviews_and_audit(self):
        with self.server.db() as con:
            con.execute("CREATE TRIGGER fail_v5_publication BEFORE INSERT ON publications "
                        "BEGIN SELECT RAISE(ABORT, 'Synthetic publication insert failure'); END")
        try:
            with patch.object(self.server.clinical, 'publish') as publish:
                with self.assertRaises(sqlite3.IntegrityError):
                    self.approve(accept_defaults=True)
                publish.assert_not_called()
            current = self.get()
            self.assertEqual(current['history'], [])
            self.assertIsNone(current['publication'])
            self.assertEqual(current['state'], 'review')
            with self.server.db() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM audit WHERE job=?', (self.job,)).fetchone()[0], 0)
        finally:
            with self.server.db() as con:
                con.execute('DROP TRIGGER fail_v5_publication')
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve(accept_defaults=True).status_code, 200)
        self.assertEqual(self.get()['review_revision'], 2)

    def test_interruption_after_plan_commit_keeps_reviews_frozen(self):
        with patch.object(self.server, 'update', side_effect=RuntimeError('Synthetic post-commit interruption')):
            with patch.object(self.server.clinical, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'Synthetic post-commit interruption'):
                    self.approve(accept_defaults=True)
                publish.assert_not_called()
        interrupted = self.get()
        self.assertEqual(interrupted['state'], 'publishing')
        self.assertEqual(interrupted['publication']['state'], 'publishing')
        self.assertEqual(interrupted['review_revision'], 2)
        self.assertEqual(self.decide(interrupted['fields'][0]).status_code, 409)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve(accept_defaults=True, review_revision=0).status_code, 200)
        current = self.get()
        self.assertEqual(current['history'], interrupted['history'])
        self.assertEqual(len(current['publication_history']), 1)

    def test_edit_requires_reason_exact_quote_and_valid_value(self):
        field = self.record['fields'][0]
        self.assertEqual(self.decide(field, 'modify', value='8', unit='', quote=field['original']['quote']).status_code, 422)
        self.assertEqual(self.decide(field, 'modify', value='7', unit='', quote=field['original']['quote'], reason='Source check').status_code, 422)
        response = self.decide(field, 'modify', value='8', unit='', quote=field['original']['quote'], reason='Source check')
        self.assertEqual(response.status_code, 200)
        current = response.json()['fields'][0]
        self.assertEqual(current['original']['value'], '3')
        self.assertEqual(current['decision']['value'], '8')
        self.assertTrue(current['decision']['actor'].startswith('synthetic-operator-'))
        self.assertEqual(len(response.json()['history']), 1)

    def test_reject_defer_and_unknown_fields_do_not_archive(self):
        self.assertEqual(self.decide({'id': 'unknown'}).status_code, 422)
        self.assertEqual(self.decide(self.record['fields'][0], 'reject', reason='Invalid source').status_code, 200)
        self.assertEqual(self.decide(self.record['fields'][1], 'defer', reason='Need source check').status_code, 200)
        with patch.object(self.server.clinical, 'publish') as publish:
            self.assertEqual(self.approve().status_code, 409)
            publish.assert_not_called()

    def test_only_selected_fields_publish_and_retry_is_idempotent(self):
        self.decide(self.record['fields'][0])
        self.decide(self.record['fields'][1], 'reject', reason='Excluded source')
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            first = self.approve()
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(self.approve().json(), first.json())
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(sum(len(v['facts']) for v in publish.call_args.args[0]['visits']), 1)
        timeline = self.client.get('/api/patients').json()
        own = next(p for p in timeline if p['patient_id'] == self.patient)
        self.assertFalse(any(f['code'] == 'igg' for v in own['visits'] for f in v['facts']))

    def test_partial_progress_freezes_review_and_interval(self):
        for field in self.record['fields']:
            self.decide(field)
        def partial(candidate, source_hash, days, actor, progress, on_progress):
            fact = candidate['visits'][0]['facts'][0]
            progress['fields'][fact['field_id']] = {'state': 'archived', 'observation': 'first', 'revision': fact['revision']}
            on_progress(progress)
            raise RuntimeError('Synthetic second-field failure')
        with patch.object(self.server.clinical, 'publish', side_effect=partial):
            self.assertEqual(self.approve().status_code, 409)
        current = self.get()
        self.assertEqual(current['state'], 'partial')
        self.assertEqual(sum(f['state'] == 'archived' for f in current['publication']['progress']['fields'].values()), 1)
        self.assertEqual(sum(f['state'] == 'pending' for f in current['publication']['progress']['fields'].values()), 1)
        self.assertEqual(self.decide(self.record['fields'][1]).status_code, 409)
        self.assertEqual(self.approve(followup_days=31).status_code, 409)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve().status_code, 200)

    def test_correction_preserves_old_receipt_and_source_candidate(self):
        field = self.record['fields'][0]
        self.decide(field)
        self.decide(self.record['fields'][1], 'defer', reason='Later check')
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve().status_code, 200)
        before = self.get()
        self.assertEqual(self.decide(field).status_code, 409)
        body = {'version': self.version, 'review_revision': before['review_revision'], 'field_id': field['id'],
                'action': 'modify', 'value': '5', 'unit': '', 'quote': field['original']['quote'], 'reason': 'Corrected report'}
        response = self.client.post('/api/jobs/' + self.job + '/correction', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.approve(followup_days=90).status_code, 409)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish) as publish:
            self.assertEqual(self.approve().status_code, 200)
            self.assertEqual(sum(len(v['facts']) for v in publish.call_args.args[0]['visits']), 1)
        after = self.get()
        self.assertEqual(after['candidate'], before['candidate'])
        self.assertEqual(len(after['publication_history']), 2)
        self.assertEqual(after['publication_history'][0]['receipt'], before['publication_history'][0]['receipt'])
        self.assertEqual(after['fields'][0]['decision']['correction_of'], before['fields'][0]['archive']['observation'])

    def test_session_origin_and_no_model_status(self):
        self.assertEqual(TestClient(self.server.app).get('/api/jobs').status_code, 401)
        with patch.object(self.server.urllib.request, 'urlopen') as external:
            status = self.client.get('/api/status')
            self.assertEqual(status.json()['mode'], 'synthetic-demo')
            external.assert_not_called()
        response = self.client.post('/api/jobs/' + self.job + '/review', headers={'origin': 'https://other.invalid'}, json={})
        self.assertEqual(response.status_code, 403)

    def test_same_day_events_remain_distinct(self):
        result = extract_csv('# SJD-SYNTHETIC\npatient_id,name,visit_date,event_id,code,value,unit\n'
            'SIM-1,Example,2026-10-22,am,igg,18,g/L\nSIM-1,Example,2026-10-22,pm,igg,19,g/L')
        self.assertEqual([v['event_id'] for v in result['visits']], ['am', 'pm'])
        self.assertEqual([v['facts'][0]['value'] for v in result['visits']], ['18', '19'])

    def test_legacy_and_v2_timeline_can_coexist(self):
        candidate = json.loads(json.dumps(self.record['candidate']))
        for visit in candidate['visits']:
            visit.pop('event_id', None)
        with self.server.db() as con:
            con.execute('INSERT INTO jobs(id,sha,filename,state,candidate,receipt,created) VALUES(?,?,?,?,?,?,?)',
                        (str(uuid.uuid4()), uuid.uuid4().hex, 'legacy.csv', 'published', json.dumps(candidate),
                         json.dumps({'patient': 'synthetic-patient'}), '!legacy'))
        for field in self.record['fields']:
            self.decide(field)
        with patch.object(self.server.clinical, 'publish', side_effect=self.fake_publish):
            self.assertEqual(self.approve().status_code, 200)
        response = self.client.get('/api/patients')
        self.assertEqual(response.status_code, 200)
        visits = next(p for p in response.json() if p['patient_id'] == self.patient)['visits']
        self.assertTrue(all(v.get('event_id') for v in visits))


if __name__ == '__main__':
    unittest.main()
