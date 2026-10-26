"""Demo provenance, integrity and refusal checks with no model calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.core import ROOT
from app.demo import make_demo_extractor


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_demo_extractor()
        self.catalog = self.engine['catalog']()

    def payload(self, **updates):
        return {'question': self.catalog['example_question'], 'disease': 'all', 'source_id': 'all',
                'index_sha256': self.catalog['index_sha256'], **updates}

    def test_default_is_explicitly_synthetic_without_fabricated_identifiers(self):
        with patch('subprocess.run', side_effect=AssertionError('model process attempted')):
            answer = self.engine['extract'](self.payload())
        self.assertEqual(self.catalog['data_origin'], 'synthetic')
        self.assertEqual(answer['status'], 'extracts')
        self.assertFalse(answer['model_called'])
        self.assertFalse(answer['translation_model_called'])
        self.assertEqual(answer['model'], 'not_connected')
        item = answer['extracts'][0]
        self.assertIsNone(item['pmid'])
        self.assertIsNone(item['doi'])
        self.assertIsNone(item['clinical_approval'])
        self.assertEqual(hashlib.sha256(item['quote'].encode()).hexdigest(), item['quote_sha256'])
        self.assertEqual(item['answer_zh'], item['quote'])
        self.assertIn(b'SYNTHETIC SOFTWARE FIXTURE', self.engine['section'](item['chunk_id']))
        self.assertIsNone(self.engine['page'](item['chunk_id']))
        self.assertEqual(self.engine['library']()['counts']['fulltext'], 0)

    def test_unknown_question_and_wrong_scope_do_not_get_an_answer(self):
        for payload in (self.payload(question='Which medication should be prescribed?'), self.payload(disease='gout')):
            result = self.engine['extract'](payload)
            self.assertEqual(result['status'], 'insufficient')
            self.assertEqual(result['extracts'], [])
            self.assertFalse(result['model_called'])

    def test_stale_index_unknown_source_and_unexpected_fields_are_rejected(self):
        for payload in (self.payload(index_sha256='0' * 64), self.payload(source_id='foreign'),
                        self.payload(disease=[]), self.payload(extra='forged')):
            with self.assertRaises(ValueError):
                self.engine['extract'](payload)
        self.assertIsNone(self.engine['section']('unknown'))

    def test_changed_source_and_fake_provenance_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.json'
            path.write_bytes((ROOT / 'data/demo.json').read_bytes())
            engine = make_demo_extractor(path)
            catalog = engine['catalog']()
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'source_integrity_failure'):
                engine['extract'](self.payload(index_sha256=catalog['index_sha256']))
            invalid = json.loads(path.read_text(encoding='utf-8'))
            invalid['data_origin'] = 'real_public_documents'
            path.write_text(json.dumps(invalid), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid_demo_provenance'):
                make_demo_extractor(path)


if __name__ == '__main__':
    unittest.main()
