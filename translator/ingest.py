"""User-mapped GSI input. No assumed chat, identity or channel fields."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import queue
import threading
import time

from diagnostic import make_server
from translator.core import Message, valid_text


def select(value, path):
    values = [value]
    for part in path:
        found = []
        for current in values:
            if part == "*":
                if isinstance(current, list):
                    found.extend(current)
                elif isinstance(current, dict):
                    found.extend(v for k, v in current.items() if k.casefold() != "auth")
            elif isinstance(current, dict) and part != "auth" and part in current:
                found.append(current[part])
            elif isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
                found.append(current[part])
        values = found[:512]
    return values


def scalar(record, path):
    if not path:
        return ""
    found = select(record, path)
    if len(found) != 1 or not isinstance(found[0], (str, int)) or isinstance(found[0], bool):
        return ""
    return str(found[0])[:200]


def checked_path(value):
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("Paths must be JSON arrays of at most 32 keys/indexes")
    if not all((isinstance(x, str) and 0 < len(x) <= 128 and x.casefold() != "auth")
               or (type(x) is int and 0 <= x < 512) for x in value):
        raise ValueError("Invalid path token")
    return value


@dataclass
class Mapping:
    enabled: bool = False
    records: list = field(default_factory=list)
    text: list = field(default_factory=list)
    event_id: list = field(default_factory=list)
    sender: list = field(default_factory=list)
    hero: list = field(default_factory=list)
    channel: list = field(default_factory=list)
    chatwheel: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Mapping must be an object")
        result = cls()
        for key in asdict(result):
            if key == "enabled":
                result.enabled = value.get(key) is True
            else:
                setattr(result, key, checked_path(value.get(key, [])))
        return result

    def extract(self, payload):
        if not self.enabled or not self.text:
            return []
        result = []
        for record in select(payload, self.records):
            texts = select(record, self.text)
            if len(texts) != 1 or not valid_text(texts[0]):
                continue
            wheel = select(record, self.chatwheel) if self.chatwheel else []
            result.append(Message(
                text=texts[0], event_id=scalar(record, self.event_id),
                sender=scalar(record, self.sender), hero=scalar(record, self.hero),
                channel=scalar(record, self.channel),
                chatwheel=len(wheel) == 1 and wheel[0] is True, origin="gsi"))
            if len(result) >= 128:
                break
        return result


def discover_strings(value, path=(), depth=0):
    """Local UI preview only; never log/save raw snapshots or candidate values."""
    if depth > 32:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() != "auth":
                yield from discover_strings(item, path + (key,), depth + 1)
    elif isinstance(value, list):
        for item in value[:128]:
            yield from discover_strings(item, path + ("*",), depth + 1)
    elif valid_text(value):
        yield list(path), value


class Receiver:
    def __init__(self, token, port=3009):
        self.snapshots = queue.Queue(maxsize=2)
        self.requests, self.last_received, self.error = 0, 0, ""
        self.server = make_server(token, self, port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="gsi-receiver")

    def record(self, payload):
        self.requests += 1
        self.last_received = time.monotonic()
        # Do not retain the receiver's auth credential in snapshots shown in UI.
        safe = {k: v for k, v in payload.items() if k.casefold() != "auth"}
        try:
            self.snapshots.put_nowait(safe)
        except queue.Full:
            try:
                self.snapshots.get_nowait()
            except queue.Empty:
                pass
            try:
                self.snapshots.put_nowait(safe)
            except queue.Full:
                pass

    def start(self):
        self.thread.start()

    def latest(self):
        latest = None
        while True:
            try:
                latest = self.snapshots.get_nowait()
            except queue.Empty:
                return latest

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
