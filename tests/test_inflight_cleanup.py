"""Exercise real child processes while cancelling an in-flight socket request."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from service.reazon import ReazonManager
from service.server import start_server
from service.state import SpeechState
from service.whisper_pipeline import WhisperConfig, WhisperPipeline

VOICE = "fox-voice-editor@foxbook.example"


class TrackingPipeline(WhisperPipeline):
    async def start(self):
        self.job = await super().start()
        return self.job


class InFlightCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.socket = self.root / "speech.sock"
        self.marker = self.root / "entered"
        self.server = None
        self.writer = None
        self.manager = None

    async def asyncTearDown(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.manager:
            await self.manager.stop()
        self.temp.cleanup()

    def executable(self, name, body):
        path = self.root / name
        path.write_text("#!/usr/bin/python3\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    async def wait_until(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    async def run_case(self, phase, disconnect):
        self.marker.unlink(missing_ok=True)
        recorder = self.executable("recorder", "import pathlib, signal, sys, time\nsignal.signal(signal.SIGINT, lambda *args: sys.exit(0))\npathlib.Path(sys.argv[-1]).touch()\nwhile True: time.sleep(.01)\n")
        blocked = f"import pathlib, time\npathlib.Path({str(self.marker)!r}).touch()\nwhile True: time.sleep(.01)\n"
        converter = self.executable("converter", blocked if phase.startswith("conversion") else "import pathlib, sys\npathlib.Path(sys.argv[-1]).touch()\n")
        cli = self.executable("cli", blocked)
        model = self.root / "model"
        model.touch()
        worker = self.executable("worker", f"import json, pathlib, sys, time\nprint(json.dumps({{'event':'ready','initializationMs':1}}), flush=True)\nfor line in sys.stdin:\n pathlib.Path({str(self.marker)!r}).touch()\n while True: time.sleep(.01)\n")
        for name in ("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"):
            (self.root / name).touch()
        self.manager = ReazonManager(Path("/usr/bin/python3"), worker, self.root, idle_seconds=0.05)
        pipeline = TrackingPipeline(WhisperConfig(recorder, converter, cli, model))
        state = SpeechState({VOICE: frozenset(("whisper", "reazonspeech_k2"))})
        self.server = await start_server(self.socket, state, pipeline, self.manager)
        reader, self.writer = await asyncio.open_unix_connection(str(self.socket))

        async def send(**message):
            self.writer.write(json.dumps(message).encode() + b"\n")
            await self.writer.drain()

        async def receive():
            return json.loads(await asyncio.wait_for(reader.readline(), 3))

        await send(type="open", extensionId=VOICE)
        await receive()
        engine = "reazonspeech_k2" if phase in ("reazon", "conversion_reazon") else "whisper"
        for action, fields in (("prepare_microphone", {}), ("prepare_engine", {"engine": engine}), ("start_recording", {})):
            await send(version=1, action=action, **fields)
            event = await receive()
            self.assertNotEqual(event.get("event"), "error", event)
        recording_id = event["recordingId"]
        await self.wait_until(lambda: hasattr(pipeline, "job"))
        job = pipeline.job
        await self.wait_until(lambda: (job.root / "recorded.wav").exists())
        await send(version=1, action="stop_recording", recordingId=recording_id)
        await self.wait_until(self.marker.exists)
        child = self.manager.process if phase == "reazon" else job.active_process
        self.assertIsNotNone(child)
        if disconnect:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
        else:
            await send(version=1, action="cancel_recording", recordingId=recording_id)
            while (await receive()).get("event") != "cancelled":
                pass
        await self.wait_until(lambda: child.returncode is not None and not job.root.exists() and state.lease is None)
        self.assertIsNotNone(job.recording.returncode)
        self.assertFalse(self.manager._users)
        if phase == "conversion_reazon":
            await self.wait_until(lambda: self.manager.process is None)
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
        self.server.close()
        await self.server.wait_closed()
        self.server = None
        await self.manager.stop()
        self.manager = None
        self.socket.unlink(missing_ok=True)

    async def test_cancel_and_disconnect_during_conversion_and_recognition(self):
        for phase in ("conversion", "conversion_reazon", "whisper", "reazon"):
            for disconnect in (False, True):
                with self.subTest(phase=phase, disconnect=disconnect):
                    await self.run_case(phase, disconnect)
