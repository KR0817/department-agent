"""Explicit offline fixture for the UI contract, never simulated model evidence."""
import copy
import hashlib
import html
import re

from app.benchmark import exact_fields
from app.core import ROOT, parse_json, require_text


def make_demo_extractor(path=None):
    """Serve one authored synthetic fixture without Docker, models or literature."""
    path = path or ROOT / 'data/demo.json'
    raw = path.read_bytes()
    if len(raw) > 32768:
        raise ValueError('demo_fixture_too_large')
    fixture = parse_json(raw.decode('utf-8'))
    exact_fields(fixture, 'schema data_origin clinical_release source_id title title_zh disease questions text')
    if (fixture['schema'] != 'synthetic-knowledge-demo-v1' or fixture['data_origin'] != 'synthetic'
            or fixture['clinical_release'] is not False or fixture['disease'] not in {'ra', 'sjd', 'gout'}
            or not re.fullmatch(r'synthetic-[a-z0-9-]{1,80}', fixture['source_id'])):
        raise ValueError('invalid_demo_provenance')
    for key in ('title', 'title_zh', 'text'):
        require_text(fixture[key], 5000)
    if 'SYNTHETIC' not in fixture['title'] or not isinstance(fixture['questions'], list) or not fixture['questions']:
        raise ValueError('invalid_demo_fixture')
    for question in fixture['questions']:
        require_text(question, 1000)
    source_hash = hashlib.sha256(raw).hexdigest()
    text_hash = hashlib.sha256(fixture['text'].encode()).hexdigest()
    cid = 'ft_' + source_hash[:24]
    locator = '/api/fulltext/section/' + cid
    source = {'id': fixture['source_id'], 'title': fixture['title'], 'title_zh': fixture['title_zh'],
        'disease': fixture['disease'], 'data_origin': 'synthetic', 'pmid': None, 'pmcid': None,
        'doi': None, 'year': None, 'source_url': None, 'evidence_kind': 'synthetic_fixture',
        'access': 'synthetic_fixture', 'identity_status': 'synthetic_fixture', 'review_status': 'not_applicable',
        'clinical_approval': None, 'retrieval_eligible': True, 'locator_url': locator}

    def intact():
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_hash:
            raise ValueError('source_integrity_failure')

    def catalog():
        intact()
        return {'enabled': True, 'answer_language': 'zh-CN', 'data_origin': 'synthetic',
            'index_sha256': source_hash, 'model': 'not_connected', 'model_status': 'not_run',
            'chunk_count': 1, 'sources': [copy.deepcopy(source)],
            'example_question': fixture['questions'][0],
            'note': 'SYNTHETIC offline software fixture. No clinical literature or model inference.'}

    def library():
        return {'version': 'synthetic-demo-1', 'answer_language': 'zh-CN', 'data_origin': 'synthetic',
            'sources': catalog()['sources'],
            'counts': {'total': 1, 'fulltext': 0, 'indexed': 0, 'synthetic': 1, 'clinical_approved': 0}}

    def extract(payload):
        exact_fields(payload, 'question disease source_id index_sha256')
        question = require_text(payload['question'], 1000).strip()
        if (not isinstance(payload['disease'], str) or payload['disease'] not in {'all', 'ra', 'sjd', 'gout'}
                or not isinstance(payload['source_id'], str)
                or payload['source_id'] not in {'all', source['id']}):
            raise ValueError('invalid_scope')
        if payload['index_sha256'] != source_hash:
            raise ValueError('stale_fulltext_index')
        intact()
        base = {'data_origin': 'synthetic', 'model': 'not_connected', 'model_called': False,
            'translation_model_called': False, 'clinical_approval': None, 'index_sha256': source_hash,
            'answer_language': 'zh-CN', 'answer_scope': 'synthetic_demo',
            'completeness': 'not_applicable', 'extraction_method': 'fixed_synthetic_example',
            'translation_status': 'not_needed', 'extracts': []}
        if question not in fixture['questions'] or payload['disease'] not in {'all', fixture['disease']}:
            return {**base, 'status': 'insufficient', 'reason': 'synthetic_demo_only',
                    'anchoring': 'not_applicable', 'retrieved_count': 0}
        item = {**copy.deepcopy(source), 'source_id': source['id'], 'chunk_id': cid,
            'quote': fixture['text'], 'context': fixture['text'], 'answer_zh': fixture['text'],
            'quote_sha256': text_hash, 'source_sha256': source_hash,
            'quote_start': 0, 'quote_end': len(fixture['text']), 'pdf_page': None,
            'page_url': locator, 'locator': 'Synthetic software fixture',
            'translation_status': 'not_needed', 'translation_origin': 'authored_synthetic_fixture',
            'translation_review_status': 'not_applicable'}
        return {**base, 'status': 'extracts', 'extracts': [item], 'anchoring': 'exact_synthetic_fixture',
                'retrieved_count': 1}

    def section(chunk_id):
        if chunk_id != cid:
            return None
        intact()
        document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>SYNTHETIC software fixture</title><body><main><h1>' + html.escape(fixture['title_zh'])
            + '</h1><p>SYNTHETIC SOFTWARE FIXTURE. Not a publication, patient record or medical recommendation.</p>'
            + '<pre class="department-source-text">' + html.escape(fixture['text']) + '</pre>'
            + '<p>SHA-256: ' + source_hash + '</p></main></body></html>')
        return document.encode('utf-8')

    return {'catalog': catalog, 'library': library, 'extract': extract,
            'page': lambda chunk_id: None, 'section': section}
