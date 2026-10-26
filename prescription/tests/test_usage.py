from datetime import date
import unittest

from mingyirx.analysis import PrescriptionVisit
from mingyirx.usage import item_usage_totals


class UsageTests(unittest.TestCase):
    def test_visit_presence_not_lines_or_patients_and_suppression(self):
        def visit(patient, identifier, items):
            return PrescriptionVisit(patient, 'group', identifier, date(2020, 1, 1),
                                     'doctor', frozenset(items), {}, False)
        visits = {
            'p1': (visit('p1', 'v1', ['A', 'A', 'B', 'C']), visit('p1', 'v2', ['A', 'C'])),
            'p2': (visit('p2', 'v3', ['A', 'B']),),
        }
        self.assertEqual(item_usage_totals(visits, 2), [
            {'item_name': 'A', 'total_usage_visits': 3},
            {'item_name': 'B', 'total_usage_visits': 2},
        ])
        self.assertEqual(item_usage_totals({}, 2), [])
        with self.assertRaises(ValueError):
            item_usage_totals(visits, 0)
