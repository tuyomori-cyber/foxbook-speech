"""Protocol validation and ownership-aware state for the shared speech service."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets

VERSION = 1
ENGINES = frozenset(("whisper", "reazonspeech_k2"))


@dataclass
class Session:
    extension_id: str
    microphone_ready: bool = False
    engine: str = "whisper"
    ready_engines: set[str] = field(default_factory=set)


@dataclass
class Lease:
    recording_id: str
    session_id: str
    engine: str
    phase: str = "recording"


class SpeechState:
    """Single-process policy core; process execution is deliberately separate."""

    def __init__(self, allowed_extensions: dict[str, frozenset[str]]) -> None:
        self.allowed_extensions = allowed_extensions
        self.sessions: dict[str, Session] = {}
        self.lease: Lease | None = None
        self.engine_generations = {engine: 0 for engine in ENGINES}

    def connect(self, extension_id: str) -> str:
        if extension_id not in self.allowed_extensions:
            raise PermissionError("UNAUTHORIZED_EXTENSION")
        session_id = secrets.token_urlsafe(24)
        self.sessions[session_id] = Session(extension_id)
        return session_id

    def disconnect(self, session_id: str) -> list[dict]:
        if session_id not in self.sessions:
            return []
        events = []
        if self.lease and self.lease.session_id == session_id:
            events.append(self._event("cancelled", recordingId=self.lease.recording_id, state="idle"))
            self.lease = None
        del self.sessions[session_id]
        return events

    def handle(self, session_id: str, request: object) -> list[dict]:
        session = self.sessions.get(session_id)
        if session is None:
            return [self._error(None, "SESSION_CLOSED", "接続は既に終了しています。")]
        if not isinstance(request, dict) or request.get("version") != VERSION or not isinstance(request.get("action"), str):
            return [self._error(None, "INVALID_REQUEST", "要求形式が正しくありません。")]
        action = request["action"]
        allowed = {
            "prepare_microphone": {"version", "action"},
            "prepare_engine": {"version", "action", "engine"},
            "start_recording": {"version", "action"},
            "stop_recording": {"version", "action", "recordingId"},
            "cancel_recording": {"version", "action", "recordingId"},
            "get_status": {"version", "action"},
        }
        if action not in allowed or set(request) != allowed[action]:
            return [self._error(None, "INVALID_REQUEST", "要求形式が正しくありません。")]
        if action == "prepare_microphone":
            if self.lease:
                return [self._error(self.lease.recording_id, "BUSY", "他の録音または認識を処理中です。")]
            session.microphone_ready = True
            return [self._event("microphone_prepared", status="ready")]
        if action == "prepare_engine":
            return self.prepare_engine(session_id, request["engine"])
        if action == "get_status":
            state = self.lease.phase if self.lease and self.lease.session_id == session_id else "idle"
            return [self._event("status", recordingId=self.lease.recording_id if self.lease and self.lease.session_id == session_id else None,
                                state=state, microphoneReady=session.microphone_ready, engine=session.engine,
                                engineStatus="ready" if session.engine in session.ready_engines else "uninitialized",
                                engineGeneration=self.engine_generations[session.engine])]
        if action == "start_recording":
            if self.lease:
                return [self._error(self.lease.recording_id, "BUSY", "他の録音または認識を処理中です。")]
            if not session.microphone_ready:
                return [self._error(None, "MICROPHONE_NOT_READY", "マイクの確認が完了していません。")]
            if session.engine not in session.ready_engines:
                return [self._error(None, "ENGINE_NOT_READY", "認識エンジンの準備が完了していません。")]
            recording_id = secrets.token_hex(16)
            self.lease = Lease(recording_id, session_id, session.engine)
            return [self._event("started", recordingId=recording_id, state="recording", engine=session.engine,
                                engineGeneration=self.engine_generations[session.engine])]
        recording_id = request["recordingId"]
        if not isinstance(recording_id, str) or not self.lease or self.lease.recording_id != recording_id or self.lease.session_id != session_id:
            return [self._error(recording_id if isinstance(recording_id, str) else None, "STALE_RECORDING", "録音の所有者または識別子が一致しません。")]
        if action == "cancel_recording":
            self.lease = None
            return [self._event("cancelled", recordingId=recording_id, state="idle")]
        if self.lease.phase != "recording":
            return [self._error(recording_id, "NOT_RECORDING", "録音中ではありません。")]
        self.lease.phase = "stopping"
        return [self._event("stopping", recordingId=recording_id, state="stopping")]

    def recording_ended(self, session_id: str) -> list[dict]:
        return self._advance(session_id, "recording", "converting")

    def conversion_ended(self, session_id: str) -> list[dict]:
        return self._advance(session_id, "converting", "recognizing")

    def prepare_engine(self, session_id: str, engine: object, initialization_ms: int = 0,
                       generation: int | None = None) -> list[dict]:
        session = self.sessions.get(session_id)
        if session is None:
            return [self._error(None, "SESSION_CLOSED", "接続は既に終了しています。")]
        if not isinstance(engine, str) or engine not in ENGINES:
            return [self._error(None, "UNKNOWN_ENGINE", "認識エンジンが不正です。")]
        if engine not in self.allowed_extensions[session.extension_id]:
            return [self._error(None, "ENGINE_NOT_ALLOWED", "この拡張では選択できない認識エンジンです。")]
        if self.lease:
            return [self._error(self.lease.recording_id, "BUSY", "他の録音または認識を処理中です。")]
        if generation is not None:
            self.engine_generations[engine] = generation
        session.engine = engine
        session.ready_engines.add(engine)
        return [self._event("engine_prepared", engine=engine, engineStatus="ready",
                            engineGeneration=self.engine_generations[engine], initializationMs=initialization_ms)]

    def succeed(self, session_id: str, text: str, **metrics: object) -> list[dict]:
        lease = self._owned(session_id, "recognizing")
        if lease is None:
            return []
        self.lease = None
        result: dict[str, object] = {
            "recordingId": lease.recording_id,
            "engine": lease.engine,
            "engineGeneration": self.engine_generations[lease.engine],
            "text": text,
            "conversionMs": None,
            "modelStartupMs": None,
            "recognitionMs": None,
            "elapsedMs": None,
            "modelName": lease.engine,
        }
        result.update(metrics)
        return [self._event("result", **result)]

    def fail(self, session_id: str, code: str, message: str) -> list[dict]:
        lease = self._owned(session_id)
        if lease is None:
            return []
        self.lease = None
        return [self._error(lease.recording_id, code, message)]

    def _advance(self, session_id: str, expected: str, next_phase: str) -> list[dict]:
        lease = self._owned(session_id, expected) or (self._owned(session_id, "stopping") if expected == "recording" else None)
        if lease is None:
            return []
        lease.phase = next_phase
        return [self._event("processing", recordingId=lease.recording_id, state=next_phase)]

    def _owned(self, session_id: str, phase: str | None = None) -> Lease | None:
        if self.lease and self.lease.session_id == session_id and (phase is None or self.lease.phase == phase):
            return self.lease
        return None

    @staticmethod
    def _event(event: str, **extra: object) -> dict:
        return {"version": VERSION, "event": event, **extra}

    @classmethod
    def _error(cls, recording_id: str | None, code: str, message: str) -> dict:
        return cls._event("error", recordingId=recording_id, code=code, message=message)
