"""Synthetic boundary checks for the opt-in interactive network."""
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_network import enhance_network
from mingyirx.dashboard_sources import build_source_dashboard
from test_original_interactions import fixture


def network_fixture(supplement=False):
    payload = fixture(supplement)
    payload["provenance"]["synthetic_mode"] = True
    payload["provenance"]["dataset_id"] = "network-layout-synthetic-secondary" if supplement else "network-layout-synthetic-primary"
    prefix = "Secondary " if supplement else "Herb "
    count = 8 if supplement else 72
    nodes = [{"group": "ra_strict", "item_name": prefix + str(index).zfill(2),
              "patients": "100", "exposed_patients": str(70 - index % 40),
              "prevalence": str((70 - index % 40) / 100),
              "node_prevalence_threshold": ".1", "edge_cosine_threshold": ".3"}
             for index in range(count)]
    edges = [{"group": "ra_strict", "item_1": nodes[index]["item_name"],
              "item_2": nodes[other]["item_name"], "cooccurrence_patients": "20",
              "support": ".2", "cosine_similarity": str(.9 - (index + other) % 30 / 100), "lift": "1.25"}
             for index in range(count) for other in range(index + 1, min(count, index + 5))]
    payload["research"].update({"nodes": nodes, "edges": edges,
        "usage": [{"item_name": row["item_name"], "total_usage_visits": str(count * 10 - index)} for index, row in enumerate(nodes)]})
    if not supplement:
        payload["research"]["cohorts"].append({"group": "empty_strict", "label": "Empty synthetic cohort", "patients": "20"})
    return payload


def page(payload=None):
    return HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(network_fixture() if payload is None else payload, ensure_ascii=True))


def script_blocks(value):
    return re.findall(r"<script\b[^>]*>.*?</script>", value, re.S)


class DashboardNetworkTests(unittest.TestCase):
    def test_preserves_all_original_scripts_and_payload_bytes(self):
        original = refine_local_layout(page())
        upgraded = enhance_network(original)
        self.assertEqual(script_blocks(upgraded)[:-1], script_blocks(original))
        self.assertIn('id="network-interactive-script"', script_blocks(upgraded)[-1])
        self.assertEqual(enhance_network(upgraded), upgraded)

    def test_preserves_original_ids_and_adds_one_complete_network_region(self):
        original = refine_local_layout(page())
        upgraded = enhance_network(original)
        ids = lambda text: Counter(re.findall(r'\bid="([^\"]+)"', text.split('<script id="dashboard-data"', 1)[0]))
        before, after = ids(original), ids(upgraded)
        for identifier, count in before.items():
            self.assertEqual(after[identifier], count, identifier)
        self.assertTrue(all(count == 1 for count in after.values()))
        for identifier in ["network-lab", "network-view-mode", "network-edge-limit", "network-motion", "network-inspector"]:
            self.assertEqual(after[identifier], 1)
        self.assertIn('class="network-entry" href="#network-lab"', upgraded)

    def test_missing_or_ambiguous_anchors_fail_closed(self):
        original = page()
        for anchor in ['<div id="network-edges"></div>', '</style>', '</body>']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_network(original.replace(anchor, '', 1))
        with self.assertRaises(DashboardError):
            enhance_network(original.replace('</style>', '</style></style>'))
        with self.assertRaises(DashboardError):
            enhance_network('<html><body>Unsupported</body></html>')

    def test_original_template_is_opt_in_and_has_no_network_dependency(self):
        self.assertNotIn('network-interactive-script', HTML_TEMPLATE)
        upgraded = enhance_network(page())
        self.assertNotRegex(script_blocks(upgraded)[-1], r'\bfetch\s*\(|https?://|\beval\s*\(|new Function\s*\(')

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_synthetic_projection_interactions_history_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [("primary", network_fixture()), ("supplement", network_fixture(True))]:
                (root / (name + ".html")).write_text(page(payload), encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html", refresh_template=True, default_source="primary")
            source = (root / "view.html").read_text(encoding="utf-8")
            upgraded = enhance_network(refine_local_layout(source))
            (root / "network.html").write_text(upgraded, encoding="utf-8")
            result = subprocess.run(["node", str(Path(__file__).with_name("network_interactive_checks.mjs")), str(root / "network.html")], capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
