"""Review lifecycle, provenance, dates and form boundaries on synthetic in-memory data."""
import copy
import json
import sqlite3
import unittest
from collections import Counter

import care
import care_demo
from patient_overview import load_demo_overview


def event(category='infection'):
    return {'category': category, 'date': '2026-10-10', 'end_date': None, 'title': 'Synthetic event',
            'details': '', 'source_type': 'unknown', 'drug_name': 'Synthetic drug' if category == 'medication' else '',
            'dose': '', 'frequency': '', 'route': '', 'status': 'unknown', 'site': '',
            'merged_into': None, 'note': 'Synthetic reviewed record', 'evidence_refs': []}


def form():
    return {'template_version': care.FORM_VERSION, 'visit_date': '2026-10-10',
            'responses': {key: {'value': None, 'missing_reason': 'Not recorded'} for key in ('dryness', 'fatigue', 'pain')},
            'medications': 'Unknown', 'infection_status': 'Unknown', 'comorbidities': 'Unknown',
            'note': 'Synthetic form', 'evidence_refs': []}


class CareTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        care.initialize(self.con)
        self.addCleanup(self.con.close)
        self.patient = load_demo_overview()['patients'][0]
        self.context = {'attention': self.patient['attention'], 'as_of': '2026-10-24',
                        'evidence_refs': ['visit:' + v['id'] for v in self.patient['visits']]}
        self.key = care.signal_key(self.context['attention'], self.context['attention']['items'][0])

    def action(self, state='acknowledged'):
        return {'state': state, 'owner': 'Synthetic reviewer', 'due_date': None, 'note': 'Synthetic review',
                'disposition': 'already_managed' if state == 'reviewed' else '',
                'evidence_note': 'Synthetic disposition evidence' if state == 'reviewed' else '',
                'evidence_refs': self.context['evidence_refs'][:1]}

    def save(self, kind, key, body, revision=0, patient='SIM-A'):
        with self.con:
            return care.save(self.con, patient, kind, key, {'expected_revision': revision, 'data': body},
                             'server-actor', self.context)

    def test_acknowledge_preserves_red_and_complete_preserves_source_history(self):
        self.save('attention', self.key, self.action())
        decorated = care.decorate(self.context['attention'], care.records(self.con, 'SIM-A'))
        self.assertEqual(decorated['level'], 'red')
        self.assertEqual(decorated['open_level'], 'red')
        self.save('attention', self.key, self.action('reviewed'), 1)
        decorated = care.decorate(self.context['attention'], care.records(self.con, 'SIM-A'))
        self.assertEqual(decorated['level'], 'red')
        self.assertEqual(decorated['reviewed_count'], 1)
        self.assertEqual(len(care.records(self.con, 'SIM-A')), 2)
        self.assertEqual(care.records(self.con, 'SIM-A')[-1]['actor'], 'server-actor')

    def test_reopen_append_only_and_stale_rejected(self):
        self.save('attention', self.key, self.action('reviewed'))
        with self.assertRaises(care.CareError) as error:
            self.save('attention', self.key, self.action(), 0)
        self.assertEqual(error.exception.status, 409)
        self.save('attention', self.key, self.action('unreviewed'), 1)
        self.assertEqual(len(care.records(self.con, 'SIM-A')), 2)

    def test_followup_disposition_stays_open_and_revision_beats_wall_clock(self):
        value = {**self.action('reviewed'), 'disposition': 'needs_followup', 'due_date': '2026-11-01'}
        with self.assertRaises(care.CareError):
            self.save('attention', self.key, value)
        self.save('attention', self.key, {**value, 'state': 'in_progress'})
        history = care.records(self.con, 'SIM-A')
        self.assertEqual(care.decorate(self.context['attention'], history)['open_level'], 'red')
        old = {**history[0], 'revision': 0, 'recorded_at': '2099-01-01'}
        self.assertEqual(care.latest(history + [old], 'attention', self.key)['revision'], 1)

    def test_patient_scope_and_source_version_separate(self):
        self.save('attention', self.key, self.action('reviewed'))
        self.assertEqual(care.records(self.con, 'SIM-B'), [])
        self.save('attention', self.key, self.action(), patient='SIM-B')
        changed = copy.deepcopy(self.context['attention'])
        changed['items'][0]['evidence'][0]['observation'] = 'corrected-version'
        self.assertNotEqual(care.signal_key(changed, changed['items'][0]), self.key)
        self.assertEqual(care.decorate(changed, care.records(self.con, 'SIM-A'))['reviewed_count'], 0)

    def test_closure_requires_evidence_and_foreign_reference_rejected(self):
        for patch in ({'evidence_note': ''}, {'disposition': ''}, {'evidence_refs': ['visit:OTHER']}, {'state': 'cleared'}):
            with self.subTest(patch=patch), self.assertRaises(care.CareError):
                self.save('attention', self.key, {**self.action('reviewed'), **patch})
        self.assertEqual(care.records(self.con, 'SIM-A'), [])

    def test_schema_revision_and_identifier_validation(self):
        for payload in ({'expected_revision': True, 'data': self.action()},
                        {'expected_revision': 0, 'data': self.action(), 'actor': 'forged'}):
            with self.assertRaises(care.CareError):
                care.save(self.con, 'SIM-A', 'attention', self.key, payload, 'server', self.context)
        with self.assertRaises(care.CareError):
            self.save('attention', 'missing', self.action())

    def test_event_unknown_stop_date_and_revisions(self):
        self.save('event', 'MED1', event('medication'))
        changed = {**event('medication'), 'dose': '10 mg', 'note': 'Source correction'}
        self.save('event', 'MED1', changed, 1)
        history = care.records(self.con, 'SIM-A')
        self.assertIsNone(history[-1]['body']['end_date'])
        self.assertEqual(history[0]['body']['dose'], '')
        self.assertEqual(len(care.timeline([], history)), 1)

    def test_infection_merge_preserves_original_and_rejects_cycles_or_foreign_patient(self):
        self.save('event', 'I1', event())
        self.save('event', 'I2', {**event(), 'merged_into': 'I1'})
        with self.assertRaises(care.CareError):
            self.save('event', 'I1', {**event(), 'merged_into': 'I2'}, 1)
        with self.assertRaises(care.CareError):
            self.save('event', 'I3', {**event(), 'merged_into': 'I1'}, patient='SIM-B')
        self.assertEqual(len(care.records(self.con, 'SIM-A')), 2)

    def test_event_future_reversed_and_empty_drug_fail(self):
        for changes in ({'date': '2027-01-01'}, {'end_date': '2026-09-01'}, {'drug_name': ''}):
            with self.subTest(changes=changes), self.assertRaises(care.CareError):
                self.save('event', 'M1', {**event('medication'), **changes})

    def test_form_zero_missing_and_version_immutable(self):
        value = form()
        value['responses']['pain'] = {'value': 0, 'missing_reason': ''}
        self.save('form', 'F1', value)
        saved = care.records(self.con, 'SIM-A')[0]
        self.assertEqual(saved['body']['responses']['pain']['value'], 0)
        self.assertIsNone(saved['body']['responses']['dryness']['value'])
        self.assertNotIn('score', saved['body'])
        value['template_version'] = 'unverified'
        with self.assertRaises(care.CareError):
            self.save('form', 'F1', value, 1)

    def test_form_invalid_values_and_missing_reasons_fail(self):
        for response in ({'value': None, 'missing_reason': ''}, {'value': 11, 'missing_reason': ''},
                         {'value': True, 'missing_reason': ''}, {'value': float('nan'), 'missing_reason': ''},
                         {'value': 3, 'missing_reason': 'contradiction'}):
            value = form()
            value['responses']['pain'] = response
            with self.subTest(response=response), self.assertRaises(care.CareError):
                self.save('form', 'F1', value)

    def test_plan_window_boundaries_and_completion_evidence(self):
        plan = {'id': 'P1', 'window_start': '2026-10-10', 'window_end': '2026-10-24'}
        for when, expected in [('2026-10-09', 'upcoming'), ('2026-10-10', 'in_window'),
                               ('2026-10-24', 'in_window'), ('2026-10-25', 'overdue')]:
            self.assertEqual(care.plan_status(plan, when), expected)
        self.assertEqual(care.plan_status({**plan, 'completed': True}, '2026-10-25'), 'overdue')
        self.assertEqual(care.plan_status({**plan, 'completed': True, 'evidence': ['Encounter/sim']}, '2026-10-25'), 'completed')
        self.assertEqual(care.plan_status({**plan, 'sync_error': 'offline'}, '2026-10-25'), 'unknown')

    def test_old_completion_does_not_hide_new_overdue(self):
        result = care.summarize_plans([
            {'id': 'old', 'due_date': '2022-01-01', 'completed': True, 'evidence': ['visit:old']},
            {'id': 'new', 'due_date': '2026-09-01', 'window_start': '2026-08-18', 'window_end': '2026-09-15'}], '2026-10-24')
        self.assertEqual(result['status'], 'overdue')
        self.assertEqual(result['selected']['id'], 'new')
        self.assertEqual(care.summarize_plans([], '2026-10-24')['status'], 'unknown')

    def test_business_authority_must_match_patient_and_completion_mode(self):
        row = {'id': 'queue', 'patient_id': 'SIM-A', 'task_id': 'task', 'due_date': '2026-09-01',
               'window_start': '2026-08-18', 'window_end': '2026-09-15', 'status': 'pending_send'}
        task = {'id': 'task', 'patient': 'Patient/fhir-a', 'status': 'completed',
                'completion_mode': 'reviewed-visit-only', 'evidence': ['Encounter/sim']}
        self.assertEqual(care.business_plans('SIM-A', [row], [task], '2026-10-24', 'fhir-a')['status'], 'completed')
        self.assertEqual(care.business_plans('SIM-A', [row], [task], '2026-10-24', 'other')['status'], 'unknown')
        task['completion_mode'] = 'legacy-unverified'
        self.assertEqual(care.business_plans('SIM-A', [row], [task], '2026-10-24', 'fhir-a')['status'], 'overdue')

    def test_frozen_scenarios_are_repeatable_and_keep_fifty_patient_identity(self):
        overview = load_demo_overview()
        before = json.dumps(overview, sort_keys=True)
        results = [care_demo.scenarios(p, overview['as_of']) for p in overview['patients']]
        self.assertEqual(Counter(r[0]['status'] for r in results),
                         {'completed': 16, 'overdue': 10, 'in_window': 10, 'upcoming': 10, 'cancelled': 2, 'unknown': 2})
        self.assertEqual(results, [care_demo.scenarios(p, overview['as_of']) for p in overview['patients']])
        self.assertEqual(json.dumps(overview, sort_keys=True), before)


if __name__ == '__main__':
    unittest.main()
