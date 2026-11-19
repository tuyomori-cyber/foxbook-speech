#!/usr/bin/env python3
"""Register only the dedicated test host without overwriting existing data."""
import json
import os
from pathlib import Path

HOST_NAME = "foxbook_native_port_probe"
EXTENSION_ID = "foxbook-native-port-probe@foxbook.example"
host = Path(__file__).resolve().with_name("probe_host.py")
manifest = Path.home() / ".mozilla" / "native-messaging-hosts" / f"{HOST_NAME}.json"
if not host.is_file() or not os.access(host, os.X_OK):
    raise SystemExit("検証Hostが見つからないか、実行権限がありません。")
manifest.parent.mkdir(parents=True, exist_ok=True)
try:
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump({"name": HOST_NAME, "description": "Foxbook test-only Native Port probe", "path": str(host),
                   "type": "stdio", "allowed_extensions": [EXTENSION_ID]}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
except FileExistsError:
    raise SystemExit(f"既存の登録を上書きしません: {manifest}")
print(f"登録しました: {manifest}")
