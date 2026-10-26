"""Synthetic contract and real HTTP checks; no clinical or model-quality claims."""

import base64
import copy
import hashlib
import http.client
import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from app import extractive
from app.core import ROOT
from app.extractive import (MODEL, build_request, build_span_request, make_extractor,
                            resolve_completion, resolve_span_completion, selection_units)
from app.server import make_server


CID = "ft_" + "1" * 24
QUOTE = "The synthetic study did not assess long-term outcomes."
TEXT = "Methods and results. " + QUOTE + " Follow-up lasted four weeks."
SOURCE = {"id": "synthetic-source", "title": "Synthetic contract fixture, not clinical evidence",
          "doi": None, "pmid": None, "disease": "gout", "quality_note": "Synthetic test only"}
CHUNK = {"id": CID, "source_id": SOURCE["id"], "pdf_page": 2, "text": TEXT,
         "quality_note": "Synthetic test only", "image_path": "work/missing-test-image.png",
         "image_sha256": "0" * 64}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGawAAAAASUVORK5CYII=")


def fixture_index(chunk=None):
    return {"version": "synthetic-test", "sha256": "a" * 64,
            "sources": [copy.deepcopy(SOURCE)], "chunks": [copy.deepcopy(chunk or CHUNK)]}


def model_completion(quote=QUOTE, cid=CID, status="extracts"):
    selections = [{"chunk_id": cid, "quote": quote}] if status == "extracts" else []
    return {"model": MODEL, "done": True, "done_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"status": status, "selections": selections})}}


def span_completion(selections=None, status="extracts"):
    if selections is None:
        unit = next(unit for unit in selection_units([CHUNK]) if unit["text"] == QUOTE)
        selections = [{"start_id": unit["id"], "end_id": unit["id"]}] if status == "extracts" else []
    return {"model": MODEL, "done": True, "done_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"status": status, "selections": selections})}}


def payload(**updates):
    return {"question": "What follow-up outcomes did the synthetic study assess?", "disease": "gout",
            "source_id": "all", "index_sha256": "a" * 64, **updates}


ZH_QUOTE = "\u8be5\u6a21\u62df\u7814\u7a76\u672a\u8bc4\u4f30\u957f\u671f\u7ed3\u5c40\u3002"


def translation_completion(text=ZH_QUOTE):
    return {"model": MODEL, "done": True, "done_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"items": [{"id": "t1", "text_zh": text}]})}}


def answer_transport(request):
    completion = translation_completion() if "items" in request["format"]["properties"] else span_completion()
    return {"completion": completion}


class QuoteContractTests(unittest.TestCase):
    def resolve(self, completion, candidates=None):
        return resolve_completion(completion, candidates or [CHUNK], [SOURCE])

    def test_exact_unique_quote_uses_server_metadata_and_offsets(self):
        status, extracts = self.resolve(model_completion())
        self.assertEqual(status, "extracts")
        item = extracts[0]
        self.assertEqual(item["quote"], QUOTE)
        self.assertEqual(TEXT[item["quote_start"]:item["quote_end"]], QUOTE)
        self.assertEqual(item["title"], SOURCE["title"])
        self.assertIsNone(item["doi"])
        self.assertIsNone(item["pmid"])
        self.assertEqual(item["pdf_page"], CHUNK["pdf_page"])
        self.assertEqual(item["context"], TEXT)
        self.assertEqual(item["quote_sha256"], hashlib.sha256(QUOTE.encode()).hexdigest())
        self.assertEqual(item["page_url"], "/api/fulltext/page/" + CID)
        self.assertNotIn("support", item)

    def test_unknown_candidate_and_forged_metadata_are_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve(model_completion(cid="ft_" + "2" * 24))
        for field in ("source_id", "pmid", "doi", "page_url", "clinical_approval"):
            with self.subTest(field=field):
                completion = model_completion()
                body = json.loads(completion["message"]["content"])
                body["selections"][0][field] = "forged"
                completion["message"]["content"] = json.dumps(body)
                with self.assertRaises(ValueError):
                    self.resolve(completion)

    def test_edited_noncontiguous_short_and_long_quotes_are_rejected(self):
        for quote in (QUOTE.replace("not ", ""), "Methods and results. ... Follow-up lasted four weeks.",
                      "short", "x" * 1601):
            with self.subTest(quote=quote[:40]), self.assertRaises(ValueError):
                self.resolve(model_completion(quote=quote))

    def test_duplicate_and_ambiguous_quotes_are_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve(model_completion(), [{**CHUNK, "text": TEXT + " " + QUOTE}])
        completion = model_completion()
        value = json.loads(completion["message"]["content"])
        value["selections"] *= 2
        completion["message"]["content"] = json.dumps(value)
        with self.assertRaises(ValueError):
            self.resolve(completion)

    def test_partial_valid_output_does_not_hide_invalid_selection(self):
        completion = model_completion()
        value = json.loads(completion["message"]["content"])
        value["selections"].append({"chunk_id": CID, "quote": "This is invented text."})
        completion["message"]["content"] = json.dumps(value)
        with self.assertRaises(ValueError):
            self.resolve(completion)

    def test_model_completion_role_tools_thinking_and_truncation(self):
        mutations = [({"done": False}, {}), ({"done": 1}, {}), ({"model": "other"}, {}),
                     ({"done_reason": "length"}, {}), ({}, {"role": "user"}),
                     ({}, {"tool_calls": [{"function": {"name": "untrusted"}}]}),
                     ({}, {"thinking": "Unexpected reasoning output"})]
        for outer, message in mutations:
            with self.subTest(outer=outer, message=message):
                completion = model_completion()
                completion.update(outer)
                completion["message"].update(message)
                with self.assertRaises(ValueError):
                    self.resolve(completion)

    def test_malformed_duplicate_key_and_extra_json_fields(self):
        values = ["not JSON", '```json\n{"status":"insufficient","selections":[]}\n```',
                  '{"status":"extracts","status":"insufficient","selections":[]}',
                  '{"status":"insufficient","selections":[],"answer":"invented"}',
                  '{"status":"extracts","selections":[]}',
                  json.dumps({"status": "insufficient", "selections": [{"chunk_id": CID, "quote": QUOTE}]}),
                  json.dumps({"status": "extracts", "selections": [{"chunk_id": CID, "quote": QUOTE}] * 4})]
        for value in values:
            with self.subTest(value=value):
                completion = model_completion()
                completion["message"]["content"] = value
                with self.assertRaises(ValueError):
                    self.resolve(completion)

    def test_insufficient_is_explicit_and_empty(self):
        self.assertEqual(self.resolve(model_completion(status="insufficient")), ("insufficient", []))


class RequestBudgetTests(unittest.TestCase):
    def test_unicode_preserved_and_budget_keeps_complete_chunks(self):
        question = "\u8bd5\u9a8c\u7684\u7ed3\u5c40\u662f\u4ec0\u4e48\uff1f"
        candidates = [{**CHUNK, "id": "ft_" + str(i) * 24,
                       "text": ("\u6c49" * 2100) + " NEGATION AND QUALIFIER AT END " + str(i)} for i in range(4)]
        request, selected = build_request(question, candidates)
        self.assertGreater(len(selected), 0)
        self.assertLess(len(selected), len(candidates))
        content = request["messages"][1]["content"]
        self.assertIn(question, content)
        decoded = json.loads(content)
        self.assertEqual(decoded["question"], question)
        self.assertEqual(decoded["candidates"], [{"chunk_id": c["id"], "text": c["text"]} for c in selected])
        self.assertTrue(all(c["text"].endswith(str(candidates.index(c))) for c in selected))
        self.assertEqual(request["format"]["properties"]["selections"]["items"]["properties"]["chunk_id"]["enum"], [c["id"] for c in selected])
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=True).encode("ascii")), 60000)
        self.assertFalse(request["stream"])
        self.assertFalse(request["think"])

    def test_oversized_chunk_skipped_without_truncating_later_chunk(self):
        candidates = [{**CHUNK, "id": "oversized", "text": "\u6c49" * 10000}, CHUNK]
        request, selected = build_request("Synthetic question", candidates)
        self.assertEqual(selected, [CHUNK])
        self.assertEqual(json.loads(request["messages"][1]["content"])["candidates"][0]["text"], TEXT)

    def test_nonallowlisted_model_rejected(self):
        with self.assertRaises(ValueError):
            build_request("Synthetic question", [CHUNK], "external-model")


class SpanSelectionTests(unittest.TestCase):
    def resolve(self, selections=None, candidates=None, status="extracts"):
        return resolve_span_completion(span_completion(selections, status), candidates or [CHUNK], [SOURCE])

    def test_single_unit_restores_original_quote_and_server_metadata(self):
        status, extracts = self.resolve()
        self.assertEqual(status, "extracts")
        self.assertEqual(extracts[0]["quote"], QUOTE)
        self.assertEqual(extracts[0]["title"], SOURCE["title"])
        self.assertEqual(extracts[0]["context"], TEXT)
        self.assertIsNone(extracts[0]["pmid"])

    def test_contiguous_range_preserves_intervening_line_breaks_and_qualifiers(self):
        text = "  First synthetic sentence.\n\nThe benefit was not\nassessed beyond four weeks.\n  Last synthetic sentence.  "
        chunk = {**CHUNK, "text": text}
        units = selection_units([chunk])
        self.assertEqual(len(units), 3)
        _, extracts = self.resolve([{"start_id": units[0]["id"], "end_id": units[1]["id"]}], [chunk])
        expected = text[units[0]["start"]:units[1]["end"]]
        self.assertEqual(extracts[0]["quote"], expected)
        self.assertIn("\n\n", extracts[0]["quote"])
        self.assertIn("not\nassessed", extracts[0]["quote"])
        self.assertEqual(extracts[0]["quote_start"], units[0]["start"])
        self.assertEqual(extracts[0]["quote_end"], units[1]["end"])

    def test_unknown_cross_chunk_reversed_and_overlapping_ids_rejected(self):
        second = {**CHUNK, "id": "ft_" + "2" * 24, "text": "Another synthetic study with a different result."}
        units = selection_units([CHUNK, second])
        first, middle, last, other = (unit["id"] for unit in units)
        invalid = [[{"start_id": "unknown", "end_id": middle}],
                   [{"start_id": middle, "end_id": other}],
                   [{"start_id": last, "end_id": first}],
                   [{"start_id": first, "end_id": middle}, {"start_id": middle, "end_id": last}],
                   [{"start_id": middle, "end_id": middle}] * 2,
                   [{"start_id": None, "end_id": middle}]]
        for selections in invalid:
            with self.subTest(selections=selections), self.assertRaises(ValueError):
                self.resolve(selections, [CHUNK, second])

    def test_nonoverlapping_ranges_remain_separate(self):
        units = selection_units([CHUNK])
        _, extracts = self.resolve([{"start_id": units[i]["id"], "end_id": units[i]["id"]} for i in (0, 2)])
        self.assertEqual([item["quote"] for item in extracts], [units[i]["text"] for i in (0, 2)])

    def test_too_short_long_or_ambiguous_restored_quotes_rejected(self):
        for text in ("Hi.", "x" * 1601 + ".", QUOTE + " " + QUOTE):
            with self.subTest(length=len(text)):
                chunk = {**CHUNK, "text": text}
                unit = selection_units([chunk])[0]
                with self.assertRaises(ValueError):
                    self.resolve([{"start_id": unit["id"], "end_id": unit["id"]}], [chunk])

    def test_extra_metadata_invalid_status_and_partial_invalid_output_rejected(self):
        unit = selection_units([CHUNK])[1]["id"]
        selection = {"start_id": unit, "end_id": unit}
        for selections, status in (([{**selection, "quote": QUOTE}], "extracts"),
                                   ([{**selection, "pmid": "forged"}], "extracts"),
                                   ([selection, {"start_id": "unknown", "end_id": unit}], "extracts"),
                                   ([selection] * 4, "extracts"), ([selection], "insufficient"),
                                   ([], "extracts"), ([], "invented")):
            with self.subTest(selections=selections, status=status), self.assertRaises(ValueError):
                self.resolve(selections, status=status)
        self.assertEqual(self.resolve([], status="insufficient"), ("insufficient", []))

    def test_span_selection_still_validates_completion_envelope(self):
        for field, value in (("done", False), ("done_reason", "length"), ("model", "another-model")):
            completion = span_completion()
            completion[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                resolve_span_completion(completion, [CHUNK], [SOURCE])
        for field, value in (("role", "user"), ("tool_calls", [{"name": "untrusted"}]), ("thinking", "unexpected")):
            completion = span_completion()
            completion["message"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                resolve_span_completion(completion, [CHUNK], [SOURCE])

    def test_unit_id_collisions_are_rejected(self):
        second = {**CHUNK, "id": CID[:-1] + "2"}
        with self.assertRaises(ValueError):
            selection_units([CHUNK, second])

    def test_span_request_preserves_unicode_and_whole_candidate_budget(self):
        question = "\u7ed3\u5c40\u6307\u6807\u662f\u4ec0\u4e48\uff1f"
        candidates = [{**CHUNK, "id": "ft_" + str(i) * 24,
                       "text": "\u6c49" * 2100 + " Final qualifier."} for i in range(4)]
        request, selected = build_span_request(question, candidates)
        self.assertGreater(len(selected), 0)
        self.assertLess(len(selected), len(candidates))
        content = request["messages"][1]["content"]
        self.assertIn(question, content)
        decoded = json.loads(content)
        units = selection_units(selected)
        expected = [{"source_id": chunk["source_id"], "source_title": None, "locator": "PDF page 2",
                     "source_type": None, "question_scope": None, "required_bundle": None,
                     "units": [{"id": unit["id"], "text": unit["text"]}
                     for unit in units if unit["chunk_id"] == chunk["id"]]} for chunk in selected]
        self.assertEqual(decoded["candidates"], expected)
        self.assertEqual(decoded["question_intent"], "general")
        self.assertTrue(all(chunk in candidates for chunk in selected))
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=True).encode("ascii")), 60000)
        properties = request["format"]["properties"]["selections"]["items"]["properties"]
        for key in ("start_id", "end_id"):
            self.assertEqual(properties[key]["enum"], [unit["id"] for unit in units])
        self.assertEqual(set(properties), {"start_id", "end_id"})


class ExtractorBehaviorTests(unittest.TestCase):
    def setUp(self):
        integrity = patch("app.extractive.check_context", return_value=None)
        integrity.start()
        self.addCleanup(integrity.stop)

    def make(self, transport=None, retrieved=None):
        retrieval = patch("app.fulltext.retrieve", return_value=[CHUNK] if retrieved is None else retrieved)
        mocked = retrieval.start()
        self.addCleanup(retrieval.stop)
        transport = transport or Mock(side_effect=answer_transport)
        return make_extractor(fixture_index(), transport=transport), transport, mocked

    def assert_unapproved(self, result):
        self.assertIsNone(result["clinical_approval"])
        self.assertEqual(result["completeness"], "unassessed")
        self.assertNotIn("support", result)

    def test_success_and_configured_inventory_are_not_clinical_approval(self):
        extractor, transport, retrieval = self.make()
        self.assertEqual(extractor["catalog"]()["model_status"], "not_run")
        result = extractor["extract"](payload(source_id=SOURCE["id"]))
        self.assertEqual(result["status"], "extracts")
        self.assertEqual(result["anchoring"], "exact_unique_substrings")
        self.assertEqual(result["extraction_method"], "server_span_selection")
        self.assert_unapproved(result)
        self.assertEqual(extractor["catalog"]()["model_status"], "completed")
        self.assertEqual(retrieval.call_args.kwargs, {"disease": "gout", "source_id": SOURCE["id"], "limit": 8})
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result["answer_language"], "zh-CN")
        self.assertEqual(result["translation_status"], "complete")
        self.assertEqual(result["extracts"][0]["answer_zh"], ZH_QUOTE)
        self.assertEqual(result["extracts"][0]["quote"], QUOTE)

    def test_no_candidates_does_not_call_model(self):
        extractor, transport, _ = self.make(retrieved=[])
        result = extractor["extract"](payload())
        self.assertEqual(result["status"], "insufficient")
        self.assertFalse(result["model_called"])
        self.assertEqual(result["retrieved_count"], 0)
        self.assert_unapproved(result)
        transport.assert_not_called()

    def test_transport_failure_is_not_insufficient_and_releases_lock(self):
        for failure in (OSError("private detail"), ValueError("private detail"), TimeoutError("private detail"),
                        subprocess.TimeoutExpired("synthetic command", 1)):
            with self.subTest(failure=type(failure).__name__):
                transport = Mock(side_effect=[failure, {"completion": span_completion()}, {"completion": translation_completion()}])
                extractor, _, _ = self.make(transport=transport)
                result = extractor["extract"](payload())
                self.assertEqual(result["status"], "model_unavailable")
                self.assertNotIn("private detail", json.dumps(result))
                self.assert_unapproved(result)
                self.assertEqual(extractor["catalog"]()["model_status"], "unavailable")
                self.assertEqual(extractor["extract"](payload())["status"], "extracts")
                self.assertEqual(transport.call_count, 3)

    def test_invalid_output_not_retried_or_returned(self):
        transport = Mock(return_value={"completion": span_completion([{"start_id": "invented private model output", "end_id": "unknown"}])})
        extractor, _, _ = self.make(transport=transport)
        result = extractor["extract"](payload())
        self.assertEqual(result["status"], "invalid_model_output")
        self.assertEqual(result["extracts"], [])
        self.assertNotIn("invented private model output", json.dumps(result))
        self.assert_unapproved(result)
        transport.assert_called_once()

    def test_model_insufficient_is_distinct_from_transport_failure(self):
        transport = Mock(return_value={"completion": span_completion(status="insufficient")})
        extractor, _, _ = self.make(transport=transport)
        result = extractor["extract"](payload())
        self.assertEqual(result["status"], "insufficient")
        self.assertTrue(result["model_called"])
        self.assertEqual(result["anchoring"], "not_applicable")
        self.assert_unapproved(result)

    def test_busy_second_request_does_not_reenter_transport(self):
        entered, release = threading.Event(), threading.Event()

        def waiting_transport(request):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic synchronization timeout")
            return answer_transport(request)

        transport = Mock(side_effect=waiting_transport)
        extractor, _, _ = self.make(transport=transport)
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(extractor["extract"], payload())
            try:
                self.assertTrue(entered.wait(2))
                result = extractor["extract"](payload())
                self.assertEqual(result["status"], "busy")
                self.assert_unapproved(result)
                transport.assert_called_once()
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2)["status"], "extracts")

    def test_translation_failure_never_falls_back_to_english_answer(self):
        for failure in (TimeoutError("private detail"), {"completion": translation_completion("Invented English answer")}):
            with self.subTest(failure=type(failure).__name__):
                transport = Mock(side_effect=[{"completion": span_completion()}, failure])
                extractor, _, _ = self.make(transport=transport)
                result = extractor["extract"](payload())
                self.assertEqual(result["status"], "extracts")
                self.assertEqual(result["translation_status"], "unavailable")
                self.assertTrue(result["translation_model_called"])
                self.assertIsNone(result["extracts"][0]["answer_zh"])
                self.assertEqual(result["extracts"][0]["quote"], QUOTE)
                self.assertNotIn("private detail", json.dumps(result))
                self.assertEqual(transport.call_count, 2)

    def test_chinese_source_passes_through_without_second_model_call(self):
        chunk = {**CHUNK, "text": ZH_QUOTE}
        unit = selection_units([chunk])[0]
        completion = span_completion([{"start_id": unit["id"], "end_id": unit["id"]}])
        transport = Mock(return_value={"completion": completion})
        with patch("app.fulltext.retrieve", return_value=[chunk]):
            result = make_extractor(fixture_index(chunk), transport=transport)["extract"](payload())
        self.assertEqual(result["extracts"][0]["answer_zh"], ZH_QUOTE)
        self.assertEqual(result["extracts"][0]["translation_status"], "source_chinese")
        self.assertFalse(result["translation_model_called"])
        transport.assert_called_once()

    def test_request_lock_stays_held_during_translation(self):
        entered, release = threading.Event(), threading.Event()

        def waiting_transport(request):
            if "items" in request["format"]["properties"]:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("synthetic synchronization timeout")
            return answer_transport(request)

        extractor, transport, _ = self.make(transport=Mock(side_effect=waiting_transport))
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(extractor["extract"], payload())
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(extractor["extract"](payload())["status"], "busy")
                self.assertEqual(transport.call_count, 2)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2)["translation_status"], "complete")

    def test_payload_and_index_validation_precede_inference(self):
        extractor, transport, _ = self.make()
        invalid = [[], {}, payload(extra="x"), payload(question=""), payload(question=1),
                   payload(question="x" * 1001), payload(disease=[]), payload(disease="unknown"),
                   payload(source_id="unknown"), payload(index_sha256="b" * 64)]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                extractor["extract"](value)
        transport.assert_not_called()


class ExtractiveHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "work").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-extractive-test-", dir=ROOT / "work")
        cls.image = Path(cls.temp.name) / "synthetic.png"
        cls.image.write_bytes(PNG)
        cls.chunk = {**CHUNK, "image_path": cls.image.relative_to(ROOT).as_posix(),
                     "image_sha256": hashlib.sha256(PNG).hexdigest()}
        cls.retrieval_patch = patch("app.fulltext.retrieve", return_value=[cls.chunk])
        cls.retrieval = cls.retrieval_patch.start()
        cls.integrity_patch = patch("app.extractive.check_context", return_value=None)
        cls.integrity_patch.start()
        cls.transport = Mock(side_effect=answer_transport)
        cls.extractor = make_extractor(fixture_index(cls.chunk), transport=cls.transport)
        cls.database = Path(cls.temp.name) / "synthetic.sqlite3"
        cls.server = make_server(0, cls.database, extractor=cls.extractor)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.retrieval_patch.stop()
        cls.integrity_patch.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.transport.reset_mock()

    def request(self, path, body=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        supplied = {"Content-Type": "application/json", **(headers or {})}
        connection.request("POST" if data is not None else "GET", path, data, supplied)
        try:
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_catalog_has_no_local_paths_and_status_keeps_separate_boundary(self):
        status, _, raw = self.request("/api/fulltext")
        data = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["answer_language"], "zh-CN")
        self.assertEqual(data["chunk_count"], 1)
        self.assertNotIn("image_path", str(data))
        self.assertNotIn("pdf_path", str(data))
        data = json.loads(self.request("/api/status")[2])
        self.assertEqual(data["model"], "not_connected")
        self.assertEqual(data["extractive_research"], "enabled")
        self.assertFalse(data["clinical_release"])

    def test_success_response_keeps_approval_empty(self):
        status, _, raw = self.request("/api/extract", payload())
        result = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "extracts")
        self.assertEqual(result["extracts"][0]["answer_zh"], ZH_QUOTE)
        self.assertEqual(result["extracts"][0]["translation_status"], "machine_translated")
        self.assertIsNone(result["clinical_approval"])
        self.assertEqual(result["completeness"], "unassessed")
        self.assertNotIn("request_id", result)
        self.assertNotIn("receipt_url", result)

    def test_source_integrity_failure_is_a_distinct_http_result(self):
        with patch("app.extractive.check_context", side_effect=ValueError("private source detail")):
            status, _, raw = self.request("/api/extract", payload())
        result = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["error"], "source_integrity_failure")
        self.assertFalse(result["model_called"])
        self.assertEqual(result["extracts"], [])
        self.assertNotIn("private source detail", raw.decode())
        self.transport.assert_not_called()

    def test_strict_payload_and_stale_index(self):
        for value in ({}, [], payload(extra="forged"), payload(source_id="unknown"), payload(disease={})):
            with self.subTest(value=value):
                self.assertEqual(self.request("/api/extract", value)[0], 400)
        status, _, raw = self.request("/api/extract", payload(index_sha256="b" * 64))
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw), {"error": "stale_fulltext_index"})
        self.transport.assert_not_called()

    def test_duplicate_keys_invalid_media_and_body_limit(self):
        self.assertEqual(self.request("/api/extract", raw=b'{"question":"one","question":"two"}')[0], 400)
        self.assertEqual(self.request("/api/extract", payload(), {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/extract", payload(question="x" * 40000))[0], 413)
        self.transport.assert_not_called()

    def test_origin_host_and_route_boundaries(self):
        self.assertEqual(self.request("/api/extract", payload(), {"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/extract", payload(), {"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/extract?unexpected=1", payload())[0], 404)
        self.transport.assert_not_called()
        self.assertEqual(self.request("/api/extract", payload(), {"Origin": f"http://127.0.0.1:{self.port}"})[0], 200)

    def test_allowlisted_page_and_unknown_paths(self):
        status, headers, raw = self.request("/api/fulltext/page/" + CID)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("image/png"))
        self.assertEqual(raw, PNG)
        for path in ("/api/fulltext/page/unknown", "/api/fulltext/page/../synthetic.png",
                     "/api/fulltext/page/%2e%2e/synthetic.png", "/api/fulltext/page/" + CID + "/extra"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_changed_page_bytes_are_not_served(self):
        try:
            self.image.write_bytes(PNG + b"tampered")
            status, _, raw = self.request("/api/fulltext/page/" + CID)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(raw), {"error": "not_found"})
        finally:
            self.image.write_bytes(PNG)

    def test_question_and_model_output_never_enter_sqlite(self):
        marker = "SYNTHETIC_QUESTION_PRIVACY_MARKER_90217"
        with closing(sqlite3.connect(self.database)) as connection:
            before = "\n".join(connection.iterdump())
        self.assertEqual(self.request("/api/extract", payload(question=marker))[0], 200)
        with closing(sqlite3.connect(self.database)) as connection:
            after = "\n".join(connection.iterdump())
        self.assertEqual(after, before)
        self.assertNotIn(marker, after)
        self.assertNotIn(QUOTE, after)
        self.assertNotIn(ZH_QUOTE, after)

    def test_page_rejects_outside_workspace_before_reading(self):
        outside = Path(ROOT.anchor) / "outside-synthetic-only.png"
        index = fixture_index({**CHUNK, "image_path": str(outside)})
        extractor = make_extractor(index, transport=self.transport)
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("outside read attempted")):
            self.assertIsNone(extractor["page"](CID))


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-source-integrity-", dir=ROOT / "work")
        self.addCleanup(self.temp.cleanup)
        self.pdf = Path(self.temp.name) / "synthetic.pdf"
        self.pdf_bytes = b"%PDF-1.4\nSynthetic source integrity fixture only.\n%%EOF\n"
        self.pdf.write_bytes(self.pdf_bytes)
        self.image = Path(self.temp.name) / "synthetic.png"
        self.image.write_bytes(PNG)
        self.source = {**SOURCE, "pdf_path": self.pdf.relative_to(ROOT).as_posix(),
                       "pdf_sha256": hashlib.sha256(self.pdf_bytes).hexdigest()}
        self.chunk = {**CHUNK, "image_path": self.image.relative_to(ROOT).as_posix(),
                      "image_sha256": hashlib.sha256(PNG).hexdigest()}
        self.sources = {self.source["id"]: self.source}

    def make(self, transport):
        index = fixture_index(self.chunk)
        index["sources"] = [self.source]
        retrieval = patch("app.fulltext.retrieve", return_value=[self.chunk])
        retrieval.start()
        self.addCleanup(retrieval.stop)
        return make_extractor(index, transport=transport)

    def test_real_context_check_accepts_matching_file_bytes(self):
        self.assertIsNone(extractive.check_context([self.chunk], self.sources))

    def test_real_context_check_rejects_changed_pdf_and_page(self):
        for path, original in ((self.pdf, self.pdf_bytes), (self.image, PNG)):
            with self.subTest(path=path.name):
                try:
                    path.write_bytes(original + b"tampered")
                    with self.assertRaises(ValueError):
                        extractive.check_context([self.chunk], self.sources)
                finally:
                    path.write_bytes(original)

    def test_real_context_check_rejects_missing_source(self):
        missing = {**self.source, "pdf_path": (Path(self.temp.name) / "missing.pdf").relative_to(ROOT).as_posix()}
        with self.assertRaises((ValueError, OSError)):
            extractive.check_context([self.chunk], {missing["id"]: missing})

    def test_changed_source_blocks_before_model_call(self):
        transport = Mock(return_value={"completion": span_completion()})
        extractor = self.make(transport)
        self.pdf.write_bytes(self.pdf_bytes + b"tampered")
        result = extractor["extract"](payload())
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["error"], "source_integrity_failure")
        self.assertFalse(result["model_called"])
        self.assertEqual(result["extracts"], [])
        self.assertIsNone(result["clinical_approval"])
        self.assertEqual(result["completeness"], "unassessed")
        self.assertEqual(extractor["catalog"]()["model_status"], "not_run")
        transport.assert_not_called()

    def test_source_change_during_inference_discards_completed_output(self):
        for path, original in ((self.pdf, self.pdf_bytes), (self.image, PNG)):
            with self.subTest(path=path.name):
                def mutating_transport(request):
                    path.write_bytes(original + b"tampered")
                    return {"completion": span_completion()}

                transport = Mock(side_effect=mutating_transport)
                extractor = self.make(transport)
                try:
                    result = extractor["extract"](payload())
                    self.assertEqual(result["status"], "source_unavailable")
                    self.assertEqual(result["error"], "source_integrity_failure")
                    self.assertTrue(result["model_called"])
                    self.assertEqual(result["extracts"], [])
                    self.assertEqual(result["anchoring"], "not_assessed")
                    self.assertIsNone(result["clinical_approval"])
                    self.assertEqual(result["completeness"], "unassessed")
                    self.assertEqual(extractor["catalog"]()["model_status"], "completed")
                    transport.assert_called_once()
                finally:
                    path.write_bytes(original)

    def test_source_change_during_translation_discards_both_outputs(self):
        def mutating_transport(request):
            if "items" in request["format"]["properties"]:
                self.pdf.write_bytes(self.pdf_bytes + b"tampered")
            return answer_transport(request)

        transport = Mock(side_effect=mutating_transport)
        result = self.make(transport)["extract"](payload())
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["extracts"], [])
        self.assertTrue(result["translation_model_called"])
        self.assertEqual(transport.call_count, 2)


if __name__ == "__main__":
    unittest.main()
