"""Index integrity and retrieval tests; fixtures are not clinical sources."""
import base64
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import fulltext
from app.core import ROOT


class FullTextTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "work")
        self.base = Path(self.directory.name)
        self.pdf = self.base / "source.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\npublic fixture, not a real article")
        self.png = self.base / "page.png"
        self.png.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII="))
        self.sid = "acr-ra-2021-acr"
        self.text = "Hydroxychloroquine was compared with placebo. No renal benefit was measured."
        self.digest = hashlib.sha256(self.text.encode()).hexdigest()
        self.image = self.png.relative_to(ROOT).as_posix()
        self.index = {"schema":"public-fulltext-index-v1","version":"test","data_origin":"real_public_documents","clinical_release":False,
            "sources":[{"id":self.sid,"title":"Trial fixture","doi":None,"pmid":None,"disease":"ra",
                "pdf_path":self.pdf.relative_to(ROOT).as_posix(),"pdf_sha256":fulltext.file_hash(self.pdf),"quality_note":"Test only","clinical_approval":None}],
            "pages":[{"source_id":self.sid,"pdf_page":1,"text":self.text,"text_sha256":self.digest,
                "image_path":self.image,"image_sha256":fulltext.file_hash(self.png)}],
            "chunks":[{"id":"ft_"+"1"*24,"source_id":self.sid,"pdf_page":1,"text":self.text,"text_sha256":self.digest,
                "page_text_sha256":self.digest,"page_start":0,"page_end":len(self.text),
                "image_path":self.image,"image_sha256":fulltext.file_hash(self.png),"retrieval_eligible":True,
                "quality_note":"Test only","clinical_approval":None}]}
        self.path = self.base / "index.json"
        self.trust = patch.object(fulltext,"TRUSTED_SOURCE_HASHES",{self.sid:fulltext.file_hash(self.pdf)})
        self.trust.start()

    def tearDown(self):
        self.trust.stop()
        self.directory.cleanup()

    def save(self, value=None):
        value = copy.deepcopy(value or self.index)
        value["sha256"] = fulltext.canonical_hash({k:v for k,v in value.items() if k != "sha256"})
        self.path.write_text(json.dumps(value),encoding="utf-8")

    def test_valid_index_and_literal_negative_context(self):
        self.save()
        index = fulltext.load_index(self.path)
        found = fulltext.retrieve(index,"hydroxychloroquine renal",disease="ra")
        self.assertEqual(found[0]["text"],self.text)
        self.assertIn("No renal benefit",found[0]["text"])

    def test_bilingual_query_and_no_unconditional_hit(self):
        self.assertEqual(len(fulltext.retrieve(self.index,"\u7f9f\u6c2f\u55b9")),1)
        self.assertEqual(fulltext.retrieve(self.index,"zzzz_unrelated_999999"),[])
        self.assertEqual(fulltext.retrieve(self.index,"hydroxychloroquine",disease="gout"),[])
        with self.assertRaises(ValueError):fulltext.retrieve(self.index,"test",source_id="not_registered")

    def test_known_corrected_page_is_not_retrieved(self):
        self.index["chunks"][0]["retrieval_eligible"] = False
        self.assertEqual(fulltext.retrieve(self.index,"hydroxychloroquine"),[])

    def test_modified_source_bytes_are_rejected(self):
        self.save()
        self.pdf.write_bytes(self.pdf.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError,"source_integrity"):fulltext.load_index(self.path)

    def test_modified_image_bytes_are_rejected(self):
        self.save()
        self.png.write_bytes(self.png.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError,"page_image_integrity"):fulltext.load_index(self.path)

    def test_outside_paths_are_rejected_even_with_matching_hash(self):
        self.index["chunks"][0]["image_path"] = str(self.png.resolve())
        self.index["pages"][0]["image_path"] = str(self.png.resolve())
        self.save()
        with self.assertRaisesRegex(ValueError,"invalid_index_path"):fulltext.load_index(self.path)

    def test_rejected_or_synthetic_source_is_not_accepted(self):
        for value in ("tcm-sjd-crcj-rct-2022","synthetic-trial"):
            index = copy.deepcopy(self.index)
            index["sources"][0]["id"] = value
            self.save(index)
            with self.assertRaisesRegex(ValueError,"untrusted"):fulltext.load_index(self.path)
        index = copy.deepcopy(self.index)
        index["data_origin"] = "synthetic"
        self.save(index)
        with self.assertRaisesRegex(ValueError,"provenance"):fulltext.load_index(self.path)

    def test_page_quote_and_hash_cannot_be_reassigned(self):
        self.index["chunks"][0]["text"] = "Renal benefit was measured."
        self.index["chunks"][0]["text_sha256"] = hashlib.sha256(self.index["chunks"][0]["text"].encode()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError,"chunk_page_binding"):fulltext.load_index(self.path)

    def test_retrieval_budget_keeps_whole_chunks(self):
        chunks = []
        for n in range(10):
            chunks.append({**self.index["chunks"][0],"id":f"ft_{n:024x}","text":"renal "*500})
        self.index["chunks"] = chunks
        found = fulltext.retrieve(self.index,"renal",limit=8)
        self.assertEqual(len(found),4)
        self.assertEqual(sum(len(c["text"]) for c in found),12000)

    def test_malformed_records_fail_as_value_error(self):
        cases = [(section, None, value) for section in ("sources", "pages", "chunks") for value in (None, [], 4)]
        cases += [("sources", "id", []), ("sources", "disease", {}),
                  ("pages", "source_id", []), ("pages", "pdf_page", {}),
                  ("chunks", "id", []), ("chunks", "source_id", {})]
        for section, field, value in cases:
            with self.subTest(section=section,field=field,value=value):
                index = copy.deepcopy(self.index)
                if field is None:
                    index[section][0] = value
                else:
                    index[section][0][field] = value
                self.save(index)
                with self.assertRaises(ValueError):fulltext.load_index(self.path)

    def test_malformed_retrieval_parameters_fail_as_value_error(self):
        for kwargs in ({"disease": []}, {"source_id": {}}, {"limit": True}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):fulltext.retrieve(self.index,"test",**kwargs)

    def test_source_title_words_do_not_crowd_out_requested_findings(self):
        self.index["sources"][0]["title"] = "Rebixiao randomized multicenter controlled double blind trial"
        self.index["chunks"] = [{**self.index["chunks"][0], "id":f"ft_{n:024x}",
            "text":"Rebixiao randomized multicenter controlled double blind trial "*55} for n in range(4)]
        target = {**self.index["chunks"][0], "id":"ft_"+"f"*24,
                  "text":"Adverse events were mild. " + "neutral "*700}
        self.index["chunks"].append(target)
        query = "What adverse events were reported in the Rebixiao randomized multicenter controlled double blind trial?"
        found = fulltext.retrieve(self.index,query,source_id=self.sid)
        self.assertIn(target["id"], [c["id"] for c in found])

    def test_source_title_filter_keeps_clinical_focus_and_title_only_queries(self):
        self.index["sources"][0]["title"] = "Efficacy of Rebixiao"
        self.index["chunks"][0]["text"] = "Efficacy was assessed."
        found = fulltext.retrieve(self.index,"Rebixiao efficacy at 12 weeks",source_id=self.sid)
        self.assertTrue(found)
        self.index["chunks"][0]["text"] = "Rebixiao"
        self.assertTrue(fulltext.retrieve(self.index,"Rebixiao",source_id=self.sid))

    def test_selected_title_does_not_erase_explicit_chinese_design_question(self):
        self.index["sources"][0]["title"] = "A multicenter double blind randomized controlled trial"
        self.index["chunks"][0]["text"] = "This multicenter double-blind randomized controlled trial was registered."
        question = "\u8fd9\u9879\u7814\u7a76\u91c7\u7528\u4ec0\u4e48\u7814\u7a76\u8bbe\u8ba1\uff0c\u662f\u5426\u591a\u4e2d\u5fc3\u548c\u53cc\u76f2\uff1f"
        self.assertTrue(fulltext.retrieve(self.index, question, source_id=self.sid))
        self.assertEqual(fulltext.retrieve(self.index, "\u672a\u77e5\u4fe1\u606f", source_id=self.sid), [])


@unittest.skipUnless(fulltext.DEFAULT_INDEX.is_file(), "Local fulltext index is not installed")
class RealFullTextRetrievalTests(unittest.TestCase):
    def test_rebixiao_adverse_events_query_retrieves_results_page(self):
        index = fulltext.load_index()
        found = fulltext.retrieve(index,"What adverse events were reported in the Rebixiao trial?",
                                  source_id="tcm-gout-rbx-rct-2020")
        self.assertIn(7, [c["pdf_page"] for c in found])
        self.assertLessEqual(sum(len(c["text"]) for c in found),12000)

    def test_default_chinese_adverse_events_prompt_keeps_results_page_in_model_request(self):
        from app.extractive import build_span_request
        index = fulltext.load_index()
        for outcome in ("\u4e0d\u826f\u4e8b\u4ef6", "\u526f\u4f5c\u7528"):
            question = "\u70ed\u75f9\u6d88\u7814\u7a76\u62a5\u544a\u4e86\u54ea\u4e9b" + outcome + "\uff1f"
            with self.subTest(outcome=outcome):
                found = fulltext.retrieve(index,question,source_id="tcm-gout-rbx-rct-2020")
                self.assertIn(7, [c["pdf_page"] for c in found])
                request, selected = build_span_request(question,found)
                self.assertIn(7, [c["pdf_page"] for c in selected])
                self.assertIn(question,request["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
