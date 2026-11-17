from __future__ import annotations

import unittest

from service.state import SpeechState


VOICE = "fox-voice-editor@foxbook.example"
OTHER = "the-session-tools@foxbook.example"


class SpeechStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SpeechState({VOICE: frozenset(("whisper", "reazonspeech_k2")), OTHER: frozenset(("whisper",))})
        self.voice = self.state.connect(VOICE)
        self.other = self.state.connect(OTHER)

    def request(self, session: str, action: str, **extra: object) -> dict:
        return self.state.handle(session, {"version": 1, "action": action, **extra})[0]

    def ready(self, session: str, engine: str = "whisper") -> None:
        self.assertEqual(self.request(session, "prepare_microphone")["event"], "microphone_prepared")
        self.assertEqual(self.request(session, "prepare_engine", engine=engine)["event"], "engine_prepared")

    def test_rejects_unknown_extensions_and_invalid_requests(self) -> None:
        with self.assertRaises(PermissionError):
            self.state.connect("untrusted@example")
        self.assertEqual(self.state.handle(self.voice, {"version": 1, "action": "start_recording", "clientId": "forged"})[0]["code"], "INVALID_REQUEST")

    def test_requires_preparation_and_enforces_global_lease(self) -> None:
        self.assertEqual(self.request(self.voice, "start_recording")["code"], "MICROPHONE_NOT_READY")
        self.ready(self.voice)
        started = self.request(self.voice, "start_recording")
        self.assertEqual(started["event"], "started")
        self.assertEqual(self.request(self.other, "prepare_microphone")["code"], "BUSY")
        self.assertEqual(self.request(self.other, "start_recording")["code"], "BUSY")

    def test_only_owner_can_stop_or_cancel_and_disconnect_releases(self) -> None:
        self.ready(self.voice)
        recording_id = self.request(self.voice, "start_recording")["recordingId"]
        self.assertEqual(self.request(self.other, "cancel_recording", recordingId=recording_id)["code"], "STALE_RECORDING")
        self.assertEqual(self.state.disconnect(self.voice)[0]["event"], "cancelled")
        self.ready(self.other)
        self.assertEqual(self.request(self.other, "start_recording")["event"], "started")

    def test_pipeline_events_and_terminal_result_release_lease(self) -> None:
        self.ready(self.voice, "reazonspeech_k2")
        recording_id = self.request(self.voice, "start_recording")["recordingId"]
        self.assertEqual(self.request(self.voice, "stop_recording", recordingId=recording_id)["state"], "stopping")
        self.assertEqual(self.state.recording_ended(self.voice)[0]["state"], "converting")
        self.assertEqual(self.state.conversion_ended(self.voice)[0]["state"], "recognizing")
        result = self.state.succeed(self.voice, "テスト成功")[0]
        self.assertEqual((result["event"], result["text"]), ("result", "テスト成功"))
        self.ready(self.other)
        self.assertEqual(self.request(self.other, "start_recording")["event"], "started")

    def test_engine_is_scoped_to_session_and_permissions_are_checked(self) -> None:
        self.ready(self.voice, "reazonspeech_k2")
        self.assertEqual(self.request(self.other, "prepare_engine", engine="reazonspeech_k2")["code"], "ENGINE_NOT_ALLOWED")
        self.assertEqual(self.request(self.other, "prepare_engine", engine="whisper")["engine"], "whisper")

    def test_tuner_uses_the_global_lease_and_only_its_owner_can_stop_it(self) -> None:
        self.assertEqual(self.request(self.other, "start_tuner")["code"], "MICROPHONE_NOT_READY")
        self.ready(self.other)
        tuner = self.request(self.other, "start_tuner")
        self.assertEqual((tuner["event"], tuner["state"]), ("tuner_started", "tuning"))
        self.assertEqual(self.request(self.voice, "start_recording")["code"], "BUSY")
        self.assertEqual(self.request(self.voice, "stop_tuner", tunerId=tuner["tunerId"])["code"], "STALE_TUNER")
        self.assertEqual(self.request(self.other, "stop_tuner", tunerId=tuner["tunerId"])["event"], "tuner_stopped")
        self.ready(self.voice)
        self.assertEqual(self.request(self.voice, "start_recording")["event"], "started")


if __name__ == "__main__":
    unittest.main()
