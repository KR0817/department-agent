"""Synthetic relevance regressions and source-bound public-standard integration."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from app import fulltext
from app.core import ROOT
from app.answerability import question_intent
from app.extractive import MODEL, make_extractor, selection_units

QUESTION = "\u5e72\u71e5\u7efc\u5408\u5f81\u7684\u8bca\u65ad\u6807\u51c6"
TCM_TEXT = "\u5e72\u71e5\u7efc\u5408\u5f81\u4e2d\u533b\u8bc1\u5019\u5206\u4e3a\u9634\u865a\u6d25\u4e8f\u8bc1\u3001\u6c14\u9634\u4e24\u865a\u8bc1\u3001\u9634\u865a\u5185\u70ed\u8bc1\u3001\u71e5\u7600\u4e92\u7ed3\u8bc1\u548c\u71e5\u6e7f\u4e92\u7ed3\u8bc1\u3002"


def fixture():
    source = {"id": "synthetic-tcm", "title": "Synthetic TCM pattern consensus", "disease": "sjd", "clinical_approval": None}
    chunk = {"id": "ft_" + "1" * 24, "source_id": source["id"], "pdf_page": 1,
             "text": TCM_TEXT, "retrieval_eligible": True, "quality_note": "Synthetic test only"}
    return {"sha256": "a" * 64, "sources": [source], "chunks": [chunk]}


def criteria_fixture():
    index = fixture()
    source = {"id": "synthetic-standard", "title": "2016 synthetic classification criteria", "disease": "sjd",
              "standard_year": 2016, "criteria_bundle_id": "synthetic-bundle", "criteria_complete": True,
              "question_scope": "classification_criteria", "evidence_kind": "html_section", "clinical_approval": None}
    texts = ["\u6a21\u62df\u5206\u7c7b\u6761\u76ee\u548c\u6743\u91cd\uff1a\u4ec5\u7528\u4e8e\u8f6f\u4ef6\u6d4b\u8bd5\uff0c\u4e0d\u662f\u4e34\u5e8a\u6807\u51c6\u3002",
             "\u6a21\u62df\u5165\u53e3\u6761\u4ef6\uff1a\u5fc5\u987b\u4fdd\u7559\u672c\u6761\u6d4b\u8bd5\u9650\u5b9a\uff0c\u4e0d\u662f\u4e34\u5e8a\u6807\u51c6\u3002",
             "\u6a21\u62df\u6392\u9664\u6761\u4ef6\uff1a\u672c\u6761\u9650\u5b9a\u4e0e\u8ba1\u5206\u540c\u65f6\u5c55\u793a\uff0c\u4e0d\u662f\u4e34\u5e8a\u6807\u51c6\u3002"]
    chunks = [{"id": "ft_" + str(i + 2) * 24, "source_id": source["id"], "pdf_page": None,
               "evidence_kind": "html_section", "text": text, "retrieval_eligible": True,
               "criteria_bundle_id": source["criteria_bundle_id"], "criteria_required": True,
               "question_scope": "classification_criteria", "quality_note": "Synthetic normalized table"}
              for i, text in enumerate(texts)]
    source["required_chunk_ids"] = [c["id"] for c in chunks]
    index["sources"].append(source)
    index["chunks"].extend(chunks)
    return index


class CriteriaRelevanceTests(unittest.TestCase):
    def test_tcm_disease_overlap_is_not_a_biomedical_criteria_candidate(self):
        self.assertEqual(fulltext.retrieve(fixture(), QUESTION, disease="sjd"), [])

    def test_related_real_quote_does_not_become_a_diagnosis_answer(self):
        index = fixture()
        units = selection_units(index["chunks"])
        completion = {"model": MODEL, "done": True, "done_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"status": "extracts", "selections": [{"start_id": units[0]["id"], "end_id": units[-1]["id"]}]})}}
        transport = Mock(return_value={"completion": completion})
        extractor = make_extractor(index=copy.deepcopy(index), transport=transport)
        with patch("app.extractive.check_context"):
            result = extractor["extract"]({"question": QUESTION, "disease": "sjd", "source_id": "all", "index_sha256": index["sha256"]})
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["extracts"], [])
        transport.assert_not_called()

    def test_explicit_tcm_question_still_retrieves_tcm_evidence(self):
        question = "\u5e72\u71e5\u7efc\u5408\u5f81\u7684\u4e2d\u533b\u8fa8\u8bc1\u5206\u578b\u6709\u54ea\u4e9b"
        self.assertEqual(question_intent(question), "tcm_syndrome")
        self.assertTrue(fulltext.retrieve(fixture(), question, disease="sjd"))

    def test_aliases_and_diacritics_keep_criteria_intent(self):
        variants = [QUESTION, "\u5e72\u71e5\u7efc\u5408\u5f81\u8bca\u65ad\u6807\u51c6", "\u5e72\u71e5\u7efc\u5408\u5f81\u5982\u4f55\u786e\u8bca", "Sj\u00f6gren diagnostic criteria", "2016 ACR/EULAR Sjogren classification criteria"]
        for question in variants:
            with self.subTest(question=question):
                chunks = fulltext.retrieve(criteria_fixture(), question)
                self.assertEqual(len(chunks), 3)
                self.assertTrue(all(c["source_id"] == "synthetic-standard" for c in chunks))
        self.assertEqual(fulltext.tokens("Sj\u00f6gren"), fulltext.tokens("Sjogren"))

    def test_wrong_disease_source_year_and_missing_conditions_do_not_fallback(self):
        for kwargs in ({"disease": "gout"}, {"source_id": "synthetic-tcm"}, {"limit": 2}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(fulltext.retrieve(criteria_fixture(), QUESTION, **kwargs), [])
        self.assertEqual(fulltext.retrieve(criteria_fixture(), "2024\u5e74" + QUESTION), [])
        missing = criteria_fixture()
        missing["chunks"].pop()
        self.assertEqual(fulltext.retrieve(missing, QUESTION), [])

    def test_trial_enrollment_and_bibliography_mentions_are_not_complete_standards(self):
        index = fixture()
        for text in ("Participants with Sjogren met the 2016 classification criteria.", "Reference: 2016 ACR/EULAR Sjogren classification criteria."):
            index["chunks"][0]["text"] = text
            self.assertEqual(fulltext.retrieve(index, QUESTION), [])

    def test_a_selected_table_row_retains_all_required_conditions(self):
        index = criteria_fixture()
        first = index["chunks"][1]
        units = selection_units([first])
        completion = {"model": MODEL, "done": True, "done_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"status": "extracts", "selections": [{"start_id": units[0]["id"], "end_id": units[0]["id"]}]})}}
        extractor = make_extractor(index=index, transport=Mock(return_value={"completion": completion}))
        with patch("app.extractive.check_context"):
            result = extractor["extract"]({"question": QUESTION, "disease": "sjd", "source_id": "all", "index_sha256": index["sha256"]})
        self.assertEqual([e["quote"] for e in result["extracts"]], [c["text"] for c in index["chunks"][1:]])
        self.assertEqual(result["answer_scope"], "classification_criteria")
        self.assertEqual(result["answerability_basis"], "complete_source_bundle")
        self.assertEqual(result["completeness"], "unassessed")
        self.assertIsNone(result["clinical_approval"])
        self.assertTrue(all(e["page_url"].startswith("/api/fulltext/section/") for e in result["extracts"]))

    def test_wrong_retriever_output_is_blocked_again_at_shared_boundary(self):
        index = criteria_fixture()
        transport = Mock()
        with patch("app.fulltext.retrieve", return_value=[index["chunks"][0]]):
            extractor = make_extractor(index=index, transport=transport)
            result = extractor["extract"]({"question": QUESTION, "disease": "sjd", "source_id": "all", "index_sha256": index["sha256"]})
        self.assertEqual(result["status"], "insufficient")
        transport.assert_not_called()

    def test_complete_but_wrong_disease_bundle_is_not_publishable(self):
        index = criteria_fixture()
        transport = Mock()
        with patch("app.fulltext.retrieve", return_value=index["chunks"][1:]):
            extractor = make_extractor(index=index, transport=transport)
            result = extractor["extract"]({"question": "\u75db\u98ce\u8bca\u65ad\u6807\u51c6", "disease": "gout", "source_id": "all", "index_sha256": index["sha256"]})
        self.assertEqual(result["status"], "insufficient")
        transport.assert_not_called()

    @unittest.skipUnless((ROOT / 'work/diagnosis-v0.16/criteria-bundle/index-final.json').is_file(), 'Original standard bundle is not distributed')
    def test_public_standard_uses_versioned_translation_after_one_selection_call(self):
        from app.criteria_sources import load_criteria_bundle
        index = load_criteria_bundle()
        units = selection_units([index["chunks"][0]])
        completion = {"model": MODEL, "done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"status": "extracts", "selections": [
                {"start_id": units[0]["id"], "end_id": units[0]["id"]}]})}}
        transport = Mock(return_value={"completion": completion})
        extractor = make_extractor(index=index, transport=transport)
        result = extractor["extract"]({"question": QUESTION, "disease": "all", "source_id": "all", "index_sha256": index["sha256"]})
        transport.assert_called_once()
        self.assertEqual(result["translation_status"], "complete")
        self.assertFalse(result["translation_model_called"])
        self.assertEqual([e["quote"] for e in result["extracts"]], [c["text"] for c in index["chunks"]])
        self.assertTrue(all(e["translation_status"] == "versioned_translation" for e in result["extracts"]))
        self.assertIsNone(result["clinical_approval"])

    @unittest.skipUnless((ROOT / 'work/diagnosis-v0.16/criteria-bundle/index-final.json').is_file(), 'Original standard bundle is not distributed')
    def test_corrupt_versioned_translation_has_no_answer_or_dynamic_fallback(self):
        from app.criteria_sources import load_criteria_bundle
        index = load_criteria_bundle()
        units = selection_units([index["chunks"][0]])
        completion = {"model": MODEL, "done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"status": "extracts", "selections": [
                {"start_id": units[0]["id"], "end_id": units[0]["id"]}]})}}
        transport = Mock(return_value={"completion": completion})
        with patch("app.criteria_chinese.translate_criteria_extracts", side_effect=ValueError("binding_failure")):
            extractor = make_extractor(index=index, transport=transport)
            result = extractor["extract"]({"question": QUESTION, "disease": "all", "source_id": "all", "index_sha256": index["sha256"]})
        transport.assert_called_once()
        self.assertEqual(result["translation_status"], "unavailable")
        self.assertFalse(result["translation_model_called"])
        self.assertTrue(all(e["answer_zh"] is None for e in result["extracts"]))
        self.assertEqual([e["quote"] for e in result["extracts"]], [c["text"] for c in index["chunks"]])


if __name__ == "__main__":
    unittest.main()
