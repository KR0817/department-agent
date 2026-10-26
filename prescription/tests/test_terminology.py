import csv
import json
import tempfile
import unittest
from pathlib import Path

from mingyirx.config import ConfigError, load_config
from mingyirx.io import file_sha256
from mingyirx.privacy import scan_public_outputs
from mingyirx.terminology import (
    FIELDS, TABLES, TerminologyError, compile_dictionary, prepare_dictionary,
)


ROOT = Path(__file__).resolve().parents[1]


def write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def approved(source="Alias", target="Herb", **overrides):
    row = dict(zip(FIELDS, (source, target, "HERB_1", "herb", "raw", "decoction",
                           "g", "approved", "reviewer_1", "synthetic_reference")))
    row.update(overrides)
    return row


class TerminologyTests(unittest.TestCase):
    def sources(self, root, exposed=10):
        for name in TABLES[:2]:
            write_rows(root / name, ("item_name", "exposed_patients", "group_patients"), [
                {"item_name": "Herb", "exposed_patients": exposed, "group_patients": 20},
                {"item_name": "Alias", "exposed_patients": 12, "group_patients": 20},
            ])
        write_rows(root / TABLES[2], ("dictionary_entries", "dictionary_version"), [
            {"dictionary_entries": 0, "dictionary_version": "source-string-v1"}])
        manifest = {"gate": "PASS_WITH_WARNINGS", "configuration": {"min_public_n": 10},
                    "artifacts": {name: file_sha256(root / name) for name in TABLES}}
        (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_prepare_is_deterministic_pending_and_cannot_activate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.sources(root)
            first = prepare_dictionary(root, root / "first")
            second = prepare_dictionary(root, root / "second")
            self.assertEqual(first, second)
            self.assertEqual(first["items"], 2)
            review = root / "first/terminology_review.csv"
            with review.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(all(row["review_status"] == "pending" for row in rows))
            self.assertEqual(scan_public_outputs(root / "first").issues, ())
            with self.assertRaises(TerminologyError):
                compile_dictionary(review, "reviewed-v1", root / "compiled")
            self.assertFalse((root / "compiled").exists())
            with self.assertRaises(TerminologyError):
                prepare_dictionary(root, root / "first")
            config = json.loads((ROOT / "configs/example.json").read_text(encoding="utf-8"))
            config["item_normalization"] = {"version": "draft", "dictionary_path": str(review)}
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(config_path)

    def test_source_tampering_and_small_cells_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.sources(root, exposed=9)
            with self.assertRaises(TerminologyError):
                prepare_dictionary(root, root / "small")
            self.sources(root)
            with (root / TABLES[0]).open("a", encoding="utf-8") as handle:
                handle.write("Tampered,10,20\n")
            with self.assertRaises(TerminologyError):
                prepare_dictionary(root, root / "tampered")
            self.assertFalse((root / "tampered").exists())

    def test_reviewed_mapping_loads_and_omits_unapproved_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            review = root / "review.csv"
            pending = dict.fromkeys(FIELDS, "")
            pending.update(source_item_name="Unresolved", review_status="pending")
            rejected = dict(pending, source_item_name="Rejected", review_status="rejected")
            write_rows(review, FIELDS, [approved(), approved("Herb"), pending, rejected])
            result = compile_dictionary(review, "reviewed-v1", root / "compiled")
            repeat = compile_dictionary(review, "reviewed-v1", root / "repeat")
            self.assertEqual(result, repeat)
            self.assertEqual(result["approved_mappings"], 2)
            self.assertEqual(result["unapproved_rows"], 2)
            self.assertEqual(scan_public_outputs(root / "compiled").issues, ())
            config = json.loads((ROOT / "configs/example.json").read_text(encoding="utf-8"))
            config["item_normalization"] = result["item_normalization"]
            path = root / "compiled/config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(load_config(path).item_normalization.mappings,
                             {"Alias": "Herb", "Herb": "Herb"})
            with self.assertRaises(TerminologyError):
                compile_dictionary(review, "reviewed-v1", root / "compiled")

    def test_incompatible_and_unreviewed_targets_are_rejected(self):
        cases = [
            [approved(preparation="unknown")],
            [approved(reviewer_id="")],
            [approved(), approved("Herb", preparation="processed")],
            [approved(), approved("Herb", unit="mg")],
            [approved(), approved("Herb", canonical_item_id="HERB_2")],
            [approved(), approved("Other", "Different")],
            [approved(), approved("Herb", "Next")],
            [approved(), approved("Herb", review_status="pending")],
            [approved(), approved("Herb", "Alias")],
            [approved(), approved(source=" Alias ")],
            [approved(evidence_reference="=EXTERNAL()")],
            [approved(review_status="APPROVED")],
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            review = root / "review.csv"
            for index, rows in enumerate(cases):
                with self.subTest(index=index):
                    write_rows(review, FIELDS, rows)
                    output = root / f"case_{index}"
                    with self.assertRaises(TerminologyError):
                        compile_dictionary(review, "reviewed-v1", output)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
