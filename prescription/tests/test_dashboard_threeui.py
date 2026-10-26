"""Contract checks for the native MIT Community adaptations."""
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
from mingyirx.dashboard_threeui import COMMUNITY_CSS, COMMUNITY_JS, WORKBENCH_CSS, WORKBENCH_JS, UPSTREAM_LICENSE, UPSTREAM_URL, enhance_community_ui
from test_dashboard_network import network_fixture


def network_page(payload=None):
    source = HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(network_fixture() if payload is None else payload))
    return enhance_network(refine_local_layout(source))


def scripts(page):
    return re.findall(r'<script\b[^>]*>.*?</script>', page, re.S)


class DashboardThreeUITests(unittest.TestCase):
    def test_existing_scripts_payload_bytes_ids_and_callbacks_remain_intact(self):
        original = network_page()
        result = enhance_community_ui(original)
        self.assertEqual(scripts(result)[:-1], scripts(original))
        before = original.split('<script id="dashboard-data"', 1)[0]
        after = result.split('<script id="dashboard-data"', 1)[0]
        original_ids = Counter(re.findall(r'\bid="([^"]+)"', before))
        upgraded_ids = Counter(re.findall(r'\bid="([^"]+)"', after))
        for identifier, count in original_ids.items():
            self.assertEqual(upgraded_ids[identifier], count, identifier)
        self.assertTrue(all(count == 1 for count in upgraded_ids.values()))
        self.assertEqual(enhance_community_ui(result), result)

    def test_semantic_navigation_moves_to_main_start_and_keeps_original_links(self):
        original = network_page()
        result = enhance_community_ui(original)
        original_nav = re.search(r'<nav class="research-nav"[^>]*>.*?</nav>', original, re.S)[0]
        upgraded_nav = re.search(r'<nav class="research-nav" id="community-dock"[^>]*>.*?</nav>', result, re.S)[0]
        for href in re.findall(r'href="([^"]+)"', original_nav):
            self.assertEqual(upgraded_nav.count('href="' + href + '"'), 1)
        self.assertEqual(upgraded_nav.count('id="strict-nav-link"'), 1)
        self.assertRegex(result, r'<main class="main"[^>]*><div id="community-dock-frame"')
        self.assertRegex(result, r'id="export-network-svg"[^>]*\bdisabled\b')
        self.assertIn('data-threeui-adaptation="SpinningBorderButton"', result)
        self.assertNotIn('aria-pressed=', upgraded_nav)

    def test_full_pinned_license_is_retained_without_runtime_dependencies(self):
        license_file = Path(__file__).resolve().parents[1] / 'third_party' / 'threeui' / 'LICENSE'
        self.assertEqual(UPSTREAM_LICENSE.strip(), license_file.read_text(encoding='utf-8').strip())
        result = enhance_community_ui(network_page())
        self.assertIn(UPSTREAM_LICENSE, result)
        self.assertIn(UPSTREAM_URL, result.split('-->', 1)[0])
        self.assertNotRegex(COMMUNITY_JS + WORKBENCH_JS, r'\bfetch\s*\(|\beval\s*\(|new Function\s*\(|https?://|\bimport\s')
        self.assertNotRegex(COMMUNITY_CSS + WORKBENCH_CSS, r'@import|url\(')
        self.assertNotRegex(result, r'<iframe|<script\b[^>]+src=|cdn\.tailwindcss\.com')

    def test_missing_ambiguous_or_unupgraded_templates_fail_closed(self):
        original = network_page()
        for anchor in ['id="network-interactive-script"', 'id="export-network-svg"', 'id="strict-nav-link"', '</style>', '</body>']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_community_ui(original.replace(anchor, '', 1))
        for anchor in ['</style>', '<main class="main" id="main-workbench" tabindex="-1">']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_community_ui(original.replace(anchor, anchor + anchor, 1))
        with self.assertRaises(DashboardError):
            enhance_community_ui(HTML_TEMPLATE)

    def test_two_source_payloads_stay_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [('primary', network_fixture()), ('supplement', network_fixture(True))]:
                (root / (name + '.html')).write_text(HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(payload)), encoding='utf-8')
            build_source_dashboard(root / 'primary.html', root / 'supplement.html', root / 'view.html', refresh_template=True, default_source='primary')
            original = enhance_network(refine_local_layout((root / 'view.html').read_text(encoding='utf-8')))
            result = enhance_community_ui(original)
            self.assertEqual(scripts(result)[:-1], scripts(original))
            for name in ['dashboard-data', 'supplement-data']:
                pattern = '<script id="' + name + '" type="application/json">(.*?)</script>'
                self.assertEqual(re.search(pattern, original, re.S)[1], re.search(pattern, result, re.S)[1])

    def test_workbench_keeps_native_fallback_and_moves_the_existing_export(self):
        original = network_page()
        result = enhance_community_ui(original)
        markup = result.split('<script id="dashboard-data"', 1)[0]
        heading = re.search(r'<div class="network-heading">.*?<p id="network-context">.*?</p></div>', markup, re.S)[0]
        toolbar = re.search(r'<div class="network-toolbar">.*?</div>', markup, re.S)[0]
        self.assertIn('id="export-network-svg"', heading)
        self.assertNotIn('id="export-network-svg"', toolbar)
        for identifier in ['network-view-mode', 'network-edge-limit']:
            pattern = r'<label>[^<]*<select id="' + identifier + r'">.*?</select></label>'
            self.assertEqual(re.search(pattern, original, re.S)[0], re.search(pattern, markup, re.S)[0])
        self.assertIn('RectangleButtons Aster and Meridian surfaces', result.split('-->', 1)[0])

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_segmented_controls_preserve_native_state_keyboard_disabled_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workbench.js'
            path.write_text(WORKBENCH_JS, encoding='utf-8')
            result = subprocess.run(['node', str(Path(__file__).with_name('community_controls_checks.mjs')), str(path)], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_native_controller_motion_focus_hidden_states_and_existing_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.html'
            path.write_text(enhance_community_ui(network_page()), encoding='utf-8')
            result = subprocess.run(['node', str(Path(__file__).with_name('threeui_interaction_checks.mjs')), str(path)], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
