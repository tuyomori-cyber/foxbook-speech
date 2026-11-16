#!/usr/bin/env python3
"""Install the per-user systemd unit for foxbook-speech.

The script only writes the unit by default.  Pass ``--enable`` after reviewing
the generated file to reload systemd and start the service for this user.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "systemd/foxbook-speech.service.in"
UNIT_NAME = "foxbook-speech.service"


def render(project_root: Path = PROJECT_ROOT) -> str:
    return TEMPLATE.read_text(encoding="utf-8").replace("@PROJECT_ROOT@", str(project_root))


def install(destination: Path, project_root: Path = PROJECT_ROOT) -> None:
    content = render(project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                     prefix=f".{UNIT_NAME}.", delete=False) as stream:
        stream.write(content)
        staged = Path(stream.name)
    try:
        staged.chmod(0o600)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable", action="store_true", help="daemon-reload後にenable --nowする")
    args = parser.parse_args()
    destination = Path.home() / ".config/systemd/user" / UNIT_NAME
    install(destination)
    print(f"unitを書き込みました: {destination}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=True)
        print(f"有効化しました: {UNIT_NAME}")
    else:
        print("内容を確認後、起動するには --enable を付けて再実行してください。")


if __name__ == "__main__":
    main()
