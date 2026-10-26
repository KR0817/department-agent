"""Serve the local workspace; every launch requires a fresh private state path."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mingyirx.clinical_server import make_server

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18961)
    parser.add_argument('--resume', action='store_true', help='Verify and resume an existing private session')
    args = parser.parse_args()
    server = make_server(args.site, args.state_dir, args.port, resume=args.resume)
    print(f'Local workspace: http://127.0.0.1:{server.server_port}/', flush=True)
    print('Press Ctrl+C to stop this owned server. Private revisions remain in work/.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
