"""Synthetic adapter regression checks; never contact running services."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import clinical


class ClinicalV2Tests(unittest.TestCase):
    def setUp(self):
        from synthetic_fhir import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'AGENT_DEMO': '1'})
        self.env.start()
        self.client = TestClient(create_app(self.temp.name), base_url='http://127.0.0.1:18113')
        self.client.__enter__()
        self.base = patch.object(clinical.http, 'BASE', 'http://127.0.0.1:18113')
        self.base.start()

        def call(method, path, payload=None, token=None, extra=None, form=False):
            self.assertIsNone(token)
            response = self.client.request(method, path, json=payload, headers=extra or {})
            return response.status_code, response.json(), dict(response.headers)

        self.transport = patch.object(clinical.http, 'call', side_effect=call)
        self.transport.start()
        self.auth = patch.object(clinical, 'authenticate', side_effect=AssertionError('Credentials accessed'))
        self.auth.start()

    def tearDown(self):
        self.auth.stop()
        self.transport.stop()
        self.base.stop()
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.temp.cleanup()

    def candidate(self, event='morning', day='2026-10-01', value='18.2', field='f1'):
        return {'patient_id': 'SIM-CLINICAL-V2', 'name': 'Synthetic Patient', 'visits': [
            {'date': day, 'event_id': event, 'facts': [{'field_id': field, 'revision': 1,
                'code': 'igg', 'value': value, 'unit': 'g/L', 'quote': 'IgG ' + value + ' g/L',
                'review': {'action': 'accept', 'actor': 'synthetic-operator', 'at': '2026-10-22T00:00:00Z', 'reason': ''}}]}]}

    def publish(self, candidate, progress=None, sink=None, source='a' * 64):
        return clinical.publish(candidate, source, 90, 'synthetic-operator', progress, sink)

    def test_same_day_events_are_distinct_and_retry_is_idempotent(self):
        first = self.publish(self.candidate())
        second = self.publish(self.candidate('afternoon', value='17.1'))
        self.assertNotEqual(first['visits'][0]['encounter'], second['visits'][0]['encounter'])
        self.assertEqual(first['task'], second['task'])
        repeated = self.publish(self.candidate(), first)
        self.assertEqual(repeated['fields']['f1']['observation'], first['fields']['f1']['observation'])
        self.assertEqual(len(clinical.search('Observation', {})), 2)
        self.assertEqual(len(clinical.search('Provenance', {})), 2)
        self.assertEqual(len(clinical.search('Task', {})), 1)

    def test_correction_keeps_old_value_and_rejects_stale_branch(self):
        first = self.publish(self.candidate())
        correction = self.candidate(value='17.9')
        fact = correction['visits'][0]['facts'][0]
        fact.update(revision=2, correction_of=first['fields']['f1']['observation'])
        fact['review'].update(action='modify', reason='Synthetic transcription correction')
        corrected = self.publish(correction, first)
        observations = clinical.search('Observation', {})
        self.assertEqual({o['valueString'] for o in observations}, {'18.2 g/L', '17.9 g/L'})
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(first['fields']['f1']['observation'], corrected['fields']['f1']['observation'])
        self.assertEqual(self.publish(correction, corrected)['fields']['f1']['observation'], corrected['fields']['f1']['observation'])
        stale = copy.deepcopy(correction)
        stale['visits'][0]['facts'][0]['revision'] = 3
        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.publish(stale, source='b' * 64)
        self.assertEqual(len(clinical.search('Observation', {})), 2)

    def test_partial_failure_and_lost_commit_reconcile(self):
        candidate = self.candidate()
        second = copy.deepcopy(candidate['visits'][0]['facts'][0])
        second.update(field_id='f2', code='c3', value='1.2', quote='C3 1.2 g/L')
        candidate['visits'][0]['facts'].append(second)
        self.client.post('/__synthetic__/fault', json={'mode': 'before_commit', 'field_id': 'f2', 'remaining': 1}).raise_for_status()
        checkpoints = []
        with self.assertRaises(RuntimeError):
            self.publish(candidate, sink=lambda progress: checkpoints.append(copy.deepcopy(progress)))
        partial = checkpoints[-1]
        self.assertEqual(partial['fields']['f1']['state'], 'archived')
        self.assertEqual(partial['fields']['f2']['state'], 'failed')
        self.assertEqual(len(clinical.search('Task', {})), 0)
        self.client.post('/__synthetic__/fault', json={'mode': 'after_commit', 'field_id': 'f2', 'remaining': 1}).raise_for_status()
        result = self.publish(candidate, partial)
        self.assertTrue(all(f['state'] == 'archived' for f in result['fields'].values()))
        self.assertEqual(len(clinical.search('Observation', {})), 2)
        self.assertEqual(len(clinical.search('Provenance', {})), 2)
        self.assertEqual(len(clinical.search('Basic', {})), 2)

    def test_followup_matches_survive_retry_and_correction_does_not_complete(self):
        first = self.publish(self.candidate(day='2026-07-01'))
        correction = self.candidate(day='2026-07-01', value='17.9')
        correction['visits'][0]['facts'][0].update(revision=2, correction_of=first['fields']['f1']['observation'])
        correction['visits'][0]['facts'][0]['review'].update(action='modify', reason='Correction')
        self.publish(correction, first)
        self.assertEqual(clinical.request('GET', '/fhir/R4/Task/' + first['task'])['status'], 'requested')
        later = self.publish(self.candidate(day='2026-10-01', field='later'))
        self.assertIn(first['task'], later['matched_followups'])
        resumed = self.publish(self.candidate(day='2026-10-01', field='later'), later)
        self.assertIn(first['task'], resumed['matched_followups'])
        self.assertEqual(len(clinical.search('Task', {})), 2)

    def test_pagination_and_untrusted_next_link(self):
        for n in range(5):
            self.publish(self.candidate(event='event-' + str(n), value=str(n + 1)))
        self.assertEqual(len(clinical.search('Observation', {'_count': '2'})), 5)
        with patch.object(clinical, 'request', return_value={'entry': [], 'link': [
                {'relation': 'next', 'url': 'https://untrusted.invalid/fhir/R4/Observation'}]}):
            with self.assertRaisesRegex(ValueError, 'pagination'):
                clinical.search('Observation', {})

    def test_demo_rejects_remote_url_without_authentication(self):
        with patch.object(clinical.http, 'BASE', 'https://untrusted.invalid'):
            with self.assertRaisesRegex(ValueError, 'loopback'):
                clinical.request('GET', '/auth/me')

    def test_conflict_and_wrong_event_correction_do_not_change_original(self):
        first = self.publish(self.candidate())
        with self.assertRaisesRegex(ValueError, 'conflicting value'):
            self.publish(self.candidate(value='99.1'))
        wrong_event = self.candidate(event='other-event', value='17.9')
        wrong_event['visits'][0]['facts'][0].update(revision=2, correction_of=first['fields']['f1']['observation'])
        with self.assertRaisesRegex(ValueError, 'patient, event and field'):
            self.publish(wrong_event)
        self.assertEqual([o['valueString'] for o in clinical.search('Observation', {})], ['18.2 g/L'])

    def test_legacy_source_discriminator_does_not_merge_distinct_documents(self):
        candidate = self.candidate()
        candidate['visits'][0].pop('event_id')
        first = self.publish(candidate)
        second = self.publish(candidate, source='b' * 64)
        self.assertNotEqual(first['visits'][0]['encounter'], second['visits'][0]['encounter'])
        self.assertEqual(len(clinical.search('Observation', {})), 2)

    def test_task_phase_failure_retains_field_and_followup_receipts(self):
        first = self.publish(self.candidate(day='2026-07-01'))
        later = self.candidate(day='2026-10-01', field='later')
        original_request = clinical.request
        checkpoints = []

        def fail_task_create(method, path, body=None, extra=None):
            if method == 'POST' and path == '/fhir/R4/Task':
                raise RuntimeError('Synthetic Task unavailable')
            return original_request(method, path, body, extra)

        with patch.object(clinical, 'request', side_effect=fail_task_create):
            with self.assertRaisesRegex(RuntimeError, 'Task unavailable'):
                self.publish(later, sink=lambda state: checkpoints.append(copy.deepcopy(state)))
        partial = checkpoints[-1]
        self.assertEqual(partial['task_phase'], 'failed')
        self.assertEqual(partial['fields']['later']['state'], 'archived')
        self.assertIn(first['task'], partial['matched_followups'])
        result = self.publish(later, partial)
        self.assertEqual(result['task_phase'], 'complete')
        self.assertIn(first['task'], result['matched_followups'])
        self.assertEqual(len(clinical.search('Provenance', {})), 2)

    def test_double_rolls_back_invalid_transaction_and_checks_task_version(self):
        response = self.client.post('/fhir/R4/', json={'resourceType': 'Bundle', 'type': 'transaction', 'entry': [
            {'resource': {'resourceType': 'Observation', 'identifier': [{'system': clinical.SYSTEM, 'value': 'rollback'}]},
             'request': {'method': 'POST', 'url': 'Observation'}},
            {'resource': {'resourceType': 'Task'}, 'request': {'method': 'DELETE', 'url': 'Task'}}]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(clinical.search('Observation', {}), [])
        receipt = self.publish(self.candidate())
        task = clinical.request('GET', '/fhir/R4/Task/' + receipt['task'])
        task['status'] = 'completed'
        response = self.client.put('/fhir/R4/Task/' + task['id'], json=task, headers={'If-Match': 'W/"stale"'})
        self.assertEqual(response.status_code, 412)
        self.assertEqual(clinical.request('GET', '/fhir/R4/Task/' + task['id'])['status'], 'requested')

    def test_same_day_deferred_event_reuses_task_and_window_conflict_precedes_writes(self):
        first = self.publish(self.candidate())
        deferred = self.candidate(event='afternoon', field='later-field', value='17.5')
        before = self.client.get('/__synthetic__/status').json()['resource_counts']
        with self.assertRaisesRegex(ValueError, 'window differs'):
            clinical.publish(deferred, 'a' * 64, 30, 'synthetic-operator')
        self.assertEqual(self.client.get('/__synthetic__/status').json()['resource_counts'], before)
        later = self.publish(deferred)
        self.assertEqual(later['task'], first['task'])
        self.assertNotEqual(later['visits'][0]['encounter'], first['visits'][0]['encounter'])
        self.assertEqual(len(clinical.search('Task', {})), 1)

    def test_retry_keeps_durable_fields_archived_during_later_lookup_failure(self):
        candidate = self.candidate()
        second = copy.deepcopy(candidate['visits'][0]['facts'][0])
        second.update(field_id='f2', code='c3', value='1.2', quote='C3 1.2 g/L')
        candidate['visits'][0]['facts'].append(second)
        self.client.post('/__synthetic__/fault', json={'mode': 'before_commit', 'field_id': 'f2', 'remaining': 1}).raise_for_status()
        checkpoints = []
        with self.assertRaises(RuntimeError):
            self.publish(candidate, sink=lambda state: checkpoints.append(copy.deepcopy(state)))
        partial = checkpoints[-1]
        completed = copy.deepcopy(partial['fields']['f1'])

        def fail_missing_field(fact, *args):
            self.assertEqual(fact['field_id'], 'f2', 'An archived field must not perform another lookup')
            raise RuntimeError('Synthetic receipt lookup unavailable')

        with patch.object(clinical, '_field_archive', side_effect=fail_missing_field) as archive:
            with self.assertRaisesRegex(RuntimeError, 'lookup unavailable'):
                self.publish(candidate, partial, lambda state: checkpoints.append(copy.deepcopy(state)))
        self.assertEqual(archive.call_count, 1)
        self.assertEqual(checkpoints[-1]['fields']['f1'], completed)
        self.assertEqual(checkpoints[-1]['fields']['f2']['state'], 'failed')

    def test_direct_completion_is_closed_and_queue_exposes_only_visit_evidence(self):
        first = self.publish(self.candidate(day='2026-07-01'))
        task = clinical.request('GET', '/fhir/R4/Task/' + first['task'])
        with self.assertRaisesRegex(ValueError, 'manual completion is disabled'):
            clinical.complete_task(task['id'], task['meta']['versionId'])
        current = clinical.request('GET', '/fhir/R4/Task/' + task['id'])
        self.assertEqual(current['status'], 'requested')
        self.assertNotIn('output', current)
        queued = next(item for item in clinical.tasks() if item['id'] == task['id'])
        self.assertEqual(queued['completion_mode'], 'reviewed-visit-only')
        self.assertEqual(queued['evidence'], [])
        later = self.publish(self.candidate(day='2026-10-01', field='later'))
        completed = next(item for item in clinical.tasks() if item['id'] == task['id'])
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['evidence'], ['Encounter/' + later['visits'][0]['encounter']])


if __name__ == '__main__':
    unittest.main()
