import csv
import hashlib
import json
import pathlib
import tempfile
import unittest

import usability


class UsabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'observations.csv'
        self.row = dict(zip(usability.COLUMNS, [
            'CLIN-SIM1', 'T01', '2026-10-22T09:00:00+08:00',
            '2026-10-22T09:02:00+08:00', '1', '1', 'completed',
            'Synthetic test row; no clinician participated']))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows):
        with self.source.open('w', encoding='utf-8', newline='') as writer:
            csv_writer = csv.DictWriter(writer, fieldnames=usability.COLUMNS)
            csv_writer.writeheader()
            csv_writer.writerows(rows)

    def test_template_is_empty_and_explicit_about_no_participants(self):
        protocol = usability.template(self.root / 'kit')
        rows, _ = usability.validate(self.root / 'kit' / 'observations.empty.csv')
        self.assertEqual(rows, [])
        self.assertEqual(len(protocol['tasks']), 5)
        self.assertEqual(protocol['actual_clinicians_participated'], 0)
        self.assertEqual(protocol['clinical_accuracy_evaluation'], 'NOT_RUN')
        with self.assertRaises(ValueError):
            usability.freeze(self.root / 'kit' / 'observations.empty.csv', self.root / 'frozen',
                             data_origin='simulated', deidentified=True)
        self.assertFalse((self.root / 'frozen').exists())

    def test_validated_import_and_write_once_freeze(self):
        self.write([self.row])
        rows, digest = usability.validate(self.source)
        self.assertEqual(rows, [self.row])
        manifest = usability.freeze(self.source, self.root / 'frozen', data_origin='simulated', deidentified=True)
        self.assertEqual(manifest['input_sha256'], digest)
        self.assertEqual(manifest['rows'], 1)
        self.assertEqual(manifest['data_origin'], 'simulated')
        self.assertEqual(manifest['actual_clinician_participation'], 'NOT_ESTABLISHED_BY_TOOL')
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((self.root / 'frozen' / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(json.loads((self.root / 'frozen' / 'manifest.json').read_text()), manifest)
        with self.assertRaises(ValueError):
            usability.freeze(self.source, self.root / 'frozen', data_origin='simulated', deidentified=True)

    def test_invalid_observations_are_not_frozen(self):
        bad = [('pseudonymous_clinician_id', 'Firstname Lastname'), ('task_id', 'T99'),
               ('start', '2026-10-22T09:00:00'), ('end', '2026-10-21T09:00:00+08:00'),
               ('corrected', '-1'), ('rejected', ''), ('outcome', 'success'),
               ('note', '=SUM(1,2)'), ('note', 'Unexpected\nnewline')]
        for field, value in bad:
            with self.subTest(field=field, value=value):
                row = dict(self.row, **{field: value})
                self.write([row])
                with self.assertRaises(ValueError):
                    usability.freeze(self.source, self.root / 'frozen', data_origin='simulated', deidentified=True)
                self.assertFalse((self.root / 'frozen').exists())

    def test_duplicate_tasks_and_wrong_columns_rejected(self):
        self.write([self.row, self.row])
        with self.assertRaises(ValueError):
            usability.validate(self.source)
        self.source.write_text('name,task\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            usability.validate(self.source)

    def test_freeze_requires_origin_and_deidentification_attestation(self):
        self.write([self.row])
        with self.assertRaises(ValueError):
            usability.freeze(self.source, self.root / 'frozen', data_origin='simulated')
        with self.assertRaises(ValueError):
            usability.freeze(self.source, self.root / 'frozen', data_origin='unknown', deidentified=True)
        self.assertFalse((self.root / 'frozen').exists())


if __name__ == '__main__':
    unittest.main()
