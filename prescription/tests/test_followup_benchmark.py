"""Deterministic synthetic checks for the unchanged-prescription benchmark."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from mingyirx.followup_benchmark import BenchmarkError, evaluate_fixture, run


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/synthetic/followup_pairs.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FollowupBenchmarkTests(unittest.TestCase):
    def test_carry_forward_exposes_changes_despite_high_similarity(self):
        result = evaluate_fixture(fixture())
        self.assertEqual(result["evidence_state"], "SYNTHETIC_SOFTWARE_CHECK_ONLY")
        self.assertFalse(result["clinical_evidence"])
        self.assertFalse(result["learned_model_evaluated"])
        summary = result["summary"]
        self.assertEqual((summary["patients"], summary["pairs"]), (2, 3))
        self.assertEqual((summary["added_events"], summary["removed_events"]), (1, 1))
        self.assertEqual(summary["change_event_recall"], 0)
        self.assertIsNone(summary["addition_precision"])
        self.assertAlmostEqual(summary["patient_equal_contextual_set_jaccard"], 5 / 6)
        first = result["pairs"][0]
        self.assertEqual(first["added"], ["\u5f53\u5f52"])
        self.assertEqual(first["removed"], ["\u9ec4\u82aa"])
        self.assertEqual(first["retained"], ["\u767d\u828d"])
        self.assertEqual(first["gap_days"], 14)

    def test_original_adjacency_never_bridges_ineligible_or_same_day(self):
        result = evaluate_fixture(fixture())
        self.assertEqual(result["skipped_original_adjacencies"], {"same_day": 1, "ambiguous_day_endpoint": 1, "ineligible_endpoint": 2})
        self.assertEqual(result["original_adjacencies"], len(result["pairs"]) + sum(result["skipped_original_adjacencies"].values()))
        self.assertEqual([(p["patient_code"], p["prior_sequence"], p["current_sequence"])
                          for p in result["pairs"]],
                         [("SYN-P-0001", 1, 2), ("SYN-P-0001", 2, 3), ("SYN-P-0002", 1, 2)])
        self.assertEqual([p["period"] for p in result["pairs"]], ["period_1", "period_2", "period_2"])
        self.assertEqual(result["periods"][-1]["pairs"], 0)
        self.assertIsNone(result["periods"][-1]["patient_equal_contextual_set_jaccard"])

    def test_dose_coverage_conflicts_units_and_direction_are_separate(self):
        result = evaluate_fixture(fixture())
        summary = result["summary"]
        self.assertEqual(summary["dose_unresolved"], {"missing": 1, "conflict": 1, "incompatible_unit": 1})
        self.assertEqual(summary["dose_comparable_events"], 4)
        self.assertAlmostEqual(summary["dose_coverage"], 4 / 7)
        self.assertEqual(summary["dose_change_events"], 2)
        self.assertEqual(summary["dose_change_recall"], 0)
        self.assertEqual(summary["dose_direction_accuracy"], 0.5)
        self.assertAlmostEqual(summary["patient_equal_dose_mae_g"], 10 / 3)
        delta = next(row for row in result["pairs"][-1]["dose_comparisons"] if row["item_name"] == "\u767d\u828d")
        self.assertEqual((delta["observed_delta_g"], delta["observed_direction"], delta["absolute_error_g"]), (-5, "decrease", 5))
        self.assertEqual(result["pairs"][1]["dose_change_events"], 0)
        self.assertTrue(result["pairs"][1]["fully_resolved_no_change"])
        self.assertFalse(result["pairs"][-1]["fully_resolved_no_change"])

    def test_unresolved_dose_does_not_hide_known_composition_change(self):
        data = fixture()
        data["patients"][0]["visits"][0]["items"][0]["dose_pairs"] = []
        first = evaluate_fixture(data)["pairs"][0]
        self.assertFalse(first["fully_resolved_no_change"])
        data["patients"][1]["visits"][1]["items"][0]["dose_pairs"][0]["value"] = 10
        last = evaluate_fixture(data)["pairs"][-1]
        self.assertIsNone(last["fully_resolved_no_change"])

    def test_no_change_events_have_undefined_recall_not_perfect_scores(self):
        data = fixture()
        patient = data["patients"][0]
        patient["visits"] = patient["visits"][:2]
        patient["visits"][1]["items"] = copy.deepcopy(patient["visits"][0]["items"])
        data["patients"] = [patient]
        result = evaluate_fixture(data)["summary"]
        self.assertEqual(result["composition_no_change_pairs"], 1)
        self.assertIsNone(result["addition_precision"])
        self.assertIsNone(result["addition_recall"])
        self.assertIsNone(result["removal_recall"])
        self.assertIsNone(result["dose_change_recall"])
        self.assertEqual(result["patient_equal_dose_mae_g"], 0)

    def test_duplicate_recorded_doses_do_not_sum_and_missing_does_not_remove_valid_pair(self):
        data = fixture()
        dose = data["patients"][0]["visits"][0]["items"][0]["dose_pairs"]
        dose.extend([dict(dose[0]), {"value": None, "unit": "g"}, {"value": 0, "unit": "g"}])
        first = evaluate_fixture(data)["pairs"][0]["dose_comparisons"][0]
        self.assertEqual(first["status"], "comparable")
        self.assertEqual(first["observed_delta_g"], 5)

    def test_schema_order_identity_and_nonfinite_inputs_block(self):
        mutations = [
            lambda d: d.update(synthetic_mode=False),
            lambda d: d.update(source_path="private.csv"),
            lambda d: d["patients"][0].update(patient_code="person@example.test"),
            lambda d: d["patients"].append(copy.deepcopy(d["patients"][0])),
            lambda d: d["patients"][0]["visits"][1].update(sequence=3),
            lambda d: d["patients"][0]["visits"][1].update(day_offset=-1),
            lambda d: d["patients"][0]["visits"][1].update(items=[]),
            lambda d: d["patients"][0]["visits"][1].update(eligible="yes"),
            lambda d: d["patients"][0]["visits"][0]["items"].append(copy.deepcopy(d["patients"][0]["visits"][0]["items"][0])),
            lambda d: d["patients"][0]["visits"][0]["items"][0]["dose_pairs"][0].update(value=float("nan")),
            lambda d: d["patients"][0]["visits"][0]["items"][0]["dose_pairs"][0].update(value=True),
            lambda d: d["patients"][0]["visits"][0]["items"][0]["dose_pairs"][0].update(value=10 ** 1000),
        ]
        for index, mutation in enumerate(mutations):
            data = fixture()
            mutation(data)
            with self.subTest(case=index), self.assertRaises(BenchmarkError) as caught:
                evaluate_fixture(data)
            self.assertNotIn("person@example.test", str(caught.exception))

    def test_cli_file_snapshot_hash_and_new_only_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            result = run(FIXTURE, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), result)
            self.assertEqual(len(result["input_sha256"]), 64)
            with self.assertRaises(FileExistsError):
                run(FIXTURE, output)
            invalid = Path(temporary) / "invalid.json"
            invalid.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaises(BenchmarkError):
                run(invalid)
            invalid.write_text('{"synthetic_mode":false,"synthetic_mode":true}', encoding="utf-8")
            with self.assertRaises(BenchmarkError):
                run(invalid)


if __name__ == "__main__":
    unittest.main()
