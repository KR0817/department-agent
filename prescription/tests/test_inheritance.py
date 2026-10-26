"""Synthetic engineering checks; confirmed fixture states are invented examples."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mingyirx import inheritance
from mingyirx.inheritance import (
    InheritanceError, assert_output_allowed, build_view, derive_pairs, freeze_bundle,
    load_bundle, read_frozen, template_bundle, validate_bundle, verify_frozen,
)
from mingyirx.io import file_sha256


FIXTURE = Path(__file__).resolve().parents[1] / "data/synthetic/inheritance_cases.json"


class InheritanceTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(FIXTURE)

    def assert_block(self, bundle, code=None):
        result = validate_bundle(bundle)
        self.assertEqual(result["gate"], "BLOCK")
        if code:
            self.assertIn(code, [error["code"] for error in result["errors"]])
        self.assertTrue(all(set(error) == {"code", "path"} for error in result["errors"]))
        return result

    def write_bundle(self, path, bundle=None):
        path.write_text(json.dumps(self.bundle if bundle is None else bundle, ensure_ascii=False), encoding="utf-8")
        return path

    def test_fixture_is_explicitly_synthetic_and_counts_subjects_once(self):
        result = validate_bundle(self.bundle)
        self.assertEqual(result["gate"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["counts"], {"cases": 5, "subjects": 4, "visits": 13, "physicians": 3,
                         "sources": 3, "reviewers": 1, "annotations": 3, "experiences": 1,
                         "pairs": 8, "eligible_pairs": 6, "unresolved_pairs": 2})
        self.assertTrue(self.bundle["synthetic"])
        self.assertEqual(self.bundle["cases"][0]["subject_id"], self.bundle["cases"][1]["subject_id"])
        readiness = build_view(self.bundle)["readiness"]
        self.assertEqual(readiness["confirmed_physicians"], 2)
        self.assertEqual(readiness["evidence_state"], "SYNTHETIC_WORKFLOW_ONLY")
        for key in ("source_hashes_independently_verified", "clinical_effectiveness_verified", "parent_chain_verified"):
            self.assertFalse(readiness[key])
        query = self.bundle["cases"][0]["visits"][0]["pre"]
        different = self.bundle["cases"][3]["visits"][0]["pre"]
        self.assertTrue({row["code"] for row in query["symptoms"]} & {row["code"] for row in different["symptoms"]})
        self.assertNotEqual(query["symptoms"], different["symptoms"])
        self.assertNotEqual(query["tongue_codes"], different["tongue_codes"])

    def test_blank_template_is_not_freezeable(self):
        blank = template_bundle()
        self.assertFalse(blank["synthetic"])
        self.assertFalse(blank["local_authorization"])
        self.assert_block(blank)
        blank.update(synthetic=True)
        self.assert_block(blank, "BLANK_BUNDLE")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_bundle(root / "blank.json", blank)
            with self.assertRaises(InheritanceError):
                freeze_bundle(root / "blank.json", root / "frozen")
            self.assertFalse((root / "frozen").exists())

    def test_import_rejects_duplicate_keys_nonfinite_malformed_size_and_bad_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            for content in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{', b'\xff', b'[]',
                            b' ' * (inheritance.MAX_INPUT_BYTES + 1)):
                with self.subTest(content_length=len(content)):
                    path.write_bytes(content)
                    with self.assertRaises(InheritanceError) as caught:
                        load_bundle(path)
                    self.assertNotIn(str(path), str(caught.exception))

    def test_import_does_not_read_declared_sources_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_bundle(Path(temporary) / "input.json")
            initial = file_sha256(path)
            with patch.object(inheritance, "file_sha256", wraps=file_sha256) as hashes:
                freeze_bundle(path, Path(temporary) / "frozen")
            self.assertTrue(all(call.args[0] == Path(inheritance.__file__) for call in hashes.call_args_list))
            self.assertEqual(file_sha256(path), initial)

    def test_unknown_fields_fail_at_coded_parent_without_echoing_unknown_key(self):
        malicious = "private-unrecognized-field"
        locations = [self.bundle, self.bundle["sources"][0], self.bundle["cases"][0],
                     self.bundle["cases"][0]["visits"][0]["pre"], self.bundle["experiences"][0]]
        for location in locations:
            location[malicious] = "private-value"
            result = self.assert_block(self.bundle, "EXACT_KEYS_REQUIRED")
            serialized = json.dumps(result)
            self.assertNotIn(malicious, serialized)
            self.assertNotIn("private-value", serialized)
            del location[malicious]

    def test_text_boundary_rejects_html_contacts_dates_and_controls(self):
        examples = ["<script>alert(1)</script>", "https://example.test", "person@example.test", "13800138000",
                    "11010519491231002X", "2026-10-24", "2026/10/24", "20261024", "555-123-4567",
                    "ordinary\ntext", "www.example.test", "example.com", "ordinary\u200btext", "file:///private"]
        for value in examples:
            with self.subTest(value=value):
                bundle = copy.deepcopy(self.bundle)
                bundle["annotations"][0]["statement"] = value
                result = self.assert_block(bundle, "TEXT_UNSAFE_OR_INVALID")
                self.assertNotIn(value, json.dumps(result, ensure_ascii=False))

    def test_bad_types_limits_and_unsafe_ids_block(self):
        mutations = [lambda b: b.update(revision=True), lambda b: b.update(synthetic="true"),
                     lambda b: b.update(dataset_id="../../private"), lambda b: b.update(cases={}),
                     lambda b: b.update(cases=b["cases"] * 21),
                     lambda b: b["cases"][0].update(visits=b["cases"][0]["visits"] * 7),
                     lambda b: b["cases"][0]["visits"][0].update(prescription=b["cases"][0]["visits"][0]["prescription"] * 21),
                     lambda b: b["vocabulary"].update(symptoms=None),
                     lambda b: b["cases"][0]["visits"][0].update(sequence=1.1),
                     lambda b: b["cases"][0]["visits"][0].update(offset_days=-1),
                     lambda b: b["cases"][0]["visits"][0]["pre"]["symptoms"][0].update(severity=True)]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle)
            mutate(bundle)
            self.assert_block(bundle)
        for value in (False, -1, 0, float("nan"), float("inf"), 10 ** 1000, "12"):
            bundle = copy.deepcopy(self.bundle)
            bundle["cases"][0]["visits"][0]["prescription"][0]["dose"] = value
            self.assert_block(bundle)

    def test_duplicate_ids_codes_drugs_and_invalid_references_block(self):
        mutations = [lambda b: b["reviewers"].append(copy.deepcopy(b["reviewers"][0])),
                     lambda b: b["vocabulary"]["medicines"].append(copy.deepcopy(b["vocabulary"]["medicines"][0])),
                     lambda b: b["cases"][0]["condition_codes"].append("SYN_FATIGUE"),
                     lambda b: b["cases"][0]["visits"][0]["prescription"].append(copy.deepcopy(b["cases"][0]["visits"][0]["prescription"][0])),
                     lambda b: b["cases"][0]["visits"][0]["pre"]["symptoms"].append(copy.deepcopy(b["cases"][0]["visits"][0]["pre"]["symptoms"][0])),
                     lambda b: b["cases"][0]["visits"][1].update(visit_id="V-1"),
                     lambda b: b["cases"][0].update(physician_id="UNKNOWN"),
                     lambda b: b["cases"][0].update(source_id="SRC-SYN-B"),
                     lambda b: b["cases"][0]["visits"][0]["pre"].update(pulse_codes=["UNKNOWN"])]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle)
            mutate(bundle)
            self.assert_block(bundle)

    def test_reviewers_and_confirmed_sources_are_required_for_approval(self):
        mutations = [lambda b: b["sources"][0].update(reviewer_id=None),
                     lambda b: b["sources"][2].update(reviewer_id="R-SYN-01"),
                     lambda b: b["sources"][0].update(reviewer_id="UNKNOWN"),
                     lambda b: b["sources"][0].update(review_status="pending", reviewer_id=None),
                     lambda b: b["physicians"][0].update(source_ids=[]),
                     lambda b: b["physicians"][0].update(review_status="pending", reviewer_id=None),
                     lambda b: b["annotations"][2].update(status="approved", reviewer_id="R-SYN-01"),
                     lambda b: b["annotations"][0].update(reviewer_id=None),
                     lambda b: b["annotations"][0].update(author_id="UNKNOWN")]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle)
            mutate(bundle)
            self.assert_block(bundle)

    def test_annotation_hash_binding_and_algorithm_origin_are_preserved(self):
        self.assertEqual(self.bundle["annotations"][1]["origin"], "algorithm")
        self.assertEqual(self.bundle["annotations"][1]["status"], "approved")
        for changes in ({"source_sha256": "a" * 64}, {"source_id": "SRC-SYN-B"}, {"visit_id": "V-UNKNOWN"}):
            bundle = copy.deepcopy(self.bundle)
            bundle["annotations"][0].update(changes)
            self.assert_block(bundle)
        self.assertEqual(build_view(self.bundle)["readiness"]["approved_annotations"], 2)
        self.assertEqual(self.bundle["annotations"][1]["origin"], "algorithm")

    def test_experience_requires_human_annotation_and_adjacent_disjoint_confirmed_pairs(self):
        mutations = [lambda e: e.update(supporting_pairs=[]),
                     lambda e: e.update(annotation_ids=["A-SYN-02"]),
                     lambda e: e.update(reviewer_id=None),
                     lambda e: e["supporting_pairs"][0].update(to_visit_id="V-3"),
                     lambda e: e["supporting_pairs"][0].update(case_id="C-SYN-03"),
                     lambda e: e["supporting_pairs"][0].update(case_id="C-SYN-05"),
                     lambda e: e["exception_pairs"].append(copy.deepcopy(e["supporting_pairs"][0])),
                     lambda e: e["supporting_pairs"].append(copy.deepcopy(e["supporting_pairs"][0]))]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle)
            mutate(bundle["experiences"][0])
            self.assert_block(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["annotations"][0]["visit_id"] = "V-3"
        self.assert_block(bundle, "APPROVED_HUMAN_ANNOTATION_REQUIRED")

    def test_empty_exceptions_and_unavailable_outcomes_do_not_invent_success(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["experiences"][0]["exception_pairs"] = []
        for case in bundle["cases"]:
            for visit in case["visits"]:
                visit["outcome_codes"] = []
        result = validate_bundle(bundle)
        self.assertEqual(result["errors"], [])
        self.assertIn("EXCEPTIONS_NOT_RECORDED", [warning["code"] for warning in result["warnings"]])

    def test_same_day_ambiguity_marks_all_touching_edges_and_never_reconnects(self):
        pairs = [pair for pair in derive_pairs(self.bundle) if pair["case_id"] == "C-SYN-03"]
        self.assertEqual([(p["from_visit_id"], p["to_visit_id"]) for p in pairs], [("V-1", "V-2"), ("V-2", "V-3")])
        for pair in pairs:
            self.assertEqual(pair["status"], "unresolved_order")
            for key in ("added", "removed", "retained", "dose_changes", "symptom_changes"):
                self.assertEqual(pair[key], [])
        bundle = copy.deepcopy(self.bundle)
        visits = bundle["cases"][2]["visits"]
        visits.insert(0, copy.deepcopy(visits[0]))
        visits[0].update(visit_id="V-BEFORE", offset_days=0, sequence=1, order_known=True)
        for index, visit in enumerate(visits[1:], start=2):
            visit["sequence"] = index
            visit["offset_days"] += 1
        pairs = [pair for pair in derive_pairs(bundle) if pair["case_id"] == "C-SYN-03"]
        self.assertEqual(len(pairs), 3)
        self.assertTrue(all(pair["status"] == "unresolved_order" for pair in pairs))

    def test_known_same_day_order_is_eligible_and_invalid_stored_order_blocks(self):
        bundle = copy.deepcopy(self.bundle)
        for visit in bundle["cases"][2]["visits"]:
            visit["order_known"] = True
        pairs = [pair for pair in derive_pairs(bundle) if pair["case_id"] == "C-SYN-03"]
        self.assertEqual(pairs[0]["interval_days"], 0)
        self.assertTrue(all(pair["status"] == "eligible" for pair in pairs))
        for changes in ({"sequence": 1}, {"offset_days": -1}):
            changed = copy.deepcopy(self.bundle)
            changed["cases"][0]["visits"][1].update(changes)
            self.assert_block(changed)
        bundle["cases"][0]["visits"][2]["offset_days"] = 1
        self.assert_block(bundle, "VISIT_ORDER_INVALID")

    def test_dose_and_composition_are_separate_and_no_change_is_explicit(self):
        pairs = derive_pairs(self.bundle)
        first = pairs[0]
        self.assertEqual(first["added"], ["CHENPI"])
        hq = next(row for row in first["dose_changes"] if row["medicine_code"] == "HUANGQI")
        self.assertEqual((hq["direction"], hq["delta"], hq["reason"]), ("increase", 5, "comparable"))
        second = pairs[1]
        self.assertEqual({row["reason"] for row in second["dose_changes"]}, {"comparable", "missing_dose", "unknown_unit"})
        unchanged = next(pair for pair in pairs if pair["case_id"] == "C-SYN-02")
        self.assertEqual((unchanged["added"], unchanged["removed"]), ([], []))
        self.assertTrue(all(row["direction"] == "unchanged" for row in unchanged["dose_changes"]))
        exception = next(pair for pair in pairs if pair["case_id"] == "C-SYN-04")
        self.assertEqual((exception["added"], exception["removed"]), (["MAIDONG"], ["FULING"]))
        self.assertEqual({row["reason"] for row in exception["dose_changes"]}, {"incompatible_unit", "incompatible_formulation"})

    def test_all_dose_comparability_reasons_and_decrease(self):
        cases = [({"dose": None}, "missing_dose"), ({"unit": "unknown"}, "unknown_unit"),
                 ({"unit": "mg"}, "incompatible_unit"), ({"basis": "unknown"}, "unknown_basis"),
                 ({"basis": "per_dose"}, "incompatible_basis"), ({"formulation": "other"}, "unknown_formulation"),
                 ({"formulation": "granule"}, "incompatible_formulation"),
                 ({"preparation": "unknown"}, "unknown_preparation"), ({"preparation": "processed"}, "incompatible_preparation")]
        for changes, reason in cases:
            bundle = copy.deepcopy(self.bundle)
            bundle["cases"][0]["visits"][1]["prescription"][0].update(changes)
            row = next(row for row in derive_pairs(bundle)[0]["dose_changes"] if row["medicine_code"] == "HUANGQI")
            self.assertEqual((row["reason"], row["direction"], row["delta"]), (reason, "unresolved", None))
        bundle = copy.deepcopy(self.bundle)
        bundle["cases"][0]["visits"][1]["prescription"][0]["dose"] = 10
        row = next(row for row in derive_pairs(bundle)[0]["dose_changes"] if row["medicine_code"] == "HUANGQI")
        self.assertEqual((row["direction"], row["delta"]), ("decrease", -5))

    def test_missing_or_absent_severity_never_becomes_improvement(self):
        first = derive_pairs(self.bundle)[0]
        self.assertEqual({row["code"]: row["direction"] for row in first["symptom_changes"]},
                         {"FATIGUE": "improved", "DRY_MOUTH": "unknown"})
        bundle = copy.deepcopy(self.bundle)
        bundle["cases"][0]["visits"][1]["pre"]["symptoms"] = []
        self.assertTrue(all(row["direction"] == "unknown" for row in derive_pairs(bundle)[0]["symptom_changes"]))

    def test_future_outcomes_do_not_change_pair_features(self):
        before = derive_pairs(self.bundle)
        for case in self.bundle["cases"]:
            for visit in case["visits"]:
                visit["outcome_codes"] = ["SYN_CHANGE"]
        self.assertEqual(derive_pairs(self.bundle), before)

    def test_revision_hash_syntax_and_parent_boundary(self):
        for revision, parent in ((0, None), (1, "a" * 64), (2, None), (2, "stale")):
            bundle = dict(self.bundle, revision=revision, parent_sha256=parent)
            self.assert_block(bundle)
        bundle = dict(self.bundle, revision=2, parent_sha256=validate_bundle(self.bundle)["content_sha256"])
        result = validate_bundle(bundle)
        self.assertEqual(result["errors"], [])
        self.assertIn("PARENT_CHAIN_NOT_VERIFIED", [warning["code"] for warning in result["warnings"]])
        self.assertFalse(build_view(bundle)["readiness"]["parent_chain_verified"])

    def test_freeze_verify_and_snapshot_read_are_deterministic_and_new_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.write_bundle(root / "input.json")
            source_hash = file_sha256(source)
            first = freeze_bundle(source, root / "one")
            second = freeze_bundle(source, root / "two")
            self.assertEqual(first, second)
            self.assertEqual(first["content_sha256"], file_sha256(root / "one/bundle.json"))
            self.assertEqual(verify_frozen(root / "one")["artifact_check"], "PASS")
            self.assertEqual(read_frozen(root / "one"), self.bundle)
            for name in (*inheritance.ARTIFACTS, "manifest.json"):
                self.assertEqual((root / "one" / name).read_bytes(), (root / "two" / name).read_bytes())
            self.assertEqual(file_sha256(source), source_hash)
            with self.assertRaises(InheritanceError):
                freeze_bundle(source, root / "one")

    def test_frozen_verification_rejects_tampering_extra_missing_and_validator_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.write_bundle(root / "input.json")
            for kind in ("bundle", "validation", "manifest", "extra", "missing", "validator"):
                target = root / kind
                if kind == "missing":
                    target.mkdir()
                else:
                    freeze_bundle(source, target)
                    if kind in ("bundle", "validation"):
                        (target / (kind + ".json")).write_text("{}", encoding="utf-8")
                    elif kind == "extra":
                        (target / "extra.json").write_text("{}", encoding="utf-8")
                    else:
                        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
                        manifest["validator_sha256" if kind == "validator" else "synthetic"] = "0" * 64 if kind == "validator" else False
                        (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.subTest(kind=kind), self.assertRaises(InheritanceError):
                    verify_frozen(target)

    def test_read_frozen_uses_verified_snapshot_without_second_bundle_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.write_bundle(root / "input.json")
            freeze_bundle(source, root / "frozen")
            real_read = inheritance._read_bytes
            calls = []

            def read_then_change(path):
                snapshot = real_read(path)
                calls.append(path.name)
                if path.name == "bundle.json":
                    path.write_text("{}", encoding="utf-8")
                return snapshot

            with patch.object(inheritance, "_read_bytes", side_effect=read_then_change):
                recovered = read_frozen(root / "frozen")
            self.assertEqual(recovered, self.bundle)
            self.assertEqual(calls.count("bundle.json"), 1)
            with self.assertRaises(InheritanceError):
                verify_frozen(root / "frozen")

    def test_restricted_flags_use_isolated_mocked_work_guard_without_real_data(self):
        # Only fixture content is used; these flags exercise the restricted branch.
        restricted = dict(self.bundle, synthetic=False, local_authorization=True, deidentified=True)
        with tempfile.TemporaryDirectory() as temporary:
            # Match the resolved production root, including Windows short paths.
            root = Path(temporary).resolve()
            with patch.object(inheritance, "CHECKOUT_ROOT", root), patch.object(inheritance.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as ignored:
                source = self.write_bundle(root / "synthetic-branch-test.json", restricted)
                frozen = root / "work" / "new" / "frozen"
                freeze_bundle(source, frozen)
                self.assertEqual(verify_frozen(frozen)["evidence_state"], "LOCAL_DECLARATIONS_UNVERIFIED")
                self.assertTrue(ignored.called)
                self.assertIn("--no-index", ignored.call_args.args[0])
                for path in (root / "outputs" / "frozen", root / "work-other" / "frozen", root / "work"):
                    with self.assertRaises(InheritanceError):
                        assert_output_allowed(restricted, path)
                with patch.object(inheritance.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                    with self.assertRaises(InheritanceError):
                        assert_output_allowed(restricted, root / "work" / "not-ignored")
            for key in ("local_authorization", "deidentified"):
                invalid = dict(restricted, **{key: False})
                self.assert_block(invalid, "LOCAL_DECLARATIONS_REQUIRED")

    def test_link_paths_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "new"
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(InheritanceError):
                    assert_output_allowed(self.bundle, target)
                with self.assertRaises(InheritanceError):
                    load_bundle(FIXTURE)
            target.mkdir()
            with self.assertRaises(InheritanceError):
                assert_output_allowed(self.bundle, target)

    def test_canonical_hash_is_stable_under_object_key_order(self):
        reverse = dict(reversed(list(self.bundle.items())))
        self.assertEqual(validate_bundle(reverse)["content_sha256"], validate_bundle(self.bundle)["content_sha256"])
        canonical = (json.dumps(self.bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), validate_bundle(self.bundle)["content_sha256"])


if __name__ == "__main__":
    unittest.main()
