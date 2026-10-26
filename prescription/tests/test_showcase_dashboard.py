"""Synthetic showcase API, source isolation and comparison-column contract."""
import csv
import json
from pathlib import Path
import re
import tempfile
import unittest

from mingyirx.__main__ import _parser
from mingyirx.dashboard import CLINICAL_TABLES, DashboardError, HTML_TEMPLATE, _read_rows
from mingyirx.dashboard_sources import build_source_dashboard


class ShowcaseDashboardTests(unittest.TestCase):
    def test_cli_accepts_explicit_showcase_profile(self):
        args = _parser().parse_args(["dashboard", "--input-dir", "synthetic", "--output", "demo.html",
                                    "--privacy-policy", "synthetic-showcase-v1"])
        self.assertEqual(args.privacy_policy, "synthetic-showcase-v1")
        self.assertEqual(args.min_public_n, 10)

    def test_comparison_denominators_are_loaded_not_discarded(self):
        required = CLINICAL_TABLES["comparisons"][1]
        denominators = {"combination_repeat_patients": "60", "single_repeat_patients": "40",
                        "combination_patients_with_change": "30", "single_patients_with_change": "20"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted(required))
                writer.writeheader()
                writer.writerow(denominators)
            loaded = _read_rows(path, required)[0]
            self.assertEqual({key: loaded[key] for key in denominators}, denominators)

    def test_showcase_source_gate_and_canonical_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "primary.html", root / "supplement.html"]
            def save(mode):
                payload = {"groups": [], "clinicalMode": True, "provenance": {"synthetic_mode": mode},
                           "research": {"private": "HIDDEN_SENTINEL"}}
                for path in paths:
                    path.write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)) + "UNFILTERED_SENTINEL", encoding="utf-8")
            for mode in [False, None, "true", 1]:
                save(mode)
                with self.subTest(mode=mode), self.assertRaises(DashboardError):
                    build_source_dashboard(*paths, root / "result.html", privacy_policy="synthetic-showcase-v1")
            save(True)
            result = build_source_dashboard(*paths, root / "result.html", privacy_policy="synthetic-showcase-v1", default_source="primary")
            self.assertEqual(result["default_source"], "primary")
            document = (root / "result.html").read_text(encoding="utf-8")
            self.assertNotIn("SENTINEL", document)
            for payload in re.findall(r'<script id="(?:dashboard|supplement)-data" type="application/json">(.*?)</script>', document):
                parsed = json.loads(payload)
                self.assertEqual(parsed["privacy"]["profile"], "synthetic-showcase-v1")
                self.assertIs(parsed["privacy"]["comparisons_enabled"], True)
                self.assertIs(parsed["privacy"]["combinations_enabled"], True)


if __name__ == "__main__":
    unittest.main()
