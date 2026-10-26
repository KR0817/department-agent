"""Same-origin adapters protected by the clinical workbench session boundary."""
import hashlib
import json
import os
import pathlib
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix='/api/department')
_services = {}
_lock = threading.Lock()
_workspaces = {}


def source_root(name):
    value = os.environ.get('DEPARTMENT_' + name.upper() + '_ROOT', '')
    return pathlib.Path(value) if value else None


def configured(name):
    root = source_root(name)
    suffix = 'app/extractive.py' if name == 'knowledge' else 'src/mingyirx/case_import.py'
    return root is not None and (root / suffix).is_file()


def service(name):
    if not configured(name):
        raise HTTPException(503, 'Department module is not configured')
    with _lock:
        if name not in _services:
            if name == 'knowledge':
                from department_knowledge import Knowledge
                _services[name] = Knowledge(source_root(name))
            else:
                from department_analysis import Analysis
                _services[name] = Analysis(source_root(name))
        return _services[name]


async def payload(request, limit):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'JSON content type required')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, 'Department request exceeds limit')
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON number')
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON field')
                result[key] = value
            return result
        value = json.loads(data, parse_constant=invalid_constant, object_pairs_hook=unique_fields)
        if not isinstance(value, dict):
            raise ValueError('Object required')
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, 'Invalid department request') from None


async def invoke(name, method, *args):
    try:
        module = await run_in_threadpool(service, name)
        return await run_in_threadpool(getattr(module, method), *args)
    except HTTPException:
        raise
    except Exception as exc:
        # Domain errors deliberately expose bounded messages, never exception text.
        from department_knowledge import KnowledgeError
        from department_analysis import AnalysisError
        if isinstance(exc, (KnowledgeError, AnalysisError)):
            raise HTTPException(exc.status, exc.detail) from None
        raise HTTPException(503, 'Department module is unavailable; check local source configuration') from None


@router.get('/status')
def status():
    return {'version': '2.0.0', 'authentication': 'clinical_workbench_session',
            'knowledge': {'configured': configured('knowledge'), 'input_scope': 'public_literature_only'},
            'analysis': {'configured': configured('mingyirx'), 'persistence': 'reviewed_versioned_collection',
                         'full_workspace': bool(os.environ.get('DEPARTMENT_MINGYIRX_SITE')),
                         'review_required': True},
            'clinical_authority': 'existing_reviewed_workflow', 'automatic_prescribing': False}


@router.get('/knowledge/catalog')
async def knowledge_catalog():
    return await invoke('knowledge', 'catalog')


@router.get('/knowledge/library')
async def knowledge_library():
    return await invoke('knowledge', 'library')


@router.post('/knowledge/extract')
async def knowledge_extract(request: Request):
    return await invoke('knowledge', 'extract', await payload(request, 32768))


@router.get('/knowledge/page/{chunk_id}')
async def knowledge_page(chunk_id: str):
    content, media_type = await invoke('knowledge', 'page', chunk_id)
    return Response(content, media_type=media_type)


@router.get('/knowledge/section/{chunk_id}')
async def knowledge_section(chunk_id: str):
    content, media_type = await invoke('knowledge', 'section', chunk_id)
    return Response(content, media_type=media_type)


@router.get('/analysis/example')
async def analysis_example():
    return await invoke('mingyirx', 'example')


@router.post('/analysis/recognize')
async def analysis_recognize(request: Request):
    return await invoke('mingyirx', 'recognize', await payload(request, 262144))


@router.post('/analysis/preview')
async def analysis_preview(request: Request):
    return await invoke('mingyirx', 'preview', await payload(request, 262144))


def full_workspace(request):
    """Keep saved collections under the authenticated account, never a client actor."""
    from department_rx_workspace import FullError, FullWorkspace
    user = getattr(request.state, 'user', None)
    if not user or not isinstance(user.get('id'), str):
        raise FullError(401, 'AUTHENTICATION_REQUIRED')
    root = source_root('mingyirx')
    site = os.environ.get('DEPARTMENT_MINGYIRX_SITE', '')
    states = os.environ.get('DEPARTMENT_MINGYIRX_STATE_ROOT', '')
    if root is None or not site or not states:
        raise FullError(503, 'WORKSPACE_NOT_CONFIGURED')
    identity = hashlib.sha256(user['id'].encode('utf-8')).hexdigest()
    key = (str(root.resolve()), str(pathlib.Path(site).resolve()),
           str(pathlib.Path(states).resolve()), identity)
    with _lock:
        if key not in _workspaces:
            _workspaces[key] = FullWorkspace(root, pathlib.Path(site), pathlib.Path(states) / identity)
        return _workspaces[key]


def full_failure(exc):
    from department_rx_workspace import FullError
    if isinstance(exc, FullError):
        return JSONResponse({'error': exc.detail}, status_code=exc.status)
    if isinstance(exc, HTTPException):
        code = {413: 'REQUEST_TOO_LARGE', 415: 'JSON_REQUIRED', 422: 'INVALID_JSON'}.get(exc.status_code, 'INVALID_REQUEST')
        return JSONResponse({'error': code}, status_code=exc.status_code)
    return JSONResponse({'error': 'WORKSPACE_UNAVAILABLE'}, status_code=503)


@router.get('/mingyirx/status')
async def full_status(request: Request):
    try:
        workspace = await run_in_threadpool(full_workspace, request)
        result = await run_in_threadpool(workspace.status)
        result['collection_scope'] = 'local_single_operator' if request.state.user['id'] == 'demo' else 'authenticated_account'
        return result
    except Exception as exc:
        return full_failure(exc)


@router.get('/mingyirx/api/state')
async def full_state(request: Request):
    try:
        workspace = await run_in_threadpool(full_workspace, request)
        return await run_in_threadpool(workspace.snapshot)
    except Exception as exc:
        return full_failure(exc)


@router.post('/mingyirx/api/{operation}')
async def full_operation(request: Request, operation: str):
    try:
        if operation not in {'recognize', 'preview', 'commit'}:
            return JSONResponse({'error': 'NOT_FOUND'}, status_code=404)
        workspace = await run_in_threadpool(full_workspace, request)
        if not workspace.valid_nonce(request.headers.get('x-mingyirx-nonce', '')):
            return JSONResponse({'error': 'NONCE_REQUIRED'}, status_code=403)
        body = await payload(request, 12 * 1024 * 1024)
        return await run_in_threadpool(getattr(workspace, operation), body)
    except Exception as exc:
        return full_failure(exc)


async def full_asset(request, name, revision=None):
    try:
        workspace = await run_in_threadpool(full_workspace, request)
        body, media_type, csp = await run_in_threadpool(workspace.asset, name, revision)
        return Response(body, media_type=media_type, headers={
            'Content-Security-Policy': csp, 'X-Frame-Options': 'SAMEORIGIN',
            'Referrer-Policy': 'no-referrer'})
    except Exception as exc:
        return full_failure(exc)


@router.get('/mingyirx/imported.html')
async def full_imported(request: Request):
    return await full_asset(request, 'imported.html', request.query_params.get('revision'))


@router.get('/mingyirx/site/{name}')
async def full_static(request: Request, name: str):
    return await full_asset(request, name)
