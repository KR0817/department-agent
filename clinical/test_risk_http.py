"""Verify demo-only prediction through real middleware and isolated stores."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import test_workbench_http as legacy


class RiskHTTPTests(unittest.TestCase):
    setUp = legacy.WorkbenchHTTPTests.setUp
    tearDown = legacy.WorkbenchHTTPTests.tearDown
    new_client = legacy.WorkbenchHTTPTests.new_client
    setup_admin = legacy.WorkbenchHTTPTests.setup_admin

    def test_authentication_and_business_scope_cannot_be_forged(self):
        self.assertEqual(self.client.get('/api/demo/patient-overview').status_code, 401)
        self.assertEqual(self.client.get('/api/patient-registry/SIM-OV50-001').status_code, 401)
        self.setup_admin()
        self.assertEqual(self.client.post('/api/patient-registry', json={
            'patient_id': 'SIM-OV50-001', 'name': 'Synthetic business patient'}).status_code, 200)
        result = self.client.get('/api/patient-registry/SIM-OV50-001?synthetic=true').json()
        self.assertEqual(result['risk']['status'], 'clinical_unavailable')
        self.assertEqual(result['risk']['models'], [])
        self.assertEqual(self.client.get('/api/patient-registry/UNKNOWN').status_code, 404)

    def test_fixture_prediction_read_only_and_historical_index(self):
        self.setup_admin()
        with self.server.db() as con:
            before = list(con.iterdump())
        response = self.client.get('/api/demo/patient-overview')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['cache-control'])
        data = response.json()
        self.assertEqual(data['summary']['enrolled'], 50)
        first = data['patients'][0]
        risk = first['risk']
        self.assertEqual(risk['mode'], 'synthetic_demo')
        self.assertEqual(risk['status'], 'available')
        self.assertEqual(risk['index_date'], first['enrolled_at'])
        self.assertEqual([m['id'] for m in risk['models']], ['activity_worsening', 'infection'])
        for model in risk['models']:
            values = [point['risk'] for point in model['estimates']]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(0 <= value <= 1 for value in values))
            self.assertEqual(model['estimates'][-1]['days'], 365)
        with self.server.db() as con:
            self.assertEqual(list(con.iterdump()), before)

    def test_missing_baseline_does_not_use_future_data_or_break_detail(self):
        self.setup_admin()
        data = self.server.load_demo_overview()
        changed = copy.deepcopy(data)
        changed['patients'][0]['visits'][0]['measurements']['igg'] = None
        with patch('server.load_demo_overview', return_value=changed):
            response = self.client.get('/api/demo/patient-overview')
        self.assertEqual(response.status_code, 200)
        patient = response.json()['patients'][0]
        self.assertEqual(len(patient['visits']), 7)
        self.assertEqual(patient['risk']['status'], 'input_unavailable')
        self.assertEqual(patient['risk']['models'], [])

    def test_model_artifact_failure_preserves_patient_detail(self):
        self.setup_admin()
        with patch.object(self.server.patient_risk, 'MODEL_PATH', Path(self.root) / 'absent-model.json'):
            response = self.client.get('/api/demo/patient-overview')
        self.assertEqual(response.status_code, 200)
        patient = response.json()['patients'][0]
        self.assertEqual(patient['risk']['status'], 'model_unavailable')
        self.assertEqual(patient['risk']['models'], [])
        self.assertEqual(len(patient['visits']), 7)
        self.assertNotIn(str(self.root), response.text)


if __name__ == '__main__':
    unittest.main()
