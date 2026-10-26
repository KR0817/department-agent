"""Source switching uses complete payloads and explicit local source identity."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import HTML_TEMPLATE
from mingyirx.dashboard_sources import build_source_dashboard


class SourceProjectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_switching_executes_with_empty_state_exports_and_back_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, n, year in [("primary", 40, "2020"), ("supplement", 20, "2026")]:
                context = {"group": "ra", "stratum_type": "overall", "stratum": "all"}
                item = {**context, "item_name": "Synthetic herb", "exposed_patients": "20", "group_patients": str(n), "prevalence": str(20/n), "dose_patients": "20", "most_common_dose_patients": "20", "most_common_dose_values_g": "12", "most_common_dose_fraction": "1", "most_common_dose_tied": "False"}
                payload = {"groups": [{"code": "ra", "label": "RA", "patients": str(n)}],
                           "provenance": {"synthetic_mode": True, "dataset_id": key}, "clinicalMode": True,
                           "summaries": [{**context, "patients": str(n), "repeat_patients": "20"}],
                           "items": [item], "yearItems": [{**item, "year": year}],
                           "yearSummaries": [{**context, "year": year, "patients": str(n)}]}
                (root/(key+".html")).write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)), encoding="utf-8")
            build_source_dashboard(root/"primary.html", root/"supplement.html", root/"combined.html", privacy_policy="conservative-v1")
            empty = {"groups": [], "provenance": {"synthetic_mode": True}}
            (root/"empty.html").write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(empty)), encoding="utf-8")
            build_source_dashboard(root/"primary.html", root/"empty.html", root/"empty-combined.html", privacy_policy="conservative-v1")
            result = subprocess.run(["node", str(Path(__file__).with_name("dashboard_sources_checks.mjs")), str(root/"combined.html"), str(root/"empty-combined.html")], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_empty_synthetic_source_is_supported_and_default_is_supplement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {"groups": [], "provenance": {"synthetic_mode": True}}
            for name in ["primary", "supplement"]:
                (root / (name + ".html")).write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)), encoding="utf-8")
            result = build_source_dashboard(root/"primary.html", root/"supplement.html", root/"combined.html",
                privacy_policy="conservative-v1", source_metadata={"primary": {"title": "Primary synthetic"}, "supplement": {"title": "Supplement synthetic"}})
            self.assertEqual(result["default_source"], "supplement")
            self.assertEqual(result["privacy_profile"], "conservative-v1")
            page = (root/"combined.html").read_text(encoding="utf-8")
            self.assertIn('id="active-source-note"', page)
            self.assertIn('id="source-title"', page)
            self.assertIn('id="dashboard-empty"', page)
