"""Synthetic boundary regressions for the existing longitudinal estimands."""
from __future__ import annotations

import csv
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from mingyirx.analysis import (
    _clinical_patient_year_rows,
    _dose_mode_summary,
    _first_visits,
    _longitudinal_item_change_rows,
    _longitudinal_rows,
    _unique_mode,
    build_visits,
    transition_metrics,
)
from mingyirx.cohort import assign_patient_groups
from mingyirx.config import load_config
from mingyirx.io import InputError, LineRecord, read_sources


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "patient_id", "visit_id", "visit_date", "diagnosis_text", "item_name",
    "dose", "unit", "physician_id",
)


class LongitudinalContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "example.json")

    @staticmethod
    def _line(patient="P1", visit="V1", when="2020-01-01", item="A", dose="10", unit="g"):
        return (patient, visit, when, "RA", item, dose, unit, "D1")

    def _read(self, partitions):
        with tempfile.TemporaryDirectory() as temporary:
            paths = []
            for index, rows in enumerate(partitions):
                path = Path(temporary) / f"synthetic_{index}.csv"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(FIELDS)
                    writer.writerows(rows)
                paths.append(path)
            return read_sources(paths, self.config)

    def _visits(self, rows):
        result = self._read([rows])
        groups = assign_patient_groups(result.records, self.config)
        return build_visits(result.records, groups.patient_groups, self.config)

    def test_patient_normalization_collision_blocks_across_files_without_echo(self):
        for variant in ("\uff30\uff11", " P1 "):
            with self.subTest(variant=variant):
                with self.assertRaises(InputError) as caught:
                    self._read([[self._line()], [self._line(patient=variant)]])
                self.assertNotIn(variant, str(caught.exception))
                self.assertNotIn("P1", str(caught.exception))

    def test_visit_normalization_collision_blocks_within_patient(self):
        with self.assertRaises(InputError) as caught:
            self._read([[self._line(), self._line(visit="\uff36\uff11")]])
        self.assertNotIn("V1", str(caught.exception))

    def test_visit_keys_are_local_to_each_patient(self):
        result = self._read([[self._line(), self._line(patient="P2", visit="\uff36\uff11")]])
        self.assertEqual(result.analysis_row_count, 2)

    def test_matching_source_keys_across_files_do_not_block(self):
        self.config = replace(self.config, cross_file_overlap_policy="max_multiplicity")
        result = self._read([[self._line(), self._line()], [self._line()]])
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.analysis_row_count, 2)
        self.assertEqual(result.cross_file_overlap_rows_removed, 1)
        self.assertEqual(result.duplicate_line_count, 1)

    def test_date_conflict_is_blocked_before_cohort_exclusion(self):
        rows = [list(self._line()), list(self._line(when="2020-02-01"))]
        for row in rows:
            row[3] = "unmatched synthetic label"
        with self.assertRaisesRegex(InputError, "conflicting dates"):
            self._read([rows])

    def test_duplicate_lines_do_not_sum_dose_or_change_item_presence(self):
        unique = [self._line(), self._line(visit="V2", when="2020-02-01", item="B")]
        one = self._visits(unique)
        repeated = self._visits([unique[0], unique[0], unique[1]])
        self.assertEqual(one.visits_by_patient, repeated.visits_by_patient)
        self.assertEqual(repeated.eligible_item_line_count, 3)
        self.assertEqual(repeated.visits_by_patient["P1"][0].doses["A"], (10.0, "g"))

    def test_same_day_visits_keep_lexical_tie_order_and_adjacency(self):
        visits = self._visits([
            self._line(visit="2", item="B"),
            self._line(visit="10", item="A"),
        ]).visits_by_patient
        self.assertEqual([visit.visit_id for visit in visits["P1"]], ["10", "2"])
        self.assertEqual(_first_visits(visits)["P1"].items, frozenset({"A"}))
        rows, _ = _longitudinal_rows(visits, ("ra",))
        self.assertEqual(rows[0]["transitions"], 1)
        self.assertEqual(rows[0]["median_patient_jaccard"], 0)

    def test_missing_invalid_and_conflicting_doses_preserve_composition(self):
        result = self._read([[
            self._line(item="A", dose=""),
            self._line(item="B", dose="nan"),
            self._line(item="C", dose="5"),
            self._line(item="C", dose="10"),
            self._line(visit="V2", when="2020-02-01", item="A"),
        ]])
        self.assertEqual(result.unresolved_dose_count, 1)
        built = build_visits(result.records, {"P1": "ra"}, self.config)
        previous, current = built.visits_by_patient["P1"]
        self.assertEqual(previous.items, frozenset({"A", "B", "C"}))
        self.assertTrue(all(value is None for value in previous.doses.values()))
        self.assertEqual(built.dose_conflict_item_count, 1)
        metric = transition_metrics(previous, current)
        self.assertAlmostEqual(metric.jaccard, 1 / 3)
        self.assertEqual(metric.mode, "dose_unresolved")
        self.assertIsNone(metric.modification_burden)

    def test_one_positive_dose_with_missing_duplicate_is_resolved_by_existing_contract(self):
        visits = self._visits([self._line(), self._line(dose="")]).visits_by_patient
        self.assertEqual(visits["P1"][0].doses["A"], (10.0, "g"))

    def test_cross_year_transition_belongs_to_later_year(self):
        visits = self._visits([
            self._line(when="2020-12-31"),
            self._line(visit="V2", when="2021-01-01", item="B"),
        ]).visits_by_patient
        summary, items, changes = _clinical_patient_year_rows(visits, ("ra",), 1)
        self.assertEqual([(row["year"], row["transitions"]) for row in summary], [(2020, 0), (2021, 1)])
        self.assertEqual({row["year"] for row in changes}, {2021})
        self.assertEqual([(row["year"], row["item_name"]) for row in items], [(2020, "A"), (2021, "B")])

    def test_patient_equal_summary_is_not_weighted_by_visit_count(self):
        visits = self._visits([
            self._line(patient="P1", visit=f"V{index}", when=f"2020-01-0{index}")
            for index in range(1, 5)
        ] + [
            self._line(patient="P2"),
            self._line(patient="P2", visit="V2", when="2020-02-01", item="B"),
        ]).visits_by_patient
        rows, _ = _longitudinal_rows(visits, ("ra",))
        self.assertEqual(rows[0]["median_patient_jaccard"], 0.5)
        changes = _longitudinal_item_change_rows(visits, ("ra",), 1)
        addition = next(row for row in changes if row["item_name"] == "B")
        self.assertEqual(addition["mean_patient_transition_fraction"], 0.5)
        self.assertEqual(len(_first_visits(visits)), 2)

    def test_personal_ties_and_group_ties_keep_distinct_rules(self):
        self.assertIsNone(_unique_mode([5.0, 10.0]))
        self.assertEqual(_unique_mode([5.0, 10.0, 5.0]), 5.0)
        summary = _dose_mode_summary([5.0] * 10 + [10.0] * 10, 10)
        self.assertEqual(summary["most_common_dose_values_g"], "5;10")
        self.assertTrue(summary["most_common_dose_tied"])
        self.assertEqual(summary["most_common_dose_patients"], 10)
        self.assertTrue(all(value is None for value in _dose_mode_summary([5.0] * 9 + [10.0] * 9, 10).values()))

    def test_small_group_warning_withholds_exact_count(self):
        record = LineRecord("P1", "V1", date(2020, 1, 1), "RA", "A", 10.0, "g", "D1")
        result = assign_patient_groups((record,), replace(self.config, min_public_n=10))
        self.assertEqual(result.group_counts["ra"], 1)
        self.assertFalse(any("has 1 assigned patients" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
