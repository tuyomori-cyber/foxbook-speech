from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest

from service.whisper_pipeline import PipelineError, WhisperConfig, WhisperPipeline


class WhisperPipelineTest(unittest.IsolatedAsyncioTestCase):
    def make_executable(self, name: str, source: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.arecord = self.make_executable("arecord", """#!/bin/sh
for arg in \"$@\"; do output=\"$arg\"; done
: > \"$output\"
trap 'exit 0' INT TERM
while :; do sleep 0.02; done
""")
        self.ffmpeg = self.make_executable("ffmpeg", """#!/bin/sh
for arg in \"$@\"; do output=\"$arg\"; done
: > \"$output\"
""")
        self.cli = self.make_executable("whisper-cli", """#!/bin/sh
previous=""
for arg in \"$@\"; do
  if [ \"$previous\" = "-of" ]; then output=\"$arg\"; fi
  previous=\"$arg\"
done
printf ' テスト認識 ' > \"$output.txt\"
""")
        self.model = Path(self.temp.name) / "model.bin"
        self.model.touch()

    async def test_runs_recording_conversion_and_recognition(self) -> None:
        pipeline = WhisperPipeline(WhisperConfig(self.arecord, self.ffmpeg, self.cli, self.model))
        job = await pipeline.start()
        # テスト用shell recorderがINT trapを登録するまで待つ。
        await asyncio.sleep(0.05)
        result = await pipeline.stop_and_recognize(job)
        self.assertEqual(result["text"], "テスト認識")
        self.assertEqual(result["modelName"], "model.bin")
        self.assertIsInstance(result["conversionMs"], int)
        self.assertIsInstance(result["elapsedMs"], int)
        root = job.root
        await pipeline.cancel(job)
        self.assertFalse(root.exists())

    async def test_cancel_terminates_recorder_and_removes_temporary_directory(self) -> None:
        pipeline = WhisperPipeline(WhisperConfig(self.arecord, self.ffmpeg, self.cli, self.model))
        job = await pipeline.start()
        root = job.root
        await pipeline.cancel(job)
        self.assertIsNotNone(job.recording.returncode)
        self.assertFalse(root.exists())

    async def test_reports_recorder_stderr_when_recording_fails(self) -> None:
        failed_arecord = self.make_executable("failed-arecord", """#!/bin/sh
echo 'audio open error: No such file or directory' >&2
exit 1
""")
        pipeline = WhisperPipeline(WhisperConfig(failed_arecord, self.ffmpeg, self.cli, self.model))
        job = await pipeline.start()
        with self.assertRaises(PipelineError) as raised:
            await pipeline.stop_recording(job)
        self.assertEqual(raised.exception.code, "RECORDING_FAILED")
        self.assertIn("audio open error", raised.exception.message)
        await pipeline.cancel(job)

    async def test_accepts_interrupted_recorder_after_a_deliberate_stop(self) -> None:
        interrupted_arecord = self.make_executable("interrupted-arecord", """#!/bin/sh
for arg in \"$@\"; do output=\"$arg\"; done
: > \"$output\"
trap 'echo "read error: Interrupted system call" >&2; exit 1' INT
while :; do sleep 0.02; done
""")
        pipeline = WhisperPipeline(WhisperConfig(interrupted_arecord, self.ffmpeg, self.cli, self.model))
        job = await pipeline.start()
        await asyncio.sleep(0.05)
        await pipeline.stop_recording(job)
        await pipeline.cancel(job)


if __name__ == "__main__":
    unittest.main()
