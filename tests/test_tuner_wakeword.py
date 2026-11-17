from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from service.server import SpeechSocketServer
from service.state import SpeechState


class FakeProcess:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.returncode = None

    def terminate(self):
        self.returncode = -15
        self.stdout.feed_eof()

    async def wait(self):
        return self.returncode


class TunerWakewordTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = SpeechState({"tst": frozenset(("whisper",))})
        self.session = self.state.connect("tst")
        self.state.handle(self.session, {"version": 1, "action": "prepare_microphone"})
        self.tuner_id = self.state.handle(self.session, {"version": 1, "action": "start_tuner"})[0]["tunerId"]
        self.server = SpeechSocketServer(self.state)
        self.process = FakeProcess()
        self.server.wakeword_processes[self.session] = self.process
        self.events = []

    async def emit(self, events):
        self.events.extend(events)

    async def test_detection_during_guard_is_ignored_then_fox_is_reported(self):
        self.process.stdout.feed_data("検出: FOX\n検出: FOX\n".encode())
        with patch("service.server.time.monotonic", side_effect=[10.0, 11.0, 12.0]):
            await self.server._watch_wakeword(self.session, self.process, self.emit, tuner_id=self.tuner_id)
        self.assertEqual([event["event"] for event in self.events], ["tuner_wakeword_detected"])
        self.assertEqual(self.events[0]["tunerId"], self.tuner_id)
        self.assertEqual(self.process.returncode, -15)

    async def test_mirai_detection_releases_input_and_reports_tuner_event(self):
        self.process.stdout.feed_data("検出: みらい (score=0.9)\n".encode())
        with patch("service.server.time.monotonic", side_effect=[10.0, 12.0]):
            await self.server._watch_wakeword(self.session, self.process, self.emit, tuner_id=self.tuner_id)
        self.assertEqual([event["event"] for event in self.events], ["tuner_wakeword_detected"])
        self.assertEqual(self.process.returncode, -15)

    async def test_mirai_normal_detection_releases_input_before_event(self):
        self.process.stdout.feed_data("検出: みらい (score=0.9)\n".encode())
        async def emit(events):
            self.assertEqual(self.process.returncode, -15)
            self.events.extend(events)
        await self.server._watch_wakeword(self.session, self.process, emit)
        self.assertEqual([event["event"] for event in self.events], ["wakeword_detected"])

    def test_mirai_selection_and_default_fox(self):
        with patch.dict("os.environ", {"FOXBOOK_WAKEWORD": "fox"}):
            self.assertTrue(self.server._wakeword_command()[0].endswith("wakeword_kws"))
        with patch.dict("os.environ", {"FOXBOOK_WAKEWORD": "mirai"}):
            with patch("service.server.MIRAI_ROOT") as root:
                runtime = root / ".venv/lib"
                runtime.glob.return_value = ["/runtime/libonnxruntime.so.1"]
                command = self.server._wakeword_command(tuner=True)
            self.assertTrue(command[0].endswith("mirai_kws"))
            self.assertIn("--tuner", command)

    async def test_manual_stop_cancels_watcher_without_detection_or_error(self):
        task = asyncio.create_task(self.server._watch_wakeword(self.session, self.process, self.emit, tuner_id=self.tuner_id))
        self.server.wakeword_tasks[self.session] = task
        await asyncio.sleep(0)
        await self.server._stop_wakeword(self.session)
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.events, [])
        self.assertEqual(self.process.returncode, -15)

    async def test_unexpected_exit_reports_error(self):
        self.process.stdout.feed_eof()
        await self.server._watch_wakeword(self.session, self.process, self.emit, tuner_id=self.tuner_id)
        self.assertEqual(self.events[0]["code"], "WAKEWORD_STOPPED")

    async def test_pitch_is_forwarded_only_for_owned_tuner_and_silence_clears(self):
        self.process.stdout.feed_data(b"PITCH: 440.2\nPITCH: 0\n")
        task = asyncio.create_task(self.server._watch_wakeword(self.session, self.process, self.emit, tuner_id=self.tuner_id))
        await asyncio.sleep(0)
        self.assertEqual([event["frequencyHz"] for event in self.events], [440.2, None])
        self.assertTrue(all(event["tunerId"] == self.tuner_id for event in self.events))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

