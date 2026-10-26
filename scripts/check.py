"""Run portable module tests in separate import namespaces."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/start.py'), '--prepare-only'], cwd=ROOT, check=True)
    suites = [('clinical', ROOT / 'clinical', ROOT / 'clinical'),
              ('knowledge', ROOT / 'knowledge', ROOT / 'knowledge/tests'),
              ('prescription', ROOT / 'prescription', ROOT / 'prescription/tests'),
              ('release', ROOT, ROOT / 'tests')]
    for name, directory, tests in suites:
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
               'DEPARTMENT_KNOWLEDGE_MODE': 'synthetic-demo'}
        env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'prescription/src'), str(directory)])
        print(json.dumps({'suite': name, 'status': 'running'}), flush=True)
        subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(tests),
                        '-p', 'test_*.py'], cwd=directory, env=env, check=True)
    print(json.dumps({'passed': True, 'suites': [name for name, _, _ in suites],
                      'clinical_accuracy_evaluated': False}))


if __name__ == '__main__':
    main()
