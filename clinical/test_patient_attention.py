"""Deterministic review signals use synthetic archived facts only."""
import json
import unittest

from patient_attention import evaluate_attention


class AttentionTests(unittest.TestCase):
    def fact(self, code='igg', value='12', unit='g/L', quote=None, **extra):
        return dict(code=code, value=value, unit=unit, quote=quote or f'{code}: {value} {unit}',
                    current=True, source_job='synthetic-source', **extra)

    def visit(self, day, *facts, event='am'):
        return {'date': day, 'event_id': event, 'facts': list(facts)}

    def evaluate(self, *visits):
        return evaluate_attention(list(visits), '2026-10-24')

    def kinds(self, result):
        return [item['kind'] for item in result['items']]

    def test_empty_and_invalid_dates_are_not_normality_claims(self):
        result = self.evaluate()
        self.assertEqual(result['level'], 'gray')
        self.assertEqual(result['items'], [])
        self.assertTrue(result['limitations'])
        future = self.evaluate(self.visit('2027-01-01', self.fact()))
        self.assertEqual(future['items'], [])
        self.assertTrue(future['limitations'])
        with self.assertRaises(ValueError):
            evaluate_attention([], '2026-99-01')

    def test_three_strictly_rising_dates_and_two_points(self):
        visits = [self.visit(day, self.fact(value=value)) for day, value in
                  [('2026-07-01', '12'), ('2026-09-01', '17'), ('2026-10-23', '22')]]
        result = self.evaluate(*visits)
        self.assertEqual(self.kinds(result), ['igg_rising'])
        self.assertEqual(result['level'], 'orange')
        self.assertEqual(len(result['items'][0]['evidence']), 3)
        self.assertEqual(self.evaluate(*visits[-2:])['level'], 'yellow')
        self.assertEqual(self.kinds(self.evaluate(*visits[-2:])), ['igg_two_point'])
        self.assertTrue(result['limitations'])

    def test_latest_missing_truncated_and_changed_unit_stop_the_trend(self):
        prior = [self.visit('2026-07-01', self.fact(value='12')),
                 self.visit('2026-09-01', self.fact(value='17'))]
        for last in [self.fact('pain', '3', ''), self.fact(value='>22'), self.fact(value='22', unit='mg/dL')]:
            with self.subTest(last=last['value']):
                result = self.evaluate(*prior, self.visit('2026-10-23', last))
                self.assertNotIn('igg_rising', self.kinds(result))
                self.assertNotIn('igg_two_point', self.kinds(result))

    def test_reordered_same_day_events_do_not_invent_chronology(self):
        first = self.visit('2026-09-01', self.fact(value='12'))
        same = [self.visit('2026-10-23', self.fact(value='17'), event='am'),
                self.visit('2026-10-23', self.fact(value='22'), event='pm')]
        left, right = self.evaluate(first, *same), self.evaluate(first, *reversed(same))
        self.assertEqual(left, right)
        self.assertEqual(left['items'], [])
        self.assertTrue(left['limitations'])

    def test_same_day_equal_observations_are_one_comparable_point(self):
        first = self.visit('2026-09-01', self.fact(value='12'))
        next_day = self.visit('2026-10-23', self.fact(value='17', observation='synthetic-o1'))
        duplicated = self.evaluate(first, next_day, next_day,
                                   self.visit('2026-10-23', self.fact(value='17'), event='pm'))
        self.assertEqual(self.kinds(duplicated), ['igg_two_point'])
        self.assertEqual(len(duplicated['items'][0]['evidence']), 2)

    def test_superseded_facts_do_not_trigger_current_rules(self):
        old = self.fact(value='22', quote='IgG: 22 g/L; \u5371\u6025\u503c')
        old['current'] = False
        result = self.evaluate(self.visit('2026-10-23', old, self.fact(value='12')))
        self.assertEqual(result['items'], [])

    def test_critical_text_is_report_based_and_survives_a_later_normal_value(self):
        text = '\u5408\u6210\u68c0\u67e5\u62a5\u544a\uff1a\u8840\u94be6.8 mmol/L\uff0c\u62a5\u544a\u6807\u8bb0\u5371\u6025\u503c\uff0c\u9700\u7acb\u5373\u5904\u7406\u3002'
        critical = self.fact('inpatient_exams', text, '', quote='\u4f4f\u9662\u68c0\u67e5\uff1a' + text)
        result = self.evaluate(self.visit('2026-07-01', critical),
                               self.visit('2026-10-23', self.fact('inpatient_exams', '\u590d\u67e5\u8840\u94be4.0 mmol/L', '')))
        self.assertEqual(result['level'], 'red')
        self.assertEqual(self.kinds(result), ['critical_report'])
        self.assertEqual(result['items'][0]['evidence'][0]['date'], '2026-07-01')
        self.assertIn('\u5904\u7406\u72b6\u6001', result['items'][0]['summary'])

    def test_a_numeric_value_without_report_marker_cannot_be_critical(self):
        result = self.evaluate(self.visit('2026-10-23', self.fact(value='999')))
        self.assertNotIn('critical_report', self.kinds(result))

    def test_confirmed_critical_pending_handling_remains_red(self):
        for text in ['\u62a5\u544a\u5371\u6025\u503c\uff0c\u5c1a\u672a\u5904\u7406', '\u5371\u6025\u503c\u672a\u5904\u7f6e',
                     '\u5df2\u590d\u6838\u786e\u8ba4\u5371\u6025\u503c']:
            with self.subTest(text=text):
                result = self.evaluate(self.visit('2026-10-23', self.fact('inpatient_exams', text, '')))
                self.assertEqual(result['level'], 'red')
        text = '\u5df2\u590d\u6838\u786e\u8ba4\u5371\u6025\u503c\u4e3a\u8bef\u62a5'
        self.assertNotEqual(self.evaluate(self.visit('2026-10-23', self.fact('inpatient_exams', text, '')))['level'], 'red')

    def test_repeated_report_value_does_not_duplicate_the_signal(self):
        quote = 'IgG: 18.2 g/L; IgG\u53c2\u8003\u8303\u56f4\uff1a7-16 g/L; \u5371\u6025\u503c'
        result = self.evaluate(self.visit('2026-10-23', self.fact(value='18.2', quote=quote, observation='synthetic-a')),
                               self.visit('2026-10-23', self.fact(value='18.2', quote=quote, observation='synthetic-b'), event='pm'))
        self.assertEqual(self.kinds(result).count('critical_report'), 1)
        self.assertEqual(self.kinds(result).count('reference_range'), 1)

    def test_critical_negation_uncertainty_history_other_person_and_resolution(self):
        for text in ['\u65e0\u5371\u6025\u503c', '\u672a\u89c1\u5371\u6025\u503c', '\u7591\u4f3c\u5371\u6025\u503c',
                     '\u5982\u679c\u51fa\u73b0\u5371\u6025\u503c\u5219\u5904\u7406', '\u5982\u51fa\u73b0\u5371\u6025\u503c\u5219\u7acb\u5373\u5904\u7406', '\u65e2\u5f80\u5371\u6025\u503c',
                     '\u5371\u6025\u503c\u5df2\u89e3\u9664', '\u5371\u6025\u503c\u5df2\u5904\u7406', '\u6bcd\u4eb2\u5371\u6025\u503c', '\u5371\u6025\u503c\u5df2\u590d\u6838\u6b63\u5e38',
                     '\u5ba3\u6559\uff1a\u201c\u5371\u6025\u503c\u9700\u5904\u7406\u201d']:
            with self.subTest(text=text):
                result = self.evaluate(self.visit('2026-10-23', self.fact('inpatient_exams', text, '')))
                self.assertNotIn('critical_report', self.kinds(result))
                self.assertTrue(result['limitations'])

    def test_explicit_reference_interval_is_yellow_and_keeps_report_values(self):
        result = self.evaluate(self.visit('2026-10-23', self.fact(value='18.2',
            quote='IgG: 18.2 g/L; IgG\u53c2\u8003\u8303\u56f4\uff1a7-16 g/L')))
        self.assertEqual(result['level'], 'yellow')
        self.assertEqual(self.kinds(result), ['reference_range'])
        self.assertEqual(result['items'][0]['evidence'][0]['value'], '18.2')

    def test_csv_reference_uses_matching_field_and_self_described_note_only(self):
        quote = 'SIM-16,Synthetic,2026-10-23,am,igg,18.2,g/L,IgG\u53c2\u8003\u8303\u56f4\uff1a7-16 g/L'
        result = self.evaluate(self.visit('2026-10-23', self.fact(value='18.2', quote=quote)))
        self.assertEqual(self.kinds(result), ['reference_range'])
        for wrong in [quote.replace('igg,18.2', 'c3,18.2'), quote.replace('IgG\u53c2\u8003', '\u53c2\u8003'),
                      quote.replace('7-16 g/L', '7-16 mg/dL'),
                      'SIM-7-16,Synthetic,2026-10-23,am,igg,18.2,g/L,not a reference range']:
            self.assertNotIn('reference_range', self.kinds(self.evaluate(self.visit('2026-10-23', self.fact(value='18.2', quote=wrong)))))

    def test_csv_arbitrary_columns_and_other_test_markers_do_not_trigger(self):
        wrong = 'SIM-1,\u5371\u6025\u503c,2026-10-23,am,igg,18.2,g/L,C3\u53c2\u8003\u8303\u56f4\uff1a0.9-1.8 g/L\uff1b\u5371\u6025\u503c'
        result = self.evaluate(self.visit('2026-10-23', self.fact(value='18.2', quote=wrong)))
        self.assertEqual(result['items'], [])

    def test_plain_text_multiple_test_scope_is_not_guessed(self):
        quote = 'IgG: 18.2 g/L; C3: 0.3 g/L; C3\u53c2\u8003\u8303\u56f4\uff1a0.9-1.8 g/L; \u5371\u6025\u503c'
        self.assertEqual(self.evaluate(self.visit('2026-10-23', self.fact(value='18.2', quote=quote)))['items'], [])

    def test_equal_infection_windows_are_required_for_count_increase(self):
        text = '\u8fd190\u5929\u611f\u67d33\u6b21\uff0c\u524d90\u5929\u611f\u67d31\u6b21\u3002'
        result = self.evaluate(self.visit('2026-10-23', self.fact('infection_status', text, '')))
        self.assertEqual(self.kinds(result), ['infection_frequency'])
        self.assertEqual(result['level'], 'orange')
        for wrong in [text.replace('\u524d90', '\u524d30'), text.replace('\u611f\u67d33', '\u611f\u67d31'),
                      '\u65e2\u5f80' + text]:
            self.assertNotIn('infection_frequency', self.kinds(self.evaluate(self.visit('2026-10-23', self.fact('infection_status', wrong, '')))))

    def test_recurrent_text_is_not_event_counting(self):
        facts = [self.visit(day, self.fact('infection_status', '\u80ba\u90e8\u611f\u67d3', '')) for day in ['2026-07-01', '2026-09-01', '2026-10-23']]
        self.assertEqual(self.evaluate(*facts)['items'], [])
        result = self.evaluate(self.visit('2026-10-23', self.fact('infection_status', '\u53cd\u590d\u611f\u67d3', '')))
        self.assertEqual(self.kinds(result), ['recurrent_infection'])
        self.assertEqual(result['level'], 'yellow')
        for text in ['\u5426\u8ba4\u53cd\u590d\u611f\u67d3', '\u65e2\u5f80\u53cd\u590d\u611f\u67d3\uff0c\u5f53\u524d\u65e0\u611f\u67d3']:
            self.assertEqual(self.evaluate(self.visit('2026-10-23', self.fact('infection_status', text, '')))['items'], [])

    def test_score_changes_are_single_items_not_a_composite_score(self):
        result = self.evaluate(self.visit('2026-09-01', self.fact('pain', '3', '')),
                               self.visit('2026-10-23', self.fact('pain', '5', '')))
        self.assertEqual(self.kinds(result), ['score_change'])
        self.assertEqual(result['level'], 'yellow')
        self.assertNotIn('ESSPRI', json.dumps(result))
        self.assertEqual(self.evaluate(self.visit('2026-09-01', self.fact('pain', '3', '')),
                         self.visit('2026-10-23', self.fact('pain', '11', '')))['items'], [])

    def test_dryness_label_is_the_specific_oral_dryness_score(self):
        result = self.evaluate(self.visit('2026-09-01', self.fact('dryness', '3', '')),
                               self.visit('2026-10-23', self.fact('dryness', '5', '')))
        self.assertEqual(result['items'][0]['title'], '\u53e3\u5e72\u8bc4\u5206\u8bb0\u5f55\u53d8\u5316')
        self.assertNotIn('\u5e72\u71e5\u8bc4\u5206', result['items'][0]['title'])

    def test_medication_changes_preserve_text_and_do_not_infer_adherence(self):
        first = self.visit('2026-09-01', self.fact('prescription', 'Synthetic medicine 5 mg', ''))
        changed = self.visit('2026-10-23', self.fact('medications', 'Synthetic medicine 10 mg', ''))
        result = self.evaluate(first, changed)
        self.assertEqual(self.kinds(result), ['medication_change'])
        self.assertEqual(result['level'], 'yellow')
        self.assertEqual(result['items'][0]['evidence'][0]['code'], 'prescription')
        self.assertIn('medication_change', self.kinds(self.evaluate(first, changed, self.visit('2026-10-24', self.fact(value='12')))))
        self.assertEqual(self.evaluate(first, self.visit('2026-10-23', self.fact('medications', 'Synthetic medicine  5 mg', '')))['items'], [])

    def test_malicious_text_is_plain_evidence_and_ids_are_stable(self):
        text = '<script>alert(1)</script> \u62a5\u544a\u5371\u6025\u503c'
        visit = self.visit('2026-10-23', self.fact('inpatient_exams', text, ''))
        first = self.evaluate(visit)
        self.assertEqual(first, self.evaluate(visit))
        self.assertEqual(first['items'][0]['evidence'][0]['value'], text)
        self.assertNotIn('<script>', first['items'][0]['title'])
        self.assertRegex(first['items'][0]['id'], r'^[0-9a-f]{24}$')


if __name__ == '__main__':
    unittest.main()
