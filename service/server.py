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
import time
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
        self.watchers: dict[str, asyncio.Task] = {}
        self.auto_stopped: dict[str, str] = {}
        self.reazon_users: dict[str, str] = {}
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
                if (isinstance(request, dict) and request.get("action") == "stop_recording"
                        and set(request) == {"version", "action", "recordingId"} and request.get("version") == 1
                        and self.auto_stopped.get(session_id) == request.get("recordingId")):
                    continue
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
                if isinstance(request, dict) and request.get("action") == "start_recording" and events and events[0].get("event") == "started" and events[0].get("engine") == "reazonspeech_k2":
                    owner = events[0]["recordingId"]
                    self.reazon.acquire(owner)
                    self.reazon_users[session_id] = owner
                    try:
                        generation, _ = await self.reazon.prepare()
                        self.state.engine_generations["reazonspeech_k2"] = generation
                        events[0]["engineGeneration"] = generation
                    except (ReazonError, OSError) as exc:
                        self._release_reazon(session_id, owner)
                        events = self.state.fail(session_id, getattr(exc, "code", "ENGINE_START_FAILED"), str(exc))
                await emit(events)
                if isinstance(request, dict) and request.get("action") == "start_recording" and events and events[0].get("event") == "started":
                    self.auto_stopped.pop(session_id, None)
                    try:
                        job = await self.whisper.start()
                        self.jobs[session_id] = job
                        self.watchers[session_id] = asyncio.create_task(self._watch_recording(session_id, job, events[0]["recordingId"], events[0]["engine"], emit))
                    except (OSError, RuntimeError, FileNotFoundError) as exc:
                        self._release_reazon(session_id)
                        await emit(self.state.fail(session_id, "RECORDING_FAILED", str(exc)))
                elif isinstance(request, dict) and request.get("action") == "stop_recording" and events and events[0].get("event") == "stopping":
                    job = self.jobs.get(session_id)
                    if job:
                        self.tasks[session_id] = asyncio.create_task(self._finish(session_id, job, events[0]["recordingId"], self.state.lease.engine if self.state.lease else "whisper", emit))
                elif isinstance(request, dict) and request.get("action") == "cancel_recording" and events and events[0].get("event") == "cancelled":
                    await self._cancel(session_id)
        except (EOFError, ConnectionError, BrokenPipeError):
            pass
        except (ValueError, UnicodeError, json.JSONDecodeError):
            await self._write(writer, {"type": "rejected", "code": "INVALID_MESSAGE"})
        finally:
            if session_id is not None:
                self.state.disconnect(session_id)
                await self._cancel(session_id)
                self.auto_stopped.pop(session_id, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, BrokenPipeError):
                pass

    async def _watch_recording(self, session_id: str, job: WhisperJob, recording_id: str, engine: str, emit) -> None:
        try:
            returncode = await job.recording.wait()
            lease = self.state.lease
            if not lease or lease.session_id != session_id or lease.recording_id != recording_id or lease.phase != "recording":
                return
            if returncode != 0:
                detail = (await job.recording.stderr.read()).decode("utf-8", errors="replace").strip() if job.recording.stderr else ""
                lease = self.state.lease
                if not lease or lease.session_id != session_id or lease.recording_id != recording_id or lease.phase != "recording":
                    return
                events = self.state.fail(session_id, "RECORDING_FAILED", detail or "録音が途中で終了しました。")
                self.jobs.pop(session_id, None)
                await self.whisper.cancel(job)
                self._release_reazon(session_id, recording_id)
                await emit(events)
                return
            job.stop_started_ns = time.monotonic_ns()
            events = self.state.handle(session_id, {"version": 1, "action": "stop_recording", "recordingId": recording_id})
            if not events or events[0].get("event") != "stopping":
                return
            self.auto_stopped[session_id] = recording_id
            events[0]["reason"] = "recording_limit"
            await emit(events)
            lease = self.state.lease
            if lease and lease.session_id == session_id and lease.recording_id == recording_id and lease.phase == "stopping":
                self.tasks[session_id] = asyncio.create_task(self._finish(session_id, job, recording_id, engine, emit))
        finally:
            if self.watchers.get(session_id) is asyncio.current_task():
                self.watchers.pop(session_id, None)

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
            self._release_reazon(session_id, recording_id)
            await emit(self.state.succeed(session_id, text, **result))
        except TimeoutError as exc:
            await emit(self.state.fail(session_id, str(exc), "音声処理が時間内に終わりませんでした。"))
        except PipelineError as exc:
            await emit(self.state.fail(session_id, exc.code, exc.message))
        except ReazonError as exc:
            await emit(self.state.fail(session_id, exc.code, exc.message))
        except (OSError, RuntimeError, UnicodeError) as exc:
            await emit(self.state.fail(session_id, str(exc), "音声処理に失敗しました。"))
        except asyncio.CancelledError:
            await self.whisper.cancel(job)
            raise
        finally:
            self.jobs.pop(session_id, None)
            job.directory.cleanup()
            self.tasks.pop(session_id, None)
            self._release_reazon(session_id, recording_id)

    async def _cancel(self, session_id: str) -> None:
        watcher = self.watchers.pop(session_id, None)
        if watcher and watcher is not asyncio.current_task():
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
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
        self._release_reazon(session_id)

    def _release_reazon(self, session_id: str, owner: str | None = None) -> None:
        current = self.reazon_users.get(session_id)
        if current is not None and (owner is None or owner == current):
            del self.reazon_users[session_id]
            self.reazon.release(current)

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
