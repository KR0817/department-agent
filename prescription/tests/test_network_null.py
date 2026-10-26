import random
import unittest
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from collections import Counter
from mingyirx.network_null import trade, fixed_margin_network


class NetworkNullTests(unittest.TestCase):
    def test_runner_hash_gate_survives_python_optimization(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            config = base/'config.json'
            config.write_text('{}', encoding='utf-8')
            (base/'run_manifest.json').write_text(json.dumps({'gate':'PASS',
                'configuration':{'absolute_path':str(config),'sha256':'0'*64}}),encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(root/'src'))
            result = subprocess.run([sys.executable,'-O',str(root/'scripts/run_network_null.py'),
                '--baseline',str(base),'--output',str(base/'output')],capture_output=True,text=True,env=env)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Configuration hash mismatch',result.stderr)
            self.assertFalse((base/'output').exists())

    def test_trade_preserves_both_margins_and_explores_tiny_space(self):
        rows = [{'A','B'}, {'C','D'}]
        rng = random.Random(11)
        seen = set()
        for _ in range(2000):
            trade(rows, rng)
            self.assertEqual([len(row) for row in rows], [2,2])
            self.assertEqual(Counter(item for row in rows for item in row), Counter('ABCD'))
            seen.add(tuple(sorted(rows[0])))
        self.assertEqual(len(seen), 6)

    def test_degenerate_matrix_has_probability_one(self):
        rows, diagnostics = fixed_margin_network([set('AB')]*10,'g',10,.2,0,.5,draws_per_chain=10)
        self.assertEqual(rows[0]['mc_upper_tail_p'],1)
        self.assertEqual(rows[0]['mc_bh_q'],1)
        self.assertEqual(rows[0]['observed_minus_null'],0)
        self.assertEqual(diagnostics['changed_trade_fraction'],0)

    def test_full_family_precedes_privacy_filter_and_is_deterministic(self):
        source=[set('AB')]*10+[set('AC')]*10+[set('BC')]
        rows, diagnostics = fixed_margin_network(source,'g',10,.1,0,.5,draws_per_chain=20)
        self.assertEqual(diagnostics['family_pairs'],3)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row['observed_cooccurrence_patients']>=10 for row in rows))
        self.assertEqual((rows,diagnostics), fixed_margin_network(source,'g',10,.1,0,.5,draws_per_chain=20))
        self.assertEqual(source,[set('AB')]*10+[set('AC')]*10+[set('BC')])

    def test_small_group_and_empty_family(self):
        self.assertEqual(fixed_margin_network([set('AB')],'g',10,.2,0,.5)[0],[])
        self.assertEqual(fixed_margin_network([{'A'}]*10,'g',10,.2,0,.5)[1]['status'],'NO_ELIGIBLE_PAIRS')
