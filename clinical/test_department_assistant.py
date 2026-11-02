"""Synthetic task boundaries, source preservation and durable account isolation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
import department_assistant as assistant
import test_workbench_http as host

IDENTITY = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
RECORD = {'record_id': 'REC-' + 'a' * 24, 'subject_code': 'SYN-1', 'episode_code': 'E1',
          'physician_code': 'D1', 'visit_code': 'V1', 'date': '2026-01-01', 'sequence': None,
          'condition': 'Synthetic', 'symptoms': 'Synthetic dry mouth', 'tongue': '', 'pulse': 'not recorded',
          'syndrome': '', 'principle': '', 'prescription': 'HerbA 10g',
          'source_sha256': 'b' * 64, 'evidence': {'symptoms': [2], 'prescription': [3]}}


def draft():
    return {'schema': 'department-task-v1', 'instruction': 'intake', 'task': 'intake',
            'data_origin': 'synthetic', 'text': 'SYNTHETIC ONLY', 'supplements': [],
            'context': {'case_query': '', 'collection_revision': None, 'knowledge_source_id': '', 'knowledge_category': 'all'}}


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'drafts.sqlite'
        assistant.initialize(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_routing_clarifies_unknown_and_multiple_intents(self):
        for value in ('hello', 'intake and prescriptions'):
            result = assistant.plan({'instruction': value, 'task': 'auto'})
            self.assertTrue(result['needs_selection'])
            self.assertIsNone(result['task'])
            self.assertFalse(result['model_called'])
        self.assertEqual(assistant.plan({'instruction': 'search cases', 'task': 'auto'})['task'], 'cases')
        self.assertEqual(assistant.plan({'instruction': 'intake and prescriptions', 'task': 'intake'})['task'], 'intake')

    def test_invalid_inputs_are_bounded(self):
        invalid = []
        for key, value in [('task', []), ('data_origin', 'real'), ('text', 'a' * 40001),
                           ('instruction', '\ud800'), ('supplements', {}), ('extra', 'secret')]:
            item = draft(); item[key] = value; invalid.append(item)
        item = draft(); item['supplements'] = [{'record_id': RECORD['record_id'], 'field': 'tongue',
                    'value': '', 'origin': 'clinician', 'status': 'recorded'}]; invalid.append(item)
        item = draft(); item['supplements'] = [{'record_id': RECORD['record_id'], 'field': 'tongue',
                    'value': 'value', 'origin': 'clinician', 'status': 'unavailable'}]; invalid.append(item)
        for value in invalid:
            with self.subTest(value_type=type(value)), self.assertRaises(HTTPException):
                assistant.validate_draft(value)

    def test_supplements_preserve_original_and_distinguish_unavailable(self):
        value = draft()
        value['supplements'] = [{'record_id': RECORD['record_id'], 'field': 'tongue',
            'value': 'Synthetic clinician observation', 'status': 'recorded', 'origin': 'clinician'},
            {'record_id': RECORD['record_id'], 'field': 'pulse', 'value': '', 'status': 'unavailable', 'origin': 'unknown'}]
        recognized = {'records': [copy.deepcopy(RECORD)], 'source_sha256': RECORD['source_sha256']}
        result = assistant.apply_supplements(recognized, assistant.validate_draft(value))
        self.assertEqual(recognized['records'][0], RECORD)
        self.assertEqual(result['original_records'][0]['tongue'], '')
        self.assertEqual(result['records'][0]['tongue'], 'Synthetic clinician observation')
        self.assertEqual(result['records'][0]['evidence'], RECORD['evidence'])
        self.assertFalse(result['review_confirmed'])
        self.assertIsNone(result['clinical_approval'])
        self.assertEqual(next(row for row in result['missing'] if row['field'] == 'pulse')['status'], 'unavailable')
        value['supplements'][0]['record_id'] = 'REC-' + 'c' * 24
        with self.assertRaises(HTTPException) as caught:
            assistant.apply_supplements(recognized, value)
        self.assertEqual(caught.exception.status_code, 409)

    def test_duplicate_supplement_rejected(self):
        value = draft(); item = {'record_id': RECORD['record_id'], 'field': 'pulse', 'value': '', 'status': 'not_asked', 'origin': 'unknown'}
        value['supplements'] = [item, item]
        with self.assertRaises(HTTPException):
            assistant.validate_draft(value)

    def test_drafts_resume_idempotence_conflict_and_account_isolation(self):
        value = {'expected_revision': 0, 'draft': draft()}
        first = assistant.save_draft(self.path, 'one', IDENTITY, value)
        self.assertEqual(first['revision'], 1)
        self.assertEqual(assistant.save_draft(self.path, 'one', IDENTITY, value), first)
        assistant.initialize(self.path)
        self.assertEqual(assistant.drafts(self.path, 'one', IDENTITY), first)
        self.assertEqual(assistant.drafts(self.path, 'two')['drafts'], [])
        with self.assertRaises(HTTPException) as caught:
            assistant.drafts(self.path, 'two', IDENTITY)
        self.assertEqual(caught.exception.status_code, 404)
        altered = copy.deepcopy(value); altered['draft']['text'] = 'Changed synthetic text'
        with self.assertRaises(HTTPException) as caught:
            assistant.save_draft(self.path, 'one', IDENTITY, altered)
        self.assertEqual(caught.exception.status_code, 409)
        altered['expected_revision'] = 1
        self.assertEqual(assistant.save_draft(self.path, 'one', IDENTITY, altered)['revision'], 2)
        self.assertEqual(len(assistant.drafts(self.path, 'one')['drafts']), 1)
        with assistant.connection(self.path) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM assistant_drafts').fetchone()[0], 2)
            self.assertEqual(json.loads(con.execute('SELECT body FROM assistant_drafts WHERE revision=1').fetchone()[0]), draft())
        self.assertEqual(assistant.save_draft(self.path, 'two', IDENTITY, value)['revision'], 1)

    def test_case_search_is_lexical_bounded_and_hides_nonce(self):
        snapshot = {'nonce': 'NOT-AN-AUTHENTICATION-SECRET-TEST', 'revision': 3, 'synthetic': True,
                    'records': [dict(RECORD, record_id='REC-' + f'{i:024x}') for i in range(12)]}
        result = assistant.search_cases(snapshot, 'mouth HerbA')
        self.assertEqual(result['total'], 12)
        self.assertEqual(len(result['matches']), 10)
        self.assertNotIn('nonce', result)
        self.assertEqual(result['matches'][0]['matched_terms'], ['herba', 'mouth'])
        self.assertEqual(result['matches'][0]['record']['source_sha256'], RECORD['source_sha256'])
        self.assertEqual(result['collection_url'], '/api/department/mingyirx/imported.html?revision=3')
        self.assertEqual(assistant.search_cases(snapshot, 'unmatched')['total'], 0)
        with self.assertRaises(HTTPException):
            assistant.search_cases(snapshot, '...')

    def test_history_pagination_isolation_and_restore_append(self):
        for revision in range(23):
            value = draft(); value['instruction'] = f'Synthetic revision {revision + 1}'
            assistant.save_draft(self.path, 'one', IDENTITY, {'expected_revision': revision, 'draft': value})
        first = assistant.draft_history(self.path, 'one', IDENTITY)
        self.assertEqual([item['revision'] for item in first['versions']], list(range(23, 3, -1)))
        self.assertNotIn('draft', first['versions'][0])
        second = assistant.draft_history(self.path, 'one', IDENTITY, first['next_before'])
        self.assertEqual([item['revision'] for item in second['versions']], [3, 2, 1])
        self.assertIsNone(second['next_before'])
        old = assistant.draft_revision(self.path, 'one', IDENTITY, 1)
        restored = assistant.save_draft(self.path, 'one', IDENTITY, {'expected_revision': 23, 'draft': old['draft']})
        self.assertEqual(restored['revision'], 24)
        self.assertEqual(restored['draft'], old['draft'])
        self.assertEqual(assistant.draft_revision(self.path, 'one', IDENTITY, 1), old)
        self.assertEqual(assistant.draft_revision(self.path, 'one', IDENTITY, 23)['draft']['instruction'], 'Synthetic revision 23')
        with self.assertRaises(HTTPException) as conflict:
            assistant.save_draft(self.path, 'one', IDENTITY, {'expected_revision': 22, 'draft': old['draft']})
        self.assertEqual(conflict.exception.status_code, 409)
        for operation in (lambda: assistant.draft_history(self.path, 'two', IDENTITY),
                          lambda: assistant.draft_revision(self.path, 'two', IDENTITY, 1),
                          lambda: assistant.draft_revision(self.path, 'one', IDENTITY, 25)):
            with self.assertRaises(HTTPException) as missing:
                operation()
            self.assertEqual(missing.exception.status_code, 404)

    def test_legacy_context_defaults_and_capacity_preserve_existing_drafts(self):
        value = draft(); value.pop('context')
        self.assertEqual(assistant.validate_draft(value)['context'], draft()['context'])
        with assistant.connection(self.path) as con:
            con.executemany('INSERT INTO assistant_drafts VALUES(?,?,?,?,?)',
                [('one', f'{i:08x}-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 1, '2026-11-02', json.dumps(draft())) for i in range(100)])
        with self.assertRaises(HTTPException) as caught:
            assistant.save_draft(self.path, 'one', IDENTITY, {'expected_revision': 0, 'draft': draft()})
        self.assertEqual(caught.exception.status_code, 429)
        saved = assistant.save_draft(self.path, 'one', '00000000-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                     {'expected_revision': 1, 'draft': draft()})
        self.assertEqual(saved['revision'], 2)

    def test_library_keeps_empty_categories_and_source_metadata(self):
        original = {'data_origin': 'synthetic', 'sources': [{'id': 'synthetic-one', 'title': 'Synthetic source'}]}
        result = assistant.library(original)
        self.assertNotIn('knowledge_category', original['sources'][0])
        counts = {c['id']: c['count'] for c in result['categories']}
        self.assertEqual(counts['synthetic'], 1)
        self.assertEqual(counts['classics'], 0)
        self.assertEqual(counts['formula'], 0)


class AssistantHTTPTests(unittest.TestCase):
    setUp = host.WorkbenchHTTPTests.setUp
    tearDown = host.WorkbenchHTTPTests.tearDown
    new_client = host.WorkbenchHTTPTests.new_client
    setup_admin = host.WorkbenchHTTPTests.setup_admin

    def test_auth_origin_and_strict_json(self):
        root = '/api/department/assistant'
        self.assertEqual(self.client.get(root + '/drafts').status_code, 401)
        self.setup_admin()
        self.assertEqual(self.client.post(root + '/plan', headers={'origin': 'https://example.invalid'},
                         json={'instruction': 'intake', 'task': 'auto'}).status_code, 403)
        self.assertEqual(self.client.post(root + '/plan', content='{"instruction":"one","instruction":"two","task":"auto"}',
                         headers={'content-type': 'application/json'}).status_code, 422)
        response = self.client.post(root + '/plan', json={'instruction': 'cases', 'task': 'auto'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['task'], 'cases')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_drafts_are_account_scoped_over_http(self):
        self.setup_admin()
        path = '/api/department/assistant/drafts/' + IDENTITY
        value = {'expected_revision': 0, 'draft': draft()}
        self.assertEqual(self.client.post(path, json=value).status_code, 200)
        self.assertEqual(self.client.get(path).json()['draft'], draft())
        history = self.client.get(path + '/history')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.headers['cache-control'], 'no-store')
        self.assertEqual(history.json()['versions'][0]['revision'], 1)
        self.assertEqual(self.client.get(path + '/revisions/1').json()['draft'], draft())
        self.assertEqual(self.client.get(path + '/revisions/2').status_code, 404)
        for suffix in ('/history?before=0', '/history?before=abc', '/revisions/0', '/revisions/1000002'):
            self.assertEqual(self.client.get(path + suffix).status_code, 422)
        self.server.accounts.create_user('staff-assistant', 'Synthetic-staff-password', 'staff')
        other = self.new_client()
        try:
            self.assertEqual(other.post('/api/auth/login', json={'username': 'staff-assistant', 'password': 'Synthetic-staff-password'}).status_code, 200)
            self.assertEqual(other.get(path).status_code, 404)
            self.assertEqual(other.get(path + '/history').status_code, 404)
            self.assertEqual(other.get(path + '/revisions/1').status_code, 404)
            self.assertEqual(other.get('/api/department/assistant/drafts').json()['drafts'], [])
        finally:
            other.close()

    def test_prepare_uses_existing_parser_and_does_not_commit(self):
        self.setup_admin()
        response = {'records': [copy.deepcopy(RECORD)], 'source_sha256': RECORD['source_sha256']}
        with patch.object(assistant, 'invoke', new=AsyncMock(return_value=response)) as invoke:
            result = self.client.post('/api/department/assistant/prepare', json=draft())
            self.assertEqual(result.status_code, 200)
            invoke.assert_awaited_once_with('mingyirx', 'recognize', {'text': 'SYNTHETIC ONLY', 'data_origin': 'synthetic'})
        self.assertFalse(result.json()['review_confirmed'])
        self.assertEqual(self.client.get('/api/department/assistant/drafts').json()['drafts'], [])

    def test_cases_derive_owner_from_host_session(self):
        self.setup_admin()
        called = []
        workspace = Mock()
        workspace.snapshot.return_value = {'revision': 1, 'synthetic': True, 'records': [RECORD]}
        def factory(request):
            called.append(request.state.user['id'])
            return workspace
        with patch.object(assistant, 'full_workspace', side_effect=factory):
            response = self.client.post('/api/department/assistant/cases', json={'query': 'mouth'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(called), 1)
        self.assertEqual(called[0], self.server.accounts.list_users()[0]['id'])
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(self.client.post('/api/department/assistant/cases', json={'query': 'mouth', 'owner': 'other'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
