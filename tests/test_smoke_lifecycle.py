"""Test interruption and cleanup without starting a process or HTTP listener."""
from contextlib import nullcontext, redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with patch.object(sys, 'path', [str(ROOT / 'scripts'), *sys.path]):
    smoke = load_module('smoke_lifecycle_subject', ROOT / 'scripts/smoke_test.py')
demo = load_module('demo_lifecycle_subject', ROOT / 'clinical/demo.py')


class SmokeLifecycleTests(unittest.TestCase):
    def test_report_requires_explicit_completion(self):
        checks = smoke.Checks()
        with redirect_stdout(StringIO()):
            checks.check('partial_check', True)
        self.assertFalse(checks.report()['passed'])
        checks.completed = True
        self.assertTrue(checks.report()['passed'])

    def exercise_smoke(self, interrupted):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clinical = root / 'clinical'
            (clinical / 'static').mkdir(parents=True)
            raw = b'<html>SYNTHETIC lifecycle test</html>'
            (clinical / 'static/index.html').write_bytes(raw)
            fake_demo = Mock()
            owned = []

            def start(*args):
                processes = [Mock(), Mock()]
                for process in processes:
                    process.poll.return_value = None
                owned.append(processes)
                return processes

            def stop(processes):
                for process in processes:
                    process.poll.return_value = 0

            fake_demo.start.side_effect = start
            fake_demo.stop.side_effect = stop
            client = MagicMock()
            client.__enter__.return_value = client

            def get(route):
                status = 200 if route == '/' or route.startswith('/static/') else 401
                return Mock(status_code=status, content=raw, headers={'content-security-policy':
                    "script-src 'self'; object-src 'none'; frame-ancestors 'none'"})

            client.get.side_effect = get
            output = StringIO()
            with patch.object(smoke, 'ROOT', root), patch.object(smoke, 'CLINICAL', clinical), \
                    patch.object(smoke, 'run_lock', side_effect=lambda path: nullcontext()), \
                    patch.object(smoke, 'prepare_site', return_value=root / 'synthetic-site'), \
                    patch.object(smoke, 'environment', return_value={}), \
                    patch.object(smoke.httpx, 'Client', return_value=client), \
                    patch.object(smoke, 'clinical_flow', return_value={}), \
                    patch.object(smoke, 'knowledge_flow'), \
                    patch.object(smoke, 'prescription_flow', return_value={}), \
                    patch.object(smoke, 'restored_flow', side_effect=KeyboardInterrupt if interrupted else None), \
                    patch.dict(sys.modules, {'demo': fake_demo}), \
                    patch.object(sys, 'argv', ['smoke_test.py']), redirect_stdout(output):
                if interrupted:
                    with self.assertRaises(KeyboardInterrupt):
                        smoke.main()
                else:
                    self.assertEqual(smoke.main(), 0)
            report_files = list((root / 'work').glob('smoke-*/report.json'))
            self.assertEqual(len(report_files), 1)
            report = json.loads(report_files[0].read_text(encoding='utf-8'))
            self.assertEqual(report['passed'], not interrupted)
            self.assertEqual(report['completed'], not interrupted)
            self.assertEqual(len(owned), 2)
            self.assertEqual(fake_demo.stop.call_count, 2)
            self.assertTrue(all(process.poll() == 0 for group in owned for process in group))
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['passed'], not interrupted)

    def test_interrupted_smoke_reports_failure_and_stops_owned_services(self):
        self.exercise_smoke(interrupted=True)

    def test_complete_mock_lifecycle_reports_success(self):
        self.exercise_smoke(interrupted=False)

    def test_partial_start_cleans_up_and_preserves_original_failure(self):
        for failure in (KeyboardInterrupt(), RuntimeError('Synthetic startup failure')):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                processes = [Mock(), Mock()]
                for process in processes:
                    process.poll.return_value = None
                ready = MagicMock()
                ready.__enter__.return_value.status = 200
                with patch.object(demo, 'available'), \
                        patch.object(demo.subprocess, 'Popen', side_effect=processes), \
                        patch.object(demo.urllib.request, 'urlopen', side_effect=[ready, failure]), \
                        patch.object(demo, 'stop') as stopped:
                    with self.assertRaises(type(failure)) as caught:
                        demo.start(root / 'data', root / 'logs')
                    self.assertIs(caught.exception, failure)
                    stopped.assert_called_once_with(processes)


if __name__ == '__main__':
    unittest.main()
