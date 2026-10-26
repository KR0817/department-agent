"""Run the integrated synthetic workbench using only this checkout."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CLINICAL = ROOT / 'clinical'
PRESCRIPTION = ROOT / 'prescription'


@contextmanager
def run_lock(path: Path):
    """Hold an OS-owned lock so two launchers cannot share one writable run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def prepare_site():
    """Build only invented examples, retaining source-bound production renderers."""
    from build_prescription_demo import build
    site = PRESCRIPTION / 'work/demo-site'
    if not site.exists():
        site = build(site)
    ledger = json.loads((site / 'source-ledger.json').read_text(encoding='utf-8'))
    if ledger.get('synthetic') is not True:
        raise ValueError('The public demo requires explicitly synthetic prescription assets')
    sys.path.insert(0, str(PRESCRIPTION / 'src'))
    from mingyirx.clinical_server import STATIC_NAMES
    if any(not (site / name).is_file() for name in STATIC_NAMES):
        raise ValueError('Synthetic prescription site is incomplete; use a fresh demo output')
    return site


def environment(site: Path, name: str, knowledge_root: Path, mode: str):
    return {'DEPARTMENT_KNOWLEDGE_ROOT': str(knowledge_root),
            'DEPARTMENT_KNOWLEDGE_MODE': mode,
            'DEPARTMENT_MINGYIRX_ROOT': str(PRESCRIPTION),
            'DEPARTMENT_MINGYIRX_SITE': str(site),
            'DEPARTMENT_MINGYIRX_STATE_ROOT': str(PRESCRIPTION / 'work/collections' / name),
            'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18894)
    parser.add_argument('--fhir-port', type=int, default=18895)
    parser.add_argument('--run-name', default='default')
    parser.add_argument('--knowledge-mode', choices=['synthetic-demo', 'fulltext'], default='synthetic-demo')
    parser.add_argument('--knowledge-root', type=Path, default=ROOT / 'knowledge')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_name):
        parser.error('Use a short alphanumeric run name, with hyphens or underscores')
    if args.port == args.fhir_port or not all(1024 <= value <= 65535 for value in (args.port, args.fhir_port)):
        parser.error('Choose two distinct unprivileged ports')
    # The original private-output guard requires a checkout and its ignore rules.
    probe = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, check=True)
    if Path(probe.stdout.strip()).resolve() != ROOT:
        raise ValueError('Run from an independent Git clone of this project')
    with run_lock(ROOT / 'work/prepare.lock'):
        site = prepare_site()
    if args.prepare_only:
        print(json.dumps({'prepared': True, 'data_origin': 'synthetic', 'site': str(site.relative_to(ROOT))}))
        return
    run = ROOT / 'work/runs' / args.run_name
    with run_lock(run / 'instance.lock'):
        os.environ.update(environment(site, args.run_name, args.knowledge_root.resolve(), args.knowledge_mode))
        sys.path.insert(0, str(CLINICAL))
        import demo
        processes = demo.start(run / 'data', run / 'logs', args.port, args.fhir_port)
        receipt = {'data_origin': 'synthetic', 'knowledge_mode': args.knowledge_mode,
                   'url': f'http://127.0.0.1:{args.port}/', 'fhir_port': args.fhir_port,
                   'owned_pids': [p.pid for p in processes], 'python': sys.executable,
                   'clinical_root': str(CLINICAL), 'site': str(site), 'run': str(run)}
        try:
            (run / 'launch.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print(json.dumps({'running': True, 'url': receipt['url'], 'run_name': args.run_name,
                              'data_origin': 'synthetic', 'knowledge_mode': args.knowledge_mode}), flush=True)
            while all(p.poll() is None for p in processes):
                time.sleep(0.3)
            raise RuntimeError('A demo service stopped unexpectedly; inspect the run-owned logs')
        except KeyboardInterrupt:
            pass
        finally:
            demo.stop(processes)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': type(exc).__name__,
              'message': 'Startup failed. Check Git, ports, synthetic assets and run-owned logs.'}), file=sys.stderr)
        raise SystemExit(1) from None
