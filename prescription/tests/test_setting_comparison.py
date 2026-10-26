import unittest
from datetime import date
from types import SimpleNamespace
from mingyirx.analysis import PrescriptionVisit
from mingyirx.setting_comparison import fingerprint_links,adjacent_pairs,conditional_rates,complementary_family,original_adjacencies

def visit(pid,key,day,items,dose=10,resolved=True):
    return PrescriptionVisit(pid,'as_strict',key,date(2020,1,day),'X',frozenset(items),{i:(dose,'g') for i in items},resolved)

class SettingComparisonTests(unittest.TestCase):
    def test_fingerprint_requires_day_items_and_doses(self):
        a={'A':(visit('A','1',1,['X','Y']),)}
        b={'B':(visit('B','2',1,['Y','X']),visit('B','3',2,['X','Y']),visit('B','4',1,['X','Y'],12))}
        counts,pairs=fingerprint_links(a,b)
        self.assertEqual(counts['matched_inpatient_records'],1)
        self.assertEqual(len(pairs),1)
        self.assertEqual(len(fingerprint_links(a,{'B':(visit('B','5',1,['X'],resolved=False),)})[1]),0)

    def test_no_bridging_excluded_record(self):
        a,c=visit('A','a',1,['X']),visit('A','c',3,['Y'])
        records=[SimpleNamespace(patient_id='A',visit_id=k,visit_date=date(2020,1,d)) for k,d in [('a',1),('b',2),('c',3)]]
        ctx=SimpleNamespace(read_result=SimpleNamespace(records=records))
        self.assertEqual(adjacent_pairs({'A':(a,c)},date(2020,1,1),date(2020,1,5),30,original_adjacencies=original_adjacencies(ctx)),{})

    def test_correct_riskset_and_equal_patient_weight(self):
        a,b,c=visit('A','a',1,['X']),visit('A','b',2,['Y']),visit('A','c',3,['X'])
        x,y=visit('B','x',1,['X']),visit('B','y',2,['X'])
        pairs={'A':[(a,b,1),(b,c,1)],'B':[(x,y,1)]}
        add=conditional_rates(pairs,'X','addition')
        self.assertEqual((add['patients'],add['opportunities'],add['mean_patient_rate']),(1,1,1))
        remove=conditional_rates(pairs,'X','removal')
        self.assertEqual((remove['patients'],remove['opportunities'],remove['mean_patient_rate']),(2,2,.5))

    def test_complementary_suppression(self):
        self.assertFalse(complementary_family([139,135,120]))
        self.assertTrue(complementary_family([139,120,100]))
        self.assertFalse(complementary_family([100,5]))

    def test_same_day_and_gap_window(self):
        a,b,c=visit('A','a',1,['X']),visit('A','b',1,['Y']),visit('A','c',4,['Z'])
        self.assertEqual(adjacent_pairs({'A':(a,b,c)},date(2020,1,1),date(2020,1,31),2),{})
        self.assertEqual(len(adjacent_pairs({'A':(a,b,c)},date(2020,1,1),date(2020,1,31),3)['A']),1)
