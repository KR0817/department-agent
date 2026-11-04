"""Synthetic consultation and transport checks; never call a paid API."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import httpx

import department_consultation as consultation
import department_llm as llm
from department_knowledge import Knowledge, KnowledgeError
from department_sources import load_package
import test_workbench_http as host

ROOT = Path(__file__).resolve().parents[1]
CID = 'ft_' + 'a' * 24
SOURCE = {'id': 'synthetic-source', 'title': 'SyntheticHerb software fixture', 'disease': 'sjd',
          'evidence_kind': 'html_section', 'retrieval_eligible': True}
INDEX = {'sha256': 'a' * 64, 'sources': [SOURCE], 'chunks': [
    {'id': CID, 'source_id': SOURCE['id'], 'evidence_kind': 'html_section', 'retrieval_eligible': True,
     'text': 'SyntheticHerb is fictional. This passage tests software provenance, not clinical claims.'}]}
CATALOG = {'index_sha256': INDEX['sha256'], 'sources': [SOURCE]}


def payload(**changes):
    return {'kind': 'herb', 'subject': 'SyntheticHerb', 'question': 'Explain this fictional herb.',
            'disease': 'all', 'source_id': 'all', 'index_sha256': INDEX['sha256'], **changes}


def completion(model='qwen3:14b', ids=None):
    content = {'status': 'answered', 'sections': [
        {'key': key, 'text': 'Synthetic software response only.', 'evidence_ids': ids or []}
        for key in ('identity', 'tradition', 'uses', 'cautions', 'uncertainty')]}
    return {'completion': {'model': model, 'done': True, 'done_reason': 'stop',
                           'message': {'role': 'assistant', 'content': json.dumps(content)}}}


class ConsultationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_package('app', ROOT / 'knowledge/app')

    def run_answer(self, body=None, response=None, integrity=None):
        value = consultation.validate_input(body or payload(), CATALOG)
        transport = Mock(return_value=response or completion(ids=[CID]))
        result = consultation.consult(value, copy.deepcopy(INDEX), transport=transport,
                                      integrity=integrity or Mock(),
                                      config={'provider': value.provider, 'model': 'qwen3:14b', 'configured': True})
        return result, transport

    def test_source_bound_answer_keeps_server_metadata_and_hash(self):
        result, transport = self.run_answer()
        self.assertEqual(result['status'], 'answer')
        self.assertTrue(result['model_called'])
        self.assertIsNone(result['clinical_approval'])
        self.assertEqual(result['content_origin'], 'model_generated')
        self.assertEqual(result['references'][0]['page_url'], '/api/department/knowledge/section/' + CID)
        self.assertEqual(result['references'][0]['support_status'], 'unassessed')
        self.assertEqual(len(result['references'][0]['quote_sha256']), 64)
        self.assertIn('SyntheticHerb is fictional', transport.call_args.args[0]['messages'][1]['content'])

    def test_missing_evidence_is_explicit_without_fabricated_references(self):
        result, _ = self.run_answer(payload(subject='MissingFictionalHerb'), completion())
        self.assertEqual(result['status'], 'answer')
        self.assertEqual(result['evidence_status'], 'no_matching_passages')
        self.assertEqual(result['references'], [])

    def test_exact_subject_and_selected_scope_filter_unrelated_passages(self):
        value = consultation.validate_input(payload(disease='ra'), CATALOG)
        self.assertEqual(consultation.select_passages(INDEX, value), [])
        for changes in ({'source_id': 'unknown'}, {'source_id': SOURCE['id'], 'disease': 'ra'},
                        {'index_sha256': 'b' * 64}, {'subject': '\n'}, {'subject': 'x' * 81},
                        {'question': ''}, {'patient_record': 'Synthetic private case'}, {'provider': 'arbitrary'},
                        {'public_topic_confirmed': 'true'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                consultation.validate_input(payload(**changes), CATALOG)

    def test_malformed_truncated_and_invented_provenance_are_not_displayed(self):
        for alteration in ('truncated', 'unknown-id', 'dose', 'url', 'missing-section', 'tools', 'duplicate-json'):
            raw = completion()
            message = raw['completion']['message']
            parsed = json.loads(message['content'])
            if alteration == 'truncated': raw['completion']['done_reason'] = 'length'
            elif alteration == 'unknown-id': parsed['sections'][0]['evidence_ids'] = ['unknown']
            elif alteration == 'dose': parsed['sections'][0]['text'] = 'Use 20 g daily.'
            elif alteration == 'url': parsed['sections'][0]['text'] = 'https://invented.example/citation'
            elif alteration == 'missing-section': parsed['sections'].pop()
            elif alteration == 'tools': message['tool_calls'] = [{'name': 'unexpected'}]
            message['content'] = json.dumps(parsed) if alteration != 'duplicate-json' else '{"status":"answered","status":"clarify","sections":[]}'
            with self.subTest(alteration=alteration):
                result, _ = self.run_answer(response=raw)
                self.assertEqual(result['status'], 'invalid_model_output')
                self.assertEqual(result['sections'], [])

    def test_source_change_during_generation_discards_content(self):
        check = Mock(side_effect=[None, ValueError('Synthetic source changed')])
        result, _ = self.run_answer(integrity=check)
        self.assertEqual(result['status'], 'source_unavailable')
        self.assertEqual(result['references'], [])
        self.assertEqual(result['sections'], [])

    def test_personal_or_urgent_requests_do_not_call_a_model(self):
        for question, status in [('\u7ed9\u6211\u5f00\u4e2a\u65b9', 'needs_clinician'),
                                 ('accidentally swallowed a fictional herb', 'urgent_care')]:
            result, transport = self.run_answer(payload(question=question))
            self.assertEqual(result['status'], status)
            transport.assert_not_called()

    def test_remote_consent_and_identifier_guard_run_before_dispatch(self):
        for changes in ({'public_topic_confirmed': False},
                        {'public_topic_confirmed': True, 'question': 'Contact synthetic@example.invalid'}):
            result, transport = self.run_answer(payload(provider='deepseek', **changes))
            self.assertEqual(result['status'], 'public_topic_required')
            transport.assert_not_called()

    def test_api_keeps_retrieved_passages_local(self):
        result, transport = self.run_answer(payload(provider='kimi', public_topic_confirmed=True), completion())
        self.assertEqual(result['status'], 'answer')
        sent = json.loads(transport.call_args.args[0]['messages'][1]['content'])
        self.assertEqual(sent['passages'], [])
        self.assertEqual(len(result['references']), 1)
        self.assertEqual(result['sent_scope'], 'public_question_only')

    def test_demo_has_no_inference_and_shared_busy_guard_covers_both_routes(self):
        service = Knowledge(ROOT / 'knowledge')
        service._extractor = {'catalog': lambda: CATALOG, 'extract': Mock()}
        with patch('department_consultation.local_completion', side_effect=AssertionError('No model')):
            self.assertEqual(service.consult(payload())['status'], 'model_disabled')
        service._mode = 'fulltext'
        service._model_lock.acquire()
        try:
            self.assertEqual(service.consult(payload())['status'], 'busy')
            self.assertEqual(service.extract({})['status'], 'busy')
        finally:
            service._model_lock.release()
        service._extractor['extract'].assert_not_called()


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_package('app', ROOT / 'knowledge/app')

    def test_remote_missing_key_is_explicit_and_never_makes_a_request(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(llm.httpx, 'Client') as client:
            rows = llm.provider_catalog(True)
            self.assertFalse(rows[1]['configured'])
            value = consultation.validate_input(payload(provider='deepseek', public_topic_confirmed=True), CATALOG)
            request = consultation.build_request(value, [], 'deepseek-flash')
            with self.assertRaises(llm.ModelError) as caught:
                llm.api_completion(request, 'deepseek')
            self.assertEqual(caught.exception.code, 'api_key_missing')
            client.assert_not_called()

    def test_both_api_providers_send_only_public_input_and_do_not_leak_keys(self):
        for provider in ('deepseek', 'kimi'):
            config = llm.API_PROVIDERS[provider]
            value = consultation.validate_input(payload(provider=provider, public_topic_confirmed=True), CATALOG)
            request = consultation.build_request(value, [], config['model'])
            injected = json.loads(request['messages'][1]['content'])
            injected['passages'] = [{'text': 'Synthetic private corpus marker'}]
            injected['patient_record'] = 'Synthetic case marker'
            request['messages'][1]['content'] = json.dumps(injected)
            sent = []
            def handler(outgoing):
                sent.append(json.loads(outgoing.content))
                self.assertEqual(str(outgoing.url), config['url'])
                result = completion()['completion']['message']
                return httpx.Response(200, json={'model': config['model'], 'choices': [{'finish_reason': 'stop', 'message': result}]})
            client_class = httpx.Client
            with patch.dict('os.environ', {config['key_env']: 'synthetic-test-only-value'}, clear=True), \
                    patch.object(llm.httpx, 'Client', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
                reply = llm.api_completion(request, provider)
                self.assertNotIn('synthetic-test-only-value', json.dumps(llm.provider_catalog(True)))
            self.assertEqual(reply['completion']['model'], config['model'])
            body = json.dumps(sent)
            self.assertNotIn('Synthetic private corpus marker', body)
            self.assertNotIn('Synthetic case marker', body)
            self.assertNotIn('synthetic-test-only-value', body)
            self.assertNotIn('tools', sent[0])

    def test_remote_errors_redirects_and_truncation_have_sanitized_codes(self):
        value = consultation.validate_input(payload(), CATALOG)
        request = consultation.build_request(value, [], 'deepseek-flash')
        client_class = httpx.Client
        for status, expected in [(401, 'api_authentication_failed'), (429, 'api_rate_limited'), (307, 'api_request_failed')]:
            handler = lambda outgoing: httpx.Response(status, json={'error': 'Synthetic secret-like response body'}, headers={'location': 'https://untrusted.invalid'})
            with self.subTest(status=status), patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-only'}, clear=True), \
                    patch.object(llm.httpx, 'Client', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
                with self.assertRaises(llm.ModelError) as caught:
                    llm.api_completion(request, 'deepseek')
                self.assertEqual(str(caught.exception), expected)

    def test_local_ollama_rejects_remote_endpoint_before_network(self):
        with patch.dict('os.environ', {'DEPARTMENT_LLM_TRANSPORT': 'ollama', 'DEPARTMENT_LLM_ENDPOINT': 'https://untrusted.invalid'}, clear=True):
            with self.assertRaises(ValueError):
                llm.local_completion({'model': 'qwen3:14b'})

    def test_cloud_ollama_entry_is_rejected_before_inference(self):
        with patch.dict('os.environ', {'DEPARTMENT_LLM_TRANSPORT': 'ollama'}, clear=True), \
                patch('app.local_model.probe', return_value={'models': [{'name': 'qwen3:14b', 'local_metadata_verified': False}]}), \
                patch('app.local_model.request_json') as request:
            with self.assertRaises(ValueError):
                llm.local_completion({'model': 'qwen3:14b'})
            request.assert_not_called()

    def test_api_truncation_tools_timeout_and_size_are_not_accepted(self):
        value = consultation.validate_input(payload(), CATALOG)
        request = consultation.build_request(value, [], 'deepseek-flash')
        client_class = httpx.Client
        for scenario, expected in [('length', 'api_invalid_response'), ('tools', 'api_invalid_response'),
                                   ('timeout', 'api_timeout'), ('size', 'api_response_limit')]:
            calls = []
            def handler(outgoing):
                calls.append(outgoing)
                if scenario == 'timeout': raise httpx.ReadTimeout('Synthetic private-looking failure')
                if scenario == 'size': return httpx.Response(200, content=b'x' * 131073)
                message = completion()['completion']['message']
                if scenario == 'tools': message['tool_calls'] = [{'name': 'unexpected'}]
                return httpx.Response(200, json={'model': 'deepseek-flash', 'choices': [
                    {'finish_reason': 'length' if scenario == 'length' else 'stop', 'message': message}]})
            with self.subTest(scenario=scenario), patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-only'}, clear=True), \
                    patch.object(llm.httpx, 'Client', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
                with self.assertRaises(llm.ModelError) as caught:
                    llm.api_completion(request, 'deepseek')
                self.assertEqual(str(caught.exception), expected)
                self.assertEqual(len(calls), 1)


class ConsultationHTTPTests(unittest.TestCase):
    setUp = host.WorkbenchHTTPTests.setUp
    tearDown = host.WorkbenchHTTPTests.tearDown
    new_client = host.WorkbenchHTTPTests.new_client
    setup_admin = host.WorkbenchHTTPTests.setup_admin

    def test_auth_origin_validation_and_success(self):
        route = '/api/department/knowledge/consult'
        self.assertEqual(self.client.post(route, json=payload()).status_code, 401)
        self.setup_admin()
        service = Knowledge(ROOT / 'knowledge', mode='fulltext')
        service._extractor = {'catalog': lambda: CATALOG}
        service._consultation_index = INDEX
        with patch('department.service', return_value=service), patch('department_consultation.consult', return_value={'status': 'answer'}) as run:
            self.assertEqual(self.client.post(route, json=payload(), headers={'origin': 'https://untrusted.invalid'}).status_code, 403)
            self.assertEqual(self.client.post(route, json=payload(index_sha256='b' * 64)).status_code, 409)
            self.assertEqual(self.client.post(route, json=payload(patient_record='Synthetic case')).status_code, 400)
            self.assertEqual(self.client.post(route, content='x' * 17000, headers={'content-type': 'application/json'}).status_code, 413)
            self.assertEqual(self.client.post(route, content='{"kind":"herb","kind":"formula"}', headers={'content-type': 'application/json'}).status_code, 422)
            run.assert_not_called()
            result = self.client.post(route, json=payload())
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['status'], 'answer')
            run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
