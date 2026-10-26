"""Integration checks for generated multidisease records and existing estimands."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from mingyirx.pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("showcase_builder", ROOT / "scripts/build_portfolio_demo.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class ShowcaseFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.sources = {}
        for source in ("primary", "supplement"):
            folder = cls.root / source
            config, records = BUILDER.source_fixture(folder, source)
            aggregates = folder / "aggregates"
            manifest = run_pipeline(config, records, aggregates)
            cls.sources[source] = (folder, config, records, aggregates, manifest)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_six_single_and_six_exact_comorbidity_groups_keep_separate_sources(self):
        expected = {
            "primary": {"ra": 120, "sjd": 100, "as": 100, "sle": 80, "oa": 120, "gout": 100,
                        "ra__sjd": 80, "sjd__sle": 60, "ra__oa": 60, "as__oa": 60,
                        "oa__gout": 60, "ra__sjd__oa": 40},
            "supplement": {"ra": 80, "sjd": 60, "as": 80, "sle": 60, "oa": 80, "gout": 60,
                           "ra__sjd": 60, "sjd__sle": 40, "ra__oa": 40, "as__oa": 40,
                           "oa__gout": 40, "ra__sjd__oa": 40},
        }
        for source, (_, _, _, output, manifest) in self.sources.items():
            summaries = rows(output / "clinical_phenotype_summary.csv")
            overall = {row["group"]: int(row["patients"]) for row in summaries if row["stratum_type"] == "overall"}
            self.assertEqual(overall, expected[source])
            self.assertIn(manifest["gate"], {"PASS", "PASS_WITH_WARNINGS"})

    def test_real_label_vocabulary_keeps_all_assignments_synthetic(self):
        vocabulary = json.loads(BUILDER.VOCABULARY.read_text(encoding="utf-8"))
        labels = {item["name"] for item in vocabulary["items"]}
        self.assertEqual(len(labels), 18)
        self.assertIn("\u767d\u828d", labels)
        for _, config, records, _, _ in self.sources.values():
            data = rows(records)
            self.assertEqual({row["item_name"] for row in data}, labels)
            self.assertTrue(all(row["patient_id"].startswith("SYNTH_") for row in data))
            self.assertIs(json.loads(config.read_text())["synthetic_mode"], True)

    def test_tied_and_missing_recorded_doses_reach_original_aggregator(self):
        items = rows(self.sources["primary"][3] / "clinical_first_prescription_item_prevalence.csv")
        first = next(row for row in items if row["group"] == "ra" and row["stratum_type"] == "overall" and row["item_name"] == "\u767d\u828d")
        self.assertEqual(int(first["exposed_patients"]), 120)
        self.assertEqual(first["most_common_dose_values_g"], "10;15")
        self.assertEqual(int(first["most_common_dose_patients"]), 60)
        self.assertEqual(float(first["most_common_dose_fraction"]), 0.5)
        missing = next(row for row in items if row["group"] == "ra" and row["stratum_type"] == "overall" and row["item_name"] == "\u77e5\u6bcd")
        self.assertEqual(missing["most_common_dose_values_g"], "")
        self.assertGreater(int(missing["exposed_patients"]), 0)

    def test_comorbidity_comparisons_cover_all_members_with_both_directions(self):
        comparisons = rows(self.sources["primary"][3] / "clinical_item_change_comparison.csv")
        comparisons = [row for row in comparisons if row["stratum_type"] == "overall"]
        members = {row["single_group"] for row in comparisons if row["combination_group"] == "ra__sjd__oa"}
        self.assertEqual(members, {"ra", "sjd", "oa"})
        differences = [float(row["mean_transition_fraction_difference"]) for row in comparisons]
        self.assertTrue(any(value > 0 for value in differences))
        self.assertTrue(any(value < 0 for value in differences))
        for row in comparisons:
            self.assertAlmostEqual(float(row["mean_transition_fraction_difference"]),
                                   float(row["combination_mean_transition_fraction"]) - float(row["single_mean_transition_fraction"]), places=5)

    def test_pairs_triples_and_four_years_are_nonempty(self):
        for source, (_, _, _, output, _) in self.sources.items():
            combinations = rows(output / "clinical_frequent_item_combinations.csv")
            stable = [row for row in combinations if row["stratum_type"] == "overall" and row["stable_core_combination"] == "True"]
            self.assertEqual({row["combination_size"] for row in stable}, {"2", "3"})
            years = {row["year"] for row in rows(output / "clinical_year_summary.csv")}
            self.assertEqual(years, {"2022", "2023", "2024", "2025"} if source == "primary" else {"2023", "2024", "2025", "2026"})


if __name__ == "__main__":
    unittest.main()
