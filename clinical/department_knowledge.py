"""Reuse the source-bound evidence service behind the workbench boundary."""
import importlib
import os
import pathlib
import re
import threading
import copy
import time
import uuid
from datetime import datetime, timezone

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
        self._consultation_index = None
        # ponytail: one inference at a time across modes; use a bounded job queue
        # if concurrent departmental use outgrows this local workbench.
        self._model_lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._jobs = {}

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
        from department_llm import provider_catalog
        from expert_graph import VERSION
        return {**_map_locators(self._ready()['catalog']()),
                'collaboration': {'enabled': self._mode == 'fulltext', 'provider': 'local',
                                  'providers': ['local', 'kimi'], 'modes': ['local', 'local_kimi', 'all_kimi'], 'workflow': VERSION},
                'consultation': {'enabled': self._mode == 'fulltext',
                                 'providers': provider_catalog(self._mode == 'fulltext'),
                                 'input_scope': 'public_topics_only'}}

    def library(self):
        self._ready()
        return _map_locators(self._library)

    def extract(self, payload):
        extractor = self._ready()
        if not self._model_lock.acquire(blocking=False):
            return {'status': 'busy', 'model_called': False, 'extracts': [], 'clinical_approval': None}
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
        finally:
            self._model_lock.release()

    def consult(self, payload):
        from department_consultation import consult, validate_input
        from department_llm import ModelError
        try:
            value = validate_input(payload, self.catalog())
        except ValueError as error:
            stale = str(error) == 'stale_fulltext_index'
            raise KnowledgeError(409 if stale else 400,
                                 'stale_fulltext_index' if stale else 'invalid_request') from None
        base = {'kind': value.kind, 'subject': value.subject, 'provider': value.provider,
                'model_called': False, 'sections': [], 'references': [], 'clinical_approval': None}
        if self._mode != 'fulltext':
            return {**base, 'status': 'model_disabled'}
        if not self._model_lock.acquire(blocking=False):
            return {**base, 'status': 'busy'}
        try:
            if self._consultation_index is None:
                self._consultation_index = importlib.import_module('app.fulltext').load_combined_index()
            if self._consultation_index['sha256'] != value.index_sha256:
                raise KnowledgeError(409, 'stale_fulltext_index')
            return consult(value, self._consultation_index)
        except ModelError as exc:
            return {**base, 'status': 'model_unavailable', 'error': exc.code}
        except (OSError, ValueError, KeyError, TypeError):
            raise KnowledgeError(503, 'fulltext_unavailable') from None
        finally:
            self._model_lock.release()

    def _prune_jobs(self):
        # ponytail: bounded ephemeral jobs; durable queues belong to a later multi-user deployment.
        finished = sorted(((key, row) for key, row in self._jobs.items() if row['finished'] is not None),
                          key=lambda item: item[1]['finished'])
        for number, (key, row) in enumerate(finished):
            if time.monotonic() - row['finished'] > 1800 or number < len(finished) - 16:
                del self._jobs[key]

    def _job(self, identity, owner):
        self._prune_jobs()
        row = self._jobs.get(identity)
        if row is None or row['owner'] != owner:
            raise KnowledgeError(404, 'collaboration_not_found')
        return row

    def collaboration(self, identity, owner):
        with self._jobs_lock:
            return copy.deepcopy(self._job(identity, owner)['public'])

    def cancel_collaboration(self, identity, owner):
        with self._jobs_lock:
            row = self._job(identity, owner)
            if row['finished'] is None:
                row['cancel'].set()
                row['public']['status'] = 'cancel_requested'
            return copy.deepcopy(row['public'])

    def collaborate(self, payload, owner):
        from department_consultation import validate_input
        from expert_graph import ExpertInput, ROLES, VERSION, collaborate, guard
        from department_llm import ModelError, model_configuration
        try:
            value = validate_input(payload, self.catalog(), input_type=ExpertInput)
            if value.provider not in ('local', 'kimi'):
                raise ValueError('unsupported_expert_provider')
            if value.expert_mode == 'all_kimi' and value.provider != 'kimi':
                raise ValueError('unsupported_expert_provider')
        except ValueError as exc:
            stale = str(exc) == 'stale_fulltext_index'
            raise KnowledgeError(409 if stale else 400, 'stale_fulltext_index' if stale else 'invalid_request') from None
        base = {'kind': value.kind, 'subject': value.subject, 'provider': value.provider, 'model_called': False,
                'clinical_approval': None, 'workflow': VERSION}
        if self._mode != 'fulltext':
            return {**base, 'status': 'model_disabled'}
        blocked = 'public_topic_required' if value.provider == 'kimi' and not value.public_topic_confirmed else guard(value)
        if value.expert_mode == 'all_kimi' and not value.public_evidence_confirmed:
            blocked = 'public_evidence_required'
        if blocked:
            return {**base, 'status': blocked}
        if value.provider == 'kimi':
            try:
                remote = model_configuration('kimi')
                if not remote['configured']:
                    raise ModelError('api_key_missing')
                if value.expert_mode == 'all_kimi' and remote['model'] != 'kimi-k3.1-pro':
                    raise ModelError('kimi31_required')
            except ModelError as exc:
                return {**base, 'status': 'model_unavailable', 'error': exc.code}
        if not self._model_lock.acquire(blocking=False):
            return {**base, 'status': 'busy'}
        try:
            if self._consultation_index is None:
                self._consultation_index = importlib.import_module('app.fulltext').load_combined_index()
            if self._consultation_index['sha256'] != value.index_sha256:
                raise KnowledgeError(409, 'stale_fulltext_index')
            identity = uuid.uuid4().hex
            row = {'owner': owner, 'cancel': threading.Event(), 'finished': None,
                   'public': {'job_id': identity, 'status': 'running', 'stage': 'queued',
                              'created_at': datetime.now(timezone.utc).isoformat(),
                              'roles': {role: 'pending' for role in ROLES}, 'result': None}}
            with self._jobs_lock:
                self._prune_jobs()
                self._jobs[identity] = row
                initial = copy.deepcopy(row['public'])

            def progress(patch):
                with self._jobs_lock:
                    row['public'].update(copy.deepcopy(patch))

            def work():
                try:
                    result = collaborate(value, self._consultation_index, progress=progress, cancelled=row['cancel'].is_set)
                except Exception:
                    # Never put exception text, prompts, source text or model output into job errors/logs.
                    result = {**base, 'status': 'failed', 'error': 'collaboration_unavailable'}
                finally:
                    self._model_lock.release()
                with self._jobs_lock:
                    if row['cancel'].is_set():
                        result = {**base, 'status': 'cancelled'}
                    row['finished'] = time.monotonic()
                    row['public'].update(status=result['status'], stage='finished', result=result)
                    for role, status in row['public']['roles'].items():
                        if status in ('pending', 'running'):
                            row['public']['roles'][role] = 'skipped'
                    self._prune_jobs()
            threading.Thread(target=work, name='knowledge-collaboration', daemon=True).start()
            return initial
        except BaseException:
            self._model_lock.release()
            raise

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
