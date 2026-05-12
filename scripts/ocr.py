"""OCR pass over extracted frames.

Tesseract is the default — it's free, installed via brew/apt, no API calls,
and good enough for the on-screen text most creator videos contain. We resize
each frame to a sane width for OCR (Tesseract chokes on huge images), then
return a `(frame_timestamp, text)` per frame.

We're deliberately permissive about errors here. OCR is additive: if Tesseract
isn't installed, or a frame fails to parse, we just skip it. The skill remains
useful without OCR; this is purely a "nice-to-have" layer for slide/code/text-
heavy videos.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class OCRResult:
    frame_path: str
    t_seconds: float
    text: str


def _have_tesseract() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_one(image_path: str) -> str:
    """Run tesseract on one image, return stripped text or empty string on error."""
    try:
        proc = subprocess.run(
            ["tesseract", image_path, "-", "-l", "eng", "--psm", "6"],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    # Collapse whitespace, drop short noise lines.
    lines = []
    for raw in proc.stdout.splitlines():
        line = " ".join(raw.split())
        if len(line) >= 3:
            lines.append(line)
    return " | ".join(lines)


def run(frames: list[tuple[float, str]]) -> list[OCRResult]:
    """Run OCR over a list of (timestamp, frame_path) tuples.

    Returns one OCRResult per frame that produced non-empty text. Frames with
    no detected text are dropped — they'd just be noise in the output block.
    """
    if not _have_tesseract():
        sys.stderr.write(
            "[scope] tesseract not installed — skipping OCR. "
            "Install with `brew install tesseract` (macOS) or `apt install tesseract-ocr` (Linux).\n"
        )
        return []

    results: list[OCRResult] = []
    for t, path in frames:
        text = _ocr_one(path)
        if text:
            results.append(OCRResult(frame_path=path, t_seconds=t, text=text))
    return results


def _cli() -> int:
    p = argparse.ArgumentParser(description="OCR a list of frames.")
    p.add_argument("--frames-json", required=True,
                   help="JSON file containing [{t_seconds, path}, ...]")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    raw = json.loads(Path(args.frames_json).read_text())
    pairs = [(float(f["t_seconds"]), f["path"]) for f in raw]
    out = run(pairs)

    if args.json:
        print(json.dumps([asdict(r) for r in out], indent=2))
    else:
        for r in out:
            m, s = divmod(int(r.t_seconds), 60)
            print(f"[t={m:02d}:{s:02d}] {r.text}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
