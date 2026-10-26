"""Synthetic document extraction and archive trust boundary checks."""
from io import BytesIO
from pathlib import Path
import unittest
import zipfile

from mingyirx.clinical_extract import ExtractError, MAX_BYTES, extract_document


def docx(xml):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return output.getvalue()


class ExtractionTests(unittest.TestCase):
    def test_text_encodings_preserve_missing_negation_and_line_breaks(self):
        text = 'subject_code: SYN-1\n\u75c7\u72b6: \u65e0\u53e3\u5e72\n'
        for encoding in ('utf-8-sig', 'gb18030'):
            result = extract_document(text.encode(encoding), 'txt', Path('.'))
            self.assertEqual(result['text'], text)
            self.assertEqual(len(result['source_sha256']), 64)

    def test_docx_reads_paragraphs_without_embedded_link_or_object_execution(self):
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>subject_code: SYN-1</w:t></w:r></w:p><w:p><w:r><w:t>visit_code: V1</w:t></w:r></w:p></w:body></w:document>'
        result = extract_document(docx(xml), 'docx', Path('.'))
        self.assertEqual(result['text'], 'subject_code: SYN-1\nvisit_code: V1')

    def test_reject_empty_unsupported_expansion_entity_and_broken_document(self):
        for raw, ext in [(b'', 'txt'), (b'a', 'exe'), (b'x' * (MAX_BYTES + 1), 'txt'),
                         (b'bad', 'docx'), (docx('<!DOCTYPE x [<!ENTITY y "z">]><x/>'), 'docx'),
                         (docx(' ' * (4 * 1024 * 1024 + 1)), 'docx')]:
            with self.subTest(ext=ext, length=len(raw)):
                with self.assertRaises(ExtractError):
                    extract_document(raw, ext, Path('.'))

    def test_reject_encoded_dtd_before_entity_expansion(self):
        xml = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY demo "SYNTHETIC_SENTINEL">]><x>&demo;</x>'
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be', 'utf-8'):
            with self.subTest(encoding=encoding), self.assertRaisesRegex(ExtractError, 'DOCX_XML_UNSAFE'):
                extract_document(docx(xml.encode(encoding)), 'docx', Path('.'))
