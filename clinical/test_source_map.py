"""Source locations use actual page structure and explicit OCR coordinates only."""
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image

import source_map


class SourceMapTests(unittest.TestCase):
    def test_duplicate_excerpts_expose_all_matches_across_pages(self):
        pages = [{'page': 1, 'text': 'IgG 12 g/L\nIgG 12 g/L', 'lines': []},
                 {'page': 2, 'text': 'IgG 12 g/L', 'lines': []}]
        found = source_map.locate({'pages': pages}, 'IgG 12 g/L')
        self.assertEqual([m['page'] for m in found], [1, 1, 2])
        self.assertTrue(all(m['boxes'] == [] for m in found))
        self.assertEqual(source_map.locate({'pages': pages}, 'IgG 13 g/L'), [])

    def test_ocr_boxes_are_bounded_and_quote_matches_actual_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'synthetic.png'
            Image.new('RGB', (300, 200), 'white').save(path)
            tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\ttext\n'
                   '5\t1\t1\t1\t1\t10\t20\t50\t20\tIgG\n'
                   '5\t1\t1\t1\t1\t70\t20\t50\t20\t12\n'
                   '5\t1\t1\t1\t1\t130\t20\t50\t20\tg/L\n'
                   '5\t1\t1\t1\t2\t500\t20\t50\t20\tinvalid\n')
            ocr = Mock()
            ocr.extract_tsv.return_value = SimpleNamespace(tsv=tsv)
            mapping = source_map.build(path, '.png', '', ocr)
            self.assertEqual(mapping['pages'][0]['text'], 'IgG 12 g/L')
            self.assertEqual(source_map.locate(mapping, 'IgG 12 g/L')[0]['boxes'], [[10, 20, 180, 40]])

    def test_unavailable_geometry_falls_back_to_text_and_no_invented_boxes(self):
        ocr = Mock()
        ocr.extract_tsv.side_effect = RuntimeError('Unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'synthetic.png'
            Image.new('RGB', (100, 100), 'white').save(path)
            mapping = source_map.build(path, '.png', 'IgG 12 g/L', ocr)
            self.assertIn('ocr_geometry_unavailable', mapping['warnings'])
            self.assertEqual(source_map.locate(mapping, 'IgG 12 g/L')[0]['boxes'], [])

    def test_text_files_have_logical_page_only(self):
        mapping = source_map.build(pathlib.Path('unused'), '.csv', 'IgG,12,g/L', None)
        self.assertFalse(mapping['pages'][0]['image_available'])
        self.assertEqual(mapping['warnings'], ['logical_page_only'])

    def test_rotated_exif_does_not_expose_misaligned_boxes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'rotated.jpg'
            image = Image.new('RGB', (300, 200), 'white')
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            ocr = Mock()
            mapping = source_map.build(path, '.jpg', 'IgG 12 g/L', ocr)
            ocr.extract_tsv.assert_not_called()
            self.assertEqual(mapping['pages'][0]['lines'], [])


if __name__ == '__main__':
    unittest.main()
