"""Synthetic fixed-coordinate comparison and disclosure-boundary checks."""
from collections import Counter
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import DashboardError
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_network import enhance_network
from mingyirx.dashboard_network_3d import enhance_network_3d
from mingyirx.dashboard_network_compare import enhance_network_compare
from mingyirx.dashboard_sources import build_source_dashboard
from test_dashboard_network import network_fixture, page, script_blocks


class NetworkCompareTests(unittest.TestCase):
    def test_appends_only_and_preserves_identifiers_and_payloads(self):
        base = enhance_network_3d(enhance_network(refine_local_layout(page())))
        upgraded = enhance_network_compare(base)
        self.assertEqual(script_blocks(base), script_blocks(upgraded)[:-1])
        self.assertEqual(upgraded, enhance_network_compare(upgraded))
        ids = Counter(re.findall(r'\bid="([^"]+)"', upgraded.split('<script id="dashboard-data"', 1)[0]))
        self.assertTrue(all(count == 1 for count in ids.values()))
        self.assertIn('id="network-compare-left-scene"', upgraded)
        self.assertNotRegex(script_blocks(upgraded)[-1], r'\bfetch\s*\(|https?://|\beval\s*\(|new Function\s*\(')

    def test_requires_complete_3d_anchors(self):
        base = enhance_network_3d(enhance_network(refine_local_layout(page())))
        with self.assertRaises(DashboardError):
            enhance_network_compare(page())
        for anchor in ['<section id="network-lab"', '</style>', '</body>']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_network_compare(base.replace(anchor, '', 1))
            with self.subTest(duplicate=anchor), self.assertRaises(DashboardError):
                enhance_network_compare(base.replace(anchor, anchor + anchor, 1))

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_comparison_and_readability_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [("primary", network_fixture()), ("supplement", network_fixture(True))]:
                (root / (name + ".html")).write_text(page(payload), encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html", refresh_template=True, default_source="primary")
            upgraded = enhance_network_compare(enhance_network_3d(enhance_network(refine_local_layout((root / "view.html").read_text(encoding="utf-8")))))
            target = root / "compare.html"
            target.write_text(upgraded, encoding="utf-8")
            result = subprocess.run(["node", str(Path(__file__).with_name("network_compare_checks.mjs")), str(target)], capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
