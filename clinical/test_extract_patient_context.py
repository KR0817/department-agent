"""Synthetic extraction checks; model transport is always a fixed in-memory stub."""
import io
import json
import re
import unittest
from unittest.mock import patch

from extract import (ALIASES, CLINICAL_TEXT_FIELDS, FIELDS, LABELS, MODEL_DIGESTS,
                     SCHEMA, _extract_single, extract_csv, extract_text, validate_result)


CONTEXT = {'patient_id': 'SIM-CONTEXT-001', 'name': 'Synthetic Example'}
MODEL = 'qwen3:14b'
BASE = 'Visit date: 2026-10-24\n'
CSV_HEADER = 'patient_id,name,visit_date,code,value,unit\n'


class FixedModel:
    def __init__(self, result=None):
        self.result = result
        self.payloads = []

    def __call__(self, request, **_kwargs):
        if isinstance(request, str):
            return io.StringIO(json.dumps({'models': [{'name': MODEL, 'digest': MODEL_DIGESTS[MODEL]}]}))
        payload = json.loads(request.data)
        self.payloads.append(payload)
        result = self.result
        if result is None:
            numbered = payload['messages'][1]['content']
            lines = [(int(number), value) for number, value in re.findall(r'^\[(\d+)\] (.*)$', numbered, re.M)]
            date_line, date_text = next((number, value) for number, value in lines if value.startswith('Visit date:'))
            facts = []
            for number, value in lines:
                for code in CLINICAL_TEXT_FIELDS:
                    if value.startswith(code + ':'):
                        facts.append({'code': code, 'value': value.split(':', 1)[1].strip(), 'unit': '', 'line': number})
            result = {'visits': [{'date': date_text.split(':', 1)[1].strip(), 'date_line': date_line, 'facts': facts}]}
        return io.StringIO(json.dumps({'message': {'content': json.dumps(result)}, 'total_duration': 1}))


def literal_result(code, value, first, end=None, date_line=1):
    fact = {'code': code, 'value': value, 'unit': '', 'line': first}
    if end is not None:
        fact['end_line'] = end
    return {'visits': [{'date': '2026-10-24', 'date_line': date_line, 'facts': [fact]}]}


class PatientContextExtractionTests(unittest.TestCase):
    def test_five_text_fields_extend_existing_schema_without_numeric_requirement(self):
        self.assertEqual(len(FIELDS), 19)
        self.assertEqual(set(FIELDS), set(LABELS))
        self.assertEqual(set(FIELDS), set(ALIASES))
        self.assertEqual(SCHEMA['properties']['visits']['items']['properties']['facts']['items']['properties']['code']['enum'], list(FIELDS))
        text = BASE + '\n'.join(code + ': literal text without any number' for code in CLINICAL_TEXT_FIELDS)
        stub = FixedModel()
        with patch('extract.urllib.request.urlopen', side_effect=stub):
            result = extract_text(text, 'http://local-model', MODEL, CONTEXT)
        self.assertEqual(len(result['visits'][0]['facts']), 5)
        available = stub.payloads[0]['format']['properties']['visits']['items']['properties']['facts']['items']['properties']['code']['enum']
        self.assertEqual(set(available), set(CLINICAL_TEXT_FIELDS))
        self.assertEqual(result['identity_source'], 'operator_selected')
        self.assertEqual(result['identity_fields'], {'patient_id': 'operator_selected', 'name': 'operator_selected'})
        source = stub.payloads[0]['messages'][1]['content']
        self.assertNotIn(CONTEXT['patient_id'], source)
        self.assertNotIn(CONTEXT['name'], source)

    def test_each_chinese_label_accepts_literal_value(self):
        for code in CLINICAL_TEXT_FIELDS:
            quote = LABELS[code] + ': \u539f\u6587\u5f85\u786e\u8ba4'
            text = '2026-10-24\n' + quote
            with self.subTest(code=code):
                result = validate_result({'visits': [{'date': '2026-10-24', 'date_quote': '2026-10-24',
                    'facts': [{'code': code, 'value': '\u539f\u6587\u5f85\u786e\u8ba4', 'unit': '', 'quote': quote}]}]}, text)
                self.assertEqual(result[0]['facts'][0]['quote'], quote)

    def test_partial_and_complete_source_identity_keep_per_field_provenance(self):
        cases = [('', 'operator_selected', 'operator_selected'),
                 ('Patient ID: SIM-CONTEXT-001\n', 'source', 'operator_selected'),
                 ('Name: Synthetic Example\n', 'operator_selected', 'source'),
                 ('Patient ID: SIM-CONTEXT-001\nName: Synthetic Example\n', 'source', 'source')]
        for header, id_source, name_source in cases:
            with self.subTest(header=header), patch('extract.urllib.request.urlopen', side_effect=FixedModel()):
                result = extract_text(header + BASE + 'medications: not documented', 'http://local-model', MODEL, CONTEXT)
                self.assertEqual(result['patient_id'], CONTEXT['patient_id'])
                self.assertEqual(result['name'], CONTEXT['name'])
                self.assertEqual(result['identity_fields'], {'patient_id': id_source, 'name': name_source})

    def test_conflicting_or_malformed_source_identity_rejects_before_any_network(self):
        headers = ['Patient ID: SIM-OTHER\n', 'Name: Other Example\n',
                   'Patient ID: SIM-CONTEXT-001\nPatient ID: SIM-OTHER\n',
                   'Name: Synthetic Example\nName: Other Example\n',
                   'Patient ID: SIM-CONTEXT-001/bad\n', 'Patient ID: A\n',
                   'Patient ID: ' + 'A' * 65 + '\n', 'Patient ID:\n',
                   'Patient ID: SIM-CONTEXT-001.extra\n', 'Name:\n',
                   'Patient ID: SIM-CONTEXT-001 OTHER\n',
                   'Patient ID: SIM-CONTEXT-001;OTHER\n', 'Patient ID: SIM-CONTEXT-001,OTHER\n',
                   'Patient ID: \uff33\uff29\uff2d-CONTEXT-001\n']
        for header in headers:
            with self.subTest(header=header), patch('extract.urllib.request.urlopen') as call:
                with self.assertRaises(ValueError):
                    extract_text(header + BASE + 'medications: literal', 'http://local-model', MODEL, CONTEXT)
                call.assert_not_called()

    def test_non_ascii_names_and_same_line_identity_are_checked(self):
        context = {'patient_id': 'SIM-ZH-001', 'name': '\u6a21\u62df\u60a3\u8005'}
        text = '\u60a3\u8005\u7f16\u53f7\uff1aSIM-ZH-001, \u59d3\u540d\uff1a\u6a21\u62df\u60a3\u8005\n' + BASE + 'infection_status: unknown'
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel()):
            result = extract_text(text, 'http://local-model', MODEL, context)
        self.assertEqual(result['identity_source'], 'source')

    def test_invalid_selected_context_never_calls_network(self):
        contexts = [[], {}, {'patient_id': 'bad/id', 'name': 'Example'},
                    {'patient_id': 'SIM-1', 'name': ''}, {'patient_id': 'SIM-1', 'name': 'A\nB'}]
        for context in contexts:
            with self.subTest(context=context), patch('extract.urllib.request.urlopen') as call:
                with self.assertRaises(ValueError):
                    extract_text(BASE + 'medications: literal', 'http://local-model', MODEL, context)
                call.assert_not_called()

    def test_context_names_use_complete_eighty_character_limit_without_truncation(self):
        name = 'A' * 80
        context = {**CONTEXT, 'name': name}
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel()):
            result = extract_text('Name: ' + name + '\n' + BASE + 'medications: literal', 'http://local-model', MODEL, context)
        self.assertEqual(result['name'], name)
        for source_name in (name + 'B', name[:40] + 'B' + name[41:]):
            with self.subTest(source_name=source_name), patch('extract.urllib.request.urlopen') as call:
                with self.assertRaises(ValueError):
                    extract_text('Name: ' + source_name + '\n' + BASE + 'medications: literal', 'http://local-model', MODEL, context)
                call.assert_not_called()

    def test_no_context_preserves_explicit_identity_requirement(self):
        with patch('extract.urllib.request.urlopen') as call:
            with self.assertRaisesRegex(ValueError, 'explicit patient identifier'):
                extract_text(BASE + 'medications: literal', 'http://local-model', MODEL)
            call.assert_not_called()
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel()):
            result = extract_text('Patient ID: SIM-OLD\nName: Existing\n' + BASE + 'medications: literal', 'http://local-model', MODEL)
        self.assertEqual(result['patient_id'], 'SIM-OLD')
        self.assertEqual(result['identity_source'], 'source')

    def test_csv_all_or_partial_blank_identity_uses_selection_without_changing_quote(self):
        for rows in [',,2026-10-24,medications,unspecified,',
                     'SIM-CONTEXT-001,,2026-10-24,medications,unspecified,',
                     ',Synthetic Example,2026-10-24,medications,unspecified,',
                     'SIM-CONTEXT-001,Synthetic Example,2026-10-24,medications,unspecified,\n,,2026-10-25,infection_status,unknown,']:
            with self.subTest(rows=rows):
                result = extract_csv(CSV_HEADER + rows, CONTEXT)
                self.assertEqual(result['patient_id'], CONTEXT['patient_id'])
                self.assertEqual(result['identity_source'], 'operator_selected')
                for visit in result['visits']:
                    self.assertIn(visit['facts'][0]['quote'], rows)

    def test_csv_matching_source_identity_is_explicit(self):
        text = CSV_HEADER + 'SIM-CONTEXT-001,Synthetic Example,2026-10-24,comorbidities,unknown,'
        result = extract_csv(text, CONTEXT)
        self.assertEqual(result['identity_source'], 'source')

    def test_csv_mismatch_multiple_and_malformed_identity_are_blocked(self):
        rows = ['SIM-OTHER,Synthetic Example,2026-10-24,medications,literal,',
                'SIM-CONTEXT-001,Other,2026-10-24,medications,literal,',
                'SIM-CONTEXT-001/bad,Synthetic Example,2026-10-24,medications,literal,',
                'SIM-CONTEXT-001,Synthetic Example,2026-10-24,medications,literal,\nSIM-OTHER,Synthetic Example,2026-10-25,medications,literal,']
        for row in rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                extract_csv(CSV_HEADER + row, CONTEXT)

    def test_csv_without_context_keeps_existing_requirements(self):
        with self.assertRaises(ValueError):
            extract_csv(CSV_HEADER + ',,2026-10-24,medications,literal,')
        result = extract_csv(CSV_HEADER + 'SIM-OLD,Existing,2026-10-24,medications,literal,')
        self.assertEqual(result['patient_id'], 'SIM-OLD')
        self.assertEqual(result['identity_source'], 'source')

    def test_text_categories_keep_literal_qualifiers_and_cannot_infer(self):
        quote = 'infection_status: not excluded; test pending'
        good = {'date': '2026-10-24', 'date_quote': '2026-10-24', 'facts': [
            {'code': 'infection_status', 'value': 'not excluded; test pending', 'unit': '', 'quote': quote}]}
        text = '2026-10-24\n' + quote
        self.assertEqual(validate_result({'visits': [good]}, text)[0]['facts'][0]['value'], 'not excluded; test pending')
        good['facts'][0]['value'] = 'infection confirmed'
        with self.assertRaises(ValueError):
            validate_result({'visits': [good]}, text)

    def test_text_category_unit_stays_inside_verbatim_value(self):
        fact = {'code': 'medications', 'value': 'drug 5 mg', 'unit': 'mg', 'quote': 'medications: drug 5 mg'}
        visit = {'date': '2026-10-24', 'date_quote': '2026-10-24', 'facts': [fact]}
        with self.assertRaisesRegex(ValueError, 'inside the literal'):
            validate_result({'visits': [visit]}, '2026-10-24\nmedications: drug 5 mg')

    def test_multiline_paragraph_is_one_exact_value_with_windows_line_endings(self):
        text = 'Visit date: 2026-10-24\r\nmedications: first drug\r\nsecond drug\r\n'
        result = literal_result('medications', 'first drug\r\nsecond drug', 2, 3)
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel(result)):
            extracted = extract_text(text, 'http://local-model', MODEL, CONTEXT)
        fact = extracted['visits'][0]['facts'][0]
        self.assertEqual(fact['quote'], 'medications: first drug\r\nsecond drug')
        self.assertIn(fact['quote'], text)

    def test_multiline_evidence_rejects_invalid_ranges_and_event_headers(self):
        cases = [(literal_result('medications', 'literal', 2, 9), BASE + 'medications: literal'),
                 (literal_result('medications', 'literal', 2, 1), BASE + 'medications: literal'),
                 (literal_result('medications', 'literal', 2, True), BASE + 'medications: literal'),
                 (literal_result('medications', 'literal', 2, 3), BASE + 'medications: literal\nEvent ID: EVENT-2'),
                 (literal_result('medications', 'literal', 2, 3), BASE + 'medications: literal\nVisit date: 2026-10-25'),
                 (literal_result('pain', '3', 2, 3), BASE + 'pain: 3\nother note')]
        for result, text in cases:
            with self.subTest(result=result), patch('extract.urllib.request.urlopen', side_effect=FixedModel(result)):
                with self.assertRaises(ValueError):
                    _extract_single(text, 'http://local-model', MODEL, CONTEXT)

    def test_model_cannot_cite_selected_identity_as_source(self):
        result = literal_result('medications', CONTEXT['name'], 2)
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel(result)):
            with self.assertRaises(ValueError):
                extract_text(BASE + 'medications: unknown', 'http://local-model', MODEL, CONTEXT)

    def test_long_source_validates_identity_before_network_and_never_injects_header(self):
        text = BASE + 'Administrative note.\n' * 150 + 'medications: first record\nVisit date: 2026-10-25\ninfection_status: pending'
        stub = FixedModel()
        with patch('extract.urllib.request.urlopen', side_effect=stub):
            result = extract_text(text, 'http://local-model', MODEL, CONTEXT)
        self.assertEqual([visit['date'] for visit in result['visits']], ['2026-10-24', '2026-10-25'])
        self.assertEqual(result['identity_source'], 'operator_selected')
        for payload in stub.payloads:
            source = payload['messages'][1]['content']
            self.assertNotIn('Patient ID:', source)
            self.assertNotIn(CONTEXT['patient_id'], source)
        with patch('extract.urllib.request.urlopen') as call:
            with self.assertRaises(ValueError):
                extract_text(text + '\nPatient ID: SIM-OTHER', 'http://local-model', MODEL, CONTEXT)
            call.assert_not_called()

    def test_legacy_long_source_keeps_original_identity_provenance(self):
        text = 'Patient ID: SIM-OLD\nName: Existing\n' + BASE + 'medications: first\nVisit date: 2026-10-25\ninfection_status: unknown'
        with patch('extract.urllib.request.urlopen', side_effect=FixedModel()):
            result = extract_text(text, 'http://local-model', MODEL)
        self.assertEqual(result['identity_source'], 'source')
        self.assertEqual(result['name'], 'Existing')

    def test_oversize_text_paragraph_does_not_silently_split_or_drop_continuation(self):
        text = BASE + 'medications: first drug\n' + 'Continuation of the original treatment paragraph.\n' * 80
        with patch('extract.urllib.request.urlopen') as call:
            with self.assertRaisesRegex(ValueError, 'paragraph exceeds'):
                extract_text(text, 'http://local-model', MODEL, CONTEXT)
            call.assert_not_called()

    def test_same_event_category_conflict_and_non_iso_date_stay_rejected(self):
        text = '2026-10-24\nmedications: first\nmedications: second'
        facts = [{'code': 'medications', 'value': value, 'unit': '', 'quote': 'medications: ' + value} for value in ('first', 'second')]
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            validate_result({'visits': [{'date': '2026-10-24', 'date_quote': '2026-10-24', 'facts': facts}]}, text)
        with self.assertRaisesRegex(ValueError, 'YYYY-MM-DD'):
            validate_result({'visits': [{'date': '20261024', 'date_quote': '20261024', 'facts': facts[:1]}]}, text.replace('2026-10-24', '20261024'))

    def test_csv_patient_identifier_and_date_digits_are_not_numeric_evidence(self):
        quote = 'SIM-7-TEST,Synthetic,2026-10-24,pain,4,'
        text = CSV_HEADER + quote
        for value in ('7', '10', '4'):
            candidate = {'visits': [{'date': '2026-10-24', 'date_quote': quote,
                'facts': [{'code': 'pain', 'value': value, 'unit': '', 'quote': quote}]}]}
            if value == '4':
                self.assertEqual(validate_result(candidate, text)[0]['facts'][0]['value'], '4')
            else:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'source field'):
                    validate_result(candidate, text)

    def test_csv_explicit_source_note_correction_remains_available(self):
        header = 'patient_id,name,visit_date,event_id,code,value,unit,source_note\n'
        quote = 'SIM-7-TEST,Synthetic,2026-10-24,am,pain,3,,pain: 8; pain: 5'
        for value in ('3', '8', '5', '7', '10'):
            candidate = {'visits': [{'date': '2026-10-24', 'date_quote': quote, 'event_id': 'am',
                'facts': [{'code': 'pain', 'value': value, 'unit': '', 'quote': quote}]}]}
            if value in ('3', '8', '5'):
                self.assertEqual(validate_result(candidate, header + quote)[0]['facts'][0]['value'], value)
            else:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'source field'):
                    validate_result(candidate, header + quote)

    def test_plain_text_numeric_value_stays_with_its_own_label(self):
        quote = 'pain: 3; fatigue: 7; Patient ID: SIM-8-TEST'
        for value in ('7', '8'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'source field'):
                validate_result({'visits': [{'date': '2026-10-24', 'date_quote': '2026-10-24',
                    'facts': [{'code': 'pain', 'value': value, 'unit': '', 'quote': quote}]}]}, '2026-10-24\n' + quote)


if __name__ == '__main__':
    unittest.main()
