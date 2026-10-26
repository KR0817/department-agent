import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mingyirx.usability import (
    FIELDS, PROTOCOL_VERSION, TASKS, UsabilityError, freeze_responses,
    prepare_template, validate_responses, verify_frozen,
)


DEMO_SHA256 = "a" * 64


def response_rows(kind="synthetic_smoke"):
    return [dict(zip(FIELDS, (
        PROTOCOL_VERSION, DEMO_SHA256, kind, "P-0001", "R-0001", task["task_id"],
        "desktop", "completed", "30", "1", "1", "4", task["interpretations"][0],
    ))) for task in TASKS]


def write_rows(path, rows, fields=FIELDS):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class UsabilityTests(unittest.TestCase):
    def test_template_is_blank_and_cannot_freeze(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = prepare_template(root / "template", DEMO_SHA256)
            self.assertEqual(result["evidence_state"], "NO_PARTICIPATION_DATA")
            source = root / "template/responses.csv"
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row["duration_seconds"] == "" for row in rows))
            with self.assertRaises(UsabilityError):
                freeze_responses(source, root / "freeze", "synthetic_smoke")
            self.assertFalse((root / "freeze").exists())
            with self.assertRaises(UsabilityError):
                prepare_template(root / "template", DEMO_SHA256)

    def test_complete_synthetic_freeze_is_deterministic_and_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "responses.csv"
            write_rows(source, response_rows())
            validation = validate_responses(source, "synthetic_smoke")
            self.assertEqual(validation["participants"], 1)
            self.assertEqual(validation["records"], 3)
            self.assertEqual(validation["clinical_evidence"], False)
            first = freeze_responses(source, root / "first", "synthetic_smoke")
            second = freeze_responses(source, root / "second", "synthetic_smoke")
            self.assertEqual(first, second)
            self.assertEqual(first["import_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            for name in ("manifest.json", *first["artifacts"]):
                self.assertEqual((root / "first" / name).read_bytes(), (root / "second" / name).read_bytes())
            self.assertEqual(verify_frozen(root / "first")["gate"], "PASS")
            with self.assertRaises(UsabilityError):
                freeze_responses(source, root / "first", "synthetic_smoke")

    def test_missing_duplicate_and_inconsistent_sessions_are_blocked(self):
        cases = []
        cases.append(response_rows()[:2])
        cases.append(response_rows() + response_rows()[:1])
        for field, value in (("reviewer_id", "R-0002"), ("device", "mobile"),
                             ("demo_sha256", "b" * 64)):
            rows = response_rows()
            rows[1][field] = value
            cases.append(rows)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "responses.csv"
            for rows in cases:
                with self.subTest(rows=len(rows)):
                    write_rows(source, rows)
                    with self.assertRaises(UsabilityError):
                        validate_responses(source, "synthetic_smoke")

    def test_invalid_values_are_blocked_without_echoing_values(self):
        cases = (
            ("participant_id", "Example Person"), ("reviewer_id", "person@example.test"),
            ("duration_seconds", "NaN"), ("duration_seconds", "1.5"),
            ("duration_seconds", "0"), ("duration_seconds", "7201"),
            ("error_count", "-1"), ("correction_count", "2"),
            ("satisfaction", "6"), ("satisfaction", ""),
            ("interpretation", "=EXTERNAL()"), ("interpretation", "sensitive narrative"),
            ("protocol_version", "old"), ("task_id", "unknown"),
            ("evidence_kind", "clinical_validated"), ("device", "phone"),
        )
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "responses.csv"
            for field, value in cases:
                rows = response_rows()
                rows[0][field] = value
                write_rows(source, rows)
                with self.subTest(field=field, value=value):
                    with self.assertRaises(UsabilityError) as caught:
                        validate_responses(source, "synthetic_smoke")
                    if len(value) > 10:
                        self.assertNotIn(value, str(caught.exception))

    def test_human_declaration_is_required_and_never_clinical_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "responses.csv"
            write_rows(source, response_rows("human_declared"))
            with self.assertRaises(UsabilityError):
                validate_responses(source, "human_declared")
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")
            result = freeze_responses(source, root / "human", "human_declared", human_declared=True)
            self.assertEqual(result["evidence_state"], "HUMAN_PARTICIPATION_DECLARED_UNVERIFIED")
            self.assertFalse(result["clinical_evidence"])
            self.assertEqual(verify_frozen(root / "human")["gate"], "PASS")
            write_rows(source, response_rows())
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke", human_declared=True)

    def test_header_only_extra_column_bad_csv_and_encoding_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "responses.csv"
            write_rows(source, [])
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")
            rows = [dict(row, notes="sensitive narrative") for row in response_rows()]
            write_rows(source, rows, FIELDS + ("notes",))
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")
            source.write_bytes(b"\xff\xfe")
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")
            source.write_text(",".join(FIELDS) + '\n"unclosed', encoding="utf-8")
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")

    def test_verify_detects_tampering_missing_and_extra_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "responses.csv"
            write_rows(source, response_rows())
            freeze_responses(source, root / "changed", "synthetic_smoke")
            (root / "changed/responses.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaises(UsabilityError):
                verify_frozen(root / "changed")
            (root / "incomplete").mkdir()
            with self.assertRaises(UsabilityError):
                verify_frozen(root / "incomplete")
            freeze_responses(source, root / "extra", "synthetic_smoke")
            (root / "extra/notes.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaises(UsabilityError):
                verify_frozen(root / "extra")

    def test_abandoned_is_recordable_without_inventing_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "responses.csv"
            rows = response_rows()
            rows[1].update(outcome="abandoned", interpretation="not_answered")
            write_rows(source, rows)
            result = validate_responses(source, "synthetic_smoke")
            self.assertEqual(result["records"], 3)
            rows[1]["outcome"] = "completed"
            write_rows(source, rows)
            with self.assertRaises(UsabilityError):
                validate_responses(source, "synthetic_smoke")

    def test_field_dictionary_matches_current_source_mapping_and_review_schema(self):
        root = Path(__file__).resolve().parents[1]
        dictionary = json.loads((root / "docs/field-dictionary.json").read_text(encoding="utf-8"))
        config = json.loads((root / "configs/local_gb18030.template.json").read_text(encoding="utf-8"))
        fields = {field["name"]: field for field in dictionary["fields"]}
        for name, selector in config["columns"].items():
            self.assertEqual(fields[name]["historical_source_selector"], selector)
        from mingyirx.terminology import FIELDS as REVIEW_FIELDS
        self.assertEqual(dictionary["terminology"]["review_fields"], list(REVIEW_FIELDS))
        self.assertFalse(dictionary["clinical_source_rows_read_this_revision"])
        self.assertFalse(dictionary["dose_contract"]["daily_dose_inference"])
        self.assertEqual(dictionary["provenance"]["source_setting"], "outpatient")


if __name__ == "__main__":
    unittest.main()
