import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_wakeword.py"
spec = importlib.util.spec_from_file_location("diagnose_wakeword", SCRIPT)
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)


class WakewordDiagnosticTest(unittest.TestCase):
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
                self.assertEqual(diagnose.main(["--word", "hey-fox", "--model-dir", str(root), "--bin-dir", str(root)]), 0)

    def test_missing_model_does_not_start_recording(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(diagnose.subprocess, "run") as run:
            self.assertEqual(diagnose.main(["--model-dir", temporary, "--bin-dir", temporary]), 1)
            run.assert_not_called()
