import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_wakeword.py"
spec = importlib.util.spec_from_file_location("diagnose_wakeword", SCRIPT)
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)
sys.modules["diagnose_wakeword"] = diagnose
worker_spec = importlib.util.spec_from_file_location("wakeword_arecord", SCRIPT.parent / "wakeword_arecord.py")
worker = importlib.util.module_from_spec(worker_spec)
worker_spec.loader.exec_module(worker)


class WakewordDiagnosticTest(unittest.TestCase):
    def test_pcm_stream_uses_left_channel_and_resets_after_detection(self):
        class Stream:
            def accept_waveform(self, rate, samples):
                self.rate, self.samples = rate, samples
        class Spotter:
            def __init__(self):
                self.stream, self.pending, self.resets = Stream(), True, 0
            def create_stream(self): return self.stream
            def is_ready(self, stream): return self.pending
            def decode_stream(self, stream): self.pending = False
            def get_result(self, stream): return "FOX"
            def reset_stream(self, stream): self.resets += 1
        spotter = Spotter()
        ready = []
        worker.process_pcm(spotter, io.BytesIO(struct.pack("<hhhh", 16384, -16384, -32768, 0)), ready.append)
        self.assertEqual(spotter.stream.rate, 44100)
        self.assertEqual(spotter.stream.samples, [0.5, -1.0])
        self.assertEqual(spotter.resets, 1)
        self.assertEqual(len(ready), 1)

    def test_builds_one_keyword_and_uses_local_microphone_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "sherpa-onnx-keyword-spotter-alsa"
            binary.touch()
            (root / "tokens.txt").touch()
            for name in ("encoder", "decoder", "joiner"):
                (root / f"{name}-{diagnose.STEM}.int8.onnx").touch()

            def run(command, check):
                keyword_file = next(x.split("=", 1)[1] for x in command if x.startswith("--keywords-file="))
                self.assertEqual(Path(keyword_file).read_text(), "▁HE Y ▁F O X @HEY_FOX\n")
                self.assertEqual(command[-1], "default")
                self.assertIn("--num-threads=1", command)
                return type("Completed", (), {"returncode": 0})()

            with patch.object(diagnose.subprocess, "run", side_effect=run):
                self.assertEqual(diagnose.main(["--word", "hey-fox", "--backend", "alsa", "--model-dir", str(root), "--bin-dir", str(root)]), 0)

    def test_missing_model_does_not_start_recording(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(diagnose.subprocess, "run") as run:
            self.assertEqual(diagnose.main(["--model-dir", temporary, "--bin-dir", temporary]), 1)
            run.assert_not_called()

    def test_portaudio_uses_default_input_without_alsa_device_argument(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sherpa-onnx-keyword-spotter-microphone").touch()
            (root / "tokens.txt").touch()
            for name in ("encoder", "decoder", "joiner"):
                (root / f"{name}-{diagnose.STEM}.int8.onnx").touch()
            with patch.object(diagnose.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(diagnose.main(["--backend", "portaudio", "--model-dir", str(root), "--bin-dir", str(root)]), 0)
                command = run.call_args.args[0]
                self.assertTrue(command[0].endswith("sherpa-onnx-keyword-spotter-microphone"))
                self.assertNotIn("default", command)

    def test_arecord_is_default_and_runs_worker_in_sherpa_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "python").touch()
            (root / "tokens.txt").touch()
            for name in ("encoder", "decoder", "joiner"):
                (root / f"{name}-{diagnose.STEM}.int8.onnx").touch()
            with patch.object(diagnose.subprocess, "run") as run, patch.object(diagnose.shutil, "which", return_value="/usr/bin/arecord"):
                run.return_value.returncode = 0
                self.assertEqual(diagnose.main(["--show-level", "--model-dir", str(root), "--bin-dir", str(root)]), 0)
                command = run.call_args.args[0]
                self.assertTrue(command[1].endswith("wakeword_arecord.py"))
                self.assertEqual(command[-3:], ["--device", "default", "--show-level"])
