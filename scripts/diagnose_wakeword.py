#!/usr/bin/env python3
"""Standalone sherpa-onnx KWS experiment; not part of the speech service."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
MODEL_DIR = ROOT / "models" / "kws" / MODEL_NAME
BIN_DIR = ROOT.parent / "reazonspeech" / ".venv" / "bin"
STEM = "epoch-12-avg-2-chunk-16-left-64"
# Generated with this model's bpe.model, using SentencePiece on uppercase text.
KEYWORDS = {"fox": "▁F O X @FOX", "hey-fox": "▁HE Y ▁F O X @HEY_FOX"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="軽量KWSでFOXまたはHEY FOXを検出する単独診断")
    parser.add_argument("--word", choices=KEYWORDS, default="fox", help="検出語句（既定: fox）")
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR, help="公式英語KWSモデルのディレクトリ")
    parser.add_argument("--bin-dir", type=Path, default=BIN_DIR, help="sherpa-onnx実行ファイルのディレクトリ")
    parser.add_argument("--backend", choices=("arecord", "alsa", "portaudio"), default="arecord", help="マイク入力方式（既定: arecord）")
    parser.add_argument("--device", default="default", help="ALSA入力デバイス（既定: default）")
    parser.add_argument("--wav", type=Path, help="マイクの代わりにモノラルPCM WAVを解析")
    parser.add_argument("--threshold", type=float, default=0.25, help="検出閾値0〜1（既定: 0.25）")
    parser.add_argument("--show-level", action="store_true", help="arecord入力のピークを2秒ごとに表示")
    parser.add_argument("--report-every", type=int, default=10, help="CPU/RSS表示間隔。0で非表示（既定: 10）")
    args = parser.parse_args(argv)
    if not 0 <= args.threshold <= 1:
        parser.error("--thresholdは0〜1で指定してください")

    executable = args.bin_dir / ("sherpa-onnx-keyword-spotter" if args.wav else
                                  "python" if args.backend == "arecord" else
                                  "sherpa-onnx-keyword-spotter-alsa" if args.backend == "alsa" else
                                  "sherpa-onnx-keyword-spotter-microphone")
    if not args.wav and args.backend == "portaudio" and args.device != "default":
        parser.error("--deviceはarecordかALSA入力でのみ指定できます")
    if args.show_level and (args.wav or args.backend != "arecord"):
        parser.error("--show-levelはarecord入力でのみ使用できます")
    if args.report_every < 0:
        parser.error("--report-everyは0以上で指定してください")
    if not args.wav and args.backend == "arecord" and not shutil.which("arecord"):
        print("arecordが見つかりません。", file=sys.stderr)
        return 1
    files = {
        "tokens": args.model_dir / "tokens.txt",
        "encoder": args.model_dir / f"encoder-{STEM}.int8.onnx",
        "decoder": args.model_dir / f"decoder-{STEM}.int8.onnx",
        "joiner": args.model_dir / f"joiner-{STEM}.int8.onnx",
    }
    for path in [executable, *files.values(), *([args.wav] if args.wav else [])]:
        if not path.is_file():
            print(f"必要なファイルが見つかりません: {path}", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory(prefix="foxbook-kws-") as directory:
        keywords = Path(directory) / "keywords.txt"
        keywords.write_text(KEYWORDS[args.word] + "\n", encoding="utf-8")
        if not args.wav and args.backend == "arecord":
            command = [str(executable), str(ROOT / "scripts" / "wakeword_arecord.py"),
                       "--model-dir", str(args.model_dir), "--keywords-file", str(keywords),
                       "--threshold", str(args.threshold), "--device", args.device]
            if args.show_level:
                command.append("--show-level")
            command.extend(["--report-every", str(args.report_every)])
        else:
            command = [str(executable), *(f"--{name}={path}" for name, path in files.items()),
                       f"--keywords-file={keywords}", f"--keywords-threshold={args.threshold}",
                       "--num-threads=1", "--provider=cpu", "--print-args=false"]
        if args.wav:
            command.append(str(args.wav))
        elif args.backend == "alsa":
            command.append(args.device)
        if not args.wav:
            print(f"{args.word.upper().replace('-', ' ')} の検出を準備中。音声は保存しません。", flush=True)
        try:
            return subprocess.run(command, check=False).returncode
        except KeyboardInterrupt:
            print("\n監視を終了しました。", flush=True)
            return 130
        except OSError as exc:
            print(f"検出器を起動できません: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
