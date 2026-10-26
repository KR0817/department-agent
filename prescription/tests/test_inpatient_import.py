import unittest
from mingyirx.inpatient_import import parse_prescription, validate_identities, candidate_status

class InpatientImportTests(unittest.TestCase):
    def test_preserves_preparation_and_decimal_dose(self):
        self.assertEqual(parse_prescription('姜厚朴 15.000g 内服 日两次；砂仁 6g 内服 日两次', 2), [('姜厚朴',15.0,'g'),('砂仁',6.0,'g')])

    def test_count_mismatch_does_not_drop_token(self):
        with self.assertRaises(ValueError): parse_prescription('砂仁 6g 内服',2)

    def test_unknown_dose_is_not_zero(self):
        for text in ['砂仁 不详g 内服','砂仁 0g 内服','砂仁 -3g 内服','砂仁 3mg 内服']:
            with self.subTest(text=text), self.assertRaises(ValueError): parse_prescription(text,1)

    def test_repeated_item_is_preserved_for_downstream_conflict_checks(self):
        self.assertEqual(len(parse_prescription('砂仁 6g\n砂仁 9g',2)),2)

    def test_repeated_identity_is_valid_but_conflicting_identity_fails(self):
        validate_identities({'IP:1': {('A','2000-01-01','F')}})
        with self.assertRaises(ValueError):
            validate_identities({'IP:1': {('A','2000-01-01','F'),('B','2000-01-01','F')}})

    def test_cross_source_id_alone_is_not_a_link(self):
        key=('A','2000-01-01','F')
        self.assertEqual(candidate_status('1',key,{'1':{('B','2000-01-01','F')}},{}),'NO_EXACT_IDENTITY_CANDIDATE')

    def test_ambiguous_demographics_are_not_confirmed(self):
        key=('A','2000-01-01','F')
        self.assertEqual(candidate_status('1',key,{}, {key:{'2','3'}}),'AMBIGUOUS_DEMOGRAPHIC_CANDIDATE')
        self.assertEqual(candidate_status('1',key,{}, {key:{'2'}}),'UNIQUE_DEMOGRAPHIC_CANDIDATE')
        self.assertEqual(candidate_status('1',key,{'1':{key}}, {key:{'1','2'}}),'EXACT_ID_AND_IDENTITY')
