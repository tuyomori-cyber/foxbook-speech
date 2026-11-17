#!/usr/bin/env python3
"""Firefox Native Messaging adapter for the shared foxbook-speech service."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import socket
import struct
import sys

MAX_MESSAGE_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = frozenset(("fox-voice-editor@foxbook.example", "the-session-tools@example.invalid"))


def service_socket_path() -> Path:
    configured = os.environ.get("FOXBOOK_SPEECH_SOCKET")
    if configured:
        return Path(configured)
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime_dir / "foxbook-speech" / "foxbook-speech.sock"


def read_native(stream) -> dict | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("incomplete native message header")
    size = struct.unpack("=I", header)[0]
    if size > MAX_MESSAGE_BYTES:
        raise ValueError("native message is too large")
    payload = stream.read(size)
    if len(payload) != size:
        raise ValueError("incomplete native message")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("native message must be an object")
    return value


def write_native(stream, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("native response is too large")
    stream.write(struct.pack("=I", len(payload)) + payload)
    stream.flush()


def send_line(connection: socket.socket, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("service request is too large")
    connection.sendall(payload + b"\n")


def relay(extension_id: str, socket_path: Path, native_input, native_output) -> int:
    if extension_id not in ALLOWED_EXTENSIONS:
        return 2
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        send_line(connection, {"type": "open", "extensionId": extension_id})
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = connection.recv(65536)
            if not chunk:
                return 1
            buffer.extend(chunk)
        opening, _, rest = buffer.partition(b"\n")
        buffer = bytearray(rest)
        reply = json.loads(opening)
        if reply != {"type": "opened", "version": 1}:
            return 2
        with selectors.DefaultSelector() as selector:
            selector.register(native_input, selectors.EVENT_READ, "native")
            selector.register(connection, selectors.EVENT_READ, "service")
            while True:
                for key, _mask in selector.select():
                    if key.data == "native":
                        request = read_native(native_input)
                        if request is None:
                            return 0
                        send_line(connection, request)
                    else:
                        chunk = connection.recv(65536)
                        if not chunk:
                            write_native(native_output, {"version": 1, "event": "error", "recordingId": None,
                                                         "code": "SERVICE_UNAVAILABLE", "message": "音声serviceとの接続が切れました。"})
                            return 1
                        buffer.extend(chunk)
                        if len(buffer) > MAX_MESSAGE_BYTES:
                            return 1
                        while b"\n" in buffer:
                            line, _, rest = buffer.partition(b"\n")
                            buffer = bytearray(rest)
                            event = json.loads(line)
                            if not isinstance(event, dict) or event.get("version") != 1 or not isinstance(event.get("event"), str):
                                return 1
                            write_native(native_output, event)


def main(argv: list[str]) -> int:
    # Firefox invokes a native host with the manifest path and initiating add-on ID.
    if len(argv) != 3 or not argv[1] or argv[2] not in ALLOWED_EXTENSIONS:
        return 2
    try:
        return relay(argv[2], service_socket_path(), sys.stdin.buffer, sys.stdout.buffer)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
