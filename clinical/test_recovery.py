import contextlib
import json
import pathlib
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

import recovery
import care


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'runtime'
        self.source.mkdir()
        (self.source / 'sources').mkdir()
        (self.source / 'SYNTHETIC_ONLY').write_bytes(recovery.MARKER)
        self.job = str(uuid.uuid4())
        (self.source / 'sources' / self.job).write_text('# SJD-SYNTHETIC\npain: 3\n', encoding='utf-8')
        with contextlib.closing(sqlite3.connect(self.source / 'jobs.sqlite')) as con, con:
            con.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,state TEXT,receipt TEXT)')
            con.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY,event TEXT)')
            con.execute('CREATE TABLE reviews(job TEXT,revision INTEGER,decision TEXT)')
            con.execute('CREATE TABLE publications(job TEXT,revision INTEGER,progress TEXT)')
            con.execute('INSERT INTO jobs VALUES(?,?,?)', (self.job, 'partial', '{"patient":"sim-patient"}'))
            con.execute('INSERT INTO audit VALUES(1,?)', ('review_modify',))
            con.execute('INSERT INTO reviews VALUES(?,1,?)', (self.job, '{"value":"3","reason":"source"}'))
            con.execute('INSERT INTO publications VALUES(?,1,?)', (self.job, '{"fields":{"pain":{"state":"archived"}}}'))
        with contextlib.closing(sqlite3.connect(self.source / 'fhir.sqlite')) as con, con:
            con.execute('CREATE TABLE resources(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
            con.execute('CREATE TABLE faults(id INTEGER PRIMARY KEY,mode TEXT,field_id TEXT,remaining INTEGER)')
            con.execute('INSERT INTO resources VALUES(?,?,?)', ('Observation', 'sim-observation', '{"status":"final"}'))

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return recovery.backup(self.source, self.root / 'snapshot', writers_stopped=True)

    def test_roundtrip_restores_files_review_audit_partial_progress_and_fhir(self):
        manifest = self.snapshot()
        result = recovery.restore(self.root / 'snapshot', self.root / 'restored')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['identity_restore'], 'NOT_TESTED')
        self.assertEqual(result['databases'], manifest['databases'])
        self.assertEqual(manifest['databases']['jobs.sqlite']['tables']['reviews']['rows'], 1)
        self.assertEqual(manifest['databases']['jobs.sqlite']['tables']['publications']['rows'], 1)
        for file in manifest['files']:
            self.assertEqual((self.root / 'snapshot' / file).read_bytes(), (self.root / 'restored' / file).read_bytes())
        with contextlib.closing(sqlite3.connect(self.root / 'restored' / 'jobs.sqlite')) as con:
            self.assertEqual(con.execute('SELECT state FROM jobs').fetchone(), ('partial',))
        self.assertNotIn('manifest.json', {p.name for p in (self.root / 'restored').iterdir()})

    def test_care_history_and_separate_demo_store_roundtrip(self):
        for database in ('jobs.sqlite', 'demo-workflow.sqlite'):
            with contextlib.closing(sqlite3.connect(self.source / database)) as con, con:
                care.initialize(con)
                con.execute('INSERT INTO care_records VALUES(?,?,?,?,?,?,?)',
                            ('SIM-A', 'form', 'F1', 1, '{}', 'synthetic-operator', '2026-10-24'))
        manifest = self.snapshot()
        restored = recovery.restore(self.root / 'snapshot', self.root / 'restored')
        self.assertEqual(restored['databases'], manifest['databases'])
        self.assertEqual(manifest['databases']['demo-workflow.sqlite']['tables']['care_records']['rows'], 1)
        self.assertEqual(manifest['databases']['jobs.sqlite']['tables']['care_records']['rows'], 1)

    def test_requires_offline_confirmation_and_fresh_disjoint_destinations(self):
        with self.assertRaises(ValueError):
            recovery.backup(self.source, self.root / 'snapshot')
        with self.assertRaises(ValueError):
            recovery.backup(self.source, self.source / 'snapshot', writers_stopped=True)
        self.snapshot()
        with self.assertRaises(ValueError):
            self.snapshot()
        (self.root / 'existing').mkdir()
        with self.assertRaises(ValueError):
            recovery.restore(self.root / 'snapshot', self.root / 'existing')
        self.assertEqual(list((self.root / 'existing').iterdir()), [])

    def test_tamper_detected_before_target_creation(self):
        self.snapshot()
        (self.root / 'snapshot' / 'sources' / self.job).write_text('tampered', encoding='utf-8')
        with self.assertRaises(ValueError):
            recovery.restore(self.root / 'snapshot', self.root / 'restored')
        self.assertFalse((self.root / 'restored').exists())

    def test_manifest_table_digest_is_verified_independently(self):
        self.snapshot()
        path = self.root / 'snapshot' / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['databases']['jobs.sqlite']['tables']['audit']['rows'] = 0
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            recovery.validate_backup(self.root / 'snapshot')

    def test_unexpected_credential_metadata_rejected_before_any_content_read(self):
        # A synthetic filename sentinel, not an actual credential or secret value.
        (self.source / 'identity.json').touch()
        with patch.object(pathlib.Path, 'read_bytes', side_effect=AssertionError('Content must not be opened')):
            with patch.object(recovery, '_connect', side_effect=AssertionError('Database must not be opened')):
                with self.assertRaises(ValueError):
                    self.snapshot()
        self.assertFalse((self.root / 'snapshot').exists())

    def test_bad_source_name_rejected_before_content_read(self):
        (self.source / 'sources' / 'not-a-uuid').touch()
        with patch.object(pathlib.Path, 'read_bytes', side_effect=AssertionError('Content must not be opened')):
            with self.assertRaises(ValueError):
                self.snapshot()

    def test_missing_or_invalid_marker_rejected(self):
        (self.source / 'SYNTHETIC_ONLY').write_bytes(b'not-synthetic\n')
        with self.assertRaises(ValueError):
            self.snapshot()
        self.assertFalse((self.root / 'snapshot').exists())

    def test_unexpected_database_table_rejected_before_copy(self):
        with contextlib.closing(sqlite3.connect(self.source / 'jobs.sqlite')) as con, con:
            con.execute('CREATE TABLE unexpected_session_data(id TEXT)')
        with self.assertRaises(ValueError):
            self.snapshot()
        self.assertFalse((self.root / 'snapshot').exists())

    def test_hardlinked_source_rejected(self):
        outside = self.root / 'outside'
        outside.write_text('synthetic sentinel', encoding='utf-8')
        (self.source / 'sources' / str(uuid.uuid4())).hardlink_to(outside)
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_wal_snapshot_captures_committed_rows(self):
        con = sqlite3.connect(self.source / 'jobs.sqlite')
        try:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('INSERT INTO audit VALUES(2,?)', ('synthetic_committed',))
            con.commit()
            # Open connection is idle; no concurrent task-owned writer is active.
            manifest = self.snapshot()
            self.assertEqual(manifest['databases']['jobs.sqlite']['tables']['audit']['rows'], 2)
            self.assertFalse(any(name.endswith(('-wal', '-shm')) for name in manifest['files']))
        finally:
            con.close()


if __name__ == '__main__':
    unittest.main()
