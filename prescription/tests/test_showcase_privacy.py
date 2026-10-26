"""Synthetic-only showcase disclosure and comparison regressions."""
import copy
import json
import unittest

from mingyirx.dashboard_privacy import protect_payload


SHOWCASE = "synthetic-showcase-v1"


def fixture():
    payload = {"version": "test", "clinicalMode": True,
               "provenance": {"synthetic_mode": True, "min_public_n": 10},
               "groups": [], "summaries": [], "items": [], "changes": [],
               "combinations": [], "comparisons": [], "yearSummaries": [],
               "yearItems": [], "yearChanges": [], "research": {}}
    for code, label, total, changed, mean in (
        ("ra", "RA", 40, 20, ".25"),
        ("sjd", "SjD", 40, 20, ".5"),
        ("ra__sjd", "RA + SjD", 60, 30, ".4"),
    ):
        context = {"group": code, "stratum_type": "overall", "stratum": "all"}
        payload["groups"].append({"code": code, "label": label,
                                  "patients": str(total), "disease_count": len(code.split("__"))})
        payload["summaries"].append({**context, "patients": str(total), "repeat_patients": str(total)})
        for name in ("Herb A", "Herb B", "Herb C"):
            payload["items"].append({**context, "item_name": name,
                                     "group_patients": str(total), "exposed_patients": str(changed),
                                     "prevalence": ".5"})
        payload["changes"].append({**context, "item_name": "Herb A", "change_type": "addition",
                                   "repeat_patients": str(total), "patients_with_change": str(changed),
                                   "patient_prevalence": ".5", "mean_patient_transition_fraction": mean,
                                   "dose_patients": str(changed), "most_common_dose_values_g": "10;15",
                                   "most_common_dose_patients": "10", "most_common_dose_fraction": str(10 / changed),
                                   "most_common_dose_tied": "True"})
        support = 20 if code == "ra__sjd" else 10
        payload["combinations"].append({**context, "patients": str(total), "combination_size": "2",
                                        "combination": "Herb A | Herb B", "support_patients": str(support),
                                        "support": str(support / total),
                                        "bootstrap_core_selection_probability": ".95", "stable_core_combination": "True"})
    payload["comparisons"] = [{"combination_group": "ra__sjd", "single_group": single,
                               "stratum_type": "overall", "stratum": "all",
                               "change_type": "addition", "item_name": "Herb A",
                               "combination_prevalence": "999", "single_prevalence": "999",
                               "mean_transition_fraction_difference": "999",
                               "combination_dose_patients": "999", "unknown": "PRIVATE_UNKNOWN"}
                              for single in ("ra", "sjd")]
    return payload


class ShowcasePrivacyTests(unittest.TestCase):
    def test_only_explicit_boolean_synthetic_flag_allows_showcase(self):
        for flag in (False, None, 0, 1, "True", "true", "False", [], {}):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                source = fixture()
                source["provenance"]["synthetic_mode"] = flag
                protect_payload(source, profile=SHOWCASE)
        source = fixture()
        del source["provenance"]["synthetic_mode"]
        with self.assertRaises(ValueError):
            protect_payload(source, profile=SHOWCASE)
        self.assertTrue(protect_payload(fixture(), profile=SHOWCASE)["privacy"]["comparisons_enabled"])

    def test_unknown_profile_fails_and_conservative_remains_unchanged(self):
        with self.assertRaises(ValueError):
            protect_payload(fixture(), profile="unknown")
        default = protect_payload(fixture())
        self.assertEqual(default, protect_payload(fixture(), profile="conservative-v1"))
        self.assertEqual(default["comparisons"], [])
        self.assertEqual(default["combinations"], [])

    def test_comparisons_reconstruct_both_sides_from_admitted_changes(self):
        source = fixture()
        original = copy.deepcopy(source)
        result = protect_payload(source, profile=SHOWCASE)
        self.assertEqual(source, original)
        self.assertNotIn("PRIVATE_UNKNOWN", json.dumps(result))
        self.assertEqual(len(result["comparisons"]), 2)
        rows = {row["single_group"]: row for row in result["comparisons"]}
        ra = rows["ra"]
        self.assertEqual(ra["combination_label"], "RA + SjD")
        self.assertEqual(ra["single_label"], "RA")
        self.assertEqual(ra["combination_repeat_patients"], "60")
        self.assertEqual(ra["combination_patients_with_change"], "30")
        self.assertEqual(ra["single_repeat_patients"], "40")
        self.assertEqual(ra["single_patients_with_change"], "20")
        self.assertEqual(ra["combination_mean_transition_fraction"], ".4")
        self.assertEqual(ra["prevalence_difference"], 0)
        self.assertAlmostEqual(ra["mean_transition_fraction_difference"], .15)
        self.assertEqual(ra["higher_frequency"], "combination")
        self.assertAlmostEqual(rows["sjd"]["mean_transition_fraction_difference"], -.1)
        self.assertEqual(rows["sjd"]["higher_frequency"], "single")
        self.assertEqual(ra["combination_most_common_dose_values_g"], "10;15")
        self.assertEqual(ra["combination_dose_patients"], "30")

    def test_suppressed_side_or_missing_direction_never_becomes_zero(self):
        for field, value in (("patients_with_change", "9"), ("repeat_patients", "39"),
                             ("patients_with_change", "35"), ("change_type", "removal")):
            with self.subTest(field=field):
                source = fixture()
                source["changes"][0][field] = value
                result = protect_payload(source, profile=SHOWCASE)
                self.assertEqual([row["single_group"] for row in result["comparisons"]], ["sjd"])
        source = fixture()
        source["changes"] = []
        self.assertEqual(protect_payload(source, profile=SHOWCASE)["comparisons"], [])

    def test_comparison_references_must_match_exact_group_members(self):
        mutations = [
            {"combination_group": "missing"}, {"single_group": "missing"},
            {"combination_group": "ra"}, {"single_group": "ra__sjd"},
            {"stratum_type": "sex"}, {"stratum": "female"}, {"year": "2026"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                source = fixture()
                source["comparisons"] = [{**source["comparisons"][0], **mutation}]
                self.assertEqual(protect_payload(source, profile=SHOWCASE)["comparisons"], [])
        source = fixture()
        source["groups"][2]["code"] = "gout__sjd"
        source["groups"][2]["disease_count"] = 1
        self.assertEqual(protect_payload(source, profile=SHOWCASE)["comparisons"], [])
        source = fixture()
        source["groups"][2]["disease_count"] = 3
        self.assertEqual(protect_payload(source, profile=SHOWCASE)["comparisons"], [])

    def test_invalid_change_rates_do_not_produce_comparisons(self):
        for field, value in (("mean_patient_transition_fraction", "nan"),
                             ("mean_patient_transition_fraction", "1.1"),
                             ("mean_patient_transition_fraction", ".6"),
                             ("patient_prevalence", ".4"), ("patient_prevalence", "")):
            with self.subTest(field=field, value=value):
                source = fixture()
                source["changes"][0][field] = value
                rows = protect_payload(source, profile=SHOWCASE)["comparisons"]
                self.assertEqual([row["single_group"] for row in rows], ["sjd"])

    def test_three_disease_comparison_requires_a_member_single_group(self):
        source = fixture()
        source["groups"].append({"code": "gout", "label": "Gout", "patients": "40", "disease_count": 1})
        source["summaries"].append({**source["summaries"][0], "group": "gout"})
        source["changes"].append({**source["changes"][0], "group": "gout"})
        source["comparisons"] = [{**source["comparisons"][0], "single_group": "gout"}]
        self.assertEqual(protect_payload(source, profile=SHOWCASE)["comparisons"], [])
        for row in source["groups"]:
            if row["code"] == "ra__sjd":
                row.update(code="ra__sjd__gout", disease_count=3, label="RA + SjD + Gout")
        for collection in ("summaries", "changes"):
            for row in source[collection]:
                if row["group"] == "ra__sjd":
                    row["group"] = "ra__sjd__gout"
        source["comparisons"][0]["combination_group"] = "ra__sjd__gout"
        result = protect_payload(source, profile=SHOWCASE)["comparisons"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["combination_label"], "RA + SjD + Gout")
        self.assertEqual(result[0]["single_group"], "gout")

    def test_equal_frequency_and_missing_dose_are_preserved(self):
        source = fixture()
        source["changes"][0]["mean_patient_transition_fraction"] = ".4"
        for field in ("dose_patients", "most_common_dose_values_g", "most_common_dose_patients",
                      "most_common_dose_fraction", "most_common_dose_tied"):
            source["changes"][0].pop(field)
        row = protect_payload(source, profile=SHOWCASE)["comparisons"][0]
        self.assertEqual(row["higher_frequency"], "equal")
        self.assertEqual(row["mean_transition_fraction_difference"], 0)
        self.assertEqual(row["single_dose_patients"], "")

    def test_comparison_dose_fields_remain_suppressed(self):
        source = fixture()
        source["changes"][0]["most_common_dose_patients"] = "9"
        result = protect_payload(source, profile=SHOWCASE)["comparisons"][0]
        self.assertEqual(result["single_dose_patients"], "")
        self.assertEqual(result["single_most_common_dose_values_g"], "")
        self.assertEqual(result["combination_most_common_dose_patients"], "10")

    def test_drug_combinations_require_admitted_members_and_consistent_counts(self):
        source = fixture()
        row = source["combinations"][0]
        row["unknown"] = "PRIVATE_COMBINATION"
        result = protect_payload(source, profile=SHOWCASE)
        self.assertEqual(len(result["combinations"]), 3)
        self.assertNotIn("PRIVATE_COMBINATION", json.dumps(result))
        mutations = [
            {"combination": "Herb A | Missing"}, {"combination": "Herb A | Herb A"},
            {"combination_size": "3"}, {"patients": "50"},
            {"support_patients": "9"}, {"support_patients": "35", "support": ".875"},
            {"support_patients": "11", "support": ".275"}, {"support": ".9"},
            {"stratum_type": "sex"}, {"stratum": "female"}, {"year": "2026"},
            {"bootstrap_core_selection_probability": "nan"},
            {"stable_core_combination": "PRIVATE_FLAG"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                source = fixture()
                source["combinations"] = [{**source["combinations"][0], **mutation}]
                self.assertEqual(protect_payload(source, profile=SHOWCASE)["combinations"], [])

    def test_threshold_cannot_be_downgraded_by_showcase(self):
        source = fixture()
        source["provenance"]["min_public_n"] = 20
        protected = protect_payload(source, profile=SHOWCASE)
        self.assertEqual(protected["privacy"]["min_public_n"], 20)
        self.assertEqual(protected["combinations"], [])
        self.assertEqual([row["single_group"] for row in protected["comparisons"]], ["ra", "sjd"])
        for row in protected["comparisons"]:
            self.assertEqual(row["combination_dose_patients"], "")
        reprojection = protect_payload(protected, profile=SHOWCASE)
        self.assertEqual(reprojection["comparisons"], protected["comparisons"])
        self.assertEqual(reprojection["privacy"]["min_public_n"], 20)

    def test_duplicate_or_ambiguous_comparison_inputs_do_not_duplicate_rows(self):
        source = fixture()
        source["comparisons"].append(copy.deepcopy(source["comparisons"][0]))
        self.assertEqual(len(protect_payload(source, profile=SHOWCASE)["comparisons"]), 2)
        source["changes"].append({**source["changes"][0], "mean_patient_transition_fraction": ".3"})
        rows = protect_payload(source, profile=SHOWCASE)["comparisons"]
        self.assertEqual([row["single_group"] for row in rows], ["sjd"])


if __name__ == "__main__":
    unittest.main()
