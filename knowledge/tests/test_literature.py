"""Synthetic JATS source-binding and safe-section checks, not clinical evidence."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core import ROOT
from app.fulltext import canonical_hash, file_hash, load_combined_index
from app.literature import build_sidecar, load_sidecar, parse_article, render_section


PARAGRAPH = (
    "The synthetic trial compared intervention with placebo for twelve weeks. "
    "No renal benefit was assessed. Adverse events were monitored in both groups. "
    "This is an artificial fixture for software validation only, not a real publication. "
)
XML = ("<?xml version='1.0'?><article><front><article-meta>"
       "<article-id pub-id-type='pmc'>123</article-id><article-id pub-id-type='pmid'>456</article-id>"
       "<article-id pub-id-type='doi'>10.0000/synthetic</article-id>"
       "<title-group><article-title>Synthetic &lt;script&gt; trial</article-title></title-group>"
       "</article-meta></front><body><sec id='methods'><title>Methods</title><p>" + PARAGRAPH + "</p>"
       "<sec id='results'><title>Results &amp; limitations</title><p>" + PARAGRAPH + "</p>"
       "<table-wrap><caption><p>Table only finding</p></caption><table><tr><td>999</td></tr></table></table-wrap>"
       "<fig><caption><p>Figure only finding</p></caption></fig></sec></sec></body>"
       "<back><ref-list><ref><mixed-citation>Bibliography must not become evidence.</mixed-citation></ref></ref-list></back></article>").encode()


class LiteratureTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "work")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.xml = self.base / "article.xml"
        self.xml.write_bytes(XML)
        self.core = self.base / "core.json"
        self.core.write_text(json.dumps({"pmcid": "PMC123", "pmid": "456", "doi": "10.0000/synthetic"}), encoding="utf-8")
        self.record = {"id": "epmc-pmc123", "title": "Synthetic <script> trial", "pmcid": "PMC123", "pmid": "456",
            "doi": "10.0000/synthetic", "disease": "ra", "source_url": "https://europepmc.org/articles/PMC123",
            "xml_path": self.xml.relative_to(ROOT).as_posix(), "xml_sha256": file_hash(self.xml),
            "core_path": self.core.relative_to(ROOT).as_posix(), "core_sha256": file_hash(self.core),
            "identity_verified": True, "review_status": "pending", "clinical_approval": None,
            "status_flags": {}, "fulltext_bytes": len(XML), "study_type": "synthetic_test_only"}
        self.manifest = self.base / "manifest.json"
        self.index = self.base / "index.json"
        self.save_manifest()

    def save_manifest(self, records=None):
        self.manifest.write_text(json.dumps({"schema": "public-literature-acquisition-v1", "records": records or [self.record]}), encoding="utf-8")

    def save_index(self, value):
        value = copy.deepcopy(value)
        value["sha256"] = canonical_hash({key: val for key, val in value.items() if key != "sha256"})
        self.index.write_text(json.dumps(value), encoding="utf-8")

    def test_body_sections_preserve_text_and_exclude_nonparagraph_material(self):
        sections, omitted = parse_article(XML, self.record)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[1]["locator"], "Methods > Results & limitations")
        self.assertEqual(sections[0]["text"], PARAGRAPH.strip())
        self.assertEqual(omitted["table-wrap"], 1)
        self.assertEqual(omitted["fig"], 1)
        self.assertNotIn("999", str(sections))
        self.assertNotIn("Bibliography", str(sections))

    def test_namespace_and_external_doctype_do_not_require_network(self):
        raw = XML.replace(b"<article>", b"<!DOCTYPE article SYSTEM 'https://invalid.example/jats.dtd'><article xmlns='urn:jats'>")
        sections, _ = parse_article(raw, self.record)
        self.assertEqual(len(sections), 2)

    def test_missing_body_wrong_identity_title_and_entities_are_rejected(self):
        invalid = [XML.replace(b"<body>", b"<other>").replace(b"</body>", b"</other>"),
            XML.replace(b">123</article-id>", b">999</article-id>"),
            XML.replace(b"Synthetic &lt;script&gt; trial", b"Forged title"),
            XML.replace(b"<article>", b"<!DOCTYPE article [<!ENTITY x 'unsafe'>]><article>"), b"<article>"]
        for raw in invalid:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                parse_article(raw, self.record)

    def test_index_roundtrip_binds_chunks_to_original_sections(self):
        value = build_sidecar(self.manifest)
        self.save_index(value)
        actual = load_sidecar(self.index)
        self.assertEqual(actual, value)
        for chunk in actual["chunks"]:
            section = next(s for s in actual["sections"] if s["section_id"] == chunk["section_id"])
            self.assertEqual(section["text"][chunk["section_start"]:chunk["section_end"]], chunk["text"])
            self.assertIsNone(chunk["pdf_page"])
            self.assertEqual(chunk["evidence_kind"], "xml_section")
            self.assertIsNone(chunk["clinical_approval"])

    def test_flagged_article_is_readable_but_never_automatically_retrieved(self):
        from app.extractive import make_extractor
        from app.fulltext import retrieve
        self.record["status_flags"] = {"retrieval_block_reason": "synthetic_numeric_mismatch", "manual_review_note_zh": "Synthetic source review note"}
        self.save_manifest()
        value = build_sidecar(self.manifest)
        self.assertFalse(value["sources"][0]["retrieval_eligible"])
        self.assertTrue(all(not chunk["retrieval_eligible"] for chunk in value["chunks"]))
        self.assertEqual(retrieve(value, "synthetic trial"), [])
        extractor = make_extractor(value, transport=Mock(side_effect=AssertionError("model must not run")))
        public = extractor["catalog"]()["sources"][0]
        self.assertFalse(public["retrieval_eligible"])
        self.assertIsNotNone(public["locator_url"])
        self.assertIn(b"Synthetic", extractor["section"](value["chunks"][0]["id"]))

    def test_recomputed_index_hash_cannot_forge_source_text(self):
        value = build_sidecar(self.manifest)
        value["sections"][0]["text"] = "Forged result"
        value["sections"][0]["text_sha256"] = hashlib.sha256(b"Forged result").hexdigest()
        self.save_index(value)
        with self.assertRaisesRegex(ValueError, "source_text_binding"):
            load_sidecar(self.index)

    def test_source_core_and_register_mutations_fail_closed(self):
        value = build_sidecar(self.manifest)
        self.save_index(value)
        for path in (self.xml, self.core, self.manifest):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"changed")
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    load_sidecar(self.index)
            finally:
                path.write_bytes(original)

    def test_duplicate_identifiers_block_promotion(self):
        self.save_manifest([self.record, copy.deepcopy(self.record)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_sidecar(self.manifest)

    def test_bad_paths_review_state_retraction_and_source_url_are_rejected(self):
        for key, value in (("xml_path", str(self.xml.resolve())), ("disease", []), ("clinical_approval", "approved"),
                           ("review_status", "approved"), ("status_flags", {"core_is_retracted": True}),
                           ("source_url", "javascript:alert(1)")):
            with self.subTest(key=key):
                record = {**self.record, key: value}
                self.save_manifest([record])
                with self.assertRaises(ValueError):
                    build_sidecar(self.manifest)

    def test_core_identity_cannot_be_reassigned_with_new_hash(self):
        self.core.write_text(json.dumps({"pmcid": "PMC999", "pmid": "456", "doi": "10.0000/synthetic"}), encoding="utf-8")
        self.record["core_sha256"] = file_hash(self.core)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "core_identity"):
            build_sidecar(self.manifest)

    def test_med_core_id_is_a_valid_pmid_fallback_only_for_med(self):
        for database, accepted in (("MED", True), ("PMC", False)):
            self.core.write_text(json.dumps({"source": database, "id": "456", "pmcid": "PMC123", "doi": "10.0000/synthetic"}), encoding="utf-8")
            self.record["core_sha256"] = file_hash(self.core)
            self.save_manifest()
            if accepted:
                self.assertEqual(len(build_sidecar(self.manifest)["sources"]), 1)
            else:
                with self.assertRaisesRegex(ValueError, "core_identity"):
                    build_sidecar(self.manifest)

    def test_deep_nonsection_content_is_rejected_without_recursion_error(self):
        raw = XML.replace(b"<body>", b"<body>" + b"<wrapper>" * 45).replace(b"</body>", b"</wrapper>" * 45 + b"</body>")
        # A separate paragraph exercises the generic content traversal depth.
        raw = raw.replace(b"<sec id='methods'>", b"<p>nested</p><sec id='methods'>", 1)
        with self.assertRaisesRegex(ValueError, "content_depth"):
            parse_article(raw, self.record)

    def test_title_translation_has_separate_frozen_provenance(self):
        titles = self.base / "titles.json"
        titles.write_text(json.dumps({self.record["id"]: "\u6a21\u62df\u8bd5\u9a8c"}), encoding="utf-8")
        value = build_sidecar(self.manifest, titles)
        self.assertEqual(value["sources"][0]["title"], self.record["title"])
        self.assertEqual(value["sources"][0]["title_translation"], "local_model_unreviewed")
        self.save_index(value)
        self.assertEqual(load_sidecar(self.index), value)
        titles.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "title_translation_integrity"):
            load_sidecar(self.index)

    def test_reading_view_escapes_text_and_does_not_claim_pdf_page(self):
        value = build_sidecar(self.manifest)
        result = render_section(value["sources"][0], {**value["sections"][0], "text": "<script>alert(1)</script>"}).decode()
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("XML", result)
        self.assertIn("https://europepmc.org/articles/PMC123", result)

    def test_merge_deduplicates_against_original_pdf_identifiers(self):
        value = build_sidecar(self.manifest)
        self.save_index(value)
        pdf = {"sources": [{"id": "legacy", "doi": self.record["doi"]}], "chunks": [], "pages": [], "sha256": "a" * 64}
        with patch("app.fulltext.load_index", return_value=pdf):
            result = load_combined_index(self.index, include_criteria=False)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["duplicate_xml_sources"], [self.record["id"]])
        self.assertEqual(result["sections"], [])

    def test_new_xml_extract_preserves_locator_and_serves_safe_original(self):
        from app.extractive import MODEL, make_extractor, selection_units
        value = build_sidecar(self.manifest)
        chunk = value["chunks"][0]
        unit = selection_units([chunk])[0]
        response = {"completion": {"model": MODEL, "done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"status": "extracts", "selections": [{"start_id": unit["id"], "end_id": unit["id"]}]})}}}
        transport = Mock(side_effect=[response, TimeoutError("private model text")])
        with patch("app.fulltext.retrieve", return_value=[chunk]):
            extractor = make_extractor(value, transport=transport)
            result = extractor["extract"]({"question": "What was compared?", "disease": "ra", "source_id": self.record["id"], "index_sha256": value["sha256"]})
        item = result["extracts"][0]
        self.assertEqual(item["evidence_kind"], "xml_section")
        self.assertIsNone(item["pdf_page"])
        self.assertIsNone(item["answer_zh"])
        self.assertTrue(item["page_url"].startswith("/api/fulltext/section/"))
        self.assertEqual(item["locator"], "Methods")
        self.assertIsNone(extractor["page"](chunk["id"]))
        self.assertIsNotNone(extractor["section"](chunk["id"]))
        self.assertNotIn("xml_path", json.dumps(extractor["catalog"]()))
        self.xml.write_bytes(XML + b"changed")
        with self.assertRaises(ValueError):
            extractor["section"](chunk["id"])


if __name__ == "__main__":
    unittest.main()
