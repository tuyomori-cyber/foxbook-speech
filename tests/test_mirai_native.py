"""Compare native inference to upstream Python for the same PCM windows.

Run with the onnx-wakeword experiment's Python after building native/mirai_kws.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    import numpy as np
    import onnxruntime
    from onnx_wakeword import WakeWordEngine
except ImportError:
    np = onnxruntime = WakeWordEngine = None

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = Path(os.environ.get("MIRAI_ROOT", Path.home() / "project/foxbook-mirai-test"))
MODELS = EXPERIMENT / "onnx-wakeword/models"
BINARY = ROOT / "build/native/mirai_kws"


@unittest.skipUnless(np is not None and BINARY.is_file() and (MODELS / "ja/model_info.json").is_file(), "mirai experiment dependencies unavailable")
class NativeParityTest(unittest.TestCase):
    def test_inference_scores_match_upstream(self):
        runtime = next((Path(onnxruntime.__file__).parent / "capi").glob("libonnxruntime.so.*"))
        mel = MODELS / "melspectrogram.onnx"
        engine = WakeWordEngine()
        engine.load(str(MODELS / "ja/model_info.json"), str(mel))
        samples = [np.zeros(16080, dtype="<i2"),
                   np.random.default_rng(42).integers(-10000, 10000, 16080, dtype=np.int16)]
        with tempfile.TemporaryDirectory() as directory:
            for audio in samples:
                raw = Path(directory) / "input.raw"
                audio.tofile(raw)
                result = subprocess.run([str(BINARY), "--runtime", str(runtime), "--mel", str(mel),
                                         "--model", str(MODELS / "ja/mirai_r1.onnx"), "--raw", str(raw)],
                                        check=True, capture_output=True, text=True)
                score = float(next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("score: ")))
                expected = engine.predict(audio.astype(np.float32))["prob"]
                self.assertAlmostEqual(score, expected, delta=1e-5)

    def test_tuner_reports_pitch_from_same_input(self):
        runtime = next((Path(onnxruntime.__file__).parent / "capi").glob("libonnxruntime.so.*"))
        t = np.arange(8000) / 16000
        audio = (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "tone.raw"
            audio.tofile(raw)
            result = subprocess.run([str(BINARY), "--runtime", str(runtime), "--mel", str(MODELS / "melspectrogram.onnx"),
                                     "--model", str(MODELS / "ja/mirai_r1.onnx"), "--raw", str(raw), "--tuner"],
                                    check=True, capture_output=True, text=True)
        pitches = [float(line.split(": ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("PITCH: ")]
        self.assertTrue(pitches)
        self.assertTrue(all(abs(frequency - 440) < 3 for frequency in pitches))


if __name__ == "__main__":
    unittest.main()
