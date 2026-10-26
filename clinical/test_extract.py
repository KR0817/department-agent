import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from extract import identity, validate_result, extract_csv, read_document, extract_text
from extract import MODEL_DIGESTS


class EvidenceTests(unittest.TestCase):
    def test_unsupported_model_fails_before_network(self):
        with patch('extract.urllib.request.urlopen') as call:
            with self.assertRaisesRegex(ValueError, 'Unsupported local model'):
                extract_text('Patient ID: SIM-1\nName: Example', 'http://model:11434', 'arbitrary:latest')
            call.assert_not_called()

    def test_wrong_model_digest_cannot_call_inference(self):
        for model in MODEL_DIGESTS:
            with self.subTest(model=model), patch('extract.urllib.request.urlopen', return_value=io.StringIO(
                    json.dumps({'models': [{'name': model, 'digest': 'wrong'}]}))) as call:
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    extract_text('Patient ID: SIM-1\nName: Example', 'http://model:11434', model)
                self.assertEqual(call.call_count, 1)

    def test_each_pinned_model_preserves_source_and_explicit_selection(self):
        source = 'Patient ID: SIM-1\nName: Example\nVisit date: 2026-10-23\npain: 3'
        result = {'visits': [{'date': '2026-10-23', 'date_line': 3,
                  'facts': [{'code': 'pain', 'value': '3', 'unit': '', 'line': 4}]}]}
        for model, digest in MODEL_DIGESTS.items():
            responses = [io.StringIO(json.dumps({'models': [{'name': model, 'digest': digest}]})),
                         io.StringIO(json.dumps({'message': {'content': json.dumps(result)}}))]
            with self.subTest(model=model), patch('extract.urllib.request.urlopen', side_effect=responses) as call:
                extracted = extract_text(source, 'http://model:11434', model)
                self.assertEqual(extracted['model'], model)
                self.assertEqual(extracted['visits'][0]['facts'][0]['quote'], 'pain: 3')
                payload = json.loads(call.call_args_list[1].args[0].data)
                self.assertEqual(payload['model'], model)

    def test_identity_requires_explicit_unique_identifier(self):
        self.assertEqual(identity('Patient ID: SIM-1\nName: Example'), ('SIM-1', 'Example'))
        for text in ['Name: Example', 'Patient ID: SIM-1\nPatient ID: SIM-2\nName: Example']:
            with self.assertRaises(ValueError):
                identity(text)

    def test_fabricated_value_and_quote_rejected(self):
        for value, quote in [('8', 'pain: 3'), ('3', 'not in source')]:
            with self.assertRaises(ValueError):
                validate_result({'visits': [{'date': '2026-10-01', 'date_quote': '2026-10-01',
                    'facts': [{'code': 'pain', 'value': value, 'unit': '', 'quote': quote}]}]}, '2026-10-01\npain: 3')

    def test_conflicting_same_visit_rejected(self):
        with self.assertRaises(ValueError):
            validate_result({'visits': [{'date': '2026-10-01', 'date_quote': '2026-10-01', 'facts': [
                {'code': 'pain', 'value': n, 'unit': '', 'quote': 'pain: ' + n} for n in ['3', '8']]}]},
                '2026-10-01\npain: 3\npain: 8')

    def test_csv_preserves_missing_and_lexical_values(self):
        result = extract_csv('# SJD-SYNTHETIC\npatient_id,name,visit_date,code,value,unit\nSIM-1,Example,2026-10-01,igg,18.20,g/L')
        self.assertEqual(result['model'], 'deterministic-csv')
        self.assertEqual(result['visits'][0]['facts'][0]['value'], '18.20')
        self.assertEqual(len(result['visits'][0]['facts']), 1)

    def test_real_data_marker_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'source'
            path.write_text('Patient ID: SIM-1\nName: Example')
            with self.assertRaises(ValueError):
                read_document(path, '.txt')

    def test_invalid_date_and_score_rejected(self):
        for date, value in [('2026-02-30', '3'), ('2026-10-01', '11')]:
            with self.assertRaises(ValueError):
                validate_result({'visits': [{'date': date, 'date_quote': date, 'facts': [
                    {'code': 'pain', 'value': value, 'unit': '', 'quote': 'pain: ' + value}]}]}, date + '\npain: ' + value)

    def test_numeric_substring_is_not_evidence(self):
        with self.assertRaises(ValueError):
            validate_result({'visits': [{'date': '2026-10-01', 'date_quote': '2026-10-01',
                'facts': [{'code': 'igg', 'value': '8.2', 'unit': '', 'quote': 'IgG: 18.2'}]}]},
                '2026-10-01\nIgG: 18.2')

    def test_model_unavailable_remains_failure(self):
        with patch('extract.urllib.request.urlopen', side_effect=URLError('offline')):
            with self.assertRaises(URLError):
                extract_text('Patient ID: SIM-1\nName: Example', 'http://model:11434', 'qwen3:4b')

    def test_docx_reader_preserves_source(self):
        text, method = read_document(pathlib.Path(__file__).parent / 'fixtures' / 'visit.docx', '.docx')
        self.assertEqual(method, 'digital-text')
        self.assertIn('SIM-SJD-001', text)
        self.assertIn('18.2 g/L', text)

    def test_wrong_field_label_rejected(self):
        with self.assertRaises(ValueError):
            validate_result({'visits': [{'date': '2026-10-01', 'date_quote': '2026-10-01',
                'facts': [{'code': 'fatigue', 'value': '3', 'unit': '', 'quote': 'pain: 3'}]}]},
                '2026-10-01\npain: 3')

    def test_long_source_without_explicit_visit_header_rejected(self):
        with self.assertRaises(ValueError):
            extract_text('Patient ID: SIM-1\nName: Example\n' + 'Administrative note.\n' * 200,
                         'http://model:11434', 'qwen3:4b')


if __name__ == '__main__':
    unittest.main()
