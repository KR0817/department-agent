"""Five-year synthetic cohort integrity and compatibility, with no business stores."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import runpy
import unittest

from patient_attention import evaluate_attention
from patient_overview import COHORT, CONTEXT_CODES, FIXTURE, _attention_visits, build_overview, load_demo_overview

GENERATOR = Path(__file__).resolve().with_name('build_cohort.py')
BUILD_SOURCE = runpy.run_path(str(GENERATOR))['build_source']
DATES = ['2021-10-24', '2022-01-22', '2022-10-24', '2023-10-24', '2024-10-24', '2025-10-24', '2026-10-24']
COLORS = {'red': 6, 'orange': 8, 'yellow': 10, 'gray': 26}


class FiveYearPatientOverviewTests(unittest.TestCase):
    def setUp(self):
        self.source = BUILD_SOURCE()

    def test_complete_frozen_five_year_cohort_and_due_dates(self):
        result = build_overview(self.source)
        self.assertEqual(result['summary'], {'enrolled': 50, 'completed': 50, 'pending': 0,
            'completion_percent': 100, 'overdue': 0, 'in_window': 0, 'upcoming': 0,
            'visits': 350, 'attention_counts': COLORS})
        self.assertEqual(result['observation_period'], {'start': DATES[0], 'end': DATES[-1], 'years': 5})
        self.assertEqual(result['detail_schema_version'], 2)
        self.assertEqual(result['cohort_id'], 'sjd-overview-demo-50-5y-v1')
        self.assertEqual(result['clinical_context_version'], 1)
        self.assertEqual([row['id'] for row in result['patients']], [f'SIM-OV50-{i:03d}' for i in range(1, 51)])
        for person in result['patients']:
            self.assertEqual([visit['date'] for visit in person['visits']], DATES)
            self.assertEqual([visit['kind'] for visit in person['visits']],
                             ['baseline', 'first_followup'] + ['annual_followup'] * 5)
            self.assertEqual(person['visit_count'], 7)
            self.assertEqual(person['first_followup']['completed_at'], DATES[1])
            self.assertEqual(person['first_followup']['status'], 'completed')
            self.assertEqual(person['next_due_date'], (date.fromisoformat(DATES[-1]) + timedelta(days=90)).isoformat())
            self.assertEqual(person['next_due_date'], '2027-01-22')

    def test_default_fixture_and_generator_are_reproducible_without_source_mutation(self):
        before = deepcopy(self.source)
        self.assertEqual(BUILD_SOURCE(), before)
        self.assertEqual(FIXTURE.name, 'patient-overview-five-year-demo.json')
        self.assertEqual(json.loads(FIXTURE.read_text(encoding='utf-8')), before)
        self.assertEqual(load_demo_overview(), build_overview(before))
        self.assertEqual(self.source, before)
        self.assertEqual(COHORT, 'sjd-overview-demo-20-v1')

    def test_all_categories_and_six_metrics_preserve_missing_and_zero_examples(self):
        result = build_overview(self.source)
        self.assertEqual(len(result['metric_definitions']), 6)
        for person in result['patients']:
            self.assertEqual(set(person['clinical_context']), set(CONTEXT_CODES))
            for code, rows in person['clinical_context'].items():
                self.assertEqual(len(rows), 7)
                self.assertEqual([row['date'] for row in rows], DATES)
                self.assertTrue(all(row['code'] == code and row['verification'] == 'synthetic_demo' for row in rows))
            for visit in person['visits']:
                self.assertEqual(set(visit['symptoms']), {'dryness', 'fatigue', 'pain'})
                self.assertEqual(set(visit['measurements']), {'igg', 'c3', 'c4'})
        people = result['patients']
        self.assertIsNone(people[24]['visits'][3]['measurements']['c3'])
        self.assertTrue(all(visit['measurements']['c4'] is None for visit in people[25]['visits']))
        self.assertIsNone(people[26]['visits'][-1]['symptoms']['pain'])
        self.assertIsNone(people[27]['visits'][-2]['measurements']['igg'])
        self.assertIsNone(people[28]['visits'][0]['symptoms']['dryness'])
        self.assertIsNone(people[29]['visits'][-1]['symptoms']['fatigue'])
        self.assertTrue(all(visit['symptoms']['pain'] == 0 for visit in people[31]['visits']))

    def test_colors_are_computed_by_unchanged_shared_engine_and_evidence(self):
        result = build_overview(self.source)
        self.assertEqual(dict(Counter(person['attention']['level'] for person in result['patients'])), COLORS)
        for person in result['patients']:
            attention = person['attention']
            self.assertEqual(attention, {**evaluate_attention(_attention_visits(person), result['as_of']),
                                         'source': 'synthetic_demo'})
            for item in attention['items']:
                for evidence in item['evidence']:
                    self.assertIn(evidence['event_id'], [visit['id'] for visit in person['visits']])
                    self.assertIn(evidence['date'], DATES)
                    self.assertIsNone(evidence['source_job'])
        for index, person in enumerate(result['patients'], 1):
            kinds = {item['kind'] for item in person['attention']['items']}
            expected = ('critical_report' if index <= 6 else 'igg_rising' if index <= 10
                        else 'infection_frequency' if index <= 14 else 'score_change' if index <= 19
                        else 'medication_change' if index <= 24 else None)
            self.assertEqual(kinds, {expected} if expected else set())
        historical = result['patients'][3]['attention']['items'][0]
        self.assertEqual(historical['evidence'][0]['date'], '2024-10-24')
        self.assertNotIn('\u5371\u6025', result['patients'][3]['clinical_context']['inpatient_exams'][-1]['value'])
        self.assertIn('\u5904\u7406\u72b6\u6001\u672a\u77e5', historical['summary'])

    def test_colors_are_not_trusted_from_input_metadata(self):
        self.source['summary'] = {'attention_counts': {'red': 50}}
        self.source['patients'][0]['attention'] = {'level': 'gray'}
        result = build_overview(self.source)
        self.assertEqual(result['summary']['attention_counts'], COLORS)
        person = self.source['patients'][0]
        row = person['clinical_context']['inpatient_exams'][-1]
        row['value'] = row['quote'] = '\u5408\u6210\u68c0\u67e5\u62a5\u544a\uff1a\u62a5\u544a\u5df2\u5f52\u6863\u3002'
        result = build_overview(self.source)
        self.assertEqual(result['patients'][0]['attention']['level'], 'gray')
        self.assertEqual(result['summary']['attention_counts'], {'red': 5, 'orange': 8, 'yellow': 10, 'gray': 27})

    def test_illegal_patient_count_identifiers_and_schema_pairing_fail(self):
        changes = [lambda s: s['patients'].pop(), lambda s: s['patients'].append(deepcopy(s['patients'][0])),
            lambda s: s['patients'][0].update(id='SIM-OV50-051'),
            lambda s: s['patients'][0].update(id='SIM-OV20-001'),
            lambda s: s['patients'][1].update(id='SIM-OV50-001'),
            lambda s: s.update(cohort_id=COHORT), lambda s: s.update(detail_schema_version=1),
            lambda s: s.update(detail_schema_version=True), lambda s: s.update(detail_schema_version=2.0),
            lambda s: s.update(synthetic=False), lambda s: s.pop('clinical_context_version')]
        for change in changes:
            source = deepcopy(self.source)
            change(source)
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_observation_period_and_frozen_date_cannot_be_shortened_or_extended(self):
        for invalid in (None, {}, {'start': '2022-10-24', 'end': DATES[-1], 'years': 4},
                        {'start': DATES[0], 'end': DATES[-1], 'years': '5'},
                        {'start': DATES[0], 'end': DATES[-1], 'years': 5.0}):
            source = deepcopy(self.source)
            source['observation_period'] = invalid
            with self.assertRaises(ValueError):
                build_overview(source)
        for invalid in ('2026-10-23', '2026-10-25'):
            source = deepcopy(self.source)
            source['as_of'] = invalid
            with self.assertRaises(ValueError):
                build_overview(source)
        self.source['patients'][0]['enrolled_at'] = '2021-10-25'
        with self.assertRaises(ValueError):
            build_overview(self.source)

    def test_missing_annual_duplicate_date_id_and_cross_patient_visit_fail(self):
        changes = [lambda p: p['visits'].pop(4),
            lambda p: p['visits'][-1].update(date='2025-10-24'),
            lambda p: p['visits'][-1].update(date='2026-10-25'),
            lambda p: p['visits'][-1].update(date='2026-10-23'),
            lambda p: p['visits'][-1].update(id=p['visits'][-2]['id']),
            lambda p: p['visits'][-1].update(id='SIM-VISIT50-002-Y5'),
            lambda p: p['visits'][-1].update(kind='first_followup'),
            lambda p: p['visits'][1].update(date='2022-01-23'),
            lambda p: p['first_followup'].update(evidence_visit_id=None),
            lambda p: p['first_followup'].update(evidence_visit_id='SIM-VISIT50-002-F1')]
        for change in changes:
            source = deepcopy(self.source)
            change(source['patients'][0])
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_context_requires_all_categories_and_own_unique_visit_evidence(self):
        changes = [lambda p: p['clinical_context'].pop('infection_status'),
            lambda p: p['clinical_context'].update(infection_status=[]),
            lambda p: p['clinical_context']['medications'][0].update(visit_id='SIM-VISIT50-002-B'),
            lambda p: p['clinical_context']['medications'][0].update(date='2025-10-24'),
            lambda p: p['clinical_context']['medications'].append(deepcopy(p['clinical_context']['medications'][0]))]
        for change in changes:
            source = deepcopy(self.source)
            change(source['patients'][0])
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_invalid_numbers_cannot_be_coerced_to_display_values(self):
        for group, code, value in [('measurements', 'igg', float('nan')), ('measurements', 'igg', float('inf')),
                                  ('measurements', 'igg', True), ('measurements', 'igg', '15'),
                                  ('measurements', 'igg', -1), ('measurements', 'igg', 1001),
                                  ('symptoms', 'dryness', 11), ('symptoms', 'pain', -1)]:
            source = deepcopy(self.source)
            source['patients'][0]['visits'][-1][group][code] = value
            with self.assertRaises(ValueError):
                build_overview(source)

    def test_visit_and_patient_order_do_not_change_derived_sorted_results(self):
        expected = build_overview(self.source)
        source = deepcopy(self.source)
        source['patients'].reverse()
        for person in source['patients']:
            person['visits'].reverse()
        self.assertEqual(build_overview(source), expected)

    def test_legacy_detail_and_clinical_fixtures_remain_readable_and_unchanged(self):
        for filename in ('patient-overview-detail-demo.json', 'patient-overview-clinical-demo.json'):
            path = FIXTURE.with_name(filename)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            source = json.loads(path.read_text(encoding='utf-8'))
            result = build_overview(source)
            self.assertEqual(result['cohort_id'], COHORT)
            self.assertEqual(result['detail_schema_version'], 1)
            self.assertEqual((result['summary']['enrolled'], result['summary']['completed']), (20, 10))
            self.assertNotIn('observation_period', result)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
