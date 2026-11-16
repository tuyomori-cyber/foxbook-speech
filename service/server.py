#!/usr/bin/env python3
"""Newline-delimited JSON Unix socket transport for foxbook-speech.

The Native Messaging adapter is the only intended client.  The adapter opens one
socket per Firefox connection and sends its already-validated extension ID in the
opening envelope.  The session identifier remains inside ``SpeechState``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Final

from service.state import SpeechState
from service.whisper_pipeline import PipelineError, WhisperConfig, WhisperJob, WhisperPipeline
from service.reazon import ReazonError, ReazonManager

MAX_MESSAGE_BYTES: Final = 1024 * 1024
DEFAULT_ALLOWED = {
    "fox-voice-editor@foxbook.example": frozenset(("whisper", "reazonspeech_k2")),
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WHISPER = WhisperConfig(Path("/usr/bin/arecord"), Path("/usr/bin/ffmpeg"),
                                PROJECT_ROOT.parent / "whisper.cpp/build/bin/whisper-cli",
                                PROJECT_ROOT.parent / "whisper.cpp/models/ggml-base.bin")
DEFAULT_REAZON = ReazonManager(PROJECT_ROOT.parent / "reazonspeech/.venv/bin/python",
                               PROJECT_ROOT / "service/reazon_worker.py", PROJECT_ROOT.parent / "reazonspeech")


class SpeechSocketServer:
    def __init__(self, state: SpeechState, whisper: WhisperPipeline | None = None, reazon: ReazonManager | None = None) -> None:
        self.state = state
        self.whisper = whisper or WhisperPipeline(DEFAULT_WHISPER)
        self.jobs: dict[str, WhisperJob] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.reazon = reazon or DEFAULT_REAZON

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session_id: str | None = None
        try:
            opening = await self._read(reader)
            if not isinstance(opening, dict) or set(opening) != {"type", "extensionId"} or opening["type"] != "open" or not isinstance(opening["extensionId"], str):
                await self._write(writer, {"type": "rejected", "code": "INVALID_OPEN"})
                return
            try:
                session_id = self.state.connect(opening["extensionId"])
            except PermissionError:
                await self._write(writer, {"type": "rejected", "code": "UNAUTHORIZED_EXTENSION"})
                return
            await self._write(writer, {"type": "opened", "version": 1})
            lock = asyncio.Lock()
            async def emit(events: list[dict]) -> None:
                async with lock:
                    for event in events:
                        await self._write(writer, event)
            while True:
                request = await self._read(reader)
                if isinstance(request, dict) and request == {"version": 1, "action": "prepare_engine", "engine": "reazonspeech_k2"}:
                    try:
                        generation, initialization_ms = await self.reazon.prepare()
                        events = self.state.prepare_engine(session_id, "reazonspeech_k2", initialization_ms, generation)
                    except ReazonError as exc:
                        events = [self.state._error(None, exc.code, exc.message)]
                    except OSError as exc:
                        events = [self.state._error(None, "ENGINE_START_FAILED", str(exc))]
                else:
                    events = self.state.handle(session_id, request)
                await emit(events)
                if isinstance(request, dict) and request.get("action") == "start_recording" and events and events[0].get("event") == "started":
                    try:
                        self.jobs[session_id] = await self.whisper.start()
                    except (OSError, RuntimeError, FileNotFoundError) as exc:
                        await emit(self.state.fail(session_id, "RECORDING_FAILED", str(exc)))
                elif isinstance(request, dict) and request.get("action") == "stop_recording" and events and events[0].get("event") == "stopping":
                    job = self.jobs.get(session_id)
                    if job:
                        self.tasks[session_id] = asyncio.create_task(self._finish(session_id, job, events[0]["recordingId"], self.state.lease.engine if self.state.lease else "whisper", emit))
                elif isinstance(request, dict) and request.get("action") == "cancel_recording":
                    await self._cancel(session_id)
        except (EOFError, ConnectionError, BrokenPipeError):
            pass
        except (ValueError, UnicodeError, json.JSONDecodeError):
            await self._write(writer, {"type": "rejected", "code": "INVALID_MESSAGE"})
        finally:
            if session_id is not None:
                self.state.disconnect(session_id)
                await self._cancel(session_id)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, BrokenPipeError):
                pass

    async def _finish(self, session_id: str, job: WhisperJob, recording_id: str, engine: str, emit) -> None:
        try:
            await self.whisper.stop_recording(job)
            await emit(self.state.recording_ended(session_id))
            conversion_ms = await self.whisper.convert(job)
            await emit(self.state.conversion_ended(session_id))
            if engine == "reazonspeech_k2":
                reazon = await self.reazon.recognize(recording_id, job.root / "converted.wav")
                result = {"text": reazon["text"], "conversionMs": conversion_ms, "modelStartupMs": None,
                          "recognitionMs": reazon.get("recognitionMs"), "elapsedMs": WhisperPipeline._elapsed(job.stop_started_ns),
                          "modelName": "ReazonSpeech K2 INT8"}
            else:
                result = await self.whisper.recognize(job, conversion_ms)
            text = result.pop("text")
            await emit(self.state.succeed(session_id, text, **result))
        except TimeoutError as exc:
            await emit(self.state.fail(session_id, str(exc), "音声処理が時間内に終わりませんでした。"))
        except PipelineError as exc:
            await emit(self.state.fail(session_id, exc.code, exc.message))
        except ReazonError as exc:
            await emit(self.state.fail(session_id, exc.code, exc.message))
        except (OSError, RuntimeError, UnicodeError) as exc:
            await emit(self.state.fail(session_id, str(exc), "音声処理に失敗しました。"))
        finally:
            self.jobs.pop(session_id, None)
            job.directory.cleanup()
            self.tasks.pop(session_id, None)
            if engine == "reazonspeech_k2":
                self.reazon.mark_idle()

    async def _cancel(self, session_id: str) -> None:
        task = self.tasks.pop(session_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        job = self.jobs.pop(session_id, None)
        if job:
            await self.whisper.cancel(job)

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> object:
        line = await reader.readline()
        if not line:
            raise EOFError
        if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
            raise ValueError("message too large")
        return json.loads(line)

    @staticmethod
    async def _write(writer: asyncio.StreamWriter, value: dict) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ValueError("response too large")
        writer.write(payload + b"\n")
        await writer.drain()


async def start_server(path: Path, state: SpeechState | None = None, whisper: WhisperPipeline | None = None, reazon: ReazonManager | None = None) -> asyncio.AbstractServer:
    if path.exists():
        raise FileExistsError(f"socket already exists: {path}")
    server = await asyncio.start_unix_server((SpeechSocketServer(state or SpeechState(DEFAULT_ALLOWED), whisper, reazon)).handle_client, path=str(path), limit=MAX_MESSAGE_BYTES + 1)
    path.chmod(0o600)
    return server


async def run(path: Path) -> None:
    server = await start_server(path)
    try:
        async with server:
            await server.serve_forever()
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.socket))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
