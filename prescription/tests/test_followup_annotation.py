"""Local metadata validation and new-only freeze, with synthetic records only."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from mingyirx.followup_annotation import (
    FIELDS, PROTOCOL_VERSION, AnnotationError, freeze_annotations,
    prepare_template, validate_annotations, verify_frozen,
)


CONTRACT, EVIDENCE = "a" * 64, "b" * 64


def row(kind="synthetic_smoke"):
    return dict(zip(FIELDS, (PROTOCOL_VERSION, CONTRACT, EVIDENCE, kind, "C-0001", "R-0001",
                            "verified", "before_prescription", "stable", "unchanged",
                            "independent_declared", "absent", "not_available")))


def write_rows(path, rows, fields=FIELDS):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class FollowupAnnotationTests(unittest.TestCase):
    def test_blank_template_does_not_imply_annotations_and_cannot_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = prepare_template(root / "template", CONTRACT, EVIDENCE)
            self.assertEqual(result["evidence_state"], "NO_ANNOTATIONS_COLLECTED")
            with self.assertRaises(AnnotationError):
                freeze_annotations(root / "template/annotations.csv", root / "frozen", CONTRACT, EVIDENCE, "synthetic_smoke")
            self.assertFalse((root / "frozen").exists())
            with self.assertRaises(AnnotationError):
                prepare_template(root / "template", CONTRACT, EVIDENCE)

    def test_freeze_is_deterministic_new_only_and_bound_to_expected_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.csv"
            write_rows(source, [dict(row(), reviewer_id="R-0002"), row()])
            first = freeze_annotations(source, root / "one", CONTRACT, EVIDENCE, "synthetic_smoke")
            second = freeze_annotations(source, root / "two", CONTRACT, EVIDENCE, "synthetic_smoke")
            self.assertEqual(first, second)
            self.assertEqual((first["records"], first["cases"], first["reviewers"]), (2, 1, 2))
            self.assertFalse(first["clinical_evidence"])
            self.assertFalse(first["independent_reference_verified"])
            self.assertEqual(verify_frozen(root / "one", CONTRACT, EVIDENCE)["artifact_check"], "PASS")
            for name in ("manifest.json", *first["artifacts"]):
                self.assertEqual((root / "one" / name).read_bytes(), (root / "two" / name).read_bytes())
            with self.assertRaises(AnnotationError):
                freeze_annotations(source, root / "one", CONTRACT, EVIDENCE, "synthetic_smoke")
            with self.assertRaises(AnnotationError):
                verify_frozen(root / "one", "c" * 64, EVIDENCE)

    def test_human_declaration_never_establishes_independence_or_clinical_validity(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.csv"
            write_rows(source, [row("human_declared")])
            with self.assertRaises(AnnotationError):
                validate_annotations(source, CONTRACT, EVIDENCE, "human_declared")
            result = validate_annotations(source, CONTRACT, EVIDENCE, "human_declared", human_declared=True)
            self.assertEqual(result["evidence_state"], "HUMAN_ANNOTATION_DECLARED_UNVERIFIED")
            self.assertFalse(result["clinical_evidence"])
            write_rows(source, [row()])
            with self.assertRaises(AnnotationError):
                validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke", human_declared=True)

    def test_unavailable_clinical_records_are_recordable_without_inventing_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.csv"
            record = dict(row(), preprescription_availability="not_recorded", symptom_change="not_assessable",
                          syndrome_change="not_assessable", independent_syndrome_label="not_available", adjacency="unknown")
            write_rows(source, [record])
            self.assertEqual(validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")["gate"], "PASS")
            record["symptom_change"] = "improved"
            write_rows(source, [record])
            with self.assertRaises(AnnotationError):
                validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")

    def test_free_text_ids_duplicate_and_nonindependent_label_are_blocked(self):
        mutations = [
            {"case_id": "Real Patient Name"}, {"reviewer_id": "person@example.test"},
            {"symptom_change": "free narrative"}, {"contract_sha256": "c" * 64},
            {"evidence_sha256": "d" * 64}, {"preprescription_availability": "after_prescription"},
            {"independent_syndrome_label": "prescription_derived"}, {"physician_provenance": "filename"},
            {"outcome_timing": "2020-01-01"}, {"adjacency": "=EXTERNAL()"}, {"case_id": ""},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.csv"
            for changes in mutations:
                with self.subTest(changes=changes):
                    write_rows(source, [dict(row(), **changes)])
                    with self.assertRaises(AnnotationError) as caught:
                        validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")
                    for value in changes.values():
                        if len(value) > 8:
                            self.assertNotIn(value, str(caught.exception))
            write_rows(source, [row(), row()])
            with self.assertRaises(AnnotationError):
                validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")
            write_rows(source, [dict(row(), notes="narrative")], FIELDS + ("notes",))
            with self.assertRaises(AnnotationError):
                validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")

    def test_tampered_extra_incomplete_and_bad_protocol_packages_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.csv"
            write_rows(source, [row()])
            for case in ("tampered", "extra", "module", "summary"):
                target = root / case
                freeze_annotations(source, target, CONTRACT, EVIDENCE, "synthetic_smoke")
                if case == "tampered":
                    (target / "annotations.csv").write_text("changed", encoding="utf-8")
                elif case == "extra":
                    (target / "extra.txt").write_text("extra", encoding="utf-8")
                else:
                    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
                    manifest["module_sha256" if case == "module" else "cases"] = "0" * 64 if case == "module" else 4
                    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.subTest(case=case), self.assertRaises(AnnotationError):
                    verify_frozen(target, CONTRACT, EVIDENCE)
            (root / "incomplete").mkdir()
            with self.assertRaises(AnnotationError):
                verify_frozen(root / "incomplete", CONTRACT, EVIDENCE)

    def test_empty_header_malformed_rows_and_encoding_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.csv"
            for payload in (",".join(FIELDS).encode(), b"\xff\xfe", (",".join(FIELDS) + '\n"unclosed').encode()):
                source.write_bytes(payload)
                with self.assertRaises(AnnotationError):
                    validate_annotations(source, CONTRACT, EVIDENCE, "synthetic_smoke")


if __name__ == "__main__":
    unittest.main()
