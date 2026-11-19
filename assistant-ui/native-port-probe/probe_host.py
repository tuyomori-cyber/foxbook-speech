#!/usr/bin/env python3
"""A one-shot delayed Native Messaging event; no microphone or network."""
import json
import os
import select
import struct
import sys
import time

EXTENSION_ID = "foxbook-native-port-probe@foxbook.example"
MAX_BYTES = 4096


def send(message):
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)) + encoded)
    sys.stdout.buffer.flush()


def main():
    if len(sys.argv) != 3 or sys.argv[2] != EXTENSION_ID:
        return 2
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        return 2
    size = struct.unpack("=I", header)[0]
    if size > MAX_BYTES:
        return 2
    payload = sys.stdin.buffer.read(size)
    if len(payload) != size:
        return 2
    request = json.loads(payload)
    if request not in ({"version": 1, "action": "start"},
                       {"version": 1, "action": "start", "durationSeconds": 90},
                       {"version": 1, "action": "start", "durationSeconds": 300}):
        return 2
    duration = request.get("durationSeconds", 90)
    pid = os.getpid()
    send({"version": 1, "event": "ready", "pid": pid})
    deadline = time.monotonic() + duration
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([sys.stdin.buffer], [], [], remaining)
        if readable:
            # Any input or disconnect ends this intentionally single-use probe.
            return 0
        if time.monotonic() >= deadline:
            send({"version": 1, "event": "delayed", "pid": pid, "durationSeconds": duration})
            select.select([sys.stdin.buffer], [], [])
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrokenPipeError, OSError, ValueError, json.JSONDecodeError):
        raise SystemExit(1)
