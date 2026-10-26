"""Allowlisted, offline recovery for the task-owned synthetic agent runtime."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import stat
import uuid


MARKER = b'simulated\n'
DATABASES = {'jobs.sqlite': {'jobs', 'audit', 'reviews', 'publications', 'followup_outbox', 'outbox_audit',
                             'patient_registry', 'job_patient_association', 'care_records'},
             'fhir.sqlite': {'resources', 'faults'}, 'demo-workflow.sqlite': {'care_records'}}
OPTIONAL_DATABASES = {'demo-workflow.sqlite'}
REQUIRED_TABLES = {'jobs.sqlite': {'jobs', 'audit'}, 'fhir.sqlite': {'resources'},
                   'demo-workflow.sqlite': {'care_records'}}
SIDECARS = {name + suffix for name in DATABASES for suffix in ('-wal', '-shm')}
FORMAT = 'synthetic-agent-recovery-v1'


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _regular(path, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or (not directory and info.st_nlink > 1) or
            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('Links and reparse points are not allowed')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('Unexpected filesystem entry type')


def _inventory(root, snapshot=False):
    """Check every entry by metadata before opening any runtime content."""
    _regular(root, directory=True)
    required = {'SYNTHETIC_ONLY', 'sources', *(set(DATABASES) - OPTIONAL_DATABASES)}
    allowed = required | OPTIONAL_DATABASES | ({'manifest.json'} if snapshot else SIDECARS)
    names = {item.name for item in root.iterdir()}
    if not required <= names or not names <= allowed:
        raise ValueError('Runtime must contain only the declared synthetic allowlist')
    if snapshot and 'manifest.json' not in names:
        raise ValueError('Snapshot manifest missing')
    files = []
    for item in root.iterdir():
        _regular(item, directory=item.name == 'sources')
        if item.name == 'sources':
            for source in item.iterdir():
                _regular(source)
                try:
                    valid = str(uuid.UUID(source.name)) == source.name
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError('Source filenames must be canonical UUIDs')
                files.append(source.relative_to(root).as_posix())
        elif item.name not in SIDECARS and item.name != 'manifest.json':
            files.append(item.name)
    if (root / 'SYNTHETIC_ONLY').read_bytes() != MARKER:
        raise ValueError('Explicit synthetic marker is invalid')
    return sorted(files)


def _connect(path):
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    return con


def _databases(root):
    return [name for name in DATABASES if (root / name).is_file()]


def _cell(value):
    return {'blob': base64.b64encode(value).decode('ascii')} if isinstance(value, bytes) else value


def database_summary(path):
    """Digest allowed table rows without exposing their values in reports."""
    con = _connect(path)
    try:
        schema = con.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        tables = {name for kind, name, _ in schema if kind == 'table'}
        if not REQUIRED_TABLES[path.name] <= tables <= DATABASES[path.name]:
            raise ValueError('Unexpected or missing database tables')
        if any(kind not in ('table', 'index') for kind, _, _ in schema):
            raise ValueError('Executable database objects are not allowed')
        if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        summary = {}
        for name in sorted(tables):
            rows = [json.dumps([_cell(value) for value in row], ensure_ascii=True,
                               separators=(',', ':'), allow_nan=False)
                    for row in con.execute('SELECT * FROM "' + name + '"')]
            digest = hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()
            summary[name] = {'rows': len(rows), 'sha256': digest}
        return {'schema_sha256': hashlib.sha256(json.dumps(schema, separators=(',', ':')).encode()).hexdigest(),
                'tables': summary}
    finally:
        con.close()


def _fresh_destination(source, destination):
    # Refuse nested destinations before creating a directory or touching a file.
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination must not exist')
    if not destination.parent.is_dir():
        raise ValueError('Destination parent must exist')
    _regular(destination.parent, directory=True)
    resolved = destination.resolve()
    if resolved == source or source in resolved.parents or resolved in source.parents:
        raise ValueError('Source and destination must be disjoint')


def _copy_new(source, target):
    with source.open('rb') as reader, target.open('xb') as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)


def backup(source, destination, *, writers_stopped=False):
    """Caller stops only its owned writers first; no live snapshot guarantee."""
    source, destination = pathlib.Path(source), pathlib.Path(destination)
    if writers_stopped is not True:
        raise ValueError('Confirm task-owned writers are stopped before backup')
    _fresh_destination(source, destination)
    files = _inventory(source)
    before = {name: database_summary(source / name) for name in _databases(source)}
    source_hashes = {name: sha256(source / name) for name in files if name not in DATABASES}
    destination.mkdir()
    (destination / 'sources').mkdir()
    for name in files:
        if name in DATABASES:
            with (destination / name).open('xb'):
                pass
            reader, writer = _connect(source / name), sqlite3.connect(destination / name)
            try:
                reader.backup(writer)
                # A portable snapshot must not depend on unbundled WAL sidecars.
                writer.execute('PRAGMA journal_mode=DELETE')
            finally:
                writer.close()
                reader.close()
        else:
            _copy_new(source / name, destination / name)
    after = {name: database_summary(destination / name) for name in _databases(destination)}
    if before != after or files != _inventory(source):
        raise ValueError('Source changed or database backup differs')
    if before != {name: database_summary(source / name) for name in _databases(source)}:
        raise ValueError('Source database changed during backup')
    for name, digest in source_hashes.items():
        if digest != sha256(source / name) or digest != sha256(destination / name):
            raise ValueError('Source file changed during backup')
    manifest = {'format': FORMAT, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'data_origin': 'simulated', 'writers_stopped': True,
                'writer_state': 'caller_asserted_offline', 'identity_restore': 'NOT_TESTED',
                'session_restore': 'EXCLUDED_REGENERATE', 'databases': after,
                'files': {name: {'sha256': sha256(destination / name),
                                 'bytes': (destination / name).stat().st_size} for name in files}}
    with (destination / 'manifest.json').open('x', encoding='utf-8') as writer:
        json.dump(manifest, writer, indent=2, sort_keys=True)
    validate_backup(destination)
    return manifest


def validate_backup(snapshot):
    snapshot = pathlib.Path(snapshot)
    files = _inventory(snapshot, snapshot=True)
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('format') != FORMAT or manifest.get('data_origin') != 'simulated' or
            manifest.get('identity_restore') != 'NOT_TESTED' or
            manifest.get('session_restore') != 'EXCLUDED_REGENERATE' or
            manifest.get('writers_stopped') is not True or
            sorted(manifest.get('files', {})) != files):
        raise ValueError('Invalid snapshot manifest')
    for name in files:
        actual = {'sha256': sha256(snapshot / name), 'bytes': (snapshot / name).stat().st_size}
        if actual != manifest['files'][name]:
            raise ValueError('Snapshot file hash or length mismatch')
    if manifest.get('databases') != {name: database_summary(snapshot / name) for name in _databases(snapshot)}:
        raise ValueError('Snapshot database digest mismatch')
    return manifest


def restore(snapshot, destination):
    """Validate before creating a fresh target. Never overwrite or remove data."""
    snapshot, destination = pathlib.Path(snapshot), pathlib.Path(destination)
    _fresh_destination(snapshot, destination)
    manifest = validate_backup(snapshot)
    destination.mkdir()
    (destination / 'sources').mkdir()
    for name in manifest['files']:
        _copy_new(snapshot / name, destination / name)
    if _inventory(destination) != sorted(manifest['files']):
        raise ValueError('Restored inventory differs')
    for name, expected in manifest['files'].items():
        if sha256(destination / name) != expected['sha256']:
            raise ValueError('Restored file digest differs')
    if {name: database_summary(destination / name) for name in _databases(destination)} != manifest['databases']:
        raise ValueError('Restored database digest differs')
    return {'format': FORMAT, 'data_origin': 'simulated', 'status': 'PASS',
            'snapshot_manifest_sha256': sha256(snapshot / 'manifest.json'),
            'identity_restore': 'NOT_TESTED', 'session_restore': 'EXCLUDED_REGENERATE',
            'databases': manifest['databases'], 'files': manifest['files']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('backup')
    create.add_argument('source', type=pathlib.Path)
    create.add_argument('destination', type=pathlib.Path)
    create.add_argument('--writers-stopped', action='store_true')
    check = commands.add_parser('validate')
    check.add_argument('snapshot', type=pathlib.Path)
    recover = commands.add_parser('restore')
    recover.add_argument('snapshot', type=pathlib.Path)
    recover.add_argument('destination', type=pathlib.Path)
    args = parser.parse_args()
    if args.command == 'backup':
        result = backup(args.source, args.destination, writers_stopped=args.writers_stopped)
    elif args.command == 'restore':
        result = restore(args.snapshot, args.destination)
    else:
        result = validate_backup(args.snapshot)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
