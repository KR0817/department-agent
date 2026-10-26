"""Reuse the source-bound evidence service behind the workbench boundary."""
import importlib
import os
import pathlib
import re
import threading

from department_sources import load_package


class KnowledgeError(Exception):
    """Expose only stable HTTP errors, never paths or supplied question text."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _map_locators(value):
    """Change route metadata without editing quotations or source identifiers."""
    if isinstance(value, list):
        return [_map_locators(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        match = (re.fullmatch(r'/api/fulltext/(page|section)/(ft_[a-f0-9]{24})', item)
                 if key in ('page_url', 'locator_url') and isinstance(item, str) else None)
        result[key] = ('/api/department/knowledge/' + match.group(1) + '/' + match.group(2)
                       if match else _map_locators(item))
    return result


class Knowledge:
    """A lazy adapter; the existing extractor owns evidence and model policy."""

    def __init__(self, root, mode=None):
        self._root = pathlib.Path(root)
        self._mode = mode if mode is not None else os.environ.get('DEPARTMENT_KNOWLEDGE_MODE', 'synthetic-demo')
        if self._mode not in ('synthetic-demo', 'fulltext'):
            raise ValueError('Invalid knowledge mode')
        self._lock = threading.Lock()
        self._extractor = None
        self._library = None

    def _ready(self):
        with self._lock:
            if self._extractor is not None:
                return self._extractor
            try:
                # Original modules use absolute app.* imports. Reserve that exact
                # package only when its source root matches; never replace Relay.
                load_package('app', self._root / 'app')
                if self._mode == 'synthetic-demo':
                    module = importlib.import_module('app.demo')
                    extractor = module.make_demo_extractor()
                    inventory = extractor['library']()
                else:
                    module = importlib.import_module('app.extractive')
                    core = importlib.import_module('app.core')
                    library = importlib.import_module('app.library')
                    extractor = module.make_extractor()
                    inventory = library.public_inventory(extractor['catalog'](),
                                                         core.public_catalog(core.load_catalog()))
            except (ImportError, OSError, ValueError, AttributeError, KeyError, TypeError):
                raise KnowledgeError(503, 'fulltext_unavailable') from None
            self._library = inventory
            self._extractor = extractor
            return extractor

    def catalog(self):
        return _map_locators(self._ready()['catalog']())

    def library(self):
        self._ready()
        return _map_locators(self._library)

    def extract(self, payload):
        extractor = self._ready()
        try:
            return _map_locators(extractor['extract'](payload))
        except ValueError as error:
            stale = str(error) == 'stale_fulltext_index'
            raise KnowledgeError(409 if stale else 400,
                                 'stale_fulltext_index' if stale else 'invalid_request') from None
        except (TypeError, KeyError, UnicodeError, RecursionError):
            raise KnowledgeError(400, 'invalid_request') from None
        except OSError:
            raise KnowledgeError(503, 'fulltext_unavailable') from None

    def _document(self, kind, chunk_id):
        if not isinstance(chunk_id, str) or not re.fullmatch(r'ft_[a-f0-9]{24}', chunk_id):
            raise KnowledgeError(404, 'not_found')
        extractor = self._ready()
        try:
            raw = extractor[kind](chunk_id)
        except (OSError, ValueError, KeyError):
            raise KnowledgeError(404, 'not_found') from None
        if not isinstance(raw, bytes) or not raw:
            raise KnowledgeError(404, 'not_found')
        return raw, 'image/png' if kind == 'page' else 'text/html'

    def page(self, chunk_id):
        return self._document('page', chunk_id)

    def section(self, chunk_id):
        raw, media = self._document('section', chunk_id)
        # Adapt only the trusted renderer's wrappers for the host's strict CSP.
        raw = raw.replace(b'<pre style="white-space:pre-wrap">',
                          b'<pre class="department-source-text">', 1)
        stylesheet = b'<link rel="stylesheet" href="/static/department-source.css">'
        return raw.replace(b'<body>', stylesheet + b'<body>', 1), media
