"""Bounded local page and excerpt navigation; coordinates come only from OCR output."""
import csv
import io
import pathlib
import re
import subprocess
import tempfile
from PIL import Image
from pypdf import PdfReader


def _compact(value):
    return re.sub(r'\s+', '', value)


def _ocr_page(path, ocr):
    with Image.open(path) as image:
        width, height = image.size
        if width * height > 20_000_000:
            raise ValueError('Source page exceeds pixel limit')
        if image.getexif().get(274, 1) != 1:
            raise ValueError('Source orientation requires manual alignment')
    tsv = ocr.extract_tsv(path).tsv
    groups = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        if not row.get('text', '').strip() or row.get('level') != '5':
            continue
        key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
        if min(x, y, w, h) < 0 or x + w > width or y + h > height:
            continue
        groups.setdefault(key, []).append((row['text'], [x, y, x + w, y + h]))
    lines = []
    for words in groups.values():
        lines.append({'text': ' '.join(w[0] for w in words),
                      'bbox': [min(w[1][0] for w in words), min(w[1][1] for w in words),
                               max(w[1][2] for w in words), max(w[1][3] for w in words)]})
    return {'text': '\n'.join(line['text'] for line in lines), 'width': width, 'height': height, 'lines': lines}


def _pdf_image(path, number, directory):
    stem = pathlib.Path(directory) / 'page'
    subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number), '-scale-to', '2400',
                    '-singlefile', '-png', str(path), str(stem)], check=True, capture_output=True, timeout=45)
    return stem.with_suffix('.png')


def build(path, suffix, fallback_text, ocr):
    pages, warnings = [], []
    if suffix == '.pdf':
        reader = PdfReader(path)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 12:
            raise ValueError('Source PDF is outside the supported bounds')
        for number, page in enumerate(reader.pages, 1):
            value = page.extract_text() or ''
            result = {'text': value, 'lines': [], 'width': None, 'height': None}
            if len(value.strip()) < 25:
                try:
                    with tempfile.TemporaryDirectory() as directory:
                        result = _ocr_page(_pdf_image(path, number, directory), ocr)
                except Exception:
                    warnings.append('ocr_geometry_unavailable')
            pages.append({**result, 'page': number, 'image_available': True})
    elif suffix in ('.png', '.jpg', '.jpeg'):
        try:
            result = _ocr_page(path, ocr)
        except Exception:
            result = {'text': fallback_text or '', 'lines': [], 'width': None, 'height': None}
            warnings.append('ocr_geometry_unavailable')
        pages.append({**result, 'page': 1, 'image_available': True})
    else:
        pages.append({'page': 1, 'text': fallback_text or '', 'lines': [], 'width': None, 'height': None,
                      'image_available': False})
        warnings.append('logical_page_only')
    if sum(len(p['text']) for p in pages) > 200000:
        raise ValueError('Source map exceeds text limit')
    return {'pages': pages, 'warnings': sorted(set(warnings)), 'geometry_basis': 'local_ocr_only'}


def locate(mapping, quote):
    needle = _compact(quote)
    matches = []
    if not needle:
        return matches
    for page in mapping['pages']:
        normalized = _compact(page['text'])
        if needle not in normalized:
            continue
        # A repeated excerpt must expose every matching occurrence, not choose the first.
        starts = [m.start() for m in re.finditer(re.escape(needle), normalized)]
        for start in starts:
            offset, boxes = 0, []
            for line in page['lines']:
                end = offset + len(_compact(line['text']))
                if offset < start + len(needle) and end > start:
                    boxes.append(line['bbox'])
                offset = end
            matches.append({'page': page['page'], 'occurrence': start, 'boxes': boxes})
    return matches


def page_image(path, suffix, number):
    if suffix in ('.png', '.jpg', '.jpeg') and number == 1:
        return path.read_bytes(), 'image/png' if suffix == '.png' else 'image/jpeg'
    if suffix == '.pdf':
        reader = PdfReader(path)
        if reader.is_encrypted or not 1 <= number <= len(reader.pages) <= 12:
            raise ValueError('Source page is invalid')
        with tempfile.TemporaryDirectory() as directory:
            return _pdf_image(path, number, directory).read_bytes(), 'image/png'
    raise ValueError('Source page is unavailable')
