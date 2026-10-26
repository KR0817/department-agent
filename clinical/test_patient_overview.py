"""Synthetic cohort arithmetic and evidence integrity, without running services."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from patient_overview import FIXTURE, build_overview, load_demo_overview


class PatientOverviewTests(unittest.TestCase):
    def setUp(self):
        self.legacy_fixture = FIXTURE.with_name('patient-overview-clinical-demo.json')
        self.source = json.loads(self.legacy_fixture.read_text(encoding='utf-8'))

    def test_clinical_extension_preserves_v7_source_and_demonstrates_unknowns(self):
        old = json.loads(FIXTURE.with_name('patient-overview-detail-demo.json').read_text(encoding='utf-8'))
        for key in old:
            if key != 'patients':
                self.assertEqual(self.source[key], old[key])
        for before, after in zip(old['patients'], self.source['patients']):
            self.assertEqual({key: after[key] for key in before}, before)
        result = build_overview(self.source)
        self.assertEqual(result['clinical_context_version'], 1)
        self.assertEqual(len(result['patients'][0]['clinical_context']), 5)
        self.assertEqual(result['patients'][2]['clinical_context']['infection_status'], [])
        self.assertEqual(result['patients'][3]['clinical_context']['baseline_exams'], [])

    def test_clinical_context_is_bound_to_own_visit_and_exact_quote(self):
        for key, invalid in [('visit_id', 'SIM-VISIT-002-B'), ('date', '2099-01-01'),
                             ('code', 'diagnosis'), ('current', 'true'), ('unit', 'mg'),
                             ('value', 'Unmarked clinical assertion'), ('quote', '\u5408\u6210 unrelated quote')]:
            with self.subTest(key=key):
                source = deepcopy(self.source)
                source['patients'][0]['clinical_context']['medications'][0][key] = invalid
                with self.assertRaises(ValueError):
                    build_overview(source)

    def test_clinical_context_schema_and_size_are_bounded(self):
        for invalid in (True, 1.0, '1', 2):
            source = deepcopy(self.source)
            source['clinical_context_version'] = invalid
            with self.assertRaises(ValueError):
                build_overview(source)
        for invalid in (None, {}, {'medications': []}):
            source = deepcopy(self.source)
            source['patients'][0]['clinical_context'] = invalid
            with self.assertRaises(ValueError):
                build_overview(source)
        for invalid in (None, {}, [None], self.source['patients'][0]['clinical_context']['medications'] * 21):
            source = deepcopy(self.source)
            source['patients'][0]['clinical_context']['medications'] = invalid
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_clinical_context_is_a_copy_with_fixed_provenance(self):
        before = deepcopy(self.source)
        row = self.source['patients'][0]['clinical_context']['medications'][0]
        row['verification'] = 'reviewed_archive'
        row['source_job'] = 'untrusted-job'
        result = build_overview(self.source)
        returned = result['patients'][0]['clinical_context']['medications'][0]
        self.assertEqual(returned['verification'], 'synthetic_demo')
        self.assertIsNone(returned['source_job'])
        self.assertEqual(returned['source_label'], self.source['patients'][0]['visits'][0]['source_label'])
        returned['value'] = 'Changed only in returned DTO'
        self.assertEqual(row['value'], before['patients'][0]['clinical_context']['medications'][0]['value'])

    def test_old_detail_fixture_remains_supported_without_context_backfill(self):
        old = json.loads(FIXTURE.with_name('patient-overview-detail-demo.json').read_text(encoding='utf-8'))
        result = build_overview(old)
        self.assertNotIn('clinical_context_version', result)
        self.assertNotIn('clinical_context', result['patients'][0])
        self.assertEqual(result['summary']['completed'], 10)

    def test_requested_counts_are_derived_and_source_is_immutable(self):
        before = deepcopy(self.source)
        result = build_overview(self.source)
        self.assertEqual(result['summary'], {'enrolled': 20, 'completed': 10, 'pending': 10,
            'completion_percent': 50, 'overdue': 3, 'in_window': 4, 'upcoming': 3, 'visits': 30})
        self.assertTrue(result['synthetic'])
        self.assertFalse(result['delivery_enabled'])
        self.assertEqual(self.source, before)
        with patch('patient_overview.FIXTURE', self.legacy_fixture):
            self.assertEqual(load_demo_overview(), result)

    def test_completed_people_still_have_a_later_next_due_date(self):
        patients = build_overview(self.source)['patients']
        complete = [p for p in patients if p['first_followup']['status'] == 'completed']
        self.assertEqual(len(complete), 10)
        for patient in complete:
            followup = patient['first_followup']
            self.assertIn(followup['evidence_visit_id'], [v['id'] for v in patient['visits']])
            self.assertGreater(patient['next_due_date'], followup['completed_at'])

    def test_removing_a_linked_followup_changes_the_derived_totals(self):
        person = self.source['patients'][0]
        person['visits'] = person['visits'][:1]
        person['first_followup']['evidence_visit_id'] = None
        totals = build_overview(self.source)['summary']
        self.assertEqual((totals['completed'], totals['pending'], totals['visits']), (9, 11, 29))

    def test_missing_or_cross_patient_completion_evidence_is_rejected(self):
        for evidence in ('SIM-VISIT-002-F1', 'SIM-VISIT-001-MISSING'):
            with self.subTest(evidence=evidence):
                candidate = deepcopy(self.source)
                candidate['patients'][0]['first_followup']['evidence_visit_id'] = evidence
                with self.assertRaises(ValueError):
                    build_overview(candidate)
        self.source['patients'][0]['first_followup']['evidence_visit_id'] = None
        with self.assertRaises(ValueError):
            build_overview(self.source)

    def test_completion_window_boundaries_are_inclusive(self):
        for day in ('2026-09-15', '2026-10-13'):
            with self.subTest(day=day):
                self.source['patients'][0]['visits'][1]['date'] = day
                self.assertEqual(build_overview(self.source)['summary']['completed'], 10)
        for day in ('2026-09-14', '2026-10-14', '2026-10-24', '2026-06-30'):
            with self.subTest(day=day):
                self.source['patients'][0]['visits'][1]['date'] = day
                with self.assertRaises(ValueError):
                    build_overview(self.source)

    def test_pending_windows_use_the_frozen_as_of_date(self):
        person = self.source['patients'][13]
        self.assertEqual(person['first_followup']['due_date'], '2026-10-19')
        for day, expected in [('2026-10-05', 'in_window'), ('2026-11-02', 'in_window'),
                              ('2026-11-03', 'overdue')]:
            candidate = deepcopy(self.source)
            candidate['as_of'] = day
            if day == '2026-10-05':
                for p in candidate['patients'][:10]:
                    p['visits'] = p['visits'][:1]
                    p['first_followup']['evidence_visit_id'] = None
            result = build_overview(candidate)
            self.assertEqual(result['patients'][13]['first_followup']['status'], expected)

    def test_duplicate_identifiers_and_unmarked_records_are_rejected(self):
        changes = [lambda s: s.update(synthetic=False), lambda s: s['patients'].pop(),
            lambda s: s['patients'][1].update(id=s['patients'][0]['id']),
            lambda s: s['patients'][0].update(name='Unmarked person'),
            lambda s: s['patients'][0]['visits'][0].update(id='SIM-VISIT-002-B')]
        for change in changes:
            candidate = deepcopy(self.source)
            change(candidate)
            with self.assertRaises(ValueError):
                build_overview(candidate)

    def test_detail_schema_and_fixed_metric_definitions(self):
        result = build_overview(self.source)
        self.assertEqual(result['detail_schema_version'], 1)
        self.assertEqual(result['metric_definitions'], [
            {'code': 'dryness', 'label': '\u53e3\u5e72\u8bc4\u5206', 'group': 'symptoms', 'unit': '\u5206', 'precision': 1},
            {'code': 'fatigue', 'label': '\u75b2\u52b3\u8bc4\u5206', 'group': 'symptoms', 'unit': '\u5206', 'precision': 1},
            {'code': 'pain', 'label': '\u75bc\u75db\u8bc4\u5206', 'group': 'symptoms', 'unit': '\u5206', 'precision': 1},
            {'code': 'igg', 'label': '\u514d\u75ab\u7403\u86cb\u767dG\uff08IgG\uff09', 'group': 'measurements', 'unit': 'g/L', 'precision': 2},
            {'code': 'c3', 'label': '\u8865\u4f53C3', 'group': 'measurements', 'unit': 'g/L', 'precision': 2},
            {'code': 'c4', 'label': '\u8865\u4f53C4', 'group': 'measurements', 'unit': 'g/L', 'precision': 2},
        ])
        for invalid in (None, True, False, 1.0, '1', 2):
            with self.subTest(version=invalid):
                self.source['detail_schema_version'] = invalid
                with self.assertRaises(ValueError):
                    build_overview(self.source)

    def test_detail_extension_preserves_all_v6_workflow_records(self):
        old = json.loads(FIXTURE.with_name('patient-overview-demo.json').read_text(encoding='utf-8'))
        for key in ('synthetic', 'cohort_id', 'as_of'):
            self.assertEqual(self.source[key], old[key])
        self.assertEqual(len(self.source['patients']), len(old['patients']))
        for original, extended in zip(old['patients'], self.source['patients']):
            self.assertEqual({key: extended[key] for key in original if key != 'visits'},
                             {key: value for key, value in original.items() if key != 'visits'})
            self.assertEqual(len(extended['visits']), len(original['visits']))
            for old_visit, new_visit in zip(original['visits'], extended['visits']):
                self.assertEqual({key: new_visit[key] for key in old_visit}, old_visit)

    def test_fixture_contains_opposite_flat_missing_and_single_point_examples(self):
        result = build_overview(self.source)
        first = result['patients'][0]['visits']
        self.assertEqual([visit['symptoms']['dryness'] for visit in first], [6, 4])
        self.assertEqual([visit['symptoms']['fatigue'] for visit in first], [5, 5])
        self.assertEqual([visit['symptoms']['pain'] for visit in first], [4, 6])
        self.assertIsNone(result['patients'][1]['visits'][1]['measurements']['c3'])
        self.assertEqual([visit['measurements']['c4'] for visit in result['patients'][2]['visits']], [None, None])
        self.assertIsNone(result['patients'][3]['visits'][0]['symptoms']['pain'])
        self.assertTrue(all(len(person['visits']) == 1 for person in result['patients'][10:]))
        self.assertEqual(result['summary']['completed'], 10)

    def test_metric_null_and_zero_are_preserved_without_changing_followup_evidence(self):
        for group, key in [('symptoms', 'pain'), ('measurements', 'c3')]:
            for value in (None, 0, 0.0):
                with self.subTest(group=group, value=value):
                    source = deepcopy(self.source)
                    source['patients'][0]['visits'][1][group][key] = value
                    result = build_overview(source)
                    self.assertEqual(result['patients'][0]['visits'][1][group][key], value)
                    self.assertEqual(result['patients'][0]['first_followup']['status'], 'completed')
                    self.assertEqual(result['summary']['completed'], 10)

    def test_invalid_metric_values_fail_without_coercion_or_clipping(self):
        for group, key, upper in [('symptoms', 'pain', 10), ('measurements', 'igg', 1000)]:
            for value in (True, False, '3', float('nan'), float('inf'), -float('inf'),
                          -0.001, upper + 0.001, 10 ** 1000, [], {}):
                with self.subTest(group=group, value=value):
                    source = deepcopy(self.source)
                    source['patients'][0]['visits'][0][group][key] = value
                    with self.assertRaises(ValueError):
                        build_overview(source)
            source = deepcopy(self.source)
            source['patients'][0]['visits'][0][group][key] = upper
            self.assertEqual(build_overview(source)['patients'][0]['visits'][0][group][key], upper)

    def test_unknown_missing_or_non_dictionary_metric_groups_are_rejected(self):
        for group in ('symptoms', 'measurements'):
            for value in (None, [], 'unknown'):
                source = deepcopy(self.source)
                source['patients'][0]['visits'][0][group] = value
                with self.assertRaises(ValueError):
                    build_overview(source)
            for mutation in ('extra', 'missing'):
                source = deepcopy(self.source)
                metrics = source['patients'][0]['visits'][0][group]
                if mutation == 'extra':
                    metrics['unknown_code'] = 1
                else:
                    metrics.pop(next(iter(metrics)))
                with self.assertRaises(ValueError):
                    build_overview(source)

    def test_profile_age_and_sex_boundaries(self):
        for age in (None, 0, 130):
            source = deepcopy(self.source)
            source['patients'][0]['profile']['age_at_enrollment'] = age
            self.assertEqual(build_overview(source)['patients'][0]['profile']['age_at_enrollment'], age)
        for age in (True, False, 48.0, '48', -1, 131):
            source = deepcopy(self.source)
            source['patients'][0]['profile']['age_at_enrollment'] = age
            with self.assertRaises(ValueError):
                build_overview(source)
        for sex in ('female', 'male', 'unknown'):
            source = deepcopy(self.source)
            source['patients'][0]['profile']['sex'] = sex
            self.assertEqual(build_overview(source)['patients'][0]['profile']['sex'], sex)
        for sex in (None, True, 'Female', '', 'unrecorded'):
            source = deepcopy(self.source)
            source['patients'][0]['profile']['sex'] = sex
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_profile_and_condition_descriptions_require_bounded_synthetic_labels(self):
        for value in (None, [], 'unknown'):
            source = deepcopy(self.source)
            source['patients'][0]['profile'] = value
            with self.assertRaises(ValueError):
                build_overview(source)
        for key, maximum in (('condition_label', 120), ('condition_note', 500)):
            for value in (None, '', 'Unmarked example', '\u5408\u6210' + 'x' * (maximum - 1), 123):
                source = deepcopy(self.source)
                target = source['patients'][0]['profile'] if key == 'condition_label' else source['patients'][0]['visits'][0]
                target[key] = value
                with self.assertRaises(ValueError):
                    build_overview(source)
            source = deepcopy(self.source)
            target = source['patients'][0]['profile'] if key == 'condition_label' else source['patients'][0]['visits'][0]
            target[key] = '\u5408\u6210' + 'x' * (maximum - 2)
            build_overview(source)

    def test_free_fields_are_not_forwarded_and_source_cannot_override_metadata(self):
        self.source['outside_schema'] = 'Synthetic private fixture metadata'
        self.source['metric_definitions'] = [{'code': 'pain', 'unit': 'wrong-unit'}]
        patient = self.source['patients'][0]
        patient['outside_schema'] = 'Synthetic extra patient field'
        patient['profile']['outside_schema'] = 'Synthetic extra profile field'
        patient['visits'][0]['outside_schema'] = 'Synthetic extra visit field'
        patient['first_followup']['status'] = 'forged-status'
        result = build_overview(self.source)
        self.assertNotIn('outside_schema', json.dumps(result))
        self.assertNotIn('wrong-unit', json.dumps(result))
        self.assertNotIn('forged-status', json.dumps(result))
        self.assertEqual(set(result['patients'][0]['profile']), {'sex', 'age_at_enrollment', 'condition_label'})
        self.assertEqual(set(result['patients'][0]['visits'][0]),
            {'id', 'date', 'kind', 'source_label', 'condition_note', 'symptoms', 'measurements'})

    def test_returned_nested_values_cannot_mutate_source_or_fixed_metadata(self):
        before = deepcopy(self.source)
        result = build_overview(self.source)
        result['patients'][0]['profile']['age_at_enrollment'] = 99
        result['patients'][0]['visits'][0]['symptoms']['pain'] = 9
        result['patients'][0]['visits'][0]['measurements']['igg'] = 99
        result['metric_definitions'][0]['unit'] = 'incorrect'
        self.assertEqual(self.source, before)
        self.assertEqual(build_overview(self.source)['metric_definitions'][0]['unit'], '\u5206')

    def test_visit_collection_size_and_type_are_bounded(self):
        for visits in (None, {}, [], self.source['patients'][0]['visits'] * 2):
            source = deepcopy(self.source)
            source['patients'][0]['visits'] = visits
            with self.assertRaises(ValueError):
                build_overview(source)


if __name__ == '__main__':
    unittest.main()
