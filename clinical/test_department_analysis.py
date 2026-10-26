"""Adapter checks use only invented records and the actual MingYiRx functions."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

from department_analysis import Analysis, AnalysisError, MAX_PAYLOAD_BYTES


ROOT = Path(os.environ.get('DEPARTMENT_MINGYIRX_ROOT', Path(__file__).resolve().parents[1] / 'prescription'))


class DepartmentAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = Analysis(ROOT)

    def setUp(self):
        self.example = self.analysis.example()
        self.records = copy.deepcopy(self.example['records'])

    def preview(self, records=None, origin='synthetic', reviewed=True):
        return self.analysis.preview({'records': self.records if records is None else records,
                                      'data_origin': origin, 'review_confirmed': reviewed})

    def assert_error(self, method, payload, status):
        with self.assertRaises(AnalysisError) as caught:
            method(payload)
        self.assertEqual(caught.exception.status, status)
        self.assertNotIn('private-fragment', caught.exception.detail)

    def test_example_recognizes_three_source_bound_unapproved_visits(self):
        self.assertEqual(len(self.records), 3)
        self.assertEqual(self.example['source_sha256'], hashlib.sha256(self.example['text'].encode()).hexdigest())
        self.assertEqual({row['source_sha256'] for row in self.records}, {self.example['source_sha256']})
        self.assertFalse(self.example['review_confirmed'])
        self.assertFalse(self.example['persisted'])
        self.assertIsNone(self.example['clinical_approval'])
        self.assertTrue(all(row['evidence']['prescription'] for row in self.records))

    def test_actual_analysis_retains_original_add_remove_and_unknown_dose_basis(self):
        result = self.preview()
        self.assertNotEqual(result['gate'], 'BLOCK', result['errors'])
        self.assertEqual(result['counts']['visits'], 3)
        self.assertEqual(result['counts']['pairs'], 2)
        self.assertEqual(result['counts']['eligible_pairs'], 2)
        labels = {row['code']: row['label'] for row in result['vocabulary']['medicines']}
        first = result['pairs'][0]
        self.assertEqual([labels[code] for code in first['added']], ['HerbC'])
        self.assertEqual([labels[code] for code in first['removed']], ['HerbB'])
        self.assertEqual(first['interval_days'], 14)
        change = first['dose_changes'][0]
        self.assertEqual((change['before'], change['after']), (10.0, 12.0))
        self.assertEqual(change['direction'], 'unresolved')
        self.assertEqual(change['reason'], 'unknown_basis')
        self.assertIsNone(change['delta'])
        self.assertFalse(result['view']['readiness']['clinical_effectiveness_verified'])

    def test_preview_matches_original_importer_and_does_not_mutate_input(self):
        before = copy.deepcopy(self.records)
        original = self.analysis._intake.prepare_import(self.records, synthetic=True)
        result = self.preview()
        for key in ('gate', 'errors', 'warnings', 'bundle', 'pairs', 'counts'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(self.records, before)

    def test_duplicate_visit_is_idempotent_and_conflict_blocks(self):
        self.records.append(copy.deepcopy(self.records[0]))
        result = self.preview()
        self.assertEqual(result['counts']['duplicates'], 1)
        self.assertEqual(result['counts']['visits'], 3)
        self.records[-1]['prescription'] = 'HerbA 15g'
        result = self.preview()
        self.assertEqual(result['gate'], 'BLOCK')
        self.assertIn('CONFLICTING_VISIT', [row['code'] for row in result['errors']])
        self.assertEqual(result['pairs'], [])
        self.assertIsNone(result['bundle'])

    def test_same_day_without_sequence_remains_unresolved(self):
        self.records[1]['date'] = self.records[0]['date']
        self.records[0]['sequence'] = None
        self.records[1]['sequence'] = None
        result = self.preview()
        self.assertNotEqual(result['gate'], 'BLOCK')
        self.assertEqual(result['counts']['unresolved_pairs'], 2)
        self.assertTrue(all(row['status'] == 'unresolved_order' for row in result['pairs']))
        self.assertTrue(all(not row['added'] and not row['dose_changes'] for row in result['pairs']))

    def test_missing_dates_and_order_blocks_without_inventing_intervals(self):
        for record in self.records:
            record['date'] = ''
            record['sequence'] = None
        result = self.preview()
        self.assertEqual(result['gate'], 'BLOCK')
        self.assertIn('ORDER_INPUT_REQUIRED', [row['code'] for row in result['errors']])
        self.assertEqual(result['pairs'], [])

    def test_declared_deidentified_preview_never_exports_authorization_bundle(self):
        result = self.preview(origin='deidentified')
        self.assertNotEqual(result['gate'], 'BLOCK')
        self.assertIsNone(result['bundle'])
        self.assertTrue(result['cases'])
        self.assertTrue(result['vocabulary'])
        self.assertFalse(result['deidentification_verified'])
        self.assertFalse(result['source_hashes_independently_verified'])
        self.assertTrue(result['data_origin_is_operator_declaration'])
        self.assertEqual(result['view']['readiness']['evidence_state'], 'LOCAL_DECLARATIONS_UNVERIFIED')
        self.assertNotIn('local_authorization', json.dumps(result))
        self.assertFalse(result['persisted'])

    def test_explicit_review_must_be_boolean_true(self):
        for reviewed in (False, None, 'true', 1):
            self.assert_error(self.analysis.preview, {'records': self.records, 'data_origin': 'synthetic',
                                                    'review_confirmed': reviewed}, 422)

    def test_exact_request_keys_and_data_origin_required(self):
        bad_requests = [None, {}, {'text': 'x'}, {'text': 'x', 'data_origin': 'real'},
                        {'text': 'x', 'data_origin': 'synthetic', 'path': 'private-fragment'}]
        for payload in bad_requests:
            self.assert_error(self.analysis.recognize, payload, 422)

    def test_original_candidate_schema_and_hash_validation_are_retained(self):
        for field, value, code in [('source_sha256', 'bad', 'SOURCE_SHA256_INVALID'),
                                    ('sequence', True, 'SEQUENCE_INVALID'),
                                    ('prescription', ['private-fragment'], 'TEXT_FIELD_INVALID')]:
            records = copy.deepcopy(self.records)
            records[0][field] = value
            result = self.preview(records)
            self.assertEqual(result['gate'], 'BLOCK')
            self.assertIn(code, [row['code'] for row in result['errors']])
        self.records[0]['name'] = 'private-fragment'
        result = self.preview()
        self.assertEqual(result['gate'], 'BLOCK')
        self.assertNotIn('private-fragment', json.dumps(result))

    def test_nonfinite_and_unicode_values_reject_before_source_call(self):
        for bad in (float('nan'), float('inf'), '\ud800'):
            records = copy.deepcopy(self.records)
            records[0]['sequence'] = bad
            self.assert_error(self.analysis.preview, {'records': records, 'data_origin': 'synthetic',
                                                    'review_confirmed': True}, 422)

    def test_body_text_and_record_limits_are_bounded(self):
        self.assert_error(self.analysis.recognize, {'text': 'x' * (MAX_PAYLOAD_BYTES + 1),
                                                    'data_origin': 'synthetic'}, 413)
        self.assert_error(self.analysis.recognize, {'text': 'x' * 100001, 'data_origin': 'synthetic'}, 413)
        self.assert_error(self.analysis.preview, {'records': [{}] * 101, 'data_origin': 'synthetic',
                                                'review_confirmed': True}, 413)
        self.assert_error(self.analysis.preview, {'records': [], 'data_origin': 'synthetic',
                                                'review_confirmed': True}, 422)

    def test_json_and_csv_use_original_parser_with_source_line_evidence(self):
        row = {key: value for key, value in self.records[0].items()
               if key not in ('record_id', 'source_sha256', 'evidence')}
        for text, kind in ((json.dumps([row]), 'json'),
                           ('subject_code,episode_code,physician_code,visit_code\nSYN-A,E1,D1,V1\n', 'csv')):
            result = self.analysis.recognize({'text': text, 'data_origin': 'synthetic'})
            self.assertEqual(result['format'], kind)
            self.assertEqual(len(result['records']), 1)
            self.assertTrue(result['records'][0]['evidence'])
        self.assert_error(self.analysis.recognize, {'text': '[{"sequence": NaN}]',
                                                   'data_origin': 'synthetic'}, 422)


if __name__ == '__main__':
    unittest.main()
