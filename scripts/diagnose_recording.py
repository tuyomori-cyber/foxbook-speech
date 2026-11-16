#!/usr/bin/env python3
"""Record a short sample through the running foxbook-speech service.

This is an operator diagnostic, not a Firefox Native Messaging client.  It
exercises the same Unix-socket API and prints every service event as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time

EXTENSION_ID = "fox-voice-editor@foxbook.example"
MAX_RECORD_SECONDS = 30


def seconds(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("秒数は整数で指定してください。") from exc
    if not 1 <= result <= MAX_RECORD_SECONDS:
        raise argparse.ArgumentTypeError(f"秒数は1〜{MAX_RECORD_SECONDS}の範囲で指定してください。")
    return result


def default_socket() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "foxbook-speech" / "foxbook-speech.sock"


def send(stream, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    stream.flush()


def receive(stream) -> dict:
    line = stream.readline()
    if not line:
        raise ConnectionError("serviceとの接続が切れました。")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("serviceから不正な応答を受け取りました。")
    print(json.dumps(value, ensure_ascii=False))
    return value


def expect_success(stream) -> dict:
    event = receive(stream)
    if event.get("event") == "error":
        raise RuntimeError(f"{event.get('code')}: {event.get('message')}")
    return event


def connect(socket_path: Path, socket_factory=socket.socket, sleep=time.sleep, monotonic=time.monotonic) -> socket.socket:
    """Wait briefly for a just-restarted user service to create its socket."""
    deadline = monotonic() + 2
    while True:
        connection = socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(75)
        try:
            connection.connect(str(socket_path))
            return connection
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            if monotonic() >= deadline:
                raise
            sleep(0.05)


def diagnose(socket_path: Path, duration: int, engine: str) -> int:
    with connect(socket_path) as connection:
        with connection.makefile("rwb") as stream:
            send(stream, {"type": "open", "extensionId": EXTENSION_ID})
            opening = receive(stream)
            if opening != {"type": "opened", "version": 1}:
                raise RuntimeError("serviceに接続を許可されませんでした。")
            for request in (
                {"version": 1, "action": "prepare_microphone"},
                {"version": 1, "action": "prepare_engine", "engine": engine},
                {"version": 1, "action": "start_recording"},
            ):
                send(stream, request)
                event = expect_success(stream)
            recording_id = event.get("recordingId")
            if not isinstance(recording_id, str):
                raise RuntimeError("録音IDを受け取れませんでした。")
            print(f"録音中です。{duration}秒間、話してください。", file=sys.stderr)
            try:
                time.sleep(duration)
            except KeyboardInterrupt:
                send(stream, {"version": 1, "action": "cancel_recording", "recordingId": recording_id})
                receive(stream)
                return 130
            send(stream, {"version": 1, "action": "stop_recording", "recordingId": recording_id})
            while True:
                event = receive(stream)
                if event.get("event") == "result":
                    return 0
                if event.get("event") == "error":
                    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="foxbook-speechの実機録音診断")
    parser.add_argument("--seconds", type=seconds, default=5, help="録音秒数（1〜30、既定5）")
    parser.add_argument("--engine", choices=("whisper", "reazonspeech_k2"), default="whisper", help="認識engine（既定whisper）")
    parser.add_argument("--socket", type=Path, default=default_socket(), help="Unix socketのパス")
    args = parser.parse_args()
    try:
        return diagnose(args.socket, args.seconds, args.engine)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"診断に失敗しました: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
