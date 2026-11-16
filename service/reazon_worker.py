#!/usr/bin/env python3
"""Persistent ReazonSpeech K2 worker; NDJSON on stdin/stdout."""
from __future__ import annotations

from array import array
import json
from pathlib import Path
import sys
import time
import wave


def send(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def samples(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getcomptype() != "NONE" or audio.getframerate() != 16000 or audio.getnframes() > 480_000:
            raise ValueError("16 kHz・16-bit mono PCM・30秒以内のWAVが必要です。")
        values = array("h")
        values.frombytes(audio.readframes(audio.getnframes()))
    if sys.byteorder != "little":
        values.byteswap()
    return 16000, [sample / 32768.0 for sample in values]


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    root = Path(sys.argv[1])
    try:
        import sherpa_onnx
        started = time.monotonic_ns()
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(root / "encoder-epoch-99-avg-1.int8.onnx"), decoder=str(root / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(root / "joiner-epoch-99-avg-1.int8.onnx"), tokens=str(root / "tokens.txt"), num_threads=2)
        send({"event": "ready", "initializationMs": round((time.monotonic_ns() - started) / 1_000_000)})
    except Exception as exc:
        send({"event": "error", "code": "MODEL_PREPARATION_FAILED", "message": str(exc)})
        return 1
    for line in sys.stdin:
        request: object = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"action", "requestId", "wavPath"} or request["action"] != "recognize" or not isinstance(request["requestId"], str) or not isinstance(request["wavPath"], str):
                raise ValueError("要求形式が正しくありません。")
            rate, audio = samples(Path(request["wavPath"]))
            started = time.monotonic_ns()
            stream = recognizer.create_stream()
            stream.accept_waveform(rate, audio)
            recognizer.decode_stream(stream)
            send({"event": "result", "requestId": request["requestId"], "text": stream.result.text.strip(),
                  "recognitionMs": round((time.monotonic_ns() - started) / 1_000_000)})
        except Exception as exc:
            request_id = request.get("requestId") if isinstance(request, dict) else None
            send({"event": "error", "requestId": request_id, "code": "RECOGNITION_FAILED", "message": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
