#!/usr/bin/env python3
"""Stream arecord's CD-format PCM into sherpa-onnx without saving audio."""
import argparse
from array import array
from pathlib import Path
import subprocess
import sys
import time

from diagnose_wakeword import STEM


def process_pcm(spotter, source, on_ready=print, show_level=False):
    stream = spotter.create_stream()
    ready = False
    peak = 0.0
    right_peak = 0.0
    next_level = time.monotonic() + 2
    while True:
        chunk = source.read(8192)
        if not chunk:
            break
        if len(chunk) % 4:
            raise RuntimeError("録音データが不完全です。")
        pcm = array("h")
        pcm.frombytes(chunk)
        if sys.byteorder != "little":
            pcm.byteswap()
        samples = [value / 32768.0 for value in pcm[::2]]
        if show_level:
            peak = max(peak, max((abs(value) for value in samples), default=0.0))
            right_peak = max(right_peak, max((abs(value) / 32768.0 for value in pcm[1::2]), default=0.0))
            if time.monotonic() >= next_level:
                print(f"入力ピーク: 左（検出に使用）{peak * 100:.1f}% / 右 {right_peak * 100:.1f}%", flush=True)
                peak = 0.0
                right_peak = 0.0
                next_level = time.monotonic() + 2
        stream.accept_waveform(44100, samples)
        if not ready:
            on_ready("マイク入力を受信中。話してください。終了は Ctrl+C。音声は保存しません。")
            ready = True
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = spotter.get_result(stream)
            if result:
                print(f"検出: {result}", flush=True)
                spotter.reset_stream(stream)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--keywords-file", type=Path, required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--show-level", action="store_true")
    args = parser.parse_args()
    try:
        import sherpa_onnx
        model = args.model_dir
        spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model / "tokens.txt"), encoder=str(model / f"encoder-{STEM}.int8.onnx"),
            decoder=str(model / f"decoder-{STEM}.int8.onnx"), joiner=str(model / f"joiner-{STEM}.int8.onnx"),
            keywords_file=str(args.keywords_file), keywords_threshold=args.threshold, num_threads=1, provider="cpu")
        process = subprocess.Popen(["arecord", "-q", "-D", args.device, "-f", "cd", "-t", "raw", "-"], stdout=subprocess.PIPE)
        try:
            process_pcm(spotter, process.stdout, lambda message: print(message, flush=True), args.show_level)
            code = process.wait()
            print(f"録音入力が終了しました（終了コード: {code}）。", file=sys.stderr)
            return code or 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
    except KeyboardInterrupt:
        return 130
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"ウェイクワード診断に失敗しました: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
