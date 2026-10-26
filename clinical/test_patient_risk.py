"""Guard demonstration inference, clinical blocking and frozen-model parity."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import patient_risk as risk
from patient_overview import load_demo_overview


class PersonalRiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overview = load_demo_overview()

    def patient(self):
        return deepcopy(self.overview['patients'][0])

    def score(self, patient=None, metrics=None):
        return risk.demo_risk(patient or self.patient(), metrics or self.overview['metric_definitions'])

    def test_clinical_has_no_probability_and_no_model_load(self):
        with patch.object(risk, '_load_model', side_effect=AssertionError('Must not load synthetic model')):
            value = risk.business_risk()
        self.assertEqual(value['status'], 'clinical_unavailable')
        self.assertEqual(value['mode'], 'clinical')
        self.assertEqual(value['models'], [])
        self.assertFalse(value['clinical_validated'])
        self.assertNotIn('risk', value)

    def test_available_dual_models_in_prespecified_order(self):
        value = self.score()
        self.assertEqual(value['status'], 'available', value)
        self.assertEqual([m['id'] for m in value['models']], list(risk.ENDPOINTS))
        self.assertEqual(value['index_date'], '2021-10-24')
        self.assertEqual(value['mode'], 'synthetic_demo')
        self.assertEqual(value['model_sha256'], risk.MODEL_SHA256)
        self.assertFalse(value['clinical_validated'])
        self.assertEqual(len(value['features']), 4)
        for model in value['models']:
            values = [row['risk'] for row in model['estimates']]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(math.isfinite(v) and 0 <= v <= 1 for v in values))
            for row in model['estimates']:
                self.assertEqual(row['date'], (date(2021, 10, 24) + timedelta(days=row['days'])).isoformat())

    def test_frozen_export_matches_lifelines_vectors(self):
        artifact = risk._load_model()
        self.assertEqual(len(artifact['verification_cases']), 24)
        for case in artifact['verification_cases']:
            model = next(m for m in artifact['models'] if m['id'] == case['endpoint_id'])
            actual = risk._predict(model, [case['features'][code] for code in risk.CODES], date(2021, 10, 24))
            for row, expected in zip(actual, case['expected_risks']):
                self.assertAlmostEqual(row['risk'], expected, places=12)

    def test_centering_is_applied(self):
        model = risk._load_model()['models'][0]
        actual = risk._predict(model, model['center'], date(2021, 1, 1))
        for row, h in zip(actual, model['baseline_cumulative_hazard']):
            self.assertAlmostEqual(row['risk'], 1 - math.exp(-h['value']), places=14)

    def test_zero_symptom_values_are_not_missing(self):
        patient = self.patient()
        patient['visits'][0]['symptoms'].update(dryness=0, fatigue=0)
        value = self.score(patient)
        self.assertEqual(value['status'], 'available')
        self.assertEqual([f['value'] for f in value['features']][-2:], [0, 0])

    def test_baseline_missing_cannot_use_later_visit(self):
        patient = self.patient()
        patient['visits'][0]['measurements']['igg'] = None
        self.assertEqual(self.score(patient)['status'], 'input_unavailable')
        self.assertEqual(self.score(patient)['models'], [])

    def test_future_values_and_attention_do_not_change_prediction(self):
        patient = self.patient()
        before = self.score(patient)
        patient['attention'] = {'level': 'red'}
        for visit in patient['visits'][1:]:
            visit['measurements'].update(igg=40, c3=0)
            visit['symptoms'].update(dryness=10, fatigue=10)
            visit['condition_note'] = 'critical'
        self.assertEqual(before['models'], self.score(patient)['models'])

    def test_invalid_numeric_inputs_fail_closed(self):
        for value in [None, float('nan'), float('inf'), True, '14.6', -1, 41]:
            with self.subTest(value=value):
                patient = self.patient()
                patient['visits'][0]['measurements']['igg'] = value
                result = self.score(patient)
                self.assertEqual(result['status'], 'input_unavailable')
                self.assertEqual(result['models'], [])

    def test_units_groups_and_duplicate_definitions_fail_closed(self):
        for mode in ['unit', 'group', 'duplicate']:
            metrics = deepcopy(self.overview['metric_definitions'])
            chosen = next(m for m in metrics if m['code'] == 'igg')
            if mode == 'unit':
                chosen['unit'] = 'mg/dL'
            elif mode == 'group':
                chosen['group'] = 'symptoms'
            else:
                metrics.append(deepcopy(chosen))
            with self.subTest(mode=mode):
                self.assertEqual(self.score(metrics=metrics)['status'], 'input_unavailable')

    def test_duplicate_baseline_and_earlier_visit_fail_closed(self):
        patient = self.patient()
        patient['visits'].append(deepcopy(patient['visits'][0]))
        self.assertEqual(self.score(patient)['status'], 'input_unavailable')
        patient = self.patient()
        patient['visits'][1]['date'] = '2020-10-24'
        self.assertEqual(self.score(patient)['status'], 'input_unavailable')

    def test_unsorted_visits_still_use_index_baseline(self):
        patient = self.patient()
        original = self.score(patient)
        patient['visits'].reverse()
        self.assertEqual(original, self.score(patient))

    def test_invalid_index_and_provenance_fail_closed(self):
        for change in ['date', 'enrollment', 'reference']:
            patient = self.patient()
            if change == 'date':
                patient['visits'][0]['date'] = '2021-02-30'
            elif change == 'enrollment':
                patient['enrolled_at'] = '2021-10-23'
            else:
                patient['visits'][0]['id'] = ''
            self.assertEqual(self.score(patient)['status'], 'input_unavailable')

    def test_missing_or_corrupt_model_does_not_crash_patient(self):
        for failure in [FileNotFoundError('private path'), ValueError('invalid artifact')]:
            with patch.object(risk, '_load_model', side_effect=failure):
                value = self.score()
                self.assertEqual(value['status'], 'model_unavailable')
                self.assertEqual(value['models'], [])
                self.assertNotIn('private', json.dumps(value))

    def test_altered_model_hash_blocks_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.json'
            path.write_text('{}', encoding='utf-8')
            with patch.object(risk, 'MODEL_PATH', path):
                self.assertEqual(self.score()['status'], 'model_unavailable')

    def test_invalid_hazard_rejected_even_with_updated_hash(self):
        artifact = risk._load_model()
        artifact['models'][0]['baseline_cumulative_hazard'][1]['value'] = -1
        raw = json.dumps(artifact).encode('utf-8')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.json'
            path.write_bytes(raw)
            with patch.object(risk, 'MODEL_PATH', path), patch.object(risk, 'MODEL_SHA256', hashlib.sha256(raw).hexdigest()):
                self.assertEqual(self.score()['status'], 'model_unavailable')

    def test_all_fifty_demo_patients_have_safe_dtos(self):
        for patient in self.overview['patients']:
            value = self.score(patient)
            self.assertIn(value['status'], ('available', 'input_unavailable'))
            if value['status'] != 'available':
                self.assertEqual(value['models'], [])


if __name__ == '__main__':
    unittest.main()
