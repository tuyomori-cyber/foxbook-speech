from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from service.server import DEFAULT_WHISPER, PROJECT_ROOT, start_server
from service.state import SpeechState


VOICE = "fox-voice-editor@foxbook.example"
OTHER = "the-session-tools@foxbook.example"


class FakeWhisperPipeline:
    def __init__(self) -> None:
        self.jobs = []

    async def start(self):
        directory = tempfile.TemporaryDirectory()
        job = SimpleNamespace(directory=directory, root=Path(directory.name), stopped=False, stop_started_ns=None,
                              recording=FakeRecording())
        self.jobs.append(job)
        return job

    async def stop_recording(self, job) -> None:
        job.stopped = True
        job.recording.complete(0)

    async def convert(self, job) -> int:
        self.assert_stopped(job)
        return 12

    async def recognize(self, job, conversion_ms: int) -> dict:
        self.assert_stopped(job)
        return {"text": "共有認識", "conversionMs": conversion_ms, "modelStartupMs": 3,
                "recognitionMs": 4, "modelName": "fake.bin"}

    async def cancel(self, job) -> None:
        job.recording.complete(-15)
        job.directory.cleanup()

    @staticmethod
    def assert_stopped(job) -> None:
        if not job.stopped:
            raise AssertionError("録音停止前に後続処理が始まりました")


class FakeRecording:
    def __init__(self):
        self.done = asyncio.Event()
        self.returncode = None
        self.stderr = None

    def complete(self, code):
        self.returncode = code
        self.done.set()

    async def wait(self):
        await self.done.wait()
        return self.returncode


class FakeReazonManager:
    def __init__(self):
        self.owners = set()

    def acquire(self, owner: str) -> None:
        self.owners.add(owner)

    def release(self, owner: str) -> None:
        self.owners.discard(owner)

    async def prepare(self) -> tuple[int, int]:
        return 7, 42

    async def recognize(self, request_id: str, _wav: Path) -> dict:
        return {"event": "result", "requestId": request_id, "text": "Reazon結果", "recognitionMs": 9}

    def mark_idle(self) -> None:
        pass


class SpeechSocketServerTest(unittest.IsolatedAsyncioTestCase):
    def test_default_whisper_paths_are_project_relative(self) -> None:
        self.assertEqual(PROJECT_ROOT.name, "foxbook-speech")
        self.assertEqual(DEFAULT_WHISPER.cli, PROJECT_ROOT.parent / "whisper.cpp/build/bin/whisper-cli")
        self.assertEqual(DEFAULT_WHISPER.model, PROJECT_ROOT.parent / "whisper.cpp/models/ggml-base.bin")

    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.temp.name) / "speech.sock"
        state = SpeechState({VOICE: frozenset(("whisper", "reazonspeech_k2")), OTHER: frozenset(("whisper",))})
        self.pipeline = FakeWhisperPipeline()
        self.reazon = FakeReazonManager()
        self.server = await start_server(self.path, state, self.pipeline, self.reazon)

    async def _cleanup(self) -> None:
        if hasattr(self, "server"):
            self.server.close()
            await self.server.wait_closed()
        self.path.unlink(missing_ok=True)
        self.temp.cleanup()

    async def open(self, extension_id: str):
        reader, writer = await asyncio.open_unix_connection(str(self.path))
        await self.send(writer, {"type": "open", "extensionId": extension_id})
        return reader, writer, await self.receive(reader)

    @staticmethod
    async def send(writer, message: dict) -> None:
        writer.write(json.dumps(message).encode() + b"\n")
        await writer.drain()

    @staticmethod
    async def receive(reader) -> dict:
        return json.loads(await asyncio.wait_for(reader.readline(), timeout=1))

    async def test_rejects_unknown_extension(self) -> None:
        reader, writer, reply = await self.open("unknown@example")
        self.assertEqual(reply, {"type": "rejected", "code": "UNAUTHORIZED_EXTENSION"})
        self.assertEqual(await reader.readline(), b"")
        writer.close()
        await writer.wait_closed()

    async def test_socket_session_owns_lease_and_disconnect_releases_it(self) -> None:
        first_reader, first_writer, opened = await self.open(VOICE)
        self.assertEqual(opened["type"], "opened")
        for request in (
            {"version": 1, "action": "prepare_microphone"},
            {"version": 1, "action": "prepare_engine", "engine": "whisper"},
            {"version": 1, "action": "start_recording"},
        ):
            await self.send(first_writer, request)
            event = await self.receive(first_reader)
        recording_id = event["recordingId"]
        second_reader, second_writer, _ = await self.open(OTHER)
        await self.send(second_writer, {"version": 1, "action": "cancel_recording", "recordingId": recording_id})
        self.assertEqual((await self.receive(second_reader))["code"], "STALE_RECORDING")
        first_writer.close()
        await first_writer.wait_closed()
        await asyncio.sleep(0)
        await self.send(second_writer, {"version": 1, "action": "prepare_microphone"})
        self.assertEqual((await self.receive(second_reader))["event"], "microphone_prepared")
        second_writer.close()
        await second_writer.wait_closed()

    async def test_whisper_job_follows_processing_states_and_returns_metrics(self) -> None:
        reader, writer, _ = await self.open(VOICE)
        for request in (
            {"version": 1, "action": "prepare_microphone"},
            {"version": 1, "action": "prepare_engine", "engine": "whisper"},
            {"version": 1, "action": "start_recording"},
        ):
            await self.send(writer, request)
            event = await self.receive(reader)
        await self.send(writer, {"version": 1, "action": "stop_recording", "recordingId": event["recordingId"]})
        events = [await self.receive(reader) for _ in range(4)]
        self.assertEqual([event["event"] for event in events], ["stopping", "processing", "processing", "result"])
        self.assertEqual([event.get("state") for event in events[:3]], ["stopping", "converting", "recognizing"])
        self.assertEqual(events[-1]["text"], "共有認識")
        self.assertEqual(events[-1]["conversionMs"], 12)
        writer.close()
        await writer.wait_closed()

    async def test_reazon_worker_is_prepared_once_and_returns_its_result(self) -> None:
        reader, writer, _ = await self.open(VOICE)
        await self.send(writer, {"version": 1, "action": "prepare_microphone"})
        await self.receive(reader)
        await self.send(writer, {"version": 1, "action": "prepare_engine", "engine": "reazonspeech_k2"})
        prepared = await self.receive(reader)
        self.assertEqual((prepared["engineGeneration"], prepared["initializationMs"]), (7, 42))
        await self.send(writer, {"version": 1, "action": "start_recording"})
        started = await self.receive(reader)
        await self.send(writer, {"version": 1, "action": "stop_recording", "recordingId": started["recordingId"]})
        events = [await self.receive(reader) for _ in range(4)]
        self.assertEqual(events[-1]["text"], "Reazon結果")
        self.assertEqual(events[-1]["engine"], "reazonspeech_k2")
        writer.close()
        await writer.wait_closed()

    async def test_reazon_recording_cancel_and_disconnect_release_owner(self) -> None:
        for disconnect in (False, True):
            reader, writer, _ = await self.open(VOICE)
            for request in (
                {"version": 1, "action": "prepare_microphone"},
                {"version": 1, "action": "prepare_engine", "engine": "reazonspeech_k2"},
                {"version": 1, "action": "start_recording"},
            ):
                await self.send(writer, request)
                event = await self.receive(reader)
            self.assertIn(event["recordingId"], self.reazon.owners)
            if not disconnect:
                await self.send(writer, {"version": 1, "action": "cancel_recording", "recordingId": event["recordingId"]})
                self.assertEqual((await self.receive(reader))["event"], "cancelled")
            writer.close()
            await writer.wait_closed()
            for _ in range(20):
                if not self.reazon.owners:
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(self.reazon.owners)

    async def test_recording_exit_automatically_stops_and_recognizes(self) -> None:
        reader, writer, _ = await self.open(VOICE)
        for request in (
            {"version": 1, "action": "prepare_microphone"},
            {"version": 1, "action": "prepare_engine", "engine": "whisper"},
            {"version": 1, "action": "start_recording"},
        ):
            await self.send(writer, request)
            started = await self.receive(reader)
        while not self.pipeline.jobs:
            await asyncio.sleep(0)
        self.pipeline.jobs[-1].recording.complete(0)
        stopping = await self.receive(reader)
        self.assertEqual((stopping["event"], stopping["reason"]), ("stopping", "recording_limit"))
        # A manual stop racing with the automatic transition must not create
        # a second result or an error.
        await self.send(writer, {"version": 1, "action": "stop_recording", "recordingId": started["recordingId"]})
        events = [await self.receive(reader) for _ in range(3)]
        self.assertEqual([event["event"] for event in events], ["processing", "processing", "result"])
        await self.send(writer, {"version": 1, "action": "get_status"})
        self.assertEqual((await self.receive(reader))["state"], "idle")
        writer.close()
        await writer.wait_closed()

    async def test_recording_failure_does_not_produce_result(self) -> None:
        reader, writer, _ = await self.open(VOICE)
        for request in (
            {"version": 1, "action": "prepare_microphone"},
            {"version": 1, "action": "prepare_engine", "engine": "whisper"},
            {"version": 1, "action": "start_recording"},
        ):
            await self.send(writer, request)
            await self.receive(reader)
        while not self.pipeline.jobs:
            await asyncio.sleep(0)
        job = self.pipeline.jobs[-1]
        job.recording.complete(1)
        event = await self.receive(reader)
        self.assertEqual(event["code"], "RECORDING_FAILED")
        self.assertFalse(job.root.exists())
        await self.send(writer, {"version": 1, "action": "get_status"})
        self.assertEqual((await self.receive(reader))["state"], "idle")
        writer.close()
        await writer.wait_closed()

    async def test_cancel_after_automatic_stop_releases_job(self) -> None:
        entered = asyncio.Event()
        async def wait_conversion(job):
            entered.set()
            await asyncio.Event().wait()
        self.pipeline.convert = wait_conversion
        reader, writer, _ = await self.open(VOICE)
        for request in (
            {"version": 1, "action": "prepare_microphone"},
            {"version": 1, "action": "prepare_engine", "engine": "whisper"},
            {"version": 1, "action": "start_recording"},
        ):
            await self.send(writer, request)
            started = await self.receive(reader)
        while not self.pipeline.jobs:
            await asyncio.sleep(0)
        job = self.pipeline.jobs[-1]
        job.recording.complete(0)
        self.assertEqual((await self.receive(reader))["event"], "stopping")
        self.assertEqual((await self.receive(reader))["state"], "converting")
        await entered.wait()
        await self.send(writer, {"version": 1, "action": "cancel_recording", "recordingId": started["recordingId"]})
        self.assertEqual((await self.receive(reader))["event"], "cancelled")
        await self.send(writer, {"version": 1, "action": "get_status"})
        self.assertEqual((await self.receive(reader))["state"], "idle")
        self.assertFalse(job.root.exists())
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
