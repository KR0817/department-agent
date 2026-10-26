"""Synthetic regression coverage for the adjacent-visit aggregate workbench."""
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE
from mingyirx.dashboard_followup import FOLLOWUP_CSS, FOLLOWUP_JS, enhance_followup
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_network import enhance_network
from mingyirx.dashboard_sources import build_source_dashboard
from mingyirx.dashboard_threeui import enhance_community_ui
from test_original_interactions import fixture


def followup_fixture(supplement=False):
    payload = fixture(supplement)
    payload['provenance']['synthetic_mode'] = True
    payload['provenance']['dataset_id'] = 'followup-synthetic-secondary' if supplement else 'followup-synthetic-primary'
    group = payload['groups'][0]['code']
    base = {'group': group, 'stratum_type': 'overall', 'stratum': 'all'}
    payload['longitudinal'] = [{**base, 'repeat_patients': '40', 'transitions': '55', 'median_patient_jaccard': '0'}]
    payload['yearSummaries'] = [{**base, 'year': '2020', 'repeat_patients': '20'}, {**base, 'year': '2022', 'repeat_patients': '30'}]
    payload['yearChanges'] = []
    herb = 'Secondary herb' if supplement else 'Herb A'
    for year, count, denom, rate, direction in [('2020', '0', '20', '0', 'addition'), ('2022', '12', '30', '.4', 'addition'), ('2022', '6', '30', '.2', 'removal')]:
        payload['yearChanges'].append({**base, 'year': year, 'item_name': herb, 'change_type': direction, 'patients_with_change': count, 'repeat_patients': denom, 'patient_prevalence': rate, 'mean_patient_transition_fraction': rate})
    payload['changes'].append({**base, 'item_name': 'Herb <unsafe&">', 'change_type': 'addition', 'patients_with_change': '0', 'repeat_patients': '40', 'patient_prevalence': '0', 'mean_patient_transition_fraction': ''})
    if supplement:
        for row in payload['changes']:
            if row['item_name'] == 'Herb A':
                row['item_name'] = herb
    return payload


def network_page(payload=None):
    raw = HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(payload if payload is not None else followup_fixture(), ensure_ascii=True))
    return enhance_network(refine_local_layout(raw))


def scripts(page):
    return re.findall(r'<script\b[^>]*>.*?</script>', page, re.S)


class DashboardFollowupTests(unittest.TestCase):
    def test_additive_adapter_preserves_scripts_payloads_and_identifiers(self):
        original = network_page()
        result = enhance_followup(original)
        self.assertEqual(scripts(result)[:-1], scripts(original))
        for identifier, count in Counter(re.findall(r'\bid="([^"]+)"', original.split('<script id="dashboard-data"', 1)[0])).items():
            self.assertEqual(result.split('<script id="dashboard-data"', 1)[0].count('id="' + identifier + '"'), count, identifier)
        self.assertEqual(enhance_followup(result), result)
        self.assertEqual(result.count('id="followup-lab"'), 1)
        self.assertEqual(result.count('href="#followup-lab"'), 1)

    def test_legacy_flows_move_whole_and_strict_cohort_identity_stays_separate(self):
        result = enhance_followup(network_page())
        legacy = result.split('<details class="followup-legacy">', 1)[1].split('</section>\n', 1)[0]
        for identifier in ['trajectory-core', 'trajectory-addition', 'trajectory-removal', 'addition-list', 'removal-list', 'formula-evidence']:
            self.assertIn('id="' + identifier + '"', legacy)
        self.assertIn('id="strict-nav-link" href="#strict-research">\u4e25\u683c\u961f\u5217\u7814\u7a76', result)
        self.assertIn('researchTable', scripts(network_page())[1])
        self.assertNotRegex(FOLLOWUP_JS, r'\bstrictRows\s*\(|\bresearchRows\s*\(')

    def test_missing_or_ambiguous_anchors_fail_closed_and_community_composes(self):
        original = network_page()
        for anchor in ['id="network-interactive-script"', '</style>', '</body>', '<section class="section" id="annual-section"', '<h3>\u590d\u8bca\u52a0\u51cf\u503e\u5411</h3>']:
            with self.subTest(anchor=anchor), self.assertRaises(DashboardError):
                enhance_followup(original.replace(anchor, '', 1))
        with self.assertRaises(DashboardError):
            enhance_followup(original.replace('</style>', '</style></style>', 1))
        with self.assertRaises(DashboardError):
            enhance_followup(enhance_community_ui(original))
        result = enhance_community_ui(enhance_followup(original))
        nav = re.search(r'<nav class="research-nav" id="community-dock".*?</nav>', result, re.S)[0]
        self.assertIn('href="#followup-lab"', nav)
        self.assertNotRegex(FOLLOWUP_JS, r'\bfetch\s*\(|\beval\s*\(|new Function\s*\(|https?://')
        self.assertNotRegex(FOLLOWUP_CSS, r'@import|url\(')

    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_real_controller_with_synthetic_source_history_and_privacy_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [('primary', followup_fixture()), ('supplement', followup_fixture(True))]:
                (root / (name + '.html')).write_text(HTML_TEMPLATE.replace('__PAYLOAD__', json.dumps(payload)), encoding='utf-8')
            build_source_dashboard(root / 'primary.html', root / 'supplement.html', root / 'view.html', refresh_template=True, default_source='primary')
            original = enhance_network(refine_local_layout((root / 'view.html').read_text(encoding='utf-8')))
            result = enhance_followup(original)
            self.assertEqual(scripts(result)[:-1], scripts(original))
            (root / 'followup.html').write_text(result, encoding='utf-8')
            checked = subprocess.run(['node', str(Path(__file__).with_name('followup_ui_checks.mjs')), str(root / 'followup.html')], capture_output=True, text=True, encoding='utf-8', timeout=40)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == '__main__':
    unittest.main()
