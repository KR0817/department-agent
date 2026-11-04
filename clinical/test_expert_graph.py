"""Synthetic graph, ownership and failure-path checks; no real model or cloud calls."""
import copy
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

import expert_graph as expert
import department_llm as llm
import httpx
from department_consultation import validate_input
from department_knowledge import Knowledge, KnowledgeError
from department_sources import load_package
from test_department_consultation import ROOT, CID, INDEX, CATALOG, payload
import test_workbench_http as host


CONFIG = {'provider': 'local', 'model': 'qwen3:14b', 'configured': True}
KIMI_CONFIG = {'provider': 'kimi', 'model': 'kimi-k3.1-pro', 'configured': True}


def fake_completion(request):
    prompt = request['messages'][0]['content']
    role = next(role for role in expert.ROLES if 'ROLE: '+role+'.' in prompt)
    content = json.loads(request['messages'][1]['content'])
    if role == 'synthesis':
        result = {'overview': 'Synthetic overview only.', 'selected_claim_ids': list(expert.claim_ids(content['reports'])),
                  'unresolved': ['Synthetic unresolved issue.']}
    else:
        sourced = role == 'evidence' and bool(content['passages'])
        result = {'uncertainties': ['Synthetic uncertainty.']}
        if role == 'evidence':
            result['findings'] = [{'text': 'Synthetic software claim only.', 'passage_id': CID}] if sourced else []
        else:
            result['risks' if role == 'pharmacy' else 'points'] = ['Synthetic software claim only.']
        if role == 'pharmacy':
            result['concerns'] = [{'claim_ids': ['tcm:1'] if 'tcm' in content['reports'] and content['reports']['tcm']['claims'] else [],
                                   'text': 'Synthetic review concern retained separately.'}]
    return {'completion': {'model': request['model'], 'done': True, 'done_reason': 'stop',
                           'message': {'role': 'assistant', 'content': json.dumps(result)}}, 'model_digest': 'synthetic'}


class GraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_package('app', ROOT / 'knowledge/app')

    def run_graph(self, body=None, transport=None, integrity=None, **kwargs):
        return expert.collaborate(validate_input(body or payload(), CATALOG), copy.deepcopy(INDEX),
                                  transport=transport or fake_completion, integrity=integrity or Mock(), config=CONFIG, **kwargs)

    def test_actual_graph_roles_are_independent_then_reviewed_and_synthesized(self):
        requests, progress = [], []
        def transport(request):
            requests.append(json.loads(request['messages'][1]['content']))
            return fake_completion(request)
        result = self.run_graph(transport=transport, progress=progress.append)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['trace'], ['retrieve', 'tcm', 'evidence', 'pharmacy', 'synthesis', 'verify'])
        self.assertEqual(len(result['model_calls']), 4)
        self.assertEqual(requests[0]['reports'], {})
        self.assertEqual(requests[0]['passages'], [])
        self.assertNotIn('question', requests[0])
        self.assertEqual(requests[1]['reports'], {})
        self.assertEqual(set(requests[2]['reports']), {'tcm', 'evidence'})
        self.assertIn('pharmacy', requests[3]['reports'])
        self.assertTrue(result['reports']['pharmacy']['concerns'])
        self.assertEqual(result['reports']['evidence']['claims'][0]['quote_identity'], 'exact_match')
        self.assertEqual(result['reports']['evidence']['claims'][0]['quote'], INDEX['chunks'][0]['text'])
        self.assertEqual(result['reports']['evidence']['claims'][0]['support_status'], 'human_review_required')
        self.assertIsNone(result['clinical_approval'])
        self.assertEqual(result['result_sha256'], expert.digest({k: v for k, v in result.items() if k != 'result_sha256'}))
        self.assertTrue(any(item['roles']['tcm'] == 'running' for item in progress))

    def test_missing_evidence_remains_visible(self):
        result = self.run_graph(payload(subject='UnrelatedFictionalName'))
        self.assertEqual(result['evidence_status'], 'no_matching_passages')
        self.assertEqual(result['roles']['evidence'], 'insufficient')
        self.assertEqual(result['references'], [])

    def test_context_budget_keeps_complete_passages_and_reports_omissions(self):
        first = {**INDEX['chunks'][0], 'text': INDEX['chunks'][0]['text']+'x'*1800}
        second = {**first, 'id': 'ft_'+'b'*24}
        with patch.object(expert, 'select_passages', return_value=[first, second]):
            result = self.run_graph()
        self.assertEqual(result['retrieval_budget'], {'included': 1, 'omitted_for_budget': 1})
        self.assertEqual(result['references'][0]['quote'], first['text'])
        self.assertEqual(result['generation_budget']['context_tokens'], 8192)

    def test_invented_quote_and_unsourced_evidence_fail_that_role(self):
        for mutation in ('quote', 'source', 'basis', 'dose', 'url', 'truncated', 'tool'):
            def transport(request):
                response = fake_completion(request)
                if 'ROLE: evidence.' in request['messages'][0]['content']:
                    raw = response['completion']; parsed = json.loads(raw['message']['content'])
                    claim = parsed['findings'][0]
                    if mutation == 'quote': claim['quote'] = 'A fabricated quotation.'
                    elif mutation == 'source': claim['passage_id'] = 'unknown'
                    elif mutation == 'basis': claim.update(basis='model_knowledge', quote='', passage_id='')
                    elif mutation == 'dose': claim['text'] = 'Take 30 g daily.'
                    elif mutation == 'url': claim['text'] = 'https://invented.example/'
                    elif mutation == 'truncated': raw['done_reason'] = 'length'
                    else: raw['message']['tool_calls'] = [{'name': 'unexpected'}]
                    raw['message']['content'] = json.dumps(parsed)
                return response
            with self.subTest(mutation=mutation):
                result = self.run_graph(transport=transport)
                self.assertEqual(result['status'], 'partial')
                self.assertEqual(result['roles']['evidence'], 'failed')
                self.assertEqual(result['reports']['evidence']['claims'], [])

    def test_evidence_cannot_select_a_passage_without_the_named_subject(self):
        unrelated = {**INDEX['chunks'][0], 'text': 'A complete fictional passage about an unrelated entity.'}
        with patch.object(expert, 'select_passages', return_value=[unrelated]):
            result = self.run_graph()
        self.assertEqual(result['roles']['evidence'], 'failed')
        self.assertEqual(result['reports']['evidence']['claims'], [])

    def test_synthesis_cannot_reference_nonexistent_claims_or_hide_concerns(self):
        def transport(request):
            response = fake_completion(request)
            if 'ROLE: synthesis.' in request['messages'][0]['content']:
                response['completion']['message']['content'] = json.dumps(
                    {'overview': 'Synthetic.', 'selected_claim_ids': ['invented:1'], 'unresolved': []})
            return response
        result = self.run_graph(transport=transport)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['synthesis'])
        self.assertTrue(result['reports']['pharmacy']['concerns'])

    def test_general_role_cannot_invent_quote_fields_or_book_attribution(self):
        for metadata in (True, False):
            def transport(request):
                response = fake_completion(request)
                if 'ROLE: tcm.' in request['messages'][0]['content']:
                    parsed = json.loads(response['completion']['message']['content'])
                    if metadata:
                        parsed['quote'] = 'Invented book quotation.'
                    else:
                        parsed['points'] = ['\u300aSyntheticBook\u300b\u8bb0\u8f7d: invented attribution.']
                    response['completion']['message']['content'] = json.dumps(parsed)
                return response
            with self.subTest(metadata=metadata):
                result = self.run_graph(transport=transport)
                self.assertEqual(result['roles']['tcm'], 'failed')
                self.assertEqual(result['reports']['tcm']['claims'], [])

    def test_pharmacy_can_complete_with_review_concerns_without_new_claims(self):
        def transport(request):
            response = fake_completion(request)
            if 'ROLE: pharmacy.' in request['messages'][0]['content']:
                parsed = json.loads(response['completion']['message']['content'])
                parsed['risks'] = []
                response['completion']['message']['content'] = json.dumps(parsed)
            return response
        result = self.run_graph(transport=transport)
        self.assertEqual(result['roles']['pharmacy'], 'completed')
        self.assertEqual(result['reports']['pharmacy']['claims'], [])
        self.assertTrue(result['reports']['pharmacy']['concerns'])

    def test_source_change_invalidates_all_generated_content(self):
        changed = threading.Event()
        def check(*_):
            if changed.is_set(): raise ValueError('Synthetic changed source')
        def transport(request):
            changed.set()
            return fake_completion(request)
        result = self.run_graph(transport=transport, integrity=check)
        self.assertEqual(result['status'], 'source_unavailable')
        self.assertEqual(result['reports'], {})
        self.assertEqual(result['references'], [])
        self.assertEqual(len(result['model_calls']), 1)

    def test_cancel_during_current_call_skips_later_roles(self):
        cancelled = threading.Event()
        def transport(request):
            cancelled.set()
            return fake_completion(request)
        result = self.run_graph(transport=transport, cancelled=cancelled.is_set)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reports'], {})
        self.assertEqual(len(result['model_calls']), 1)

    def test_public_guards_and_unsupported_provider_rejected_without_call(self):
        for question in ('accidentally swallowed a fictional herb', 'prescribe for me', 'Email example@example.com'):
            model = Mock()
            result = self.run_graph(payload(question=question), transport=model)
            self.assertFalse(result['model_called']); model.assert_not_called()
        with self.assertRaises(ValueError):
            self.run_graph(payload(provider='deepseek'))

    def hybrid(self, **kwargs):
        return self.run_graph(payload(provider='kimi', public_topic_confirmed=True), api_config=KIMI_CONFIG,
                              **kwargs)

    def test_hybrid_reference_calls_overlap_and_join_before_local_review(self):
        from langsmith import get_tracing_context
        local_started, remote_started = threading.Event(), threading.Event()
        remote_requests, local_requests = [], []
        def local(request):
            self.assertFalse(get_tracing_context()['enabled'])
            content = json.loads(request['messages'][1]['content']); local_requests.append(content)
            if 'ROLE: evidence.' in request['messages'][0]['content']:
                local_started.set(); self.assertTrue(remote_started.wait(3))
                self.assertEqual(content['reports'], {})
            else:
                self.assertTrue(remote_started.is_set())
                self.assertEqual(set(content['reports']) & {'tcm', 'evidence'}, {'tcm', 'evidence'})
            return fake_completion(request)
        def remote(request):
            self.assertFalse(get_tracing_context()['enabled'])
            remote_started.set(); self.assertTrue(local_started.wait(3)); remote_requests.append(request)
            result = fake_completion(request); result['reported_model'] = KIMI_CONFIG['model']; return result
        with patch.dict('os.environ', {'LANGSMITH_TRACING': 'true'}):
            result = self.hybrid(transport=local, api_transport=remote)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(remote_requests), 1); self.assertEqual(len(local_requests), 3)
        public = json.loads(remote_requests[0]['messages'][1]['content'])
        self.assertEqual(set(public), {'kind', 'subject', 'question'})
        self.assertNotIn(INDEX['chunks'][0]['text'], json.dumps(remote_requests))
        self.assertNotIn(CID, json.dumps(remote_requests))
        self.assertEqual(result['role_models']['tcm'], {'provider': 'kimi', 'model': 'kimi-k3.1-pro'})
        self.assertEqual(result['model_calls'][0]['reported_model'], 'kimi-k3.1-pro')
        self.assertEqual(result['model_calls'][0]['sent_scope'], 'public_question_only')
        self.assertEqual(result['trace'], ['retrieve', 'tcm', 'evidence', 'pharmacy', 'synthesis', 'verify'])

    def test_hybrid_provider_failures_do_not_retry_or_poison_the_other_provider(self):
        remote = Mock(side_effect=llm.ModelError('api_authentication_failed'))
        local = Mock(side_effect=fake_completion)
        result = self.hybrid(transport=local, api_transport=remote)
        self.assertEqual(result['status'], 'partial'); remote.assert_called_once()
        self.assertEqual(local.call_count, 3)
        self.assertEqual(result['roles']['synthesis'], 'completed')
        self.assertEqual(result['model_calls'][0]['provider_error'], 'api_authentication_failed')
        local = Mock(side_effect=TimeoutError('Synthetic private failure'))
        remote = Mock(side_effect=fake_completion)
        result = self.hybrid(transport=local, api_transport=remote)
        local.assert_called_once(); remote.assert_called_once()
        self.assertEqual(result['roles']['tcm'], 'completed')
        self.assertEqual(result['roles']['pharmacy'], 'skipped')
        self.assertEqual(result['status'], 'partial')
        self.assertNotIn('Synthetic private failure', json.dumps(result))

    def test_hybrid_requires_public_ack_and_key_before_any_role(self):
        for confirmed, configured, status in [(False, True, 'public_topic_required'), (True, False, 'model_unavailable')]:
            local, remote = Mock(), Mock()
            result = self.run_graph(
                payload(provider='kimi', public_topic_confirmed=confirmed), transport=local, api_transport=remote,
                api_config={**KIMI_CONFIG, 'configured': configured})
            self.assertEqual(result['status'], status); local.assert_not_called(); remote.assert_not_called()

    def test_hybrid_cancellation_and_source_change_withhold_reports_and_skip_review(self):
        for scenario in ('cancel', 'source'):
            changed, both = threading.Event(), threading.Barrier(2)
            def check(*_):
                if scenario == 'source' and changed.is_set(): raise ValueError('Synthetic changed source')
            def complete(request):
                both.wait(3); changed.set(); return fake_completion(request)
            result = self.hybrid(transport=complete, api_transport=complete, integrity=check,
                                 cancelled=lambda: scenario == 'cancel' and changed.is_set())
            self.assertEqual(result['status'], 'cancelled' if scenario == 'cancel' else 'source_unavailable')
            self.assertEqual(len(result['model_calls']), 2)
            self.assertEqual(result['reports'], {}); self.assertEqual(result['references'], [])

    def test_kimi_http_boundary_strips_corpus_reports_and_uses_k3_parameters(self):
        request = llm.structured_request('kimi-k3.1-pro', expert.ROLE_PROMPTS['tcm'] + expert.COMMON,
            {'kind': 'herb', 'subject': 'SyntheticHerb', 'question': 'Fictional public question',
             'passages': [{'text': 'PRIVATE-CORPUS-MARKER'}], 'reports': {'text': 'PRIVATE-REPORT-MARKER'},
             'patient_record': 'PRIVATE-CASE-MARKER'}, expert.Report.model_json_schema())
        sent = []
        def handler(outgoing):
            sent.append(json.loads(outgoing.content))
            self.assertEqual(str(outgoing.url), 'https://api.moonshot.cn/v1/chat/completions')
            return httpx.Response(200, json={'model': 'kimi-k3.1-pro', 'choices': [{
                'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"points":[],"uncertainties":["Synthetic"]}',
                                                  'reasoning_content': 'PRIVATE-REASONING-MARKER'}}]})
        client_class = httpx.Client
        with patch.dict('os.environ', {'MOONSHOT_API_KEY': 'synthetic-only', 'DEPARTMENT_KIMI_MODEL': 'kimi-k3.1-pro'}, clear=True), \
             patch.object(llm.httpx, 'Client', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
            reply = llm.api_reference_completion(request)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['reasoning_effort'], 'low'); self.assertNotIn('thinking', sent[0])
        self.assertEqual(set(json.loads(sent[0]['messages'][1]['content'])), {'kind', 'subject', 'question'})
        self.assertNotIn('PRIVATE-', json.dumps(sent)); self.assertNotIn('PRIVATE-', json.dumps(reply))

    def all_kimi(self, *, index=None, changes=None, remote=None, **kwargs):
        body = payload(provider='kimi', public_topic_confirmed=True, expert_mode='all_kimi', public_evidence_confirmed=True)
        body.update(changes or {})
        public_index = copy.deepcopy(index or INDEX)
        if index is None:
            public_index['sources'][0]['pmid'] = '99999999'  # Synthetic identity, never a clinical citation.
        return expert.collaborate(validate_input(body, CATALOG, input_type=expert.ExpertInput), public_index,
                                  api_config=KIMI_CONFIG, api_transport=remote or fake_completion,
                                  transport=Mock(side_effect=AssertionError('Local inference forbidden')),
                                  integrity=Mock(), **kwargs)

    def test_all_kimi_uses_four_api_roles_without_local_model_configuration(self):
        requests = []
        def remote(request):
            requests.append(request)
            return {**fake_completion(request), 'reported_model': 'kimi-k3.1-pro'}
        with patch.object(expert, 'model_configuration', side_effect=AssertionError('Local configuration forbidden')):
            result = self.all_kimi(remote=remote)
        self.assertEqual(result['status'], 'completed'); self.assertEqual(len(requests), 4)
        self.assertEqual(result['execution'], 'all_kimi')
        self.assertTrue(all(call['provider'] == 'kimi' and call['model'] == 'kimi-k3.1-pro' for call in result['model_calls']))
        self.assertEqual(result['model_calls'][1]['sent_passage_count'], 1)
        self.assertEqual(result['reports']['evidence']['claims'][0]['quote'], INDEX['chunks'][0]['text'])
        pharmacy = next(row for row in requests if 'ROLE: pharmacy.' in row['messages'][0]['content'])
        self.assertEqual(set(json.loads(pharmacy['messages'][1]['content'])['reports']), {'tcm', 'evidence'})

    def test_all_kimi_consent_and_source_identity_guards(self):
        remote = Mock()
        result = self.all_kimi(changes={'public_evidence_confirmed': False}, remote=remote)
        self.assertEqual(result['status'], 'public_evidence_required'); remote.assert_not_called()
        for marker in (False, True):
            index = copy.deepcopy(INDEX)
            if marker:
                index['sources'][0]['pmid'] = '99999999'
                index['chunks'][0]['text'] += ' Email private@example.com'
            sent = []
            def transport(request):
                sent.append(request); return fake_completion(request)
            result = self.all_kimi(index=index, remote=transport)
            self.assertEqual(result['retrieval_budget']['omitted_for_public_scope'], 1)
            self.assertEqual(result['roles']['evidence'], 'insufficient')
            self.assertNotIn(INDEX['chunks'][0]['text'], json.dumps(sent))
            self.assertNotIn('private@example.com', json.dumps(sent))

    def test_all_kimi_transport_failure_prevents_downstream_api_calls(self):
        barrier = threading.Barrier(2)
        def remote(request):
            barrier.wait(3)
            if 'ROLE: evidence.' in request['messages'][0]['content']:
                raise llm.ModelError('api_rate_limited')
            return fake_completion(request)
        result = self.all_kimi(remote=remote)
        self.assertEqual(len(result['model_calls']), 2)
        self.assertEqual(result['roles']['pharmacy'], 'skipped')
        self.assertEqual(result['roles']['synthesis'], 'skipped')
        self.assertEqual(result['status'], 'partial')

    def test_all_kimi_http_allowlist_forwards_public_materials_without_metadata_or_duplicate_quotes(self):
        claim = {'id':'evidence:1','text':'Synthetic finding','basis':'source','passage_id':CID,
                 'quote':'DUPLICATE-QUOTE-MARKER','local_path':'PRIVATE-PATH-MARKER'}
        content = {'kind':'herb','subject':'SyntheticHerb','question':'Public question',
                   'passages':[{'id':CID,'text':'AUTHORIZED-PUBLIC-EXCERPT','path':'PRIVATE-PATH-MARKER'}],
                   'reports':{'evidence':{'status':'complete','claims':[claim],'uncertainties':[],
                                          'patient_record':'PRIVATE-CASE-MARKER'}},
                   'patient_record':'PRIVATE-CASE-MARKER','whole_index':'PRIVATE-INDEX-MARKER'}
        request = llm.structured_request('kimi-k3.1-pro', expert.ROLE_PROMPTS['pharmacy'],content,expert.PharmacyReport.model_json_schema())
        with patch.object(llm, '_public_api_completion', return_value={}) as send:
            with self.assertRaises(llm.ModelError): llm.api_expert_completion(request, 'pharmacy')
            send.assert_not_called()
            llm.api_expert_completion(request, 'pharmacy', public_evidence_confirmed=True)
            transmitted = send.call_args.args[3]
            self.assertIn('AUTHORIZED-PUBLIC-EXCERPT', json.dumps(transmitted))
            self.assertNotIn('PRIVATE-', json.dumps(transmitted)); self.assertNotIn('DUPLICATE-', json.dumps(transmitted))
            llm.api_expert_completion(request, 'synthesis', public_evidence_confirmed=True)
            self.assertNotIn('passages', send.call_args.args[3])
            llm.api_expert_completion(request, 'tcm', public_evidence_confirmed=True)
            self.assertEqual(set(send.call_args.args[3]), {'kind', 'subject', 'question'})
        content['passages'][0]['text'] = 'x' * 2601
        request['messages'][1]['content'] = json.dumps(content)
        with patch.object(llm, '_public_api_completion') as send, self.assertRaises(llm.ModelError):
            llm.api_expert_completion(request, 'evidence', public_evidence_confirmed=True)
        send.assert_not_called()

    def test_external_tracing_is_disabled(self):
        from langsmith import get_tracing_context
        def transport(request):
            self.assertFalse(get_tracing_context()['enabled'])
            return fake_completion(request)
        with patch.dict('os.environ', {'LANGSMITH_TRACING': 'true', 'LANGCHAIN_TRACING_V2': 'true'}):
            self.run_graph(transport=transport)

    def test_transport_failure_skips_later_calls_without_retry(self):
        transport = Mock(side_effect=TimeoutError('Synthetic timeout'))
        result = self.run_graph(transport=transport)
        transport.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['roles']['tcm'], 'failed')
        self.assertEqual(result['roles']['pharmacy'], 'skipped')
        self.assertEqual(result['model_calls'][0]['error'], 'transport_unavailable')


class JobTests(unittest.TestCase):
    def service(self):
        service = Knowledge(ROOT / 'knowledge', 'fulltext')
        service.catalog = Mock(return_value=CATALOG)
        service._consultation_index = copy.deepcopy(INDEX)
        return service

    def test_job_ownership_busy_cancel_and_lock_release(self):
        service, started, finish = self.service(), threading.Event(), threading.Event()
        def work(value, index, progress, cancelled):
            progress({'stage': 'tcm', 'roles': {'tcm': 'running'}}); started.set()
            finish.wait(3)
            return {'status': 'cancelled' if cancelled() else 'completed'}
        with patch('expert_graph.collaborate', work):
            initial = service.collaborate(payload(), 'account-a'); self.assertTrue(started.wait(2))
            identity = initial['job_id']
            self.assertEqual(service.collaborate(payload(), 'account-a')['status'], 'busy')
            for action in (service.collaboration, service.cancel_collaboration):
                with self.assertRaises(KnowledgeError) as caught: action(identity, 'account-b')
                self.assertEqual(caught.exception.status, 404)
            self.assertEqual(service.collaboration(identity, 'account-a')['stage'], 'tcm')
            self.assertEqual(service.cancel_collaboration(identity, 'account-a')['status'], 'cancel_requested')
            finish.set()
            for _ in range(100):
                result = service.collaboration(identity, 'account-a')
                if result['status'] == 'cancelled': break
                time.sleep(.01)
            self.assertEqual(result['status'], 'cancelled')
            self.assertTrue(service._model_lock.acquire(False)); service._model_lock.release()

    def test_invalid_disabled_and_stale_requests_never_start(self):
        service = self.service()
        for changes in ({'provider': 'deepseek'}, {'index_sha256': 'b' * 64}, {'extra': 1}):
            with self.assertRaises(KnowledgeError): service.collaborate(payload(**changes), 'account-a')
        service._mode = 'synthetic-demo'
        self.assertEqual(service.collaborate(payload(), 'account-a')['status'], 'model_disabled')
        self.assertFalse(service._jobs)

    def test_hybrid_preflight_does_not_start_unacknowledged_or_unconfigured_jobs(self):
        service = self.service()
        self.assertEqual(service.collaborate(payload(provider='kimi'), 'a')['status'], 'public_topic_required')
        with patch('department_llm.model_configuration', return_value={**KIMI_CONFIG, 'configured': False}):
            result = service.collaborate(payload(provider='kimi', public_topic_confirmed=True), 'a')
        self.assertEqual(result['error'], 'api_key_missing'); self.assertFalse(service._jobs)

    def test_all_kimi_model_and_consent_checked_before_starting_job(self):
        service = self.service()
        body = payload(provider='kimi', public_topic_confirmed=True, expert_mode='all_kimi')
        self.assertEqual(service.collaborate(body, 'a')['status'], 'public_evidence_required')
        with patch('department_llm.model_configuration', return_value={**KIMI_CONFIG, 'model':'kimi-k2.6'}):
            result = service.collaborate({**body,'public_evidence_confirmed':True}, 'a')
        self.assertEqual(result['error'], 'kimi31_required'); self.assertFalse(service._jobs)
        with self.assertRaises(ValueError): validate_input(body, CATALOG)

    def test_expired_jobs_and_memory_bound(self):
        service = self.service()
        for i in range(20):
            service._jobs[str(i)] = {'owner': 'a', 'finished': time.monotonic() - (1900 if i == 0 else 20-i), 'public': {}}
        service._prune_jobs()
        self.assertEqual(len(service._jobs), 16)
        self.assertNotIn('0', service._jobs)


class ExpertHTTPTests(unittest.TestCase):
    setUp = host.WorkbenchHTTPTests.setUp
    tearDown = host.WorkbenchHTTPTests.tearDown
    new_client = host.WorkbenchHTTPTests.new_client
    setup_admin = host.WorkbenchHTTPTests.setup_admin

    def test_session_origin_payload_and_account_boundary(self):
        route = '/api/department/knowledge/collaborate'
        self.assertEqual(self.client.post(route, json=payload()).status_code, 401)
        self.assertEqual(self.client.get('/api/department/knowledge/collaborations/unknown').status_code, 401)
        self.setup_admin()
        service = Knowledge(ROOT / 'knowledge', 'fulltext')
        service.catalog = Mock(return_value=CATALOG)
        service._consultation_index = INDEX
        service.collaborate = Mock(return_value={'job_id': 'synthetic', 'status': 'running'})
        with patch('department.service', return_value=service):
            self.assertEqual(self.client.post(route, json=payload(), headers={'origin': 'https://untrusted.invalid'}).status_code, 403)
            self.assertEqual(self.client.post(route, content='x'*17000, headers={'content-type': 'application/json'}).status_code, 413)
            service.collaborate.assert_not_called()
            response = self.client.post(route, json=payload())
            self.assertEqual(response.status_code, 200)
            owner = service.collaborate.call_args.args[1]
            self.assertIsInstance(owner, str)
            self.assertTrue(owner)
            service._jobs['synthetic'] = {'owner': 'a-different-account', 'finished': None, 'public': {}, 'cancel': threading.Event()}
            self.assertEqual(self.client.get('/api/department/knowledge/collaborations/synthetic').status_code, 404)
            cancel = '/api/department/knowledge/collaborations/synthetic/cancel'
            self.assertEqual(self.client.post(cancel, json={}).status_code, 404)
            service._jobs['synthetic']['owner'] = owner
            self.assertEqual(self.client.post(cancel, json={'extra': True}).status_code, 422)
            self.assertEqual(self.client.post(cancel, json={}, headers={'origin': 'https://untrusted.invalid'}).status_code, 403)
            self.assertEqual(self.client.post(cancel, json={}).json()['status'], 'cancel_requested')


if __name__ == '__main__':
    unittest.main()
