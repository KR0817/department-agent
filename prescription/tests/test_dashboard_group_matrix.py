"""Exact-group matrix checks with fabricated data and real source handlers."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE
from mingyirx.dashboard_followup import enhance_followup
from mingyirx.dashboard_group_matrix import GROUP_MATRIX_CSS, GROUP_MATRIX_JS, enhance_group_matrix
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_network import enhance_network
from mingyirx.dashboard_sources import build_source_dashboard
from test_dashboard_followup import followup_fixture


def matrix_page():
    return enhance_followup(enhance_network(refine_local_layout(
        HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(followup_fixture())))))


class DashboardGroupMatrixTests(unittest.TestCase):
    def test_additive_markup_preserves_all_existing_payloads_scripts_and_controls(self):
        original = matrix_page()
        enhanced = enhance_group_matrix(original)
        scripts = lambda page: re.findall(r'<script\b[^>]*>.*?</script>', page, re.S)
        self.assertEqual(scripts(enhanced)[:-1], scripts(original))
        self.assertEqual(enhance_group_matrix(enhanced), enhanced)
        self.assertEqual(enhanced.count('id="group-matrix-lab"'), 1)
        self.assertEqual(enhanced.count('id="overview-groups"'), 1)
        self.assertIn('<details class="group-matrix-legacy">', enhanced)
        self.assertNotRegex(GROUP_MATRIX_JS, r'\bfetch\s*\(|\beval\s*\(|new Function\s*\(|https?://')
        self.assertNotRegex(GROUP_MATRIX_CSS, r'@import|url\(')

    def test_missing_or_duplicate_anchors_fail_without_a_partial_adapter(self):
        original = matrix_page()
        for anchor in ['<script id="dashboard-data"', '</style>', '</body>', '<div class="overview-groups" id="overview-groups"></div>']:
            with self.subTest(anchor=anchor):
                with self.assertRaises(DashboardError):
                    enhance_group_matrix(original.replace(anchor, '', 1))
                with self.assertRaises(DashboardError):
                    enhance_group_matrix(original.replace(anchor, anchor + anchor, 1))

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_real_group_source_history_followup_and_missing_value_flows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [('primary', followup_fixture()), ('supplement', followup_fixture(True))]:
                for index, row in enumerate(payload['summaries']):
                    if row['stratum_type'] == 'overall':
                        row['visits'] = str(100 + index)
                (root / (name + '.html')).write_text(HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(payload)), encoding='utf-8')
            build_source_dashboard(root / 'primary.html', root / 'supplement.html', root / 'view.html', refresh_template=True, default_source='primary')
            page = enhance_group_matrix(enhance_followup(enhance_network(refine_local_layout((root / 'view.html').read_text(encoding='utf-8')))))
            (root / 'matrix.html').write_text(page, encoding='utf-8')
            result = subprocess.run(['node', str(Path(__file__).with_name('group_matrix_checks.mjs')), str(root / 'matrix.html')], capture_output=True, text=True, encoding='utf-8', timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
