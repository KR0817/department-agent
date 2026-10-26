"""Authenticated host adapter for the complete, authoritative MingYiRx workspace."""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import importlib
import json
from pathlib import Path
import re
import secrets

from department_sources import load_package


PREFIX = '/api/department/mingyirx'
ENTRY_URL = PREFIX + '/site/index.html'
MAX_REQUEST = 12 * 1024 * 1024
_MARKER = '.department-workspace.json'
_CONTROLLER = b'<script id="clinical-workspace-controller">'


class FullError(ValueError):
    """An input-independent code that the authenticated router may expose."""

    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


def _scoped_index(raw: bytes) -> bytes:
    """Change only transport and loopback host seams; embedded JSON stays exact."""
    if raw.count(_CONTROLLER) != 1:
        raise FullError(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED')
    start = raw.index(_CONTROLLER) + len(_CONTROLLER)
    end = raw.find(b'</script>', start)
    if end < 0:
        raise FullError(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED')
    body = raw[start:end]
    prefix = PREFIX.encode('ascii')
    replacements = (
        (b"location.hostname==='127.0.0.1'",
         b"['127.0.0.1','localhost'].includes(location.hostname)", 1),
        (b'fetch(route,', b"fetch('" + prefix + b"'+route,", 1),
        (b".setAttribute('src',committedUrl)",
         b".setAttribute('src','" + prefix + b"'+committedUrl)", 2),
        (b".getAttribute('src')!==committedUrl",
         b".getAttribute('src')!=='" + prefix + b"'+committedUrl", 1),
    )
    if body.count(b'fetch(') != 1 or prefix in body:
        raise FullError(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED')
    for before, after, count in replacements:
        if body.count(before) != count:
            raise FullError(503, 'WORKSPACE_CONTROLLER_UNSUPPORTED')
        body = body.replace(before, after)
    return raw[:start] + body + raw[end:]


class _InlineScripts(HTMLParser):
    """Hash parsed executable text, excluding data blocks and external scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.executable = False
        self.body = []
        self.hashes = set()

    def handle_starttag(self, tag, attrs):
        if tag != 'script':
            return
        if self.active:
            raise FullError(503, 'WORKSPACE_SCRIPT_UNSUPPORTED')
        attributes = dict(attrs)
        kind = (attributes.get('type') or '').strip().lower()
        self.active = True
        self.executable = 'src' not in attributes and kind in (
            '', 'module', 'text/javascript', 'application/javascript',
            'text/ecmascript', 'application/ecmascript',
        )
        self.body = []

    def handle_data(self, data):
        if self.active and self.executable:
            self.body.append(data)

    def handle_endtag(self, tag):
        if tag != 'script' or not self.active:
            return
        if self.executable:
            # HTML normalizes CRLF/CR before computing an inline-script CSP hash.
            script = ''.join(self.body).replace('\r\n', '\n').replace('\r', '\n')
            digest = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode('ascii')
            self.hashes.add("'sha256-" + digest + "'")
        self.active = False
        self.body = []


def _content_security_policy(raw: bytes, html: bool) -> str:
    hashes = []
    if html:
        parser = _InlineScripts()
        try:
            parser.feed(raw.decode('utf-8'))
            parser.close()
        except (UnicodeError, ValueError):
            raise FullError(503, 'WORKSPACE_HTML_INVALID') from None
        if parser.active:
            raise FullError(503, 'WORKSPACE_SCRIPT_UNSUPPORTED')
        hashes = sorted(parser.hashes)
    scripts = ' '.join(["'self'", *hashes])
    return ("default-src 'none'; script-src " + scripts +
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self'; connect-src 'self'; frame-src 'self'; "
            "frame-ancestors 'self'; base-uri 'none'; form-action 'none'; object-src 'none'")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


class FullWorkspace:
    """Keep original business methods and persistence behind a per-user host session."""

    def __init__(self, root, site, state_dir):
        try:
            self.root = Path(root).resolve(strict=True)
            site_path = Path(site).absolute()
            if any(_is_link(path) for path in (site_path, *site_path.parents)):
                raise FullError(503, 'WORKSPACE_SITE_INVALID')
            self.site = site_path.resolve(strict=True)
            if not self.site.is_dir() or not self.site.is_relative_to(self.root):
                raise FullError(503, 'WORKSPACE_SITE_INVALID')
            load_package('department_mingyirx', self.root / 'src' / 'mingyirx')
            self._server = importlib.import_module('department_mingyirx.clinical_server')
            self.static_names = self._server.STATIC_NAMES
            self.max_request = self._server.MAX_REQUEST
            # Verify the supported shell before creating or resuming any collection.
            self.asset('index.html')
            state = Path(state_dir).absolute()
            if any(_is_link(path) for path in (state, *state.parents)):
                raise FullError(503, 'WORKSPACE_STATE_INVALID')
            resolved = state.resolve()
            private_root = self.root / 'work'
            if resolved == private_root or not resolved.is_relative_to(private_root):
                raise FullError(503, 'WORKSPACE_STATE_INVALID')
            binding = hashlib.sha256((str(self.root) + '\n' + str(self.site)).encode('utf-8')).hexdigest()
            marker = json.dumps({'schema': 'department-mingyirx-workspace-v1',
                                 'source_binding': binding}, sort_keys=True).encode('ascii')
            marker_path = state / _MARKER
            resume = state.exists()
            if resume:
                if (not state.is_dir() or _is_link(marker_path) or not marker_path.is_file()
                        or marker_path.stat().st_size != len(marker)
                        or marker_path.read_bytes() != marker):
                    raise FullError(503, 'WORKSPACE_STATE_NOT_OWNED')
            self._workspace = self._server.LocalWorkspace(self.site, state, resume=resume)
            if not resume:
                with marker_path.open('xb') as stream:
                    stream.write(marker)
        except FullError:
            raise
        except Exception:
            raise FullError(503, 'WORKSPACE_UNAVAILABLE') from None

    def status(self):
        """Expose capability and collection counts without records, nonce or paths."""
        with self._workspace.lock:
            return {'available': True, 'entry_url': ENTRY_URL,
                    'revision': self._workspace.revision,
                    'record_count': len(self._workspace.records),
                    'synthetic': self._workspace.mode,
                    'formats': list(self._server.FORMATS),
                    'max_upload_bytes': self._server.MAX_BYTES,
                    'max_request_bytes': self.max_request,
                    'static_assets': sorted(name for name in self.static_names
                                            if (self.site / name).is_file())}

    def snapshot(self):
        """Return the complete original snapshot only to the authenticated caller."""
        with self._workspace.lock:
            return self._workspace.snapshot()

    def valid_nonce(self, value):
        return (isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', value) is not None
                and secrets.compare_digest(value, self._workspace.nonce))

    def _call(self, method, payload):
        if not isinstance(payload, dict):
            raise FullError(400, 'REQUEST_INVALID')
        try:
            size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                  separators=(',', ':')).encode('utf-8'))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise FullError(400, 'JSON_INVALID') from None
        if size > self.max_request:
            raise FullError(413, 'REQUEST_SIZE_LIMIT')
        try:
            with self._workspace.lock:
                return getattr(self._workspace, method)(payload)
        except (self._server.ExtractError, self._server.InheritanceError) as error:
            code = str(error)
            safe = code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', code) else 'INPUT_REJECTED'
            status = 409 if safe in ('REVISION_CONFLICT', 'COLLECTION_MODE_CONFLICT', 'REVISION_PATH_CONFLICT') else 400
            raise FullError(status, safe) from None
        except Exception:
            raise FullError(400, 'OPERATION_FAILED') from None

    def recognize(self, payload):
        return self._call('recognize', payload)

    def preview(self, payload):
        return self._call('preview', payload)

    def commit(self, payload):
        return self._call('commit', payload)

    def asset(self, name, revision=None):
        """Serve only original named assets or the current user's committed view."""
        if name == 'imported.html':
            with self._workspace.lock:
                if self._workspace.page is None:
                    raise FullError(404, 'NO_COMMITTED_CASES')
                if revision is not None and (isinstance(revision, bool)
                        or not re.fullmatch(r'[1-9][0-9]{0,8}', str(revision))
                        or int(revision) != self._workspace.revision):
                    raise FullError(404, 'REVISION_NOT_FOUND')
                raw = self._workspace.page
        else:
            if not isinstance(name, str) or name not in self.static_names:
                raise FullError(404, 'NOT_FOUND')
            path = self.site / name
            try:
                if _is_link(path) or not path.is_file() or path.resolve().parent != self.site:
                    raise FullError(404, 'NOT_FOUND')
                raw = path.read_bytes()
            except OSError:
                raise FullError(404, 'NOT_FOUND') from None
            if name == 'index.html':
                raw = _scoped_index(raw)
        html = name.endswith('.html')
        media = ('text/html' if html else 'application/json' if name.endswith('.json')
                 else 'text/csv' if name.endswith('.csv') else 'text/plain')
        return raw, media + '; charset=utf-8', _content_security_policy(raw, html)
