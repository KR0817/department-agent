"""Single-operator loopback workspace with private, append-only revisions."""
from __future__ import annotations

import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import uuid

from .case_import import recognize_text, prepare_import
from .clinical_extract import ExtractError, FORMATS, MAX_BYTES, extract_document
from .dashboard_inheritance import render_inheritance
from .inheritance import InheritanceError, assert_output_allowed, build_view, freeze_bundle, read_frozen

STATIC_NAMES = frozenset({'index.html', 'aggregate.html', 'inheritance.html',
    'exact-rx.html',
    'teaching-provenance.json', 'research-report.html', 'conditional_retention.csv',
    'disease-change-results.csv', 'literature-analysis-results.csv', 'source-ledger.json',
    'supplement.html', 'analysis-report.md', 'robots.txt', 'source-correction.json'})
MAX_REQUEST = 12 * 1024 * 1024


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True) + '\n').encode('utf-8')


def _read_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


class LocalWorkspace:
    """State is private and revisions never overwrite an existing version."""

    def __init__(self, site: Path, state_dir: Path, resume: bool = False):
        self.site = site.resolve(strict=True)
        self.state_dir = Path(state_dir).absolute()
        # Existing core enforces the checkout's ignored work/ boundary and checks junctions.
        guard_path = self.state_dir / ('resume-check-' + uuid.uuid4().hex) if resume else self.state_dir
        assert_output_allowed({'synthetic': False, 'local_authorization': True, 'deidentified': True}, guard_path)
        if resume and not self.state_dir.is_dir():
            raise ExtractError('SESSION_NOT_FOUND')
        self.state_dir.mkdir(parents=True, exist_ok=resume)
        self.uploads = self.state_dir / 'uploads'
        self.uploads.mkdir(exist_ok=resume)
        self.nonce = secrets.token_urlsafe(32)
        self.records = []
        self.revision = 0
        self.page = None
        self.mode = None
        self.lock = threading.Lock()
        if resume:
            revisions = sorted(p for p in self.state_dir.iterdir() if re.fullmatch(r'revision-\d{4}', p.name))
            previous_hash = None
            for expected, folder in enumerate(revisions, 1):
                if folder.name != f'revision-{expected:04d}' or folder.is_symlink():
                    raise ExtractError('SESSION_CHAIN_INVALID')
                for name in ('records.json', 'receipt.json', 'frozen'):
                    path = folder / name
                    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                        raise ExtractError('SESSION_LINK_REJECTED')
                frozen = read_frozen(folder / 'frozen')
                receipt = _read_json((folder / 'receipt.json').read_bytes())
                records = _read_json((folder / 'records.json').read_bytes())
                if frozen['revision'] != expected or frozen['parent_sha256'] != previous_hash or receipt['records_sha256'] != hashlib.sha256(_json_bytes(records)).hexdigest():
                    raise ExtractError('SESSION_CHAIN_INVALID')
                rebuilt = prepare_import(records, synthetic=frozen['synthetic'])
                if rebuilt['gate'] == 'BLOCK':
                    raise ExtractError('SESSION_RECORDS_INVALID')
                rebuilt['bundle'].update(revision=expected, parent_sha256=previous_hash)
                if rebuilt['bundle'] != frozen:
                    raise ExtractError('SESSION_CONTENT_MISMATCH')
                self.records, self.revision, self.mode = records, expected, frozen['synthetic']
                self.page = render_inheritance(frozen, build_view(frozen)).encode('utf-8')
                previous_hash = build_view(frozen)['validation']['content_sha256']

    def snapshot(self):
        return {'online': True, 'nonce': self.nonce, 'formats': FORMATS,
                'records': copy.deepcopy(self.records), 'revision': self.revision, 'synthetic': self.mode}

    def recognize(self, payload):
        if set(payload) != {'filename', 'data_base64'} or not all(isinstance(v, str) for v in payload.values()):
            raise ExtractError('UPLOAD_REQUEST_INVALID')
        filename = payload['filename']
        if len(filename) > 240 or not re.fullmatch(r'[^\x00-\x1f]+\.[A-Za-z0-9]+', filename):
            raise ExtractError('UPLOAD_NAME_INVALID')
        encoded = payload['data_base64']
        if len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
            raise ExtractError('FILE_SIZE_LIMIT')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ExtractError('UPLOAD_ENCODING_INVALID') from error
        extracted = extract_document(raw, filename.rsplit('.', 1)[-1], self.uploads)
        proposal = recognize_text(extracted['text'], extracted['source_sha256'], extracted['format_name'])
        return {**proposal, 'extractor': extracted['extractor'], 'source_sha256': extracted['source_sha256']}

    def preview(self, payload):
        if set(payload) != {'records', 'synthetic'} or type(payload['synthetic']) is not bool:
            raise ExtractError('PREVIEW_REQUEST_INVALID')
        result = prepare_import(payload['records'], synthetic=payload['synthetic'])
        public = {key: value for key, value in result.items() if key != 'bundle'}
        bundle = result.get('bundle')
        public['medicine_labels'] = {r['code']: r['label'] for r in bundle['vocabulary']['medicines']} if bundle else {}
        return public

    def commit(self, payload):
        if set(payload) != {'records', 'synthetic', 'confirmed', 'deidentified', 'revision'}:
            raise ExtractError('COMMIT_REQUEST_INVALID')
        if payload['confirmed'] is not True or payload['deidentified'] is not True:
            raise ExtractError('REVIEW_CONFIRMATION_REQUIRED')
        if type(payload['synthetic']) is not bool or type(payload['revision']) is not int:
            raise ExtractError('COMMIT_REQUEST_INVALID')
        if payload['revision'] != self.revision:
            raise ExtractError('REVISION_CONFLICT')
        if self.mode is not None and payload['synthetic'] != self.mode:
            raise ExtractError('COLLECTION_MODE_CONFLICT')
        result = prepare_import(payload['records'], synthetic=payload['synthetic'])
        if result['gate'] == 'BLOCK':
            return {key: value for key, value in result.items() if key != 'bundle'}
        bundle = result['bundle']
        revision = self.revision + 1
        bundle['revision'] = revision
        bundle['parent_sha256'] = build_view(read_frozen(self.state_dir / f'revision-{self.revision:04d}' / 'frozen'))['validation']['content_sha256'] if self.revision else None
        destination = self.state_dir / f'revision-{revision:04d}'
        if destination.exists():
            raise ExtractError('REVISION_PATH_CONFLICT')
        target = self.state_dir / ('pending-' + uuid.uuid4().hex)
        target.mkdir(exist_ok=False)
        with (target / 'records.json').open('xb') as file:
            file.write(_json_bytes(payload['records']))
        source = target / 'bundle-input.json'
        with source.open('xb') as file:
            file.write(_json_bytes(bundle))
        freeze_bundle(source, target / 'frozen')
        frozen = read_frozen(target / 'frozen')
        page = render_inheritance(frozen, build_view(frozen)).encode('utf-8')
        with (target / 'inheritance.html').open('xb') as file:
            file.write(page)
        receipt = {'revision': revision, 'source_count': len({r['source_sha256'] for r in payload['records']}),
                   'clinical_validation': False, 'synthetic': payload['synthetic'],
                   'records_sha256': hashlib.sha256(_json_bytes(payload['records'])).hexdigest()}
        with (target / 'receipt.json').open('xb') as file:
            file.write(_json_bytes(receipt))
        target.rename(destination)
        self.records = copy.deepcopy(payload['records'])
        self.revision, self.page, self.mode = revision, page, payload['synthetic']
        return {'gate': result['gate'], 'revision': revision, 'counts': result['counts'],
                'case_url': f'/imported.html?revision={revision}'}


def make_server(site: Path, state_dir: Path, port: int = 18961, *, resume: bool = False):
    """Return an owned server; callers control its lifetime and never stop peers."""
    workspace = LocalWorkspace(site, state_dir, resume)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *args):
            pass

        def _reply(self, code, value, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else _json_bytes(value)
            self.send_response(code)
            for key, val in {'Content-Type': content_type, 'Content-Length': str(len(body)),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'SAMEORIGIN'}.items():
                self.send_header(key, val)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _origin_ok(self):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == expected_host
                and self.headers.get('Origin', 'http://' + expected_host) == 'http://' + expected_host
                and self.headers.get('Sec-Fetch-Site', 'same-origin') in ('same-origin', 'none'))

        def do_GET(self):
            if not self._origin_ok():
                return self._reply(403, {'error': 'ORIGIN_REJECTED'})
            if not self.path.startswith('/') or self.path.startswith('//') or len(self.path) > 4096:
                return self._reply(400, {'error': 'REQUEST_TARGET_INVALID'})
            route = self.path.split('?', 1)[0]
            if route == '/api/state':
                with workspace.lock:
                    return self._reply(200, workspace.snapshot())
            if route == '/imported.html':
                with workspace.lock:
                    if workspace.page is None:
                        return self._reply(404, {'error': 'NO_COMMITTED_CASES'})
                    return self._reply(200, workspace.page, 'text/html; charset=utf-8')
            name = 'index.html' if route == '/' else route[1:]
            if name not in STATIC_NAMES:
                return self._reply(404, {'error': 'NOT_FOUND'})
            file = workspace.site / name
            if file.is_symlink() or not file.is_file() or file.resolve().parent != workspace.site:
                return self._reply(404, {'error': 'NOT_FOUND'})
            kind = 'text/html' if file.suffix == '.html' else 'application/json' if file.suffix == '.json' else 'text/plain'
            return self._reply(200, file.read_bytes(), kind + '; charset=utf-8')

        def do_POST(self):
            supplied_nonce = self.headers.get('X-MingYiRx-Nonce', '')
            if not self._origin_ok() or not re.fullmatch(r'[A-Za-z0-9_-]{43}', supplied_nonce) or not secrets.compare_digest(supplied_nonce, workspace.nonce):
                return self._reply(403, {'error': 'REQUEST_REJECTED'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Transfer-Encoding'):
                return self._reply(415, {'error': 'JSON_REQUIRED'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_REQUEST:
                    return self._reply(413, {'error': 'REQUEST_SIZE_LIMIT'})
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('INCOMPLETE_BODY')
                payload = _read_json(raw)
                if not isinstance(payload, dict):
                    raise ValueError('REQUEST_INVALID')
            except (ValueError, RecursionError, TimeoutError):
                return self._reply(400, {'error': 'JSON_INVALID'})
            routes = {'/api/recognize': workspace.recognize, '/api/preview': workspace.preview, '/api/commit': workspace.commit}
            if self.path not in routes:
                return self._reply(404, {'error': 'NOT_FOUND'})
            try:
                with workspace.lock:
                    result = routes[self.path](payload)
                return self._reply(200, result)
            except (ExtractError, InheritanceError) as error:
                code = str(error)
                return self._reply(400, {'error': code if re.fullmatch(r'[A-Z0-9_]+', code) else 'INPUT_REJECTED'})
            except Exception:
                return self._reply(400, {'error': 'OPERATION_FAILED'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.workspace = workspace
    return server
