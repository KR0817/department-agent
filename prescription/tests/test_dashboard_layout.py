"""Synthetic contract checks for the opt-in markup-only layout refinement."""
from collections import Counter
import json
from pathlib import Path
import re
import tempfile
import unittest

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_sources import build_source_dashboard
from test_original_interactions import fixture


def source_page(payload=None):
    data = fixture() if payload is None else payload
    data["provenance"]["synthetic_mode"] = True
    return HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(data, ensure_ascii=True)).replace("__TITLE__", "Synthetic layout fixture")


def scripts(page):
    return re.findall(r"<script\b[^>]*>.*?</script>", page, re.S)


class DashboardLayoutTests(unittest.TestCase):
    def test_preserves_all_existing_scripts_and_embedded_values(self):
        page = source_page()
        result = refine_local_layout(page)
        original_scripts = scripts(page)
        self.assertEqual(scripts(result)[:len(original_scripts)], original_scripts)
        self.assertEqual(len(scripts(result)), len(original_scripts) + 1)
        payload_pattern = r'<script id="dashboard-data" type="application/json">(.*?)</script>'
        self.assertEqual(json.loads(re.search(payload_pattern, result, re.S)[1]),
                         json.loads(re.search(payload_pattern, page, re.S)[1]))

    def test_preserves_interaction_ids_without_duplicates(self):
        page = source_page()
        result = refine_local_layout(page)
        original_markup = page.split('<script id="dashboard-data"', 1)[0]
        refined_markup = result.split('<script id="dashboard-data"', 1)[0]
        original_ids = Counter(re.findall(r'\bid="([^"]+)"', original_markup))
        refined_ids = Counter(re.findall(r'\bid="([^"]+)"', refined_markup))
        for identifier, count in original_ids.items():
            self.assertEqual(refined_ids[identifier], count, identifier)
        self.assertTrue(all(count == 1 for count in refined_ids.values()))
        for identifier in ("analysis-source", "research-item", "annual-item", "network-item", "view-back"):
            if identifier in original_ids:
                self.assertIn(identifier, refined_ids)

    def test_two_source_payloads_and_existing_handlers_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in (("primary", fixture()), ("supplement", fixture(True))):
                (root / (name + ".html")).write_text(source_page(payload), encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html",
                                   refresh_template=True, default_source="primary")
            page = (root / "view.html").read_text(encoding="utf-8")
            result = refine_local_layout(page)
            self.assertEqual(scripts(result)[:len(scripts(page))], scripts(page))
            self.assertEqual(result.count('id="analysis-source"'), 1)
            for identifier in ("dashboard-data", "supplement-data"):
                expression = '<script id="' + identifier + '" type="application/json">(.*?)</script>'
                self.assertEqual(re.search(expression, result, re.S)[1], re.search(expression, page, re.S)[1])

    def test_idempotence_does_not_duplicate_styles_or_controls(self):
        once = refine_local_layout(source_page())
        self.assertEqual(refine_local_layout(once), once)
        self.assertEqual(once.count('<body class="local-original-view">'), 1)
        self.assertEqual(once.count('id="formula-evidence"'), 1)

    def test_missing_required_markup_fails_closed(self):
        page = source_page()
        for anchor in ("<body>", '<main class="main">', "</style>", '<details class="evidence">',
                       '<p id="research-order-note">', '  <div class="focus-state">'):
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                refine_local_layout(page.replace(anchor, "", 1))

    def test_ambiguous_required_markup_fails_closed(self):
        page = source_page()
        for anchor in ("<body>", '<main class="main">', "</style>", '<details class="evidence">'):
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                refine_local_layout(page.replace(anchor, anchor + anchor, 1))

    def test_unsupported_empty_page_fails_closed(self):
        with self.assertRaises(DashboardError):
            refine_local_layout("<html><body>Empty fixture</body></html>")


if __name__ == "__main__":
    unittest.main()
