"""One reusable ReazonSpeech worker for the whole speech service."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Final

MAX_MESSAGE_BYTES: Final = 1024 * 1024


class ReazonError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code, self.message = code, message


class ReazonManager:
    def __init__(self, python: Path, worker: Path, model: Path, idle_seconds: int = 300) -> None:
        self.python, self.worker, self.model, self.idle_seconds = python, worker, model, idle_seconds
        self.process: asyncio.subprocess.Process | None = None
        self.generation = 0
        self._lock = asyncio.Lock()
        self._idle: asyncio.Task | None = None
        self._users: set[str] = set()

    def acquire(self, owner: str) -> None:
        self._users.add(owner)
        self._idle = None

    def release(self, owner: str) -> None:
        self._users.discard(owner)
        self.mark_idle()

    def validate(self) -> None:
        for path in (self.python, self.worker, self.model / "encoder-epoch-99-avg-1.int8.onnx",
                     self.model / "decoder-epoch-99-avg-1.onnx", self.model / "joiner-epoch-99-avg-1.int8.onnx", self.model / "tokens.txt"):
            if not path.is_file():
                raise ReazonError("ENGINE_FILES_MISSING", str(path))

    async def prepare(self) -> tuple[int, int]:
        async with self._lock:
            self._idle = None
            if self.process and self.process.returncode is None:
                self.mark_idle()
                return self.generation, 0
            await self.stop()
            self.validate()
            self.process = await asyncio.create_subprocess_exec(str(self.python), str(self.worker), str(self.model),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                event = await self._read(45)
            except BaseException:
                await self.stop()
                raise
            if event.get("event") != "ready" or not isinstance(event.get("initializationMs"), int):
                await self.stop()
                raise ReazonError(event.get("code", "ENGINE_PROTOCOL_ERROR"), event.get("message", "Workerを準備できませんでした。"))
            self.generation += 1
            self.mark_idle()
            return self.generation, event["initializationMs"]

    async def recognize(self, request_id: str, wav: Path) -> dict:
        async with self._lock:
            process = self.process
            if not process or process.returncode is not None or not process.stdin:
                raise ReazonError("ENGINE_NOT_READY", "ReazonSpeech Workerの準備が完了していません。")
            payload = json.dumps({"action": "recognize", "requestId": request_id, "wavPath": str(wav)}, separators=(",", ":")).encode() + b"\n"
            process.stdin.write(payload); await process.stdin.drain()
            try:
                event = await self._read(60)
            except BaseException:
                await self.stop()
                raise
            if event.get("event") != "result" or event.get("requestId") != request_id or not isinstance(event.get("text"), str):
                await self.stop()
                raise ReazonError(event.get("code", "RECOGNITION_FAILED"), event.get("message", "ReazonSpeech認識に失敗しました。"))
            return event

    def mark_idle(self) -> None:
        if not self._users and self.process and self.process.returncode is None and not self._idle:
            self._idle = asyncio.create_task(self._stop_when_idle())

    async def _stop_when_idle(self) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
            async with self._lock:
                if self._idle is asyncio.current_task() and not self._users:
                    await self.stop()
        except asyncio.CancelledError:
            pass
        finally:
            if self._idle is asyncio.current_task():
                self._idle = None

    async def stop(self) -> None:
        process, self.process = self.process, None
        if not process:
            return
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), .5)
            except asyncio.TimeoutError:
                process.kill(); await process.wait()

    async def _read(self, timeout: int) -> dict:
        if not self.process or not self.process.stdout:
            raise ReazonError("ENGINE_EXITED", "ReazonSpeech Workerが終了しました。")
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
        except asyncio.TimeoutError as exc:
            raise ReazonError("ENGINE_PREPARATION_TIMEOUT", "ReazonSpeech Workerの準備が時間内に終わりませんでした。") from exc
        if not line or len(line) > MAX_MESSAGE_BYTES:
            raise ReazonError("ENGINE_PROTOCOL_ERROR", "Workerの応答が不正です。")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ReazonError("ENGINE_PROTOCOL_ERROR", "Workerの応答が不正です。")
        return value
