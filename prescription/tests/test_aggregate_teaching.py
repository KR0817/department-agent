"""Fabricated aggregate fixtures only; every clinical attribute is simulated."""
from copy import deepcopy
import unittest

from mingyirx.aggregate_teaching import AggregateTeachingError, build_teaching_bundle
from mingyirx.inheritance import derive_pairs, validate_bundle
from mingyirx.reviewed_dashboard import TABLES, payload_hash


def aggregate_fixture(groups=("ra_strict", "sjd_strict", "as_strict", "ra_strict__sjd_strict")):
    """Model an approved aggregate shape without using real patients or statistics."""
    payload = {key: [] for key in TABLES}
    payload.update(version="synthetic-test-fixture", clinicalMode=True, research={},
                   provenance={"synthetic_mode": False, "min_public_n": 10,
                               "dataset_id": "AGGREGATE-FIXTURE-NO-REAL-DATA"})
    for group in groups:
        payload["groups"].append({"code": group, "group": group, "patients": "20"})
        payload["combinations"].append({"group": group, "stratum_type": "overall", "stratum": "all",
            "patients": "20", "combination_size": "3", "combination": "Herb A | Herb B | Herb C",
            "support_patients": "12", "support": "0.6", "bootstrap_core_selection_probability": "0.8",
            "stable_core_combination": "True"})
    return payload


class AggregateTeachingTests(unittest.TestCase):
    def test_five_targets_keep_exact_rows_and_pending_simulation(self):
        payloads = {"primary": aggregate_fixture(), "supplement": aggregate_fixture(("as_strict",))}
        before = deepcopy(payloads)
        bundle, sidecar = build_teaching_bundle(payloads)
        self.assertEqual(payloads, before)
        self.assertEqual(len(bundle["cases"]), 5)
        self.assertEqual(sidecar["case_count"], 5)
        self.assertEqual(sidecar["unavailable"], [])
        self.assertEqual(validate_bundle(bundle)["gate"], "PASS_WITH_WARNINGS")
        self.assertTrue(bundle["synthetic"])
        self.assertFalse(bundle["local_authorization"])
        self.assertTrue(all(row["review_status"] == "pending" and row["reviewer_id"] is None
                            for row in bundle["sources"] + bundle["physicians"]))
        self.assertTrue(all(row["origin"] == "algorithm" and row["status"] == "draft"
                            for row in bundle["annotations"]))
        self.assertEqual(bundle["experiences"], [])
        for anchor in sidecar["anchors"]:
            source = payloads[anchor["source"]]
            self.assertEqual(anchor["row"], source["combinations"][anchor["row_index"]])
            self.assertEqual(anchor["row_sha256"], payload_hash(anchor["row"]))
            self.assertEqual(anchor["source_payload_sha256"], payload_hash(source))
            self.assertEqual(anchor["group"], anchor["row"]["group"])
            self.assertIn("visits[*].pre.syndrome_codes", anchor["simulated_fields"])
        sidecar["anchors"][0]["row"]["support"] = "changed-test-copy"
        self.assertEqual(payloads, before)

    def test_adjacent_changes_are_simulated_and_no_marginal_dose_is_used(self):
        payload = aggregate_fixture(("ra_strict",))
        payload["items"] = [{"item_name": "Herb A", "most_common_dose_values_g": "999"}]
        bundle, sidecar = build_teaching_bundle({"primary": payload})
        visits = bundle["cases"][0]["visits"]
        self.assertEqual([len(v["prescription"]) for v in visits], [3, 2, 3])
        self.assertEqual([v["offset_days"] for v in visits], [0, 14, 28])
        self.assertTrue(all(drug["dose"] is None and drug["unit"] == "unknown" and drug["basis"] == "unknown"
                            for visit in visits for drug in visit["prescription"]))
        pairs = derive_pairs(bundle)
        self.assertEqual(len(pairs[0]["removed"]), 1)
        self.assertEqual(pairs[0]["removed"], pairs[1]["added"])
        self.assertTrue(all(row["delta"] is None and row["reason"] == "missing_dose"
                            for pair in pairs for row in pair["dose_changes"]))
        self.assertFalse(sidecar["syndromes_inferred_from_prescriptions"])
        for category, rows in bundle["vocabulary"].items():
            if category != "medicines":
                self.assertTrue(all(row["label"].startswith("\u6559\u5b66\u8bbe\u5b9a") for row in rows))

    def test_absent_or_suppressed_targets_stay_unavailable_without_borrowing(self):
        payload = aggregate_fixture(("ra_strict", "sjd_strict"))
        payload["combinations"][1].update(support_patients="9", support="0.45")
        bundle, sidecar = build_teaching_bundle({"primary": payload})
        self.assertEqual(len(bundle["cases"]), 1)
        self.assertEqual(sidecar["anchors"][0]["group"], "ra_strict")
        unavailable = {(row["source"], row["group"]) for row in sidecar["unavailable"]}
        self.assertIn(("primary", "sjd_strict"), unavailable)
        self.assertIn(("supplement", "as_strict"), unavailable)
        empty, empty_sidecar = build_teaching_bundle({})
        self.assertEqual(empty["cases"], [])
        self.assertEqual(empty_sidecar["gate"], "UNAVAILABLE")
        self.assertEqual(validate_bundle(empty)["gate"], "BLOCK")

    def test_selection_is_deterministic_and_preserves_full_raw_row(self):
        payload = aggregate_fixture(("ra_strict",))
        other = deepcopy(payload["combinations"][0])
        other.update(combination="Herb D | Herb E | Herb F", support_patients="14", support="0.7")
        other["reviewed_extra_field"] = "unchanged aggregate metadata"
        payload["combinations"].append(other)
        first = build_teaching_bundle({"primary": payload})
        second = build_teaching_bundle({"primary": payload})
        self.assertEqual(first, second)
        self.assertEqual(first[1]["anchors"][0]["row"], other)
        self.assertEqual(first[1]["anchors"][0]["row_index"], 1)

    def test_source_and_disclosure_boundary_fail_closed(self):
        for change in (
            lambda p: p["provenance"].update(synthetic_mode=True),
            lambda p: p["provenance"].update(min_public_n=9),
            lambda p: p.update(clinicalMode=False),
            lambda p: p["combinations"][0].update(combination="Herb A | Herb A | Herb C"),
            lambda p: p["combinations"][0].update(patients="21"),
            lambda p: p["combinations"][0].update(support="0.9"),
            lambda p: p["combinations"][0].update(bootstrap_core_selection_probability="NaN"),
            lambda p: p["combinations"][0].update(stable_core_combination=1),
            lambda p: p["combinations"][0].update(combination="<script> | Herb B | Herb C"),
        ):
            payload = aggregate_fixture(("ra_strict",))
            change(payload)
            with self.subTest(change=change):
                with self.assertRaises(AggregateTeachingError) as caught:
                    build_teaching_bundle({"primary": payload})
                self.assertNotIn("Herb", str(caught.exception))
                self.assertNotIn("<script>", str(caught.exception))
        with self.assertRaises(AggregateTeachingError):
            build_teaching_bundle({"unexpected-source": aggregate_fixture()})


if __name__ == "__main__":
    unittest.main()
