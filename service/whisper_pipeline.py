"""Whisper recording pipeline owned by the shared speech service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import tempfile
import time


@dataclass(frozen=True)
class WhisperConfig:
    arecord: Path
    ffmpeg: Path
    cli: Path
    model: Path
    max_record_seconds: int = 30
    convert_timeout_seconds: int = 10
    recognize_timeout_seconds: int = 60


@dataclass
class WhisperJob:
    directory: tempfile.TemporaryDirectory
    recording: asyncio.subprocess.Process
    active_process: asyncio.subprocess.Process | None = None
    stop_started_ns: int | None = None

    @property
    def root(self) -> Path:
        return Path(self.directory.name)


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class WhisperPipeline:
    """Runs one Whisper job. The caller owns lease/state transitions and events."""

    def __init__(self, config: WhisperConfig) -> None:
        self.config = config

    def validate(self) -> None:
        for path in (self.config.arecord, self.config.ffmpeg, self.config.cli, self.config.model):
            if not path.is_file():
                raise FileNotFoundError(str(path))

    async def start(self) -> WhisperJob:
        self.validate()
        directory = tempfile.TemporaryDirectory(prefix="foxbook-speech-")
        root = Path(directory.name)
        try:
            recording = await asyncio.create_subprocess_exec(
                str(self.config.arecord), "-q", "-d", str(self.config.max_record_seconds), "-f", "cd", str(root / "recorded.wav"),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
        except Exception:
            directory.cleanup()
            raise
        return WhisperJob(directory, recording)

    async def stop_recording(self, job: WhisperJob) -> None:
        if job.recording.returncode is None:
            job.stop_started_ns = time.monotonic_ns()
            job.recording.send_signal(signal.SIGINT)
        try:
            await asyncio.wait_for(job.recording.wait(), timeout=2)
        except asyncio.TimeoutError as exc:
            await self.cancel(job)
            raise TimeoutError("RECORDING_TIMEOUT") from exc
        recording_file = job.root / "recorded.wav"
        # arecord reports EINTR with a non-zero status when SIGINT is the
        # deliberate stop request.  A completed WAV is the authority here;
        # ffmpeg validates it in the following phase.
        if job.recording.returncode not in (0, None) and (job.stop_started_ns is None or not recording_file.is_file()):
            detail = ""
            if job.recording.stderr is not None:
                detail = (await job.recording.stderr.read()).decode("utf-8", errors="replace").strip()
            raise PipelineError("RECORDING_FAILED", detail or "arecordが録音を開始できませんでした。")

    async def convert(self, job: WhisperJob) -> int | None:
        converted = job.root / "converted.wav"
        await self._run(job, (str(self.config.ffmpeg), "-y", "-loglevel", "error", "-i", str(job.root / "recorded.wav"), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(converted)), self.config.convert_timeout_seconds, "CONVERSION")
        return self._elapsed(job.stop_started_ns)

    async def recognize(self, job: WhisperJob, conversion_ms: int | None) -> dict[str, int | str | None]:
        converted = job.root / "converted.wav"
        transcript_base = job.root / "transcript"
        whisper_started = time.monotonic_ns()
        stderr = job.root / "stderr.log"
        with stderr.open("wb") as err:
            process = await asyncio.create_subprocess_exec(
                str(self.config.cli), "-m", str(self.config.model), "-f", str(converted), "-l", "ja", "-nt", "-np", "-otxt", "-of", str(transcript_base),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=err,
                env={**os.environ, "WHISPER_CLI_TIMING_MARKERS": "1"},
            )
            job.active_process = process
            try:
                await asyncio.wait_for(process.wait(), timeout=self.config.recognize_timeout_seconds)
            except asyncio.TimeoutError as exc:
                process.kill(); await process.wait()
                raise TimeoutError("RECOGNITION_TIMEOUT") from exc
            finally:
                job.active_process = None
        transcript = transcript_base.with_suffix(".txt")
        if process.returncode != 0 or not transcript.is_file():
            raise RuntimeError("RECOGNITION_FAILED")
        text = transcript.read_text(encoding="utf-8").strip()
        if not text:
            raise RuntimeError("EMPTY_RESULT")
        startup, recognition = self._timings(stderr, whisper_started)
        return {"text": text, "conversionMs": conversion_ms, "modelStartupMs": startup,
                "recognitionMs": recognition, "elapsedMs": self._elapsed(job.stop_started_ns),
                "modelName": self.config.model.name}

    async def stop_and_recognize(self, job: WhisperJob) -> dict[str, int | str | None]:
        await self.stop_recording(job)
        conversion_ms = await self.convert(job)
        return await self.recognize(job, conversion_ms)

    async def cancel(self, job: WhisperJob) -> None:
        processes = [job.recording]
        if job.active_process is not None and job.active_process is not job.recording:
            processes.append(job.active_process)
        for process in processes:
            if process.returncode is None:
                process.terminate()
        for process in processes:
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=.5)
                except asyncio.TimeoutError:
                    process.kill(); await process.wait()
        job.directory.cleanup()

    async def _run(self, job: WhisperJob, args: tuple[str, ...], timeout: int, prefix: str) -> None:
        process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        job.active_process = process
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill(); await process.wait()
            raise TimeoutError(f"{prefix}_TIMEOUT") from exc
        finally:
            job.active_process = None
        if process.returncode != 0:
            raise RuntimeError(f"{prefix}_FAILED")

    @staticmethod
    def _elapsed(started_ns: int | None) -> int | None:
        return None if started_ns is None else round((time.monotonic_ns() - started_ns) / 1_000_000)

    @staticmethod
    def _timings(stderr: Path, started_ns: int) -> tuple[int | None, int | None]:
        text = stderr.read_text(encoding="utf-8", errors="replace")
        ready = re.search(r"(?m)^whisper_cli_timing: model_ready_ns = (\d+)$", text)
        done = re.search(r"(?m)^whisper_cli_timing: recognition_done_ns = (\d+)$", text)
        if not ready or not done:
            return None, None
        ready_ns, done_ns = int(ready.group(1)), int(done.group(1))
        if not started_ns <= ready_ns <= done_ns <= time.monotonic_ns():
            return None, None
        return round((ready_ns - started_ns) / 1_000_000), round((done_ns - ready_ns) / 1_000_000)
