"""Exercise the compiled graph using synthetic source records only."""
import copy
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import consultation_graph as workflow
from test_department_assistant import RECORD, draft
import test_workbench_http as host


class ConsultationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.raw = {'records': [copy.deepcopy(RECORD)], 'source_sha256': RECORD['source_sha256']}
        self.invoke = AsyncMock(return_value=self.raw)
        self.patch = patch.object(workflow, 'invoke', self.invoke)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()

    async def test_real_graph_routes_multiple_turns_and_explicit_review(self):
        value = draft()
        result = await workflow.consultation({'action': 'advance', 'draft': value})
        self.assertEqual(result['trace'], ['recognize', 'assess', 'ask_question'])
        self.assertEqual(result['engine'], 'langgraph')
        self.assertFalse(result['model_called'])
        self.assertEqual(result['question']['field'], 'tongue')
        for index in range(4):
            question = result['question']
            value['supplements'].append({'record_id': question['record_id'], 'field': question['field'],
                'value': 'Synthetic observation' if index == 0 else '',
                'status': 'recorded' if index == 0 else 'unavailable', 'origin': 'clinician'})
            result = await workflow.consultation({'action': 'advance', 'draft': value})
        self.assertEqual(result['stage'], 'review_ready')
        self.assertEqual(result['counts'], {'pending': 0, 'recorded': 1, 'unavailable': 3})
        self.assertEqual(result['prepared']['original_records'], [RECORD])
        self.assertEqual(result['prepared']['source_sha256'], RECORD['source_sha256'])
        self.assertFalse(result['prepared']['review_confirmed'])
        reviewed = await workflow.consultation({'action': 'review', 'draft': value})
        self.assertEqual(reviewed['stage'], 'reviewed')
        self.assertIsNone(reviewed['clinical_approval'])
        self.assertEqual(reviewed['trace'], ['recognize', 'assess', 'review'])
        # New source edits must be evaluated afresh, never inherit a prior confirmation.
        self.assertEqual((await workflow.consultation({'action': 'advance', 'draft': value}))['stage'], 'review_ready')

    async def test_empty_source_and_premature_review(self):
        value = draft(); value['text'] = ''
        result = await workflow.consultation({'action': 'advance', 'draft': value})
        self.assertEqual(result['stage'], 'need_source')
        self.assertEqual(result['trace'], ['recognize', 'assess', 'request_source'])
        self.invoke.assert_not_awaited()
        for value in (value, draft()):
            with self.assertRaises(HTTPException) as caught:
                await workflow.consultation({'action': 'review', 'draft': value})
            self.assertEqual(caught.exception.status_code, 409)

    async def test_stale_ids_and_malformed_observations_rejected(self):
        value = draft()
        value['supplements'] = [{'record_id': 'REC-' + 'c' * 24, 'field': 'tongue', 'value': 'Synthetic', 'status': 'recorded', 'origin': 'clinician'}]
        with self.assertRaises(HTTPException) as caught:
            await workflow.consultation({'action': 'advance', 'draft': value})
        self.assertEqual(caught.exception.status_code, 409)
        value['supplements'][0]['value'] = ''
        with self.assertRaises(HTTPException) as caught:
            await workflow.consultation({'action': 'advance', 'draft': value})
        self.assertEqual(caught.exception.status_code, 422)
        value = draft(); value['task'] = 'knowledge'
        with self.assertRaises(HTTPException):
            await workflow.consultation({'action': 'advance', 'draft': value})

    async def test_environment_cannot_enable_external_tracing(self):
        with patch.dict(os.environ, {'LANGSMITH_TRACING': 'true', 'LANGCHAIN_TRACING_V2': 'true'}), \
             patch('langsmith.client.Client.create_run') as trace:
            await workflow.consultation({'action': 'advance', 'draft': draft()})
            trace.assert_not_called()


class ConsultationHTTPTests(unittest.TestCase):
    setUp = host.WorkbenchHTTPTests.setUp
    tearDown = host.WorkbenchHTTPTests.tearDown
    new_client = host.WorkbenchHTTPTests.new_client
    setup_admin = host.WorkbenchHTTPTests.setup_admin

    def test_auth_origin_and_actual_graph_http(self):
        url = '/api/department/assistant/consultation'
        body = {'action': 'advance', 'draft': draft()}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        self.setup_admin()
        self.assertEqual(self.client.post(url, json=body, headers={'origin': 'https://example.invalid'}).status_code, 403)
        with patch.object(workflow, 'invoke', AsyncMock(return_value={'records': [copy.deepcopy(RECORD)]})):
            response = self.client.post(url, json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json()['stage'], 'question')
        self.assertEqual(self.client.get('/api/department/assistant/drafts').json()['drafts'], [])
        self.assertEqual(self.client.post(url, json={**body, 'owner': 'other'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
