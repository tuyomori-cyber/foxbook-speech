from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.install_service import install, render


class InstallServiceTest(unittest.TestCase):
    def test_render_uses_project_root_and_runtime_socket(self) -> None:
        content = render(Path("/example/foxbook-speech"))
        self.assertIn("WorkingDirectory=/example/foxbook-speech", content)
        self.assertIn("RuntimeDirectory=foxbook-speech", content)
        self.assertIn("--socket %t/foxbook-speech/foxbook-speech.sock", content)

    def test_install_writes_private_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "user" / "foxbook-speech.service"
            install(destination, Path("/example/foxbook-speech"))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertIn("WorkingDirectory=/example/foxbook-speech", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
