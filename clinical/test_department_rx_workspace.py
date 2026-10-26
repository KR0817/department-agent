"""Full-source synthetic tests; private source rows are never opened or emitted."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from department_rx_workspace import FullError, FullWorkspace, PREFIX, _scoped_index


ROOT = Path(os.environ.get('DEPARTMENT_MINGYIRX_ROOT', Path(__file__).resolve().parents[1] / 'prescription'))
SITE = Path(os.environ.get('DEPARTMENT_MINGYIRX_SITE', ROOT / 'work/demo-site'))
TEXT = ('subject_code: SYN-FULL\nepisode_code: E1\nphysician_code: D1\n'
        'visit_code: V1\ndate: 2025-01-01\ncondition: Demo\n'
        'symptoms: No dry mouth\nprescription: HerbA 10g\n\n---\n'
        'subject_code: SYN-FULL\nepisode_code: E1\nphysician_code: D1\n'
        'visit_code: V2\ndate: 2025-01-15\ncondition: Demo\n'
        'symptoms: Dry mouth\nprescription: HerbA 12g; HerbB 5g')


class FullWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'work/department-full-workspace-tests'
        parent.mkdir(parents=True, exist_ok=True)
        cls.folder = Path(tempfile.mkdtemp(prefix='synthetic-', dir=parent))
        cls.source_hashes = {path.name: hashlib.sha256(path.read_bytes()).digest()
                             for path in SITE.iterdir() if path.is_file()}

    @classmethod
    def tearDownClass(cls):
        after = {path.name: hashlib.sha256(path.read_bytes()).digest()
                 for path in SITE.iterdir() if path.is_file()}
        if cls.source_hashes != after:
            raise AssertionError('Synthetic source assets changed')

    def setUp(self):
        self.state = self.folder / self._testMethodName
        self.workspace = FullWorkspace(ROOT, SITE, self.state)

    def records(self):
        result = self.workspace.recognize({'filename': 'synthetic.txt',
                    'data_base64': base64.b64encode(TEXT.encode()).decode('ascii')})
        self.assertEqual(result['source_sha256'], hashlib.sha256(TEXT.encode()).hexdigest())
        return result['records']

    def committed(self, records=None, revision=0, synthetic=True):
        return {'records': records if records is not None else self.records(),
                'synthetic': synthetic, 'confirmed': True, 'deidentified': True,
                'revision': revision}

    def assert_error(self, status, detail, method, *args):
        with self.assertRaises(FullError) as caught:
            method(*args)
        self.assertEqual(caught.exception.status, status)
        self.assertEqual(caught.exception.detail, detail)
        self.assertNotIn('private-fragment', str(caught.exception))

    def test_complete_original_snapshot_and_safe_status(self):
        snapshot = self.workspace.snapshot()
        self.assertEqual(set(snapshot), {'online', 'nonce', 'formats', 'records', 'revision', 'synthetic'})
        self.assertEqual(snapshot['records'], [])
        self.assertTrue(snapshot['online'])
        status = self.workspace.status()
        self.assertTrue(status['available'])
        self.assertEqual(status['entry_url'], PREFIX + '/site/index.html')
        self.assertEqual(status['record_count'], 0)
        self.assertEqual(set(status['static_assets']), set(self.source_hashes))
        self.assertNotIn(snapshot['nonce'], json.dumps(status))
        self.assertNotIn(str(ROOT), json.dumps(status))
        self.assertNotIn('records', status)

    def test_recognize_preview_save_reopen_and_chain(self):
        records = self.records()
        self.assertEqual(len(records), 2)
        preview = self.workspace.preview({'records': records, 'synthetic': True})
        original = self.workspace._workspace.preview({'records': records, 'synthetic': True})
        self.assertEqual(preview, original)
        self.assertNotEqual(preview['gate'], 'BLOCK')
        self.assertEqual(len(preview['pairs']), 1)
        self.assertNotIn('bundle', preview)
        first = self.workspace.commit(self.committed(records))
        self.assertEqual(first['case_url'], '/imported.html?revision=1')
        second = self.workspace.commit(self.committed(records, revision=1))
        self.assertEqual(second['case_url'], '/imported.html?revision=2')
        raw, media, csp = self.workspace.asset('imported.html', '2')
        self.assertEqual(raw, self.workspace._workspace.page)
        self.assertEqual(media, 'text/html; charset=utf-8')
        self.assertIn("frame-ancestors 'self'", csp)
        reopened = FullWorkspace(ROOT, SITE, self.state)
        self.assertEqual(reopened.snapshot()['records'], records)
        self.assertEqual(reopened.snapshot()['revision'], 2)
        self.assertEqual(reopened.asset('imported.html', 2)[0], raw)
        self.assertNotEqual(reopened.snapshot()['nonce'], self.workspace.snapshot()['nonce'])
        snapshot = reopened.snapshot()
        snapshot['records'][0]['prescription'] = 'Changed only in caller'
        self.assertEqual(reopened.snapshot()['records'], records)

    def test_duplicate_and_conflicting_visits_keep_original_gates(self):
        records = self.records()
        records.append(copy.deepcopy(records[0]))
        result = self.workspace.preview({'records': records, 'synthetic': True})
        self.assertEqual(result['counts']['duplicates'], 1)
        self.assertEqual(result['counts']['visits'], 2)
        records[-1]['prescription'] = 'HerbA 15g'
        result = self.workspace.commit(self.committed(records))
        self.assertEqual(result['gate'], 'BLOCK')
        self.assertIn('CONFLICTING_VISIT', [row['code'] for row in result['errors']])
        self.assertEqual(self.workspace.snapshot()['revision'], 0)

    def test_confirmation_revision_and_collection_mode_conflicts(self):
        payload = self.committed()
        self.assert_error(400, 'REVIEW_CONFIRMATION_REQUIRED', self.workspace.commit,
                          {**payload, 'confirmed': False})
        self.assert_error(400, 'REVIEW_CONFIRMATION_REQUIRED', self.workspace.commit,
                          {**payload, 'deidentified': False})
        self.workspace.commit(payload)
        self.assert_error(409, 'REVISION_CONFLICT', self.workspace.commit, payload)
        self.assert_error(409, 'COLLECTION_MODE_CONFLICT', self.workspace.commit,
                          {**payload, 'revision': 1, 'synthetic': False})
        self.assert_error(404, 'REVISION_NOT_FOUND', self.workspace.asset, 'imported.html', 2)
        self.assert_error(404, 'REVISION_NOT_FOUND', self.workspace.asset, 'imported.html', True)

    def test_static_allowlist_and_original_asset_bytes(self):
        self.assertEqual(self.workspace.static_names, self.workspace._server.STATIC_NAMES)
        for name in self.source_hashes:
            raw, media, csp = self.workspace.asset(name)
            if name != 'index.html':
                self.assertEqual(hashlib.sha256(raw).digest(), self.source_hashes[name])
            self.assertIn("frame-ancestors 'self'", csp)
            self.assertIn("connect-src 'self'", csp)
            self.assertNotIn("script-src 'unsafe-inline'", csp)
        for name in ('../index.html', '..\\index.html', '/index.html', '%2e%2e/index.html',
                     'records.json', 'uploads/a.txt', 'index.html?x=1', 'private-fragment', None):
            self.assert_error(404, 'NOT_FOUND', self.workspace.asset, name)
        # The public synthetic report is part of the declared static allowlist.
        self.assert_error(404, 'NO_COMMITTED_CASES', self.workspace.asset, 'imported.html')

    def test_only_controller_transport_is_changed_and_data_exact(self):
        original = (SITE / 'index.html').read_bytes()
        result = self.workspace.asset('index.html')[0]
        pattern = rb'(<script id="clinical-workspace-controller">)(.*?)(</script>)'
        before = re.search(pattern, original, re.S)
        after = re.search(pattern, result, re.S)
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertEqual(original[:before.start(2)], result[:after.start(2)])
        self.assertEqual(original[before.end(2):], result[after.end(2):])
        body = before.group(2)
        expected = body.replace(b"location.hostname==='127.0.0.1'",
                                b"['127.0.0.1','localhost'].includes(location.hostname)")
        expected = expected.replace(b'fetch(route,', b"fetch('" + PREFIX.encode() + b"'+route,")
        expected = expected.replace(b".setAttribute('src',committedUrl)",
                                    b".setAttribute('src','" + PREFIX.encode() + b"'+committedUrl)")
        expected = expected.replace(b".getAttribute('src')!==committedUrl",
                                    b".getAttribute('src')!=='" + PREFIX.encode() + b"'+committedUrl")
        self.assertEqual(after.group(2), expected)
        data = rb'<script id="clinical-workspace-data" type="application/json">(.*?)</script>'
        self.assertEqual(re.search(data, original, re.S).group(1), re.search(data, result, re.S).group(1))
        self.assertEqual(after.group(2).count(PREFIX.encode()), 4)
        self.assertIn(b'function safeCaseUrl', after.group(2))
        self.assertIn(b"['127.0.0.1','localhost'].includes(location.hostname)", after.group(2))

    def test_csp_hashes_match_executable_scripts_and_exclude_json(self):
        for name in ('index.html', 'aggregate.html', 'inheritance.html', 'exact-rx.html'):
            raw, _, csp = self.workspace.asset(name)
            expected = set()
            for attrs, body in re.findall(rb'<script\b([^>]*)>(.*?)</script>', raw, re.S):
                normalized = body.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
                digest = base64.b64encode(hashlib.sha256(normalized).digest()).decode('ascii')
                if b'application/json' in attrs:
                    self.assertNotIn(digest, csp)
                else:
                    expected.add(digest)
            self.assertTrue(expected)
            self.assertEqual(set(re.findall(r"'sha256-([^']+)'", csp)), expected)
            self.assertIn("style-src 'self' 'unsafe-inline'", csp)

    def test_unsupported_shell_fails_before_state_creation(self):
        original = (SITE / 'index.html').read_bytes()
        for altered in (original.replace(b'fetch(route,', b'fetch(route ,'),
                        original.replace(b".setAttribute('src',committedUrl)", b'changed', 1),
                        original.replace(b"location.hostname==='127.0.0.1'", b'unknownHost()'),
                        original.replace(b'clinical-workspace-controller', b'unknown-controller')):
            self.assert_error(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED', _scoped_index, altered)
        site = self.folder / 'unsupported-site'
        site.mkdir()
        (site / 'index.html').write_bytes(original.replace(b'fetch(route,', b'fetch(route ,'))
        state = self.folder / 'unsupported-state'
        self.assert_error(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED', FullWorkspace, ROOT, site, state)
        self.assertFalse(state.exists())

    def test_owned_state_marker_prevents_old_or_other_site_resume(self):
        unknown = self.folder / 'unknown-state'
        unknown.mkdir()
        with patch.object(self.workspace._server, 'LocalWorkspace') as original:
            self.assert_error(503, 'WORKSPACE_STATE_NOT_OWNED', FullWorkspace, ROOT, SITE, unknown)
            original.assert_not_called()
        other_site = self.folder / 'different-site'
        other_site.mkdir()
        (other_site / 'index.html').write_bytes((SITE / 'index.html').read_bytes())
        self.assert_error(503, 'WORKSPACE_STATE_NOT_OWNED', FullWorkspace, ROOT, other_site, self.state)
        self.assert_error(503, 'WORKSPACE_STATE_INVALID', FullWorkspace, ROOT, SITE, ROOT / 'outputs/not-state')

    def test_independent_users_have_independent_records_and_nonce(self):
        other = FullWorkspace(ROOT, SITE, self.folder / 'another-user-state')
        self.workspace.commit(self.committed())
        self.assertEqual(other.snapshot()['records'], [])
        self.assertEqual(other.snapshot()['revision'], 0)
        self.assertFalse(other.valid_nonce(self.workspace.snapshot()['nonce']))
        self.assert_error(404, 'NO_COMMITTED_CASES', other.asset, 'imported.html')

    def test_nonce_requires_exact_ascii_token(self):
        self.assertTrue(self.workspace.valid_nonce(self.workspace.snapshot()['nonce']))
        for bad in (None, False, 42, 'bad', 'x' * 43, '\u00e9' * 43, 'x' * 10000):
            self.assertFalse(self.workspace.valid_nonce(bad))

    def test_original_upload_and_record_limits_and_safe_errors(self):
        self.assert_error(400, 'UNSUPPORTED_FORMAT', self.workspace.recognize,
                          {'filename': 'private-fragment.exe', 'data_base64': 'YQ=='})
        self.assert_error(400, 'UPLOAD_ENCODING_INVALID', self.workspace.recognize,
                          {'filename': 'synthetic.txt', 'data_base64': '%%%bad'})
        self.assert_error(400, 'JSON_INVALID', self.workspace.preview,
                          {'records': [], 'synthetic': float('nan')})
        self.assert_error(400, 'JSON_INVALID', self.workspace.preview,
                          {'records': ['\ud800'], 'synthetic': True})
        self.assert_error(400, 'REQUEST_INVALID', self.workspace.preview, [])
        self.assert_error(413, 'REQUEST_SIZE_LIMIT', self.workspace.recognize,
                          {'filename': 'synthetic.txt', 'data_base64': 'x' * self.workspace.max_request})
        result = self.workspace.preview({'records': [{}] * 1001, 'synthetic': True})
        self.assertEqual(result['gate'], 'BLOCK')
        self.assertEqual(self.workspace.snapshot()['revision'], 0)


if __name__ == '__main__':
    unittest.main()
