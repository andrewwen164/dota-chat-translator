"""Local-only stage-1 diagnostic. No chat schema or live provenance is assumed."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import shutil
import socket
import threading

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1024 * 1024
MAX_NODES = 20000
CONFIG_NAME = "gamestate_integration_personal_chat_diagnostic.cfg"
# Observed in local integration configs or contemporary first-person reports.
# No undocumented 'chat' data flag is invented here.
DATA_COMPONENTS = ("provider", "map", "player", "hero", "abilities", "items",
                   "events", "buildings", "league", "draft", "wearables",
                   "minimap", "roshan", "couriers", "neutralitems")


def walk(value, path="$", depth=0):
    if depth > 32:
        raise ValueError("payload nesting exceeds limit")
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            # Wildcards avoid persisting names, IDs, or text used as object keys.
            yield from walk(item, path + ".*", depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, path + "[]", depth + 1)


def decode_payload(body):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON keys")
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError("nonfinite JSON number")
    if not body or len(body) > MAX_BODY:
        raise ValueError("invalid body length")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        for count, _ in enumerate(walk(value), 1):
            if count > MAX_NODES:
                raise ValueError("too many payload nodes")
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    return value


class Evidence:
    def __init__(self, team_marker="", all_marker=""):
        self.lock = threading.Lock()
        self.markers = {"team": team_marker, "all": all_marker}
        self.requests = 0
        self.duplicates = 0
        self.previous = None
        self.hits = Counter()
        self.shapes = Counter()
        self.components = Counter()
        self.latest = None
        self.string_count = 0

    def record(self, payload):
        # Auth is excluded from inspection, hashing, and all reports.
        safe = {k: v for k, v in payload.items() if k.casefold() != "auth"}
        digest = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).digest()
        shapes = Counter()
        hits = set()
        strings = 0
        for path, value in walk(safe):
            shapes[f"{path}:{type(value).__name__}"] += 1
            if isinstance(value, str):
                strings += 1
                for channel, marker in self.markers.items():
                    if marker and marker in value:
                        hits.add(channel)
        with self.lock:
            self.requests += 1
            self.duplicates += int(digest == self.previous)
            self.previous = digest
            self.hits.update(hits)
            self.shapes.update(shapes)
            self.components.update(k for k in DATA_COMPONENTS if k in safe)
            self.string_count = strings
            self.latest = datetime.now(timezone.utc).isoformat()

    def report(self):
        with self.lock:
            return {
                "stage": 1,
                "provenance": "HTTP sender not independently verified; no live integration claim",
                "accepted_requests": self.requests,
                "consecutive_duplicate_payloads": self.duplicates,
                "last_received_utc": self.latest,
                "strings_in_latest_payload": self.string_count,
                "requests_with_known_components": dict(self.components),
                "configured_markers": {k: bool(v) for k, v in self.markers.items()},
                "requests_containing_marker": dict(self.hits),
                "observed_shapes_keys_redacted": dict(self.shapes),
                "interpretation": "Marker hits are candidates; confirm against your actual in-game sends. "
                                  "No hits is inconclusive without receiving game state during both tests.",
            }


def make_server(token, evidence, port=3009):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log request lines, arbitrary HTTP data, or payload text.

        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def reply(self, code, body=b""):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, b'{"status":"listening","live_chat":"unverified"}')
            else:
                self.reply(404)

        def do_POST(self):
            if self.path != "/gsi":
                self.reply(404)
                return
            if self.headers.get("Transfer-Encoding"):
                self.reply(400)
                return
            lengths = self.headers.get_all("Content-Length", [])
            try:
                if len(lengths) != 1:
                    raise ValueError()
                length = int(lengths[0])
                if length < 1 or length > MAX_BODY:
                    self.reply(413)
                    return
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError()
                payload = decode_payload(body)
            except (ValueError, OSError, socket.timeout):
                self.reply(400)
                return
            auth = payload.get("auth")
            supplied = auth.get("token") if isinstance(auth, dict) else None
            if not isinstance(supplied, str) or not hmac.compare_digest(
                    supplied.encode(), token.encode()):
                self.reply(403)
                return
            evidence.record(payload)
            self.reply(200, b"{}")

    class LocalServer(HTTPServer):
        # A bounded, serial receiver avoids unbounded request threads.
        allow_reuse_address = False
        request_queue_size = 8

        def handle_error(self, request, client_address):
            pass  # HTTP disconnects must not dump chat-bearing tracebacks.

    return LocalServer(("127.0.0.1", port), Handler)


def configuration(token, port):
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    fields = "\n".join(f'        "{name}" "1"' for name in DATA_COMPONENTS)
    return (f'"Personal chat diagnostic"\n{{\n    "uri" "http://127.0.0.1:{port}/gsi"\n'
            '    "timeout" "5.0"\n    "buffer" "0.1"\n    "throttle" "0.5"\n'
            f'    "heartbeat" "10.0"\n    "auth" {{ "token" "{token}" }}\n'
            f'    "data"\n    {{\n{fields}\n    }}\n}}\n')


def install_config(source, dota_dir):
    dota_dir = Path(dota_dir).resolve(strict=True)
    # A full installation root is required to reduce accidental writes elsewhere.
    cfg_dir = dota_dir / "game" / "dota" / "cfg"
    if not cfg_dir.is_dir():
        raise ValueError("expected Dota installation containing game/dota/cfg")
    destination = cfg_dir / "gamestate_integration" / CONFIG_NAME
    destination.parent.mkdir(exist_ok=True)
    backup = None
    if destination.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = destination.with_name(destination.name + "." + stamp + ".bak")
        shutil.copy2(destination, backup)  # Must succeed before replacement.
    temporary = destination.with_name(destination.name + ".tmp-" + secrets.token_hex(6))
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3009)
    parser.add_argument("--team-marker", default="")
    parser.add_argument("--all-marker", default="")
    parser.add_argument("--prepare", action="store_true", help="generate local config and token, then exit")
    parser.add_argument("--install", type=Path, metavar="DOTA_ROOT", help="install prepared config, backing up this app's previous config")
    args = parser.parse_args()
    if args.team_marker and args.team_marker == args.all_marker:
        parser.error("use different markers for team and all chat")
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    token_path = local / "receiver-token.txt"
    cfg_path = local / CONFIG_NAME
    if args.prepare:
        if not token_path.exists():
            token_path.write_text(secrets.token_hex(32), encoding="utf-8")
        token = token_path.read_text(encoding="utf-8").strip()
        cfg_path.write_text(configuration(token, args.port), encoding="utf-8")
        print("Prepared ignored local config. No game files were changed.")
        return
    if not token_path.exists() or not cfg_path.exists():
        parser.error("run --prepare first")
    if args.install:
        destination, backup = install_config(cfg_path, args.install)
        print(f"Installed: {destination}\nBackup: {backup or 'not needed; new file'}")
        return
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        parser.error("empty receiver token; remove local config and run --prepare")
    evidence = Evidence(args.team_marker, args.all_marker)
    server = make_server(token, evidence, args.port)
    print(f"Listening only on http://127.0.0.1:{args.port}/gsi")
    print("LIVE CHAT UNVERIFIED. No chat text, auth tokens, or player IDs are logged.")
    print("Send distinct test markers in real team/all chat. Ctrl+C saves a metadata-only report.")
    def status():
        while not stopped.wait(5):
            r = evidence.report()
            print(f"received={r['accepted_requests']} duplicates={r['consecutive_duplicate_payloads']} "
                  f"marker_hits={r['requests_containing_marker']}", flush=True)
    stopped = threading.Event()
    reporter = threading.Thread(target=status, daemon=True)
    reporter.start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        report_path = local / "evidence-report.json"
        report_path.write_text(json.dumps(evidence.report(), indent=2), encoding="utf-8")
        print(f"Saved metadata report: {report_path}")


if __name__ == "__main__":
    main()
