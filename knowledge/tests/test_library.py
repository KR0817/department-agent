"""Synthetic inventory boundaries; no clinical conclusions."""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from app.core import ROOT, load_catalog
from app.library import public_inventory
from app.server import make_server


class LibraryTests(unittest.TestCase):
    def source(self, **updates):
        return {"id": "synthetic-paper", "title": "Synthetic full text", "pmid": "999999999",
                "doi": "10.1234/SYNTHETIC", "pmcid": "PMC999999999", "disease": "ra",
                "evidence_kind": "xml_section", "retrieval_eligible": True,
                "locator_url": "/api/fulltext/section/ft_" + "1" * 24,
                "xml_path": "private/local/path", "xml_sha256": "private-hash", **updates}

    def test_identity_dedup_and_actual_access_counts(self):
        fulltext = {"sources": [self.source(), self.source(id="other-id", doi="https://doi.org/10.1234/synthetic")]}
        clinical = {"sources": [self.source(id="third-id"), self.source(id="abstract", pmid="111", doi=None, pmcid=None)]}
        before = copy.deepcopy((fulltext, clinical))
        result = public_inventory(fulltext, clinical)
        self.assertEqual(result["counts"], {"total": 2, "fulltext": 1, "indexed": 1, "clinical_approved": 0})
        self.assertEqual((fulltext, clinical), before)
        self.assertEqual(result["sources"][0]["access"], "fulltext_xml")
        self.assertEqual(result["sources"][1]["access"], "abstract_only")
        self.assertIsNone(result["sources"][1]["fulltext_source_id"])
        self.assertNotIn("private", json.dumps(result))

    def test_ineligible_sources_do_not_get_ask_action_or_approval(self):
        result = public_inventory({"sources": [self.source(retrieval_eligible=False, clinical_approval="forged")]}, {})
        self.assertIsNone(result["sources"][0]["fulltext_source_id"])
        self.assertEqual(result["sources"][0]["review_status"], "pending")
        self.assertIsNone(result["sources"][0]["clinical_approval"])
        self.assertEqual(result["counts"]["indexed"], 0)

    def test_external_locator_and_active_source_url_not_projected(self):
        result = public_inventory({"sources": [self.source(locator_url="https://attacker.example/path", source_url="javascript:alert(1)")]}, {})
        self.assertIsNone(result["sources"][0]["locator_url"])
        self.assertEqual(result["sources"][0]["source_url"], "https://pmc.ncbi.nlm.nih.gov/articles/PMC999999999/")

    def test_real_http_inventory_and_section_keep_clinical_catalog_separate(self):
        (ROOT / "work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as directory:
            extractor = {"catalog": lambda: {"sources": [self.source()]},
                         "section": lambda cid: b"<p>Synthetic escaped section</p>" if cid == "ft_" + "1" * 24 else None}
            server = make_server(0, Path(directory) / "test.sqlite3", extractor=extractor)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def get(path):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                try:
                    conn.request("GET", path)
                    response = conn.getresponse()
                    return response.status, response.getheader("Content-Type"), response.read()
                finally:
                    conn.close()
            try:
                status, _, raw = get("/api/literature")
                self.assertEqual(status, 200)
                result = json.loads(raw)
                self.assertEqual(result["counts"]["total"], 1)
                self.assertEqual(result["counts"]["fulltext"], 1)
                clinical = json.loads(get("/api/catalog")[2])
                self.assertEqual(len(clinical["sources"]), 0)
                status, media, _ = get("/api/fulltext/section/ft_" + "1" * 24)
                self.assertEqual(status, 200)
                self.assertTrue(media.startswith("text/html"))
                self.assertEqual(get("/api/fulltext/section/unknown")[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
