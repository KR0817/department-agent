"""Check the public Git candidate set without reading excluded private files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

MAX_FILE_BYTES = 2 * 1024 * 1024
ROOT_FILES = {
    'AGENTS.md', 'MEMORY.md', 'Tech-Spec.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'README.md', 'README.zh-CN.md', 'SECURITY.md', 'CONTRIBUTING.md', 'CHANGELOG.md',
    'CODE_OF_CONDUCT.md', 'pyproject.toml', 'uv.lock', 'requirements.lock',
    'requirements.txt', '.gitignore', '.gitattributes', '.dockerignore',
    '.python-version', '.editorconfig', 'Dockerfile', 'compose.yaml',
    'docker-compose.yml', 'Makefile', 'Start-Department-Agent.ps1',
}
ROOT_DIRS = {'clinical', 'knowledge', 'prescription', 'scripts', 'tests', 'docs',
             'licenses', '.github'}
EXCLUDED_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
                 '.mypy_cache', '.ruff_cache', '.uv-cache', 'work', 'outputs',
                 'evidence', 'runtime', 'runtime_data', 'restored_runs', 'private',
                 'clinical-private', 'original_exports', '04_raw_sources',
                 '05_runtime_snapshots', '06_environment', 'paper-intake'}
CLINICAL_FIXTURES = {
    'followup-demo-zh.csv', 'followup-demo.csv', 'lab.csv', 'longitudinal.txt',
    'patient-overview-clinical-demo.json', 'patient-overview-demo.json',
    'patient-overview-detail-demo.json', 'patient-overview-five-year-demo.json',
    'review-demo-zh.csv', 'review-demo.csv', 'risk-models-v1.json',
    'scan.pdf', 'scan.png', 'visit-1.txt', 'visit-2.txt', 'visit.docx',
}
TEXT_SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.html', '.md',
                 '.txt', '.json', '.toml', '.lock', '.yaml', '.yml', '.ini', '.cfg',
                 '.ps1', '.sh', '.bat', '.svg', '.csv', '.tsv', '.jsonl', '.ndjson',
                 '.xml', '.sql'}
DATA_SUFFIXES = {'.csv', '.tsv', '.jsonl', '.ndjson', '.xml', '.pdf', '.docx', '.xlsx', '.xls'}
DENIED_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.jks', '.keystore', '.gguf',
                   '.safetensors', '.pt', '.pth', '.onnx', '.bin', '.tar', '.zip',
                   '.7z', '.gz', '.exe', '.dll', '.pyc', '.pyo', '.log'}
PRIVATE_NAME = re.compile(
    r'(?i)^(?:\.env.*|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|'
    r'(?:credentials?|secrets?|tokens?|service-identity|accounts)(?:[-_.].*)?\.(?:json|txt|ya?ml))$'
)
DATABASE_NAME = re.compile(r'(?i)\.(?:sqlite3?|db3?)(?:[-.].*)?$')
PATTERNS = (
    ('private_key_material', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----')),
    ('github_token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')),
    ('provider_key', re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b')),
    ('cloud_access_key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('slack_token', re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b')),
    ('credential_url', re.compile(r'https?://[^\s/:@]+:[^\s/@]+@', re.I)),
    ('jwt_literal', re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b')),
    ('personal_machine_path', re.compile(
        r'(?i)(?:\bgla' r'h1\b|Baidu' r'Syncdisk|xwechat' r'_files|'
        r'[A-Z]:[\\/]+Users[\\/]+|[\\/]+Codex[\\/]+\d{4}-\d{2}-\d{2}[\\/]+|'
        r'[A-Z]:[\\/]+DepartmentAgent_(?:Backup|OpenSource))')),
)


def _git(root: Path, args: list[str], content: bytes | None = None) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], input=content,
                            capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('git_inventory_failed')
    return result.stdout


def _index(root: Path) -> dict[str, tuple[str, str, str]]:
    result = {}
    for item in _git(root, ['ls-files', '--stage', '-z']).split(b'\0'):
        if not item:
            continue
        header, path = item.split(b'\t', 1)
        mode, oid, stage = header.decode('ascii').split()
        name = path.decode('utf-8', 'surrogateescape')
        previous = result.get(name)
        if previous is not None:
            stage = 'unmerged'
        result[name] = (mode, oid, stage)
    return result


def _fixture_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (path.startswith('clinical/fixtures/') and len(parts) == 3 and parts[-1] in CLINICAL_FIXTURES
            or path.startswith(('prescription/data/synthetic/', 'knowledge/data/synthetic/'))
            or '/tests/fixtures/synthetic/' in '/' + path)


def path_rule(path: str) -> str | None:
    """Reject sensitive or unapproved paths before reading their size or contents."""
    pure = PurePosixPath(path)
    parts = pure.parts
    if not parts or pure.is_absolute() or '..' in parts or '\\' in path:
        return 'invalid_repository_path'
    if any(part.lower() in EXCLUDED_DIRS for part in parts[:-1]):
        return 'private_or_generated_directory'
    if PRIVATE_NAME.fullmatch(pure.name) or pure.suffix.lower() in {'.pem', '.key', '.pfx', '.p12', '.jks', '.keystore'}:
        return 'credential_filename'
    if DATABASE_NAME.search(pure.name):
        return 'runtime_database'
    if pure.suffix.lower() in DENIED_SUFFIXES:
        return 'runtime_binary_archive_or_log'
    if (len(parts) == 1 and path not in ROOT_FILES
            or len(parts) > 1 and parts[0] not in ROOT_DIRS):
        return 'unapproved_root'
    if parts[:2] == ('clinical', 'fixtures') and not _fixture_path(path):
        return 'unapproved_fixture'
    if parts[:2] == ('knowledge', 'data') and path not in {'knowledge/data/demo.json', 'knowledge/data/corpus.json'} and not _fixture_path(path):
        return 'unapproved_knowledge_data'
    if parts[:2] == ('prescription', 'data') and not _fixture_path(path):
        return 'unapproved_prescription_data'
    if pure.suffix.lower() in DATA_SUFFIXES and not _fixture_path(path):
        return 'unapproved_data_artifact'
    if pure.suffix.lower() == '.html' and not (
        path in {'clinical/static/index.html', 'knowledge/app/static/index.html',
                 'knowledge/app/report_template.html'}
        or path.startswith('prescription/third_party/')):
        return 'generated_html_not_source'
    suffix = pure.suffix.lower()
    binary_allowed = (suffix in {'.woff', '.woff2', '.ttf', '.otf'} and path.startswith('clinical/static/fonts/')
                      or _fixture_path(path) and suffix in {'.png', '.pdf', '.docx'}
                      or path.startswith('docs/images/synthetic-') and suffix in {'.png', '.jpg', '.jpeg', '.webp'})
    if not binary_allowed and suffix not in TEXT_SUFFIXES and pure.name not in ROOT_FILES and pure.name not in {'LICENSE', 'NOTICE', 'COPYING', 'RELAY-LICENSE'}:
        return 'unapproved_file_type'
    return None


def _is_text(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() not in {'.woff', '.woff2', '.ttf', '.otf', '.png', '.jpg', '.jpeg', '.webp', '.pdf', '.docx'}


def _text_findings(path: str, content: bytes) -> list[dict]:
    try:
        text = content.decode('utf-8-sig')
    except UnicodeError:
        return [{'path': path, 'line': None, 'rule': 'non_utf8_text'}]
    if '\0' in text:
        return [{'path': path, 'line': None, 'rule': 'binary_in_text_file'}]
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in PATTERNS:
            if pattern.search(line):
                findings.append({'path': path, 'line': number, 'rule': rule})
    if path in {'knowledge/data/demo.json', 'knowledge/data/corpus.json'}:
        try:
            data = json.loads(text)
            valid = isinstance(data, dict)
            if path.endswith('/demo.json'):
                valid = valid and data.get('schema') == 'synthetic-knowledge-demo-v1' and data.get('data_origin') == 'synthetic' and data.get('clinical_release') is False
            else:
                valid = valid and data.get('sources') == [] and data.get('claims') == []
        except (ValueError, TypeError):
            valid = False
        if not valid:
            findings.append({'path': path, 'line': None, 'rule': 'knowledge_seed_boundary'})
    return findings


def scan(root: Path, working_tree: bool = False) -> dict:
    """Scan index blobs by default; never read a path rejected by the filename gate."""
    root = root.resolve()
    index = _index(root)
    names = sorted(index)
    if working_tree:
        names = sorted({name.decode('utf-8', 'surrogateescape') for name in
                        _git(root, ['ls-files', '--cached', '--others', '--exclude-standard', '-z']).split(b'\0') if name})
        names = [name for name in names if name in index or not any(
            part.lower() in EXCLUDED_DIRS for part in PurePosixPath(name).parts[:-1])]
    findings = []
    if not names:
        findings.append({'path': None, 'line': None, 'rule': 'empty_candidate_set'})
    candidates = []
    for name in names:
        rule = path_rule(name)
        if rule:
            findings.append({'path': name, 'line': None, 'rule': rule})
            continue
        if working_tree:
            path = root / name
            ancestors = [path, *path.parents]
            ancestors = ancestors[:ancestors.index(root)]
            if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in ancestors):
                findings.append({'path': name, 'line': None, 'rule': 'symlink_or_junction'})
                continue
            if not path.is_file():
                findings.append({'path': name, 'line': None, 'rule': 'missing_working_file'})
                continue
            size = path.stat().st_size
        else:
            mode, oid, stage = index[name]
            if stage != '0' or mode not in {'100644', '100755'}:
                findings.append({'path': name, 'line': None, 'rule': 'unmerged_or_nonregular_index_entry'})
                continue
            size = int(_git(root, ['cat-file', '-s', oid]).strip())
        if size > MAX_FILE_BYTES:
            findings.append({'path': name, 'line': None, 'rule': 'oversized_file'})
            continue
        if _is_text(name):
            candidates.append(name)
    if working_tree:
        for name in candidates:
            findings.extend(_text_findings(name, (root / name).read_bytes()))
    elif candidates:
        content = ('\n'.join(index[name][1] for name in candidates) + '\n').encode('ascii')
        batch = _git(root, ['cat-file', '--batch'], content)
        offset = 0
        for name in candidates:
            end = batch.index(b'\n', offset)
            oid, kind, size_raw = batch[offset:end].split()
            size = int(size_raw)
            if kind != b'blob' or oid.decode('ascii') != index[name][1]:
                raise RuntimeError('git_blob_mismatch')
            offset = end + 1
            body = batch[offset:offset + size]
            if len(body) != size or batch[offset + size:offset + size + 1] != b'\n':
                raise RuntimeError('git_blob_truncated')
            findings.extend(_text_findings(name, body))
            offset += size + 1
    return {'passed': not findings, 'mode': 'working_tree' if working_tree else 'index',
            'files_checked': len(names), 'text_files_checked': len(candidates),
            'findings': findings,
            'limitations': 'Filename and text checks do not prove absence of PHI or establish redistribution rights; binary fixture contents require separate provenance review.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-tree', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        report = scan(args.root, args.working_tree)
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({'passed': False, 'error': 'release_inventory_failed'}))
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
