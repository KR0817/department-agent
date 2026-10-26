"""Source integrity and complete-table coverage; no clinical approval fixtures."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app import criteria_sources as criteria
from app.core import ROOT
from app.fulltext import canonical_hash


@unittest.skipUnless((ROOT / criteria.SOURCE_HTML).is_file(), "Reviewed criteria source is not installed")
class CriteriaSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (ROOT / criteria.SOURCE_HTML).read_bytes()
        cls.bundle = criteria.build_criteria_bundle()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "work")
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, value):
        value = copy.deepcopy(value)
        value["sha256"] = canonical_hash({key: item for key, item in value.items() if key != "sha256"})
        target = self.base / "index.json"
        target.write_text(json.dumps(value), encoding="utf-8")
        return target

    def test_complete_table_retains_weights_conditions_and_unit_footnote(self):
        source = self.bundle["sources"][0]
        chunks = self.bundle["chunks"]
        self.assertEqual(source["required_chunk_ids"], [chunk["id"] for chunk in chunks])
        self.assertEqual([len(chunk["text"]) for chunk in chunks], [966, 619, 711])
        self.assertEqual([chunk["criteria_order"] for chunk in chunks], [1, 2, 3])
        self.assertTrue(all(chunk["criteria_required"] and len(chunk["text"]) <= 1600 for chunk in chunks))
        self.assertIn("score \u2265 4", chunks[0]["text"])
        self.assertIn("focus score \u2265 1. | 3", chunks[0]["text"])
        self.assertNotIn("score \u2265 1.3", chunks[0]["text"])
        self.assertIn("per 4 mm\u00b2", chunks[0]["text"])
        self.assertIn("flow rate \u2264 0.1 ml/min | 1", chunks[0]["text"])
        self.assertIn("or suspicion of SS from ESSDAI", chunks[1]["text"])
        self.assertIn("positive PCR", chunks[2]["text"])
        self.assertIn("IgG4-related disease", chunks[2]["text"])
        self.assertIn("sufficient interval off these medications", chunks[2]["text"])
        self.assertEqual({item["target"] for item in self.bundle["footnote_callout_links"]}, {"#TFN6", "#TFN7", "#TFN8", "#TFN9", "#TFN10"})

    def test_source_type_year_and_approval_are_honest(self):
        source = self.bundle["sources"][0]
        self.assertEqual(source["standard_year"], 2016)
        self.assertEqual(source["year"], 2017)
        self.assertEqual(source["evidence_kind"], "html_section")
        self.assertEqual(source["question_scope"], "classification_criteria")
        self.assertEqual(source["source_version"], "public_author_manuscript_html")
        self.assertEqual(source["review_status"], "pending")
        self.assertIsNone(source["clinical_approval"])
        self.assertTrue(all(chunk["pdf_page"] is None for chunk in self.bundle["chunks"]))
        self.assertIn("\u5206\u7c7b\u6807\u51c6", source["title_zh"])

    def test_saved_index_rebuilds_exactly_from_original_bytes(self):
        self.assertEqual(criteria.load_criteria_bundle(self.save(self.bundle)), self.bundle)
        for chunk, section in zip(self.bundle["chunks"], self.bundle["sections"]):
            self.assertEqual(chunk["text"], section["text"][chunk["section_start"]:chunk["section_end"]])
            self.assertEqual(chunk["text_sha256"], hashlib.sha256(chunk["text"].encode()).hexdigest())

    def test_self_hashed_modified_text_or_dropped_qualification_is_rejected(self):
        for alteration in ("text", "required", "remove", "source", "approval"):
            with self.subTest(alteration=alteration):
                value = copy.deepcopy(self.bundle)
                if alteration == "text":
                    value["chunks"][0]["text"] = value["chunks"][0]["text"].replace("score \u2265 4", "score \u2265 3")
                    value["chunks"][0]["text_sha256"] = hashlib.sha256(value["chunks"][0]["text"].encode()).hexdigest()
                elif alteration == "required":
                    value["chunks"][2]["criteria_required"] = False
                elif alteration == "remove":
                    value["chunks"].pop()
                    value["sections"].pop()
                    value["sources"][0]["required_chunk_ids"].pop()
                elif alteration == "source":
                    value["sources"][0]["disease"] = "gout"
                else:
                    value["sources"][0]["clinical_approval"] = True
                with self.assertRaises(ValueError):
                    criteria.load_criteria_bundle(self.save(value))

    def test_modified_original_with_recomputed_index_hash_is_rejected(self):
        changed = self.base / "changed.html"
        changed.write_bytes(self.original.replace(b"positive PCR", b"negative PCR"))
        value = copy.deepcopy(self.bundle)
        value["sources"][0]["html_path"] = changed.relative_to(ROOT).as_posix()
        value["sources"][0]["html_sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "criteria_source_integrity_failure"):
            criteria.load_criteria_bundle(self.save(value))

    def test_changed_metadata_or_outside_paths_are_rejected(self):
        changed = self.base / "changed.json"
        changed.write_text("{}", encoding="utf-8")
        for field, path in (("core_path", changed.relative_to(ROOT).as_posix()), ("html_path", "../outside.html")):
            with self.subTest(field=field):
                value = copy.deepcopy(self.bundle)
                value["sources"][0][field] = path
                with self.assertRaises(ValueError):
                    criteria.load_criteria_bundle(self.save(value))

    def test_missing_or_duplicate_qualifying_ids_are_rejected(self):
        for raw in (self.original.replace(b'id="P76"', b'id="different"'),
                    self.original + b'<p id="P75">Duplicated qualifying text.</p>'):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                criteria._parse(raw)

    def test_unexpected_table_shape_or_footnote_inventory_is_rejected(self):
        for raw in (self.original.replace(b'colspan="1"', b'colspan="2"'),
                    self.original.replace(b'id="TFN10"', b'id="missing-footnote"')):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                criteria._parse(raw)

    def test_changed_html_identity_or_duplicate_identity_is_rejected(self):
        for raw in (self.original.replace(b'content="27785888"', b'content="27785889"'),
                    self.original + b'<meta name="citation_pmid" content="27785888">'):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                criteria._parse(raw)

    def test_size_entity_and_encoding_bounds(self):
        for raw in (b"", b"x" * (criteria.MAX_HTML_BYTES + 1), b"<!ENTITY danger SYSTEM 'outside'>", b"\xff"):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                criteria._parse(raw)

    def test_malformed_index_shapes_fail_closed(self):
        for sources in ([], None, {}, "source", [None]):
            value = copy.deepcopy(self.bundle)
            value["sources"] = sources
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                criteria.load_criteria_bundle(self.save(value))

    def test_rendered_table_is_escaped_and_does_not_serve_original_scripts(self):
        source = {**self.bundle["sources"][0], "title": "<script>untrusted</script>"}
        section = {**self.bundle["sections"][0], "text": '<img src="https://outside.test" onerror="bad()">'}
        output = criteria.render_section(source, section).decode("utf-8")
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("&lt;img", output)
        self.assertNotIn("<script", output)
        self.assertNotIn("<img", output)
        self.assertIn(criteria.SOURCE_URL + "#T3", output)


if __name__ == "__main__":
    unittest.main()
