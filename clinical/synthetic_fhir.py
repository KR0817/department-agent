"""Persistent, deliberately bounded synthetic FHIR double; not a FHIR server."""
import copy
from contextlib import contextmanager
import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
import urllib.parse
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

SYSTEM = 'https://example.invalid/sjd-agent'
KINDS = {'Patient', 'Encounter', 'Observation', 'Provenance', 'Basic', 'Task'}


def create_app(store_path=None):
    """Only an explicitly enabled, marked local synthetic store may be opened."""
    app = FastAPI(title='Synthetic FHIR double', docs_url=None, redoc_url=None)
    root = pathlib.Path(store_path or os.environ.get('SYNTHETIC_FHIR_DATA') or
                        os.environ.get('AGENT_DATA') or 'work/synthetic-fhir')
    lock = threading.RLock()

    @contextmanager
    def connect():
        if os.environ.get('AGENT_DEMO') != '1':
            raise HTTPException(503, 'AGENT_DEMO=1 is required for the synthetic double')
        root.mkdir(parents=True, exist_ok=True)
        marker = root / 'SYNTHETIC_ONLY'
        database = root / 'fhir.sqlite'
        if marker.exists():
            if marker.read_bytes() != b'simulated\n':
                raise HTTPException(409, 'Synthetic store marker mismatch')
        elif database.exists():
            raise HTTPException(409, 'Existing unmarked database cannot be opened')
        else:
            marker.write_bytes(b'simulated\n')
        connection = sqlite3.connect(database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE IF NOT EXISTS resources (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
        connection.execute('CREATE TABLE IF NOT EXISTS faults (id INTEGER PRIMARY KEY, mode TEXT, field_id TEXT, remaining INTEGER)')
        connection.commit()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @app.middleware('http')
    async def local_only(request, call_next):
        host = urllib.parse.urlsplit('http://' + request.headers.get('host', '')).hostname
        if host not in ('127.0.0.1', 'localhost', '::1'):
            return JSONResponse({'detail': 'Synthetic double requires a loopback Host'}, status_code=403)
        origin = request.headers.get('origin')
        if origin:
            parsed_origin = urllib.parse.urlsplit(origin)
            if parsed_origin.scheme != 'http' or parsed_origin.netloc != request.headers.get('host'):
                return JSONResponse({'detail': 'Cross-origin synthetic requests are denied'}, status_code=403)
        if request.headers.get('authorization'):
            return JSONResponse({'detail': 'Credentials are not accepted by the synthetic double'}, status_code=400)
        if os.environ.get('AGENT_DEMO') != '1':
            return JSONResponse({'detail': 'Synthetic double is disabled'}, status_code=503)
        return await call_next(request)

    def supported(kind):
        if kind not in KINDS:
            raise HTTPException(404, 'Unsupported synthetic resource type')

    def matches(resource, params):
        for key, value in params.items():
            if key.startswith('_') and key != '_id':
                continue
            if key == '_id' and resource.get('id') != value:
                return False
            if key == 'identifier':
                parts = value.split('|', 1)
                if len(parts) != 2 or not any(i.get('system') == parts[0] and i.get('value') == parts[1]
                                             for i in resource.get('identifier', [])):
                    return False
            if key in ('patient', 'subject'):
                subject = resource.get('for' if resource['resourceType'] == 'Task' else 'subject', {})
                if subject.get('reference') != value:
                    return False
            if key == 'encounter' and resource.get('encounter', {}).get('reference') != value:
                return False
            if key == 'status' and resource.get('status') != value:
                return False
            if key not in {'_id', 'identifier', 'patient', 'subject', 'encounter', 'status'} and not key.startswith('_'):
                raise HTTPException(400, 'Unsupported synthetic search parameter')
        return True

    def find(connection, kind, params):
        supported(kind)
        rows = [json.loads(row['body']) for row in connection.execute('SELECT body FROM resources WHERE kind=? ORDER BY id', (kind,))]
        rows = [row for row in rows if matches(row, params)]
        if params.get('_sort') == '-_lastUpdated':
            rows.sort(key=lambda row: row['meta']['lastUpdated'], reverse=True)
        return rows

    def read(connection, kind, resource_id):
        supported(kind)
        row = connection.execute('SELECT body FROM resources WHERE kind=? AND id=?', (kind, resource_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Synthetic resource not found')
        return json.loads(row['body'])

    def marked(resource):
        if isinstance(resource, dict):
            return any(marked(value) for value in resource.values())
        if isinstance(resource, list):
            return any(marked(value) for value in resource)
        return isinstance(resource, str) and resource.startswith(SYSTEM)

    def insert(connection, kind, resource, condition=None):
        supported(kind)
        if not isinstance(resource, dict) or resource.get('resourceType') != kind or not marked(resource):
            raise HTTPException(400, 'A marked synthetic resource is required')
        if condition:
            params = dict(urllib.parse.parse_qsl(condition))
            if set(params) != {'identifier'}:
                raise HTTPException(400, 'Only identifier conditional create is supported')
            found = find(connection, kind, params)
            if len(found) > 1:
                raise HTTPException(412, 'Conditional create matched multiple resources')
            if found:
                return found[0], 200
        result = copy.deepcopy(resource)
        result['id'] = str(uuid.uuid4())
        result['meta'] = {'versionId': '1', 'lastUpdated': dt.datetime.now(dt.timezone.utc).isoformat()}
        connection.execute('INSERT INTO resources(kind,id,body) VALUES(?,?,?)',
                           (kind, result['id'], json.dumps(result, sort_keys=True)))
        return result, 201

    def replace_refs(value, references):
        if isinstance(value, dict):
            return {key: references.get(item, item) if key == 'reference' and isinstance(item, str)
                    else replace_refs(item, references) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_refs(item, references) for item in value]
        return value

    @app.get('/auth/me')
    def context():
        with lock, connect() as connection:
            connection.execute('SELECT 1')
        return {'project': {'id': 'synthetic-local-only', 'features': ['transaction-bundles']},
                'data_origin': 'simulated', 'implementation': 'bounded-test-double'}

    @app.get('/__synthetic__/status')
    def status():
        with lock, connect() as connection:
            counts = {row['kind']: row['n'] for row in connection.execute('SELECT kind,COUNT(*) n FROM resources GROUP BY kind')}
        return {'data_origin': 'simulated', 'resource_counts': counts}

    @app.post('/__synthetic__/fault')
    async def inject_fault(request: Request):
        value = await request.json()
        if (not isinstance(value, dict) or value.get('mode') not in ('before_commit', 'after_commit') or
                not isinstance(value.get('field_id', '*'), str) or type(value.get('remaining', 1)) is not int or
                not 1 <= value.get('remaining', 1) <= 10):
            raise HTTPException(400, 'Invalid bounded synthetic fault')
        with lock, connect() as connection:
            connection.execute('INSERT INTO faults(mode,field_id,remaining) VALUES(?,?,?)',
                               (value['mode'], value.get('field_id', '*'), value.get('remaining', 1)))
        return {'data_origin': 'simulated', 'armed': True}

    @app.get('/fhir/R4/{kind}')
    def search(kind: str, request: Request):
        params = dict(request.query_params)
        try:
            count = min(200, max(1, int(params.get('_count', 50))))
            offset = max(0, int(params.get('_offset', 0)))
        except ValueError:
            raise HTTPException(400, 'Invalid pagination') from None
        with lock, connect() as connection:
            resources = find(connection, kind, params)
        result = {'resourceType': 'Bundle', 'type': 'searchset', 'total': len(resources),
                  'entry': [{'resource': resource} for resource in resources[offset:offset + count]]}
        if offset + count < len(resources):
            next_params = {**params, '_count': str(count), '_offset': str(offset + count)}
            result['link'] = [{'relation': 'next', 'url': '/fhir/R4/' + kind + '?' + urllib.parse.urlencode(next_params)}]
        return result

    @app.get('/fhir/R4/{kind}/{resource_id}')
    def get_resource(kind: str, resource_id: str):
        with lock, connect() as connection:
            return read(connection, kind, resource_id)

    @app.post('/fhir/R4/{kind}')
    async def create_resource(kind: str, request: Request):
        value = await request.json()
        with lock, connect() as connection:
            result, status_code = insert(connection, kind, value, request.headers.get('if-none-exist'))
        return JSONResponse(result, status_code=status_code)

    @app.put('/fhir/R4/Task/{resource_id}')
    async def update_task(resource_id: str, request: Request):
        value = await request.json()
        with lock, connect() as connection:
            current = read(connection, 'Task', resource_id)
            expected = 'W/"' + current['meta']['versionId'] + '"'
            if request.headers.get('if-match') != expected:
                raise HTTPException(412, 'Synthetic Task version conflict')
            if (value.get('resourceType') != 'Task' or value.get('id') != resource_id or
                    value.get('for') != current.get('for') or value.get('identifier') != current.get('identifier')):
                raise HTTPException(400, 'Task identity is immutable')
            result = copy.deepcopy(value)
            result['meta'] = {'versionId': str(int(current['meta']['versionId']) + 1),
                              'lastUpdated': dt.datetime.now(dt.timezone.utc).isoformat()}
            connection.execute('UPDATE resources SET body=? WHERE kind=? AND id=?',
                               (json.dumps(result, sort_keys=True), 'Task', resource_id))
        return result

    @app.post('/fhir/R4/')
    async def transaction(request: Request):
        bundle = await request.json()
        entries = bundle.get('entry', []) if isinstance(bundle, dict) else []
        if bundle.get('type') != 'transaction' or not 1 <= len(entries) <= 3:
            raise HTTPException(400, 'Only bounded synthetic transactions are supported')
        field_ids = {extension.get('valueString') for item in entries
                     if item.get('resource', {}).get('resourceType') == 'Observation'
                     for extension in item['resource'].get('extension', []) if extension.get('url') == SYSTEM + '/field-id'}
        with lock:
            with connect() as connection:
                fault = next((row for row in connection.execute('SELECT * FROM faults WHERE remaining>0 ORDER BY id')
                              if field_ids and (row['field_id'] == '*' or row['field_id'] in field_ids)), None)
                if fault:
                    connection.execute('UPDATE faults SET remaining=remaining-1 WHERE id=?', (fault['id'],))
            if fault and fault['mode'] == 'before_commit':
                return JSONResponse({'detail': 'Injected synthetic failure before commit'}, status_code=503)
            with connect() as connection:
                references, responses = {}, []
                for item in entries:
                    operation = item.get('request', {})
                    kind = operation.get('url')
                    if operation.get('method') != 'POST' or kind not in KINDS:
                        raise HTTPException(400, 'Unsupported transaction operation')
                    resource = replace_refs(item.get('resource'), references)
                    result, status_code = insert(connection, kind, resource, operation.get('ifNoneExist'))
                    reference = kind + '/' + result['id']
                    if item.get('fullUrl'):
                        references[item['fullUrl']] = reference
                    responses.append({'response': {'status': str(status_code), 'location': reference}, 'resource': result})
            if fault and fault['mode'] == 'after_commit':
                return JSONResponse({'detail': 'Injected synthetic response loss after commit'}, status_code=503)
        return {'resourceType': 'Bundle', 'type': 'transaction-response', 'entry': responses}

    return app


app = create_app()
