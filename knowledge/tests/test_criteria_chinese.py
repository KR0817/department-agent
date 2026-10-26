"""Versioned criteria translations preserve exact evidence and pending review."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import criteria_chinese
from app.core import ROOT
from app.criteria_sources import DEFAULT_BUNDLE, load_criteria_bundle


@unittest.skipUnless(DEFAULT_BUNDLE.is_file(), "Reviewed source bundle is not installed")
class CriteriaChineseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_criteria_bundle()
        cls.translation_bytes = criteria_chinese.TRANSLATION_PATH.read_bytes()

    def excerpts(self):
        source = self.bundle["sources"][0]
        return [{"source_id": source["id"], "chunk_id": chunk["id"], "quote": chunk["text"],
                 "quote_sha256": chunk["text_sha256"], "quote_start": 0, "quote_end": len(chunk["text"]),
                 "pmid": source["pmid"], "pmcid": source["pmcid"], "doi": source["doi"],
                 "evidence_kind": "html_section", "pdf_page": None, "locator": chunk["locator"]}
                for chunk in self.bundle["chunks"]]

    def test_complete_exact_blocks_receive_versioned_chinese_without_model(self):
        originals = self.excerpts()
        frozen = copy.deepcopy(originals)
        result = criteria_chinese.translate_criteria_extracts(originals)
        self.assertEqual(originals, frozen)
        self.assertEqual(result["translation_status"], "complete")
        self.assertFalse(result["translation_model_called"])
        self.assertIsNone(result["translation_error"])
        self.assertIsNone(result["clinical_approval"])
        for original, translated in zip(originals, result["extracts"]):
            self.assertEqual(translated["quote"], original["quote"])
            self.assertEqual(translated["quote_sha256"], original["quote_sha256"])
            self.assertEqual(translated["translation_status"], "versioned_translation")
            self.assertEqual(translated["translation_origin"], "versioned_assistant_translation")
            self.assertEqual(translated["translation_review_status"], "pending_clinician_review")
            self.assertEqual(translated["translation_checks"]["semantic_fidelity"], "unassessed")
            self.assertTrue(all(value for key, value in translated["translation_checks"].items() if key != "semantic_fidelity"))
            self.assertIsNone(translated["clinical_approval"])
        text = result["extracts"][0]["answer_zh"]
        self.assertIn("\u773c\u8868\u67d3\u8272\u8bc4\u5206", text)
        self.assertIn("\u5507\u817a", text)
        self.assertIn("\u553e\u6db2\u817a\u708e", text)
        self.assertNotIn("\u89d2\u819c", text)
        inclusion = result["extracts"][1]["answer_zh"]
        self.assertIn("\u773c\u4e2d\u6709\u7802\u783e", inclusion)
        self.assertNotIn("\u5f02\u7269", inclusion)
        self.assertIn("\u996e\u7528\u6db2\u4f53\u5e2e\u52a9\u541e\u54bd", inclusion)

    def test_missing_duplicate_wrong_source_or_wrong_quote_is_rejected(self):
        cases = []
        cases.append(self.excerpts()[:2])
        cases.append([self.excerpts()[0]] * 3)
        for key, value in (("source_id", "different-source"), ("quote", "not the original quote"),
                           ("quote_sha256", "0" * 64), ("pmid", "999999"), ("quote_start", 1),
                           ("clinical_approval", True), ("evidence_kind", "pdf_page")):
            items = self.excerpts()
            items[0][key] = value
            cases.append(items)
        for items in cases:
            with self.subTest(items=str(items)[:60]), self.assertRaises(ValueError):
                criteria_chinese.translate_criteria_extracts(items)

    def test_unchanged_complete_set_can_preserve_input_order(self):
        items = list(reversed(self.excerpts()))
        result = criteria_chinese.translate_criteria_extracts(items)
        self.assertEqual([x["chunk_id"] for x in result["extracts"]], [x["chunk_id"] for x in items])

    def test_modified_translation_or_metadata_is_rejected_by_pinned_file_hash(self):
        for key, value in (("origin", "machine_translated"), ("clinical_approval", True),
                           ("review_status", "approved"), ("bundle_sha256", "0" * 64), ("answer_zh", "changed")):
            data = json.loads(self.translation_bytes)
            if key == "answer_zh":
                data["items"][0][key] = value
            else:
                data[key] = value
            with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
                target = Path(folder) / "changed.json"
                target.write_text(json.dumps(data), encoding="utf-8")
                with patch.object(criteria_chinese, "TRANSLATION_PATH", target), self.assertRaisesRegex(ValueError, "integrity_failure"):
                    criteria_chinese.translate_criteria_extracts(self.excerpts())

    def test_metadata_and_quote_binding_are_validated_beyond_file_digest(self):
        for alteration in ("source_id", "required", "quote_hash", "omit", "approval"):
            data = json.loads(self.translation_bytes)
            if alteration == "source_id":
                data["source_id"] = "different"
            elif alteration == "required":
                data["required_chunk_ids"] = list(reversed(data["required_chunk_ids"]))
            elif alteration == "quote_hash":
                data["items"][0]["source_quote_sha256"] = "0" * 64
            elif alteration == "omit":
                data["items"].pop()
            else:
                data["clinical_approval"] = True
            with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
                target = Path(folder) / "changed.json"
                target.write_text(json.dumps(data), encoding="utf-8")
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                with patch.object(criteria_chinese, "TRANSLATION_PATH", target), patch.object(criteria_chinese, "TRUSTED_TRANSLATION_SHA256", digest), self.assertRaises(ValueError):
                    criteria_chinese.translate_criteria_extracts(self.excerpts())

    def test_source_bundle_change_or_integrity_failure_has_no_fallback(self):
        altered = copy.deepcopy(self.bundle)
        altered["sha256"] = "0" * 64
        with patch.object(criteria_chinese, "load_criteria_bundle", return_value=altered), self.assertRaises(ValueError):
            criteria_chinese.translate_criteria_extracts(self.excerpts())
        with patch.object(criteria_chinese, "load_criteria_bundle", side_effect=ValueError("source_integrity_failure")), self.assertRaises(ValueError):
            criteria_chinese.translate_criteria_extracts(self.excerpts())

    def test_existing_guard_still_checks_the_versioned_text(self):
        with patch.object(criteria_chinese, "_translation_checks", side_effect=ValueError("translation_checks_failed")), self.assertRaises(ValueError):
            criteria_chinese.translate_criteria_extracts(self.excerpts())

    def test_source_and_translation_files_are_not_written(self):
        source = self.bundle["sources"][0]
        paths = [ROOT / source["html_path"], ROOT / source["core_path"], DEFAULT_BUNDLE,
                 criteria_chinese.TRANSLATION_PATH, ROOT / "work/literature-v0.15/index.json"]
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        criteria_chinese.translate_criteria_extracts(self.excerpts())
        self.assertEqual(before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})


if __name__ == "__main__":
    unittest.main()
