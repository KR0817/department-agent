"""Exercise release boundaries using only disposable, synthetic Git fixtures."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_check', ROOT / 'scripts/release_check.py')
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='department-release-test-')
        self.root = Path(self.temporary.name)
        self.git(['init', '--quiet'])

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, args, content=None):
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run(['git', '-C', str(self.root), *args], input=content,
                                capture_output=True, check=True, env=environment)
        return result.stdout

    def stage(self, name, content, mode='100644'):
        raw = content.encode('utf-8') if isinstance(content, str) else content
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        oid = self.git(['hash-object', '-w', '--stdin'], raw).decode('ascii').strip()
        self.git(['update-index', '--add', '--cacheinfo', mode, oid, name])
        return oid

    def rules(self, report):
        return {finding['rule'] for finding in report['findings']}

    def test_empty_candidate_set_fails_in_both_modes(self):
        for working_tree in (False, True):
            with self.subTest(working_tree=working_tree):
                report = release_check.scan(self.root, working_tree=working_tree)
                self.assertFalse(report['passed'])
                self.assertEqual(report['files_checked'], 0)
                self.assertIn('empty_candidate_set', self.rules(report))
        self.stage('README.md', 'Synthetic public source fixture\n')
        self.assertTrue(release_check.scan(self.root)['passed'])

    def test_index_checks_staged_content_not_changed_working_copy(self):
        self.stage('clinical/example.py', 'VALUE = 1\n')
        private_path = 'C:/' + 'Users/' + 'gla' + 'h1' + '/sample'
        (self.root / 'clinical/example.py').write_text('VALUE = ' + repr(private_path), encoding='utf-8')
        self.assertTrue(release_check.scan(self.root)['passed'])
        report = release_check.scan(self.root, working_tree=True)
        self.assertIn('personal_machine_path', self.rules(report))

    def test_sensitive_filename_is_rejected_without_reading_blob(self):
        oid = self.stage('.env.local', 'DISPOSABLE_FIXTURE=not-a-credential\n')
        actual_git = release_check._git
        calls = []
        def guarded(root, args, content=None):
            calls.append((args, content))
            if args[0] == 'cat-file' and (oid in args or content and oid.encode('ascii') in content):
                self.fail('A forbidden file reached object reading')
            return actual_git(root, args, content)
        with patch.object(release_check, '_git', side_effect=guarded):
            report = release_check.scan(self.root)
        self.assertIn('credential_filename', self.rules(report))
        self.assertFalse(any(args[0] == 'cat-file' for args, _ in calls))

    def test_token_match_reports_line_without_value(self):
        synthetic_token = 'gh' + 'p_' + 'Z' * 36
        self.stage('clinical/example.py', '# synthetic test fixture\nVALUE = ' + repr(synthetic_token) + '\n')
        report = release_check.scan(self.root)
        self.assertEqual(report['findings'], [
            {'path': 'clinical/example.py', 'line': 2, 'rule': 'github_token'}])
        self.assertNotIn(synthetic_token, json.dumps(report))

    def test_private_artifact_paths_are_rejected(self):
        fixtures = {
            'clinical/exports/visits.csv': 'unapproved_data_artifact',
            'prescription/site/research-report.html': 'generated_html_not_source',
            'clinical/state.sqlite': 'runtime_database',
            'clinical/work/snapshot.json': 'private_or_generated_directory',
            'knowledge/data/unreviewed.json': 'unapproved_knowledge_data',
        }
        for name in fixtures:
            self.stage(name, 'synthetic fixture only\n')
        report = release_check.scan(self.root)
        actual = {f['path']: f['rule'] for f in report['findings']}
        self.assertEqual(actual, fixtures)

    def test_actual_licenses_are_not_misidentified(self):
        for name in ['LICENSE', 'licenses/MingYiRx-MIT.txt', 'licenses/Geist-OFL-1.1.txt']:
            self.stage(name, (ROOT / name).read_bytes())
        report = release_check.scan(self.root)
        self.assertTrue(report['passed'], report)

    def test_source_pages_are_allowed_but_generated_reports_are_not(self):
        for name in ['clinical/static/index.html', 'knowledge/app/static/index.html',
                     'knowledge/app/report_template.html']:
            self.stage(name, '<html><title>Synthetic source-page fixture</title></html>')
        self.assertTrue(release_check.scan(self.root)['passed'])
        self.stage('knowledge/app/static/report.html', '<html>Synthetic generated report</html>')
        report = release_check.scan(self.root)
        self.assertEqual(report['findings'], [
            {'path': 'knowledge/app/static/report.html', 'line': None,
             'rule': 'generated_html_not_source'}])

    def test_large_file_is_rejected_before_text_scan(self):
        self.stage('clinical/large.py', b'#' * (release_check.MAX_FILE_BYTES + 1))
        with patch.object(release_check, '_text_findings', side_effect=AssertionError('No content scan expected')):
            report = release_check.scan(self.root)
        self.assertIn('oversized_file', self.rules(report))

    def test_untracked_runtime_and_cache_directories_are_not_read(self):
        for name in ['work/item.txt', '.venv/item.txt', 'node_modules/item.txt', 'clinical/__pycache__/item.txt']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic ignored runtime', encoding='utf-8')
        (self.root / 'README.md').write_text('Public fixture\n', encoding='utf-8')
        report = release_check.scan(self.root, working_tree=True)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['files_checked'], 1)

    def test_knowledge_seed_contract_is_enforced(self):
        valid = {'schema': 'synthetic-knowledge-demo-v1', 'data_origin': 'synthetic', 'clinical_release': False}
        self.stage('knowledge/data/demo.json', json.dumps(valid))
        self.stage('knowledge/data/corpus.json', json.dumps({'sources': [], 'claims': []}))
        self.assertTrue(release_check.scan(self.root)['passed'])
        valid['data_origin'] = 'unverified'
        self.stage('knowledge/data/demo.json', json.dumps(valid))
        report = release_check.scan(self.root)
        self.assertIn('knowledge_seed_boundary', self.rules(report))

    def test_symlink_index_entry_is_rejected(self):
        self.stage('clinical/example.py', '../../outside', mode='120000')
        report = release_check.scan(self.root)
        self.assertIn('unmerged_or_nonregular_index_entry', self.rules(report))

    def test_clinical_fixture_allowlist_rejects_renamed_export(self):
        self.stage('clinical/fixtures/unreviewed.csv', 'synthetic boundary probe\n')
        report = release_check.scan(self.root)
        self.assertIn('unapproved_fixture', self.rules(report))


if __name__ == '__main__':
    unittest.main()
