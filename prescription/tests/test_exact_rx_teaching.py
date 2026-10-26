"""Only invented input is used for exact-prescription and privacy regression."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mingyirx.dashboard_exact_rx import render_exact_rx
from mingyirx.dashboard_clinical import render_clinical_workspace
from mingyirx.exact_rx_teaching import (FIELDS, SCHEMA, digest, presentable, read_source,
    select_episodes, simulate, verify_exact)
from mingyirx.inheritance import InheritanceError, assert_output_allowed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_exact_rx_workspace import create_fixture


class ExactRxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'source.csv'
        self.rules = json.loads((ROOT / 'configs/exact_rx_teaching_rules.json').read_text('utf-8'))
        create_fixture(self.path, self.rules)

    def load(self):
        groups, _ = read_source(self.path, digest(self.path))
        return select_episodes(groups, self.rules, r'ExcludedProduct')

    def mutate(self, change):
        with self.path.open(encoding='gb18030', newline='') as file:
            rows = list(csv.reader(file))
        change(rows)
        with self.path.open('w', encoding='gb18030', newline='') as file:
            csv.writer(file).writerows(rows)

    def bundle(self):
        episodes = self.load()
        return {'schema_version': SCHEMA, 'mode': 'synthetic_software_fixture',
                'episodes': episodes, 'rule_version': self.rules['version'],
                'rule_sha256': 'a' * 64, 'source_sha256': digest(self.path),
                'verification': verify_exact(self.path, episodes, digest(self.path))}

    def test_all_fields_duplicates_and_relative_time_survive(self):
        episodes = self.load()
        self.assertEqual(len(episodes), 5)
        self.assertTrue(all(len(e['visits']) == 3 for e in episodes))
        self.assertTrue(all([v['offset_days'] for v in e['visits']] == [0, 14, 28] for e in episodes))
        rows = [v['raw_rows'] for e in episodes for v in e['visits']]
        self.assertTrue(any(len({r['item_name'] for r in rs}) < len(rs) for rs in rows))
        self.assertTrue(any(r['dose'] == '10.00' for rs in rows for r in rs))
        self.assertTrue(all(set(r) == set(FIELDS) for rs in rows for r in rs))
        self.assertEqual(verify_exact(self.path, episodes, digest(self.path))['verified_raw_fields'], 540)

    def test_source_hash_and_row_tamper_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_HASH_MISMATCH'):
            read_source(self.path, '0'*64)
        episodes = self.load()
        episodes[0]['visits'][0]['raw_rows'][0]['dose'] = '999'
        with self.assertRaisesRegex(ValueError, 'EXACT_PRESCRIPTION_MISMATCH'):
            verify_exact(self.path, episodes, digest(self.path))

    def test_invalid_date_cannot_be_bridged(self):
        self.mutate(lambda rows: rows[7].__setitem__(4, 'not-a-date'))
        self.assertEqual(len(self.load()), 4)

    def test_missing_key_row_does_not_make_incomplete_prescription(self):
        self.mutate(lambda rows: rows[7].__setitem__(3, ''))
        self.assertEqual(len(self.load()), 4)

    def test_excluded_row_invalidates_entire_visit(self):
        self.mutate(lambda rows: rows[7].__setitem__(11, 'ExcludedProduct'))
        self.assertEqual(len(self.load()), 4)

    def test_same_day_ambiguity_is_not_bridged(self):
        def add(rows):
            extra = copy.deepcopy(rows[7:13])
            for row in extra:
                row[4] = '2000/01/15 12:00:00'
                row[2] = 'SYN-CLINIC-EXTRA'
            rows.extend(extra)
        self.mutate(add)
        self.assertEqual(len(self.load()), 4)

    def test_timestamp_clinic_collision_is_excluded(self):
        self.mutate(lambda rows: rows[7].__setitem__(2, 'SYN-CLINIC-CONFLICT'))
        self.assertEqual(len(self.load()), 4)

    def test_stable_cues_do_not_invent_improvement(self):
        sample = self.load()[0]['visits'][0]['raw_rows']
        first = simulate(sample, self.rules)
        second = simulate(sample, self.rules)
        self.assertEqual(first, second)
        self.assertEqual(first['origin'], 'SIMULATED_FROM_PRESCRIPTION_NOT_OBSERVED')
        self.assertEqual(simulate([{'item_name':'No matching cue'}], self.rules)['profile_id'], 'UNDETERMINED')

    def test_html_never_contains_keys_dates_or_private_row_references(self):
        bundle = self.bundle()
        rendered = render_exact_rx(bundle)
        for unsafe in ('SYN-SUBJECT-', '2000/01/', 'private_source_rows', 'PHYSICAL_CARDNO', 'RELA_PHONE'):
            self.assertNotIn(unsafe, rendered)
        self.assertNotIn('private_source_rows', json.dumps(presentable(bundle)))
        self.assertIn('synthetic_software_fixture', rendered)
        self.assertIn('10.00', rendered)
        self.assertNotIn('fetch(', rendered)

    def test_html_script_injection_is_escaped(self):
        bundle = self.bundle()
        bundle['episodes'][0]['visits'][0]['raw_rows'][0]['item_name'] = '</script><img src=x onerror=bad()>'
        rendered = render_exact_rx(bundle)
        self.assertNotIn('</script><img', rendered)
        self.assertIn('\\u003c/script\\u003e', rendered)

    def test_real_output_guard_and_shell_mode(self):
        with self.assertRaises(InheritanceError):
            assert_output_allowed({'synthetic': False, 'local_authorization': True,
                'deidentified': True}, Path(self.temporary.name) / 'public')
        self.assertIn('"exact_rx_teaching":true', render_clinical_workspace(exact_rx_teaching=True))
        with self.assertRaisesRegex(ValueError, 'EXACT_RX_TEACHING_BOOLEAN_REQUIRED'):
            render_clinical_workspace(exact_rx_teaching='yes')


if __name__ == '__main__':
    unittest.main()
