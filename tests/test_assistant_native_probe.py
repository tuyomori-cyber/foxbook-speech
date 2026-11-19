import json
import os
from pathlib import Path
import struct
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "assistant-ui/native-port-probe/probe_host.py"
EXTENSION_ID = "foxbook-native-port-probe@foxbook.example"


class NativePortProbeTest(unittest.TestCase):
    def test_host_ready_and_exit_when_browser_closes_pipe(self):
        self.assertTrue(os.access(HOST, os.X_OK))
        process = subprocess.Popen([str(HOST), "/test/manifest.json", EXTENSION_ID],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            payload = json.dumps({"version": 1, "action": "start", "durationSeconds": 300}).encode()
            process.stdin.write(struct.pack("=I", len(payload)) + payload)
            process.stdin.flush()
            header = process.stdout.read(4)
            self.assertEqual(len(header), 4)
            result = json.loads(process.stdout.read(struct.unpack("=I", header)[0]))
            self.assertEqual(result["event"], "ready")
            self.assertEqual(result["pid"], process.pid)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=3), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            if not process.stdin.closed:
                process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_rejects_other_extension(self):
        result = subprocess.run([str(HOST), "/test/manifest.json", "wrong@example.invalid"],
                                input=b"", capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)

    def test_rejects_unsupported_duration(self):
        payload = json.dumps({"version": 1, "action": "start", "durationSeconds": 1}).encode()
        frame = struct.pack("=I", len(payload)) + payload
        result = subprocess.run([str(HOST), "/test/manifest.json", EXTENSION_ID],
                                input=frame, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
