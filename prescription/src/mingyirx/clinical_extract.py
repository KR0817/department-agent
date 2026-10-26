"""Bounded local document extraction; no remote OCR or model fallback."""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from xml.etree import ElementTree
from xml.parsers import expat

MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 500_000
FORMATS = ['txt', 'csv', 'json', 'docx', 'pdf', 'png', 'jpg', 'jpeg', 'bmp']


class ExtractError(ValueError):
    """An input-independent error safe for an HTTP response."""


def extract_document(data: bytes, extension: str, private_dir: Path) -> dict:
    """Extract text, keeping any necessary OCR source only in private storage."""
    extension = extension.lower().lstrip('.')
    if extension not in FORMATS:
        raise ExtractError('UNSUPPORTED_FORMAT')
    if not data or len(data) > MAX_BYTES:
        raise ExtractError('FILE_SIZE_LIMIT')
    digest = hashlib.sha256(data).hexdigest()
    extractor = 'decoded-text'
    try:
        if extension in ('txt', 'csv', 'json'):
            try:
                text = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = data.decode('gb18030')
                extractor = 'decoded-gb18030'
        elif extension == 'docx':
            extractor = 'docx-document-xml'
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or sum(x.file_size for x in entries) > 32 * 1024 * 1024:
                    raise ExtractError('DOCX_EXPANSION_LIMIT')
                candidates = [e for e in entries if e.filename == 'word/document.xml']
                if len(candidates) != 1 or candidates[0].file_size > 4 * 1024 * 1024:
                    raise ExtractError('DOCX_DOCUMENT_INVALID')
                xml = archive.read(candidates[0])
                if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                    raise ExtractError('DOCX_XML_UNSAFE')
                def reject_dtd(*_args):
                    raise ExtractError('DOCX_XML_UNSAFE')
                parser = expat.ParserCreate()
                parser.StartDoctypeDeclHandler = reject_dtd
                parser.EntityDeclHandler = reject_dtd
                parser.ExternalEntityRefHandler = reject_dtd
                parser.Parse(xml, True)
                root = ElementTree.fromstring(xml)
                namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                text = '\n'.join(''.join(t.text or '' for t in paragraph.iter(namespace + 't'))
                                 for paragraph in root.iter(namespace + 'p'))
        elif extension == 'pdf':
            extractor = 'pypdf-text'
            try:
                from pypdf import PdfReader
            except ImportError as error:
                raise ExtractError('PDF_REQUIRES_LOCAL_PYPDF') from error
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ExtractError('PDF_ENCRYPTED')
            if len(reader.pages) > 30:
                raise ExtractError('PDF_PAGE_LIMIT')
            pieces = []
            for page in reader.pages:
                value = page.extract_text() or ''
                pieces.append(value)
                if sum(map(len, pieces)) > MAX_TEXT:
                    raise ExtractError('TEXT_SIZE_LIMIT')
            text = '\n'.join(pieces)
            if not text.strip():
                raise ExtractError('SCANNED_PDF_EXPORT_PAGES_FOR_OCR')
        else:
            extractor = 'windows-local-ocr'
            if sys.platform != 'win32':
                raise ExtractError('LOCAL_WINDOWS_OCR_UNAVAILABLE')
            path = private_dir.resolve() / (digest + '.' + extension)
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(data)
            elif path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ExtractError('OCR_SOURCE_CONFLICT')
            script = Path(__file__).with_name('clinical_ocr.ps1')
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                '-ExecutionPolicy', 'Bypass', '-File', str(script), '-InputPath', str(path)],
                capture_output=True, timeout=60, encoding='utf-8', errors='replace')
            if process.returncode:
                raise ExtractError('LOCAL_OCR_FAILED')
            result = json.loads(process.stdout.lstrip('\ufeff'))
            text = result['text']
            extractor += ':' + result['language']
    except ExtractError:
        raise
    except subprocess.TimeoutExpired as error:
        raise ExtractError('LOCAL_EXTRACTION_TIMEOUT') from error
    except Exception as error:
        raise ExtractError('DOCUMENT_INVALID') from error
    if not isinstance(text, str) or not text.strip() or '\x00' in text:
        raise ExtractError('DOCUMENT_TEXT_EMPTY_OR_INVALID')
    if len(text) > MAX_TEXT:
        raise ExtractError('TEXT_SIZE_LIMIT')
    return {'text': text, 'source_sha256': digest, 'extractor': extractor,
            'format_name': extension if extension in ('csv', 'json') else 'txt'}
