"""Real loopback requests, only fabricated coded records and local state."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from mingyirx.clinical_server import make_server, LocalWorkspace
from mingyirx.inheritance import verify_frozen

ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'work/clinical-test-state'
        parent.mkdir(parents=True, exist_ok=True)
        cls.folder = Path(tempfile.mkdtemp(prefix='synthetic-', dir=parent))
        cls.site = cls.folder / 'site'
        cls.site.mkdir()
        (cls.site / 'index.html').write_text('<h1>Synthetic only</h1>', encoding='utf-8')
        cls.server = make_server(cls.site, cls.folder / 'session', 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, value=None, extra=None):
        headers = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json',
                   'X-MingYiRx-Nonce': self.server.workspace.nonce}
        headers.update(extra or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        connection.request(method, path, body=json.dumps(value) if value is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        result = (response.status, raw, dict(response.getheaders()))
        connection.close()
        return result

    def test_host_origin_nonce_and_path_rejection(self):
        for headers in [{'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.request('GET', '/api/state', extra=headers)[0], 403)
        self.assertEqual(self.request('POST', '/api/recognize', {}, {'X-MingYiRx-Nonce': 'bad'})[0], 403)
        for path in ['/../records.json', '/%2e%2e/records.json', '/uploads/a.txt', '/api/unknown']:
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/')[2]['Cache-Control'], 'no-store')
        self.assertEqual(self.request('GET', 'http://[')[0], 400)
        self.assertEqual(self.request('POST', '/api/recognize', {}, {'X-MingYiRx-Nonce': '\u00e9'})[0], 403)

    def test_upload_preview_commit_and_optimistic_revision(self):
        text = 'subject_code: SYN-HTTP\nepisode_code: E1\nphysician_code: D1\nvisit_code: V1\ndate: 2025-01-01\ncondition: Demo\nsymptoms: No dry mouth\nprescription: HerbA 10g\n\n---\nsubject_code: SYN-HTTP\nepisode_code: E1\nphysician_code: D1\nvisit_code: V2\ndate: 2025-01-15\ncondition: Demo\nsymptoms: Dry mouth\nprescription: HerbA 12g; HerbB 5g'
        status, raw, _ = self.request('POST', '/api/recognize', {'filename': 'synthetic.txt', 'data_base64': base64.b64encode(text.encode()).decode()})
        self.assertEqual(status, 200, raw)
        records = json.loads(raw)['records']
        self.assertEqual(len(records), 2)
        status, raw, _ = self.request('POST', '/api/preview', {'records': records, 'synthetic': False})
        self.assertEqual(status, 200, raw)
        preview = json.loads(raw)
        self.assertNotEqual(preview['gate'], 'BLOCK', preview)
        self.assertNotIn('bundle', preview)
        self.assertEqual(len(preview['pairs']), 1)
        commit = {'records': records, 'synthetic': False, 'confirmed': True, 'deidentified': True, 'revision': 0}
        self.assertEqual(self.request('POST', '/api/commit', {**commit, 'confirmed': False})[0], 400)
        status, raw, _ = self.request('POST', '/api/commit', commit)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['revision'], 1)
        self.assertEqual(self.request('POST', '/api/commit', commit)[0], 400)
        self.assertEqual(self.request('GET', '/imported.html?revision=1')[0], 200)
        report = verify_frozen(self.folder / 'session/revision-0001/frozen')
        self.assertNotEqual(report['gate'], 'BLOCK')
        self.assertNotIn('2025-01-01', (self.folder / 'session/revision-0001/frozen/bundle.json').read_text())
        status, raw, _ = self.request('POST', '/api/commit', {**commit, 'revision': 1})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['revision'], 2)
        resumed = LocalWorkspace(self.site, self.folder / 'session', resume=True)
        self.assertEqual(resumed.revision, 2)
        self.assertEqual(resumed.records, records)
        self.assertIs(resumed.snapshot()['synthetic'], False)
        self.assertTrue(resumed.page)

    def test_bad_upload_does_not_echo_filename_or_input(self):
        status, raw, _ = self.request('POST', '/api/recognize', {'filename': 'SENSITIVE_NAME.exe', 'data_base64': 'YQ=='})
        self.assertEqual(status, 400)
        self.assertNotIn(b'SENSITIVE', raw)
        self.assertEqual(self.request('POST', '/api/recognize', {'filename': 'synthetic.txt', 'data_base64': '%%%bad'})[0], 400)
