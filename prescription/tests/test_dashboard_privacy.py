"""Synthetic disclosure-boundary regressions for the presentation projection."""
import copy
import json
import unittest

from mingyirx.dashboard_privacy import protect_payload


def fixture(n=20, exposed=10):
    context = {"group": "ra", "stratum_type": "overall", "stratum": "all"}
    item = {**context, "item_name": "Synthetic herb", "group_patients": str(n),
            "exposed_patients": str(exposed), "prevalence": str(exposed/n)}
    return {"version": "test", "clinicalMode": True,
            "provenance": {"synthetic_mode": True},
            "groups": [{"code": "ra", "label": "RA", "patients": str(n)}],
            "summaries": [{**context, "patients": str(n), "repeat_patients": "1",
                           "visits": str(n+1), "transitions": "1"}],
            "items": [item], "changes": [], "longitudinal": [],
            "combinations": [{**context, "combination": "PRIVATE_PAIR"}],
            "comparisons": [], "yearSummaries": [{**context, "year": "2026", "patients": str(n)}],
            "yearItems": [{**item, "year": "2026"}], "yearChanges": [],
            "research": {"nodes": [{"item_name": "PRIVATE_NODE"}], "cohorts": []}}


class PresentationPrivacyTests(unittest.TestCase):
    def test_patient_and_complement_boundaries(self):
        for n, exposed, expected in [(9, 9, 0), (10, 10, 1), (11, 10, 0), (20, 10, 1), (21, 11, 1)]:
            with self.subTest(n=n, exposed=exposed):
                result = protect_payload(fixture(n, exposed), 10)
                self.assertEqual(len(result["items"]), expected)
        result = protect_payload(fixture(11, 10), 10)
        self.assertEqual(result["summaries"][0]["repeat_patients"], "")
        self.assertNotIn("visits", result["summaries"][0])
        self.assertNotIn("transitions", result["summaries"][0])

    def test_projection_removes_hidden_overlaps_without_mutation(self):
        source = fixture()
        source["items"].append({**source["items"][0], "stratum_type": "sex", "stratum": "female", "item_name": "PRIVATE_STRATUM"})
        original = copy.deepcopy(source)
        result = protect_payload(source, 10)
        self.assertEqual(source, original)
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertEqual(result["privacy"]["profile"], "conservative-v1")

    def test_dose_modes_require_usable_and_category_complements(self):
        for dose_n, mode_n, expected in [(9, 9, False), (10, 10, True), (11, 10, False), (20, 10, True)]:
            with self.subTest(dose_n=dose_n, mode_n=mode_n):
                source = fixture(40, 20)
                source["items"][0].update(dose_patients=str(dose_n), most_common_dose_patients=str(mode_n),
                    most_common_dose_values_g="12", most_common_dose_fraction=str(mode_n/dose_n), most_common_dose_tied="False")
                result = protect_payload(source, 10)["items"][0]
                self.assertEqual(bool(result.get("most_common_dose_values_g")), expected)

    def test_real_annual_overlap_is_not_serialized(self):
        source = fixture()
        source["provenance"]["synthetic_mode"] = False
        result = protect_payload(source, 10)
        self.assertEqual(result["yearItems"], [])
        self.assertEqual(result["yearSummaries"], [])
        self.assertEqual(protect_payload(fixture(), 10)["yearItems"][0]["year"], "2026")

    def test_real_first_and_removal_projections_cannot_be_differenced(self):
        source = fixture(21, 11)
        source["summaries"][0]["repeat_patients"] = "21"
        source["changes"] = [{"group": "ra", "stratum_type": "overall", "stratum": "all",
                              "item_name": "Synthetic herb", "change_type": "removal",
                              "repeat_patients": "21", "patients_with_change": "10",
                              "patient_prevalence": str(10/21), "mean_patient_transition_fraction": str(10/21)}]
        self.assertEqual(len(protect_payload(source, 10)["changes"]), 1)
        for mode in [False, None]:
            source["provenance"]["synthetic_mode"] = mode
            protected = protect_payload(source, 10)
            self.assertEqual(protected["changes"], [])
            self.assertEqual(len(protected["items"]), 1)

    def test_annual_repeat_complement_cannot_reappear_via_change_rows(self):
        source = fixture(21, 11)
        source["yearSummaries"][0]["repeat_patients"] = "20"
        source["yearChanges"] = [{"group": "ra", "stratum_type": "overall", "stratum": "all", "year": "2026",
                                  "item_name": "Synthetic herb", "change_type": "addition", "repeat_patients": "20",
                                  "patients_with_change": "10", "patient_prevalence": ".5", "mean_patient_transition_fraction": ".5"}]
        protected = protect_payload(source, 10)
        self.assertEqual(protected["yearSummaries"][0]["repeat_patients"], "")
        self.assertEqual(protected["yearChanges"], [])

    def test_rows_require_the_matching_source_denominator(self):
        source = fixture(40, 20)
        source["items"][0]["group_patients"] = "30"
        source["yearItems"][0]["group_patients"] = "30"
        protected = protect_payload(source, 10)
        self.assertEqual(protected["items"], [])
        self.assertEqual(protected["yearItems"], [])
        source = fixture(40, 20)
        source["summaries"][0]["patients"] = "30"
        self.assertEqual(protect_payload(source, 10)["summaries"], [])
        source = fixture(40, 20)
        source["summaries"][0]["repeat_patients"] = "10"
        source["yearSummaries"][0]["repeat_patients"] = "10"
        change = {"group": "ra", "stratum_type": "overall", "stratum": "all",
                  "item_name": "Synthetic herb", "change_type": "removal", "repeat_patients": "20",
                  "patients_with_change": "10", "patient_prevalence": ".5", "mean_patient_transition_fraction": ".5"}
        source["changes"] = [change]
        source["yearChanges"] = [{**change, "year": "2026"}]
        protected = protect_payload(source, 10)
        self.assertEqual(protected["changes"], [])
        self.assertEqual(protected["yearChanges"], [])

    def test_empty_payload_and_invalid_threshold(self):
        source = fixture(9, 9)
        self.assertEqual(protect_payload(source, 10)["groups"], [])
        for threshold in [0, 9, True, 10.5]:
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                protect_payload(source, threshold)

    def test_requested_threshold_cannot_downgrade_the_source_policy(self):
        source = fixture(35, 20)
        source["provenance"].update(synthetic_mode=False, min_public_n=20)
        protected = protect_payload(source, 10)
        self.assertEqual(protected["items"], [])
        self.assertEqual(protected["privacy"]["min_public_n"], 20)
        self.assertEqual(protected["provenance"]["min_public_n"], 20)
        self.assertEqual(protected["privacy"]["requested_min_public_n"], 10)
        source["provenance"]["min_public_n"] = 10
        protected = protect_payload(source, 20)
        self.assertEqual(protected["privacy"]["min_public_n"], 20)
        self.assertEqual(protected["provenance"]["min_public_n"], 10)
        self.assertEqual(protected["privacy"]["source_min_public_n"], 10)
        protected_again = protect_payload(protected, 10)
        self.assertEqual(protected_again["privacy"]["min_public_n"], 20)
        self.assertEqual(protected_again["privacy"]["input_presentation_min_public_n"], 20)
