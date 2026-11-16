#!/usr/bin/env python3
"""Install the shared foxbook_speech Native Messaging manifest for Firefox."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

HOST_NAME = "foxbook_speech"
EXTENSIONS = ["fox-voice-editor@foxbook.example"]
HOST = Path(__file__).resolve().parents[1] / "native_host/foxbook_speech.py"
MANIFEST = Path.home() / ".mozilla/native-messaging-hosts" / f"{HOST_NAME}.json"


def main() -> None:
    if not HOST.is_file() or not os.access(HOST, os.X_OK):
        raise SystemExit("Native Hostが見つからないか、実行権限がありません。")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=MANIFEST.parent, prefix=f".{HOST_NAME}.", delete=False) as stream:
        json.dump({"name": HOST_NAME, "description": "foxbook shared local speech adapter", "path": str(HOST),
                   "type": "stdio", "allowed_extensions": EXTENSIONS}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        staged = Path(stream.name)
    try:
        staged.chmod(0o600)
        os.replace(staged, MANIFEST)
    finally:
        staged.unlink(missing_ok=True)
    print(f"登録しました: {MANIFEST}")


if __name__ == "__main__":
    main()
