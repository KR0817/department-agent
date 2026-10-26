"""Regression checks for release trust boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from mingyirx.config import ConfigError, load_config
from mingyirx.dashboard import DashboardError
from mingyirx.dashboard_sources import build_source_dashboard

ROOT = Path(__file__).resolve().parents[1]

class ReleaseSafetyTests(unittest.TestCase):
    def test_source_switch_preserves_distinct_payloads_and_escapes_markup(self):
        template = '''<main class="main"><script id="dashboard-data" type="application/json">PAYLOAD</script><script>const data=JSON.parse(document.getElementById('dashboard-data').textContent);const research = data.research || {};const provenance = data.provenance || {};initializeResearch();initializeReference();render();</script>'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b, out = [root/name for name in ['a.html', 'b.html', 'out.html']]
            a.write_text(template.replace('PAYLOAD', json.dumps({'groups': [{'code': 'a'}]})), encoding='utf-8')
            b.write_text(template.replace('PAYLOAD', json.dumps({'groups': [{'code': 'b'}], 'label': '<safe>'})), encoding='utf-8')
            result = build_source_dashboard(a, b, out)
            self.assertFalse(result['patient_identity_merge'])
            html = out.read_text(encoding='utf-8')
            self.assertIn('\\u003csafe>', html)
            self.assertIn('let research', html)
            self.assertIn('id="analysis-source"', html)
            with self.assertRaises(DashboardError):
                build_source_dashboard(out, b, root/'again.html')
            b.write_text('<html>invalid</html>', encoding='utf-8')
            with self.assertRaises(DashboardError):
                build_source_dashboard(a, b, out)

    def test_synthetic_mode_rejects_strings_and_numbers(self):
        raw = json.loads((ROOT/'configs/example.json').read_text(encoding='utf-8'))
        for value in ['false', 'true', 0, 1, None, [], {}]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                raw['synthetic_mode'] = value
                path = Path(directory)/'config.json'
                path.write_text(json.dumps(raw),encoding='utf-8')
                with self.assertRaisesRegex(ConfigError,'JSON boolean'):
                    load_config(path)
