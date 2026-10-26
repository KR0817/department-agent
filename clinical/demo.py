"""Start only this task's synthetic services; never manage shared processes."""
import argparse
import importlib.metadata
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent


def available(port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise OSError('Port already has a listener: ' + str(port))
    with socket.socket() as listener:
        # Allow the closed listener's TIME_WAIT while still rejecting an active one.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', port))


def start(data, logs, agent_port=13012, fhir_port=18113):
    """Return owned process handles; a caller may stop only these handles."""
    available(agent_port)
    available(fhir_port)
    data = pathlib.Path(data).resolve()
    logs = pathlib.Path(logs).resolve()
    if not data.exists():
        data.mkdir(parents=True)
        (data / 'SYNTHETIC_ONLY').write_bytes(b'simulated\n')
    if (data / 'SYNTHETIC_ONLY').read_bytes() != b'simulated\n':
        raise ValueError('Only explicitly marked synthetic data may be started')
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(AGENT_DEMO='1', AGENT_DATA=str(data), AGENT_PORT=str(agent_port),
               SYNTHETIC_FHIR_DATA=str(data), FHIR_URL=f'http://127.0.0.1:{fhir_port}',
               PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    processes = []
    try:
        for module, port in [('synthetic_fhir:app', fhir_port), ('server:app', agent_port)]:
            log = (logs / (module.split(':')[0] + '-' + uuid.uuid4().hex[:8] + '.log')).open('x', encoding='utf-8')
            try:
                proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', module, '--host', '127.0.0.1',
                    '--port', str(port), '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            finally:
                log.close()
            processes.append(proc)
            deadline = time.monotonic() + 25
            url = f'http://127.0.0.1:{port}' + ('/auth/me' if module.startswith('synthetic') else '/')
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError('Synthetic service exited; inspect its task-owned log')
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.15)
            else:
                raise RuntimeError('Synthetic service startup timed out')
        return processes
    except BaseException:
        # Startup may be interrupted before the caller receives process handles.
        stop(processes)
        raise


def stop(processes):
    for proc in reversed(processes):
        if proc.poll() is None:
            if os.name == 'nt':
                # The Windows venv launcher owns a child interpreter process.
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], check=True,
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.terminate()
            proc.wait(timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=pathlib.Path, required=True)
    parser.add_argument('--logs', type=pathlib.Path, required=True)
    parser.add_argument('--agent-port', type=int, default=13012)
    parser.add_argument('--fhir-port', type=int, default=18113)
    args = parser.parse_args()
    processes = start(args.data, args.logs, args.agent_port, args.fhir_port)
    receipt = {'data_origin': 'simulated', 'agent_url': f'http://127.0.0.1:{args.agent_port}',
               'fhir_url': f'http://127.0.0.1:{args.fhir_port}', 'owned_pids': [p.pid for p in processes],
               'data': str(args.data.resolve()), 'python': sys.version,
               'packages': {name: importlib.metadata.version(name) for name in
                            ('fastapi', 'uvicorn', 'httpx', 'pypdf', 'pillow', 'python-multipart')}}
    path = args.logs / ('processes-' + uuid.uuid4().hex[:8] + '.json')
    path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'running': True, 'url': receipt['agent_url'], 'process_record': str(path)}), flush=True)
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop(processes)


if __name__ == '__main__':
    main()
