"""Loopback-only reference application. Not a production web server."""

import argparse
import copy
import json
import re
import socket
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.core import ROOT, catalog_hash, check_binding, load_catalog, parse_json, public_catalog, search, validate_catalog
from app.review import review_packet, sanitized_receipt
from app.answer_audit import audit_answer, segment_answer
from app.library import public_inventory

STATIC = ROOT / "app" / "static"
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"), "/zh.json": ("zh.json", "application/json")}
MAX_BODY = 32768
MAX_REJECT_DRAIN = MAX_BODY * 2
REJECT_DRAIN_SECONDS = 0.25
POST_ROUTES = {"/api/search": search, "/api/check": check_binding, "/api/segment-answer": segment_answer, "/api/audit-answer": audit_answer}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(database):
    connection = sqlite3.connect(database, timeout=5)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(database, catalog):
    database.parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS snapshots (sha256 TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, operation TEXT NOT NULL, disposition TEXT NOT NULL, corpus_sha256 TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS receipts (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?)", (catalog_hash(catalog), timestamp(), json.dumps(catalog, ensure_ascii=True)))


def record(database, operation, disposition, corpus_digest, receipt):
    request_id = str(uuid.uuid4())
    with connect(database) as connection:
        connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", (request_id, timestamp(), operation, disposition, corpus_digest))
        connection.execute("INSERT INTO receipts VALUES (?, ?)", (request_id, json.dumps(receipt, ensure_ascii=True)))
    return request_id


def read_receipt(database, request_id):
    with connect(database) as connection:
        row = connection.execute("SELECT r.payload, e.created_at, s.payload FROM receipts r JOIN events e ON r.request_id=e.id JOIN snapshots s ON s.sha256=e.corpus_sha256 WHERE r.request_id=?", (request_id,)).fetchone()
    if not row:
        return None
    snapshot = public_catalog(json.loads(row[2]))
    return {**json.loads(row[0]), "request_id": request_id, "created_at": row[1], "catalog_snapshot": snapshot, "snapshot_sha256": catalog_hash(snapshot)}


def make_server(port=8765, database=None, catalog=None, extractor=None):
    catalog = copy.deepcopy(validate_catalog(catalog)) if catalog is not None else load_catalog()
    database = Path(database) if database else ROOT / "work" / "evidence.sqlite3"
    initialize(database, catalog)
    corpus_digest = catalog_hash(catalog)
    literature = public_inventory(extractor["catalog"]() if extractor else {}, public_catalog(catalog))

    class Handler(BaseHTTPRequestHandler):
        server_version = "EvidenceDesk/0.4"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            # URLs and questions must not enter request logs.
            return

        def reject(self, status, error):
            self.close_connection = True
            self.send_content(status, {"error": error})
            if self.command != "POST":
                return
            # An unread, late body can reset the socket and erase the rejection.
            # Send a FIN first, then discard bytes without parsing or persisting.
            try:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                deadline = time.monotonic() + REJECT_DRAIN_SECONDS
                remaining = MAX_REJECT_DRAIN
                while remaining:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        break
                    self.connection.settimeout(timeout)
                    data = self.rfile.read1(min(8192, remaining))
                    if not data:
                        break
                    remaining -= len(data)
            except OSError:
                # The response is already sent; canceled clients need no retry.
                pass

        def send_content(self, status, body, media="application/json", filename=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", media + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # A superseded browser query may cancel its response connection.
                return

        def trusted_request(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host_headers = self.headers.get_all("Host", [])
            if len(host_headers) != 1 or host_headers[0] not in hosts:
                self.reject(403, "untrusted_host")
                return False
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or (origins and origins[0] not in {"http://" + h for h in hosts}):
                self.reject(403, "untrusted_origin")
                return False
            return True

        def do_GET(self):
            if not self.trusted_request():
                return
            path = urlsplit(self.path).path
            if path in ASSETS:
                filename, media = ASSETS[path]
                self.send_content(200, (STATIC / filename).read_bytes(), media)
            elif path == "/api/status":
                public = public_catalog(catalog)
                self.send_content(200, {"version": "0.12.0", "corpus_sha256": corpus_digest, "source_count": len(public["sources"]), "claim_count": len(public["claims"]), "reviewed_count": sum(c["review"] == "approved" for c in public["claims"]), "network": "loopback_only", "model": "not_connected", "semantic_verification": "not_run", "clinical_release": False, "corpus_version": catalog["version"], "extractive_research": "enabled" if extractor else "unavailable", "literature_count": literature["counts"]["total"]})
            elif path == "/api/literature":
                self.send_content(200, literature)
            elif path == "/api/fulltext":
                self.send_content(200, extractor["catalog"]() if extractor else {"enabled": False, "answer_language": "zh-CN", "sources": [], "chunk_count": 0, "model": None, "index_sha256": None})
            elif path.startswith("/api/fulltext/page/") and extractor:
                try:
                    raw = extractor["page"](path[len("/api/fulltext/page/"):])
                    self.send_content(200, raw, "image/png") if raw else self.send_content(404, {"error": "not_found"})
                except (OSError, ValueError):
                    self.send_content(404, {"error": "not_found"})
            elif path.startswith("/api/fulltext/section/") and extractor and "section" in extractor:
                try:
                    raw = extractor["section"](path[len("/api/fulltext/section/"):])
                    self.send_content(200, raw, "text/html") if raw else self.send_content(404, {"error": "not_found"})
                except (OSError, ValueError):
                    self.send_content(404, {"error": "not_found"})
            elif path == "/api/catalog":
                self.send_content(200, {**public_catalog(catalog), "corpus_sha256": corpus_digest})
            elif path == "/api/review-packet":
                self.send_content(200, review_packet(catalog), filename=f"review-{corpus_digest[:12]}.json")
            elif re.fullmatch(r"/api/receipts/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path):
                request_id = path.rsplit("/", 1)[-1]
                try:
                    receipt = read_receipt(database, request_id)
                    self.send_content(200, receipt, filename=f"receipt-{request_id}.json") if receipt else self.send_content(404, {"error": "not_found"})
                except (sqlite3.Error, OSError, ValueError):
                    self.send_content(500, {"error": "local_service_error"})
            else:
                self.send_content(404, {"error": "not_found"})

        def do_POST(self):
            if not self.trusted_request():
                return
            if self.path not in POST_ROUTES and self.path != "/api/extract":
                self.reject(404, "not_found")
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.reject(415, "json_required")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                self.reject(400, "invalid_length")
                return
            try:
                size = int(lengths[0])
            except ValueError:
                self.reject(400, "invalid_length")
                return
            if size < 1 or size > MAX_BODY:
                self.reject(413, "body_too_large")
                return
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("incomplete_body")
                payload = parse_json(raw.decode("utf-8"))
                if self.path == "/api/extract":
                    if not extractor:
                        self.send_content(503, {"error": "fulltext_unavailable"})
                    else:
                        # Interactive text and raw model output never enter audit receipts.
                        try:
                            self.send_content(200, extractor["extract"](payload))
                        except ValueError as error:
                            stale = str(error) == "stale_fulltext_index"
                            self.send_content(409 if stale else 400, {"error": "stale_fulltext_index" if stale else "invalid_request"})
                    return
                result = POST_ROUTES[self.path](catalog, payload)
                if self.path == "/api/segment-answer":
                    self.send_content(200, result)
                    return
                operation = self.path.rsplit("/", 1)[-1]
                receipt = sanitized_receipt(catalog, operation, payload, result)
                result["request_id"] = record(database, operation, result["status"], corpus_digest, receipt)
                result["corpus_sha256"] = corpus_digest
                result["receipt_url"] = "/api/receipts/" + result["request_id"]
                self.send_content(200, result)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.send_content(400, {"error": "invalid_request"})
            except (sqlite3.Error, OSError):
                self.send_content(500, {"error": "local_service_error"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Start the local reference workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--extract-model", choices=("qwen3:4b", "qwen3:14b"), default="qwen3:14b")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    from app.extractive import make_extractor
    try:
        extractor = make_extractor(model=args.extract_model)
    except (OSError, ValueError):
        extractor = None
    server = make_server(args.port, extractor=extractor)
    print(f"Evidence Desk: http://127.0.0.1:{server.server_port}", flush=True)
    print("Local prototype. No clinical release. Extractive research: " + ("configured" if extractor else "unavailable"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
