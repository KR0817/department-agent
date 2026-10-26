"""Synthetic validation of the perspective adapter and its existing-data bridge."""
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
from mingyirx.dashboard_sources import build_source_dashboard
from mingyirx.dashboard_threeui import enhance_community_ui
from test_dashboard_network import network_fixture, page, script_blocks


class Network3DTests(unittest.TestCase):
    def test_preserves_payload_scripts_ids_and_supports_community(self):
        base = enhance_network(refine_local_layout(page()))
        for original in [base, enhance_community_ui(base)]:
            upgraded = enhance_network_3d(original)
            self.assertEqual(script_blocks(original), script_blocks(upgraded)[:-1])
            self.assertEqual(enhance_network_3d(upgraded), upgraded)
            ids = lambda value: Counter(re.findall(r'\bid="([^"]+)"', value.split('<script id="dashboard-data"', 1)[0]))
            before, after = ids(original), ids(upgraded)
            self.assertTrue(all(count == 1 for count in after.values()))
            for identifier, count in before.items():
                self.assertEqual(after[identifier], count, identifier)
            self.assertIn('id="network3d-scene"', upgraded)
            self.assertNotRegex(script_blocks(upgraded)[-1], r'\bfetch\s*\(|https?://|\beval\s*\(|new Function\s*\(')

    def test_unsupported_or_ambiguous_markup_fails_closed(self):
        base = enhance_network(refine_local_layout(page()))
        with self.assertRaises(DashboardError):
            enhance_network_3d(page())
        for anchor in ['<div class="network-stage">', '</style>', '</body>']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_network_3d(base.replace(anchor, '', 1))
            with self.subTest(duplicate=anchor), self.assertRaises(DashboardError):
                enhance_network_3d(base.replace(anchor, anchor + anchor, 1))

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_perspective_interactions_sources_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [("primary", network_fixture()), ("supplement", network_fixture(True))]:
                (root / (name + ".html")).write_text(page(payload), encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html", refresh_template=True, default_source="primary")
            upgraded = enhance_network_3d(enhance_network(refine_local_layout((root / "view.html").read_text(encoding="utf-8"))))
            target = root / "3d.html"
            target.write_text(upgraded, encoding="utf-8")
            result = subprocess.run(["node", str(Path(__file__).with_name("network_3d_checks.mjs")), str(target)], capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
