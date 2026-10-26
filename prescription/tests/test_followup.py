import unittest
from datetime import date, timedelta
from mingyirx.analysis import PrescriptionVisit
from mingyirx.followup import visit_gap_sensitivity


def history(patient, days, items):
    return tuple(PrescriptionVisit(patient, 'group', str(i), date(2020, 1, 1)+timedelta(days=day),
                                   'doctor', frozenset(item), {}, False)
                 for i, (day, item) in enumerate(zip(days, items)))


class FollowupTests(unittest.TestCase):
    def test_inclusive_boundaries_and_no_bridging(self):
        data = {'p': history('p', [0, 0, 30, 120, 300, 481], ['A','B','B','C','C','D'])}
        result = visit_gap_sensitivity(data, 1, 30)
        self.assertEqual([r['median_patient_gap_days'] for r in result], [135,30,60,90])
        self.assertEqual([r['median_patient_jaccard'] for r in result], [.5,1,.5,1])
        self.assertEqual(result, visit_gap_sensitivity(data, 1, 30))

    def test_patient_equal_not_transition_weighted(self):
        data = {'a':history('a',[0,10,20,30,40],['A']*5),
                'b':history('b',[0,10],['A','B'])}
        self.assertEqual(visit_gap_sensitivity(data, 1, 30)[0]['median_patient_jaccard'], .5)

    def test_small_nested_difference_suppresses_entire_family(self):
        data = {str(i):history(str(i),[0,10],['A','A']) for i in range(10)}
        data['long'] = history('long',[0,60],['A','B'])
        rows = visit_gap_sensitivity(data, 10, 30)
        self.assertTrue(all(row['patients'] == '' and row['disclosure'] == 'SUPPRESSED_FAMILY' for row in rows))

    def test_no_positive_gaps_and_unsorted_dates(self):
        rows = visit_gap_sensitivity({'p':history('p',[0,0],['A','A'])}, 1, 30)
        self.assertTrue(all(row['patients'] == '' for row in rows))
        with self.assertRaises(ValueError):
            visit_gap_sensitivity({'p':history('p',[10,0],['A','A'])},1,30)
