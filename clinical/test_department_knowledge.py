"""Public distribution mode selection and same-origin synthetic source mapping."""
import importlib
import pathlib
import unittest
from unittest.mock import patch

from department_knowledge import Knowledge, KnowledgeError

ROOT = pathlib.Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / 'knowledge'


class KnowledgeDistributionTests(unittest.TestCase):
    def test_explicit_demo_maps_source_links_and_never_starts_a_model(self):
        with patch.dict('os.environ', {'DEPARTMENT_KNOWLEDGE_MODE': 'synthetic-demo'}), \
                patch('subprocess.run', side_effect=AssertionError('model process attempted')):
            service = Knowledge(KNOWLEDGE)
            catalog = service.catalog()
            answer = service.extract({'question': catalog['example_question'], 'disease': 'all',
                'source_id': 'all', 'index_sha256': catalog['index_sha256']})
        self.assertEqual(catalog['data_origin'], 'synthetic')
        self.assertEqual(service.library()['counts']['synthetic'], 1)
        self.assertTrue(answer['extracts'][0]['page_url'].startswith('/api/department/knowledge/section/'))
        self.assertFalse(answer['model_called'])
        raw, media = service.section(answer['extracts'][0]['chunk_id'])
        self.assertEqual(media, 'text/html')
        self.assertIn(b'SYNTHETIC SOFTWARE FIXTURE', raw)
        self.assertIn(b'/static/department-source.css', raw)

    def test_fulltext_mode_keeps_original_factory_instead_of_demo_fallback(self):
        service = Knowledge(KNOWLEDGE, mode='synthetic-demo')
        service.catalog()
        module = importlib.import_module('app.extractive')
        with patch.object(module, 'make_extractor', side_effect=FileNotFoundError('missing source')) as factory:
            with self.assertRaises(KnowledgeError) as error:
                Knowledge(KNOWLEDGE, mode='fulltext').catalog()
        factory.assert_called_once_with()
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.detail, 'fulltext_unavailable')

    def test_invalid_mode_and_stale_demo_binding_are_rejected(self):
        with self.assertRaises(ValueError):
            Knowledge(KNOWLEDGE, mode='automatic')
        service = Knowledge(KNOWLEDGE, mode='synthetic-demo')
        catalog = service.catalog()
        with self.assertRaises(KnowledgeError) as error:
            service.extract({'question': catalog['example_question'], 'disease': 'all', 'source_id': 'all',
                             'index_sha256': '0' * 64})
        self.assertEqual(error.exception.status, 409)


if __name__ == '__main__':
    unittest.main()
