#!/usr/bin/env python3
"""scope — orchestrator.

Pipeline:
1. Download (yt-dlp) or probe local file.
2. Detect chapters (yt-dlp metadata → description timestamps → silence segments).
3. Extract scene-aware frames (with optional --start/--end window).
4. OCR each frame (if mode requires it).
5. Get transcript (VTT captions → Whisper fallback).
6. Print a structured output block Claude can `Read` against, ending in the
   mode-specific prompt template.

Calling convention:
    scope.py <URL_OR_PATH> [QUESTION_AS_FREE_TEXT] [--mode ...] [other flags]

The free-text question (anything after the URL/path that isn't a flag) is used
for mode inference when --mode isn't passed explicitly. The orchestrator does
not interpret the question itself — that's Claude's job after reading the output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

# Local imports — add script dir to sys.path so this runs both as a script and
# when invoked via a Claude Code skill where __file__ isn't necessarily on path.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import chapters as chapters_mod  # noqa: E402
import download as download_mod  # noqa: E402
import frames as frames_mod      # noqa: E402
import modes as modes_mod        # noqa: E402
import ocr as ocr_mod            # noqa: E402
import transcribe as transcribe_mod  # noqa: E402


# ---------- arg parsing ----------

def _parse_timecode(s: str | None) -> float | None:
    if s is None:
        return None
    if ":" not in s:
        return float(s)
    parts = [float(p) for p in s.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Bad timecode: {s}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scope",
        description="Watch any video with Claude.",
    )
    p.add_argument("source", nargs="?", help="URL or local file path")
    p.add_argument("question", nargs="*", help="Free-text question (used for mode inference)")
    p.add_argument("--mode", choices=list(modes_mod.MODES.keys()), default=None)
    p.add_argument("--start", default=None, help="Window start (MM:SS or HH:MM:SS or seconds)")
    p.add_argument("--end", default=None, help="Window end")
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--scene-threshold", type=float, default=None)
    p.add_argument("--resolution", type=int, default=None)
    p.add_argument("--ocr", choices=["auto", "on", "off"], default=None)
    p.add_argument("--no-chapters", action="store_true")
    p.add_argument("--whisper", choices=["groq", "openai", "off"], default="groq")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--setup", action="store_true",
                   help="Run preflight installer instead of normal pipeline.")
    return p


# ---------- pipeline ----------

def run(args: argparse.Namespace) -> int:
    if args.setup:
        from setup import main as setup_main  # noqa: WPS433
        return setup_main()  # type: ignore[no-any-return]

    if not args.source:
        print("error: source URL or path required", file=sys.stderr)
        return 2

    # Resolve mode + flag defaults from mode config.
    question_text = " ".join(args.question or [])
    mode_name = args.mode or modes_mod.infer_from_question(question_text)
    mode = modes_mod.get(mode_name)

    # Window: explicit args override mode defaults.
    start = _parse_timecode(args.start)
    end = _parse_timecode(args.end)
    if start is None and end is None:
        start, end = mode.window

    scene_threshold = args.scene_threshold if args.scene_threshold is not None else mode.scene_threshold
    resolution = args.resolution if args.resolution is not None else mode.resolution
    max_frames = args.max_frames if args.max_frames is not None else mode.max_frames

    if args.ocr is not None:
        ocr_setting = args.ocr
    else:
        ocr_setting = mode.ocr
    use_ocr = ocr_setting == "on" or (ocr_setting == "auto" and mode.ocr in {"on", "auto"})

    # Working directory — under tmpdir unless user pinned one.
    if args.out_dir:
        work_dir = Path(args.out_dir).expanduser().resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_root = Path(tempfile.gettempdir()) / ".scope-work"
        tmp_root.mkdir(parents=True, exist_ok=True)
        work_dir = tmp_root / uuid.uuid4().hex[:10]
        work_dir.mkdir(parents=True, exist_ok=True)

    # 1) Download or probe local file.
    dl = download_mod.fetch(args.source, str(work_dir / "media"))

    # 2) Chapters.
    if args.no_chapters:
        chapter_list, chapter_source = [], "skipped"
    else:
        chapter_list, chapter_source = chapters_mod.detect(
            dl.info_json_path, dl.video_path, dl.duration,
        )

    # 3) Frames.
    frame_list = frames_mod.extract(
        dl.video_path, str(work_dir / "frames"),
        scene_threshold=scene_threshold,
        max_frames=max_frames,
        width=resolution,
        start=start, end=end,
    )

    # 4) OCR.
    ocr_results = []
    if use_ocr and frame_list:
        ocr_results = ocr_mod.run([(f.t_seconds, f.path) for f in frame_list])

    # 5) Transcript.
    transcript_lines, transcript_source = transcribe_mod.get_transcript(
        dl.video_path, str(work_dir / "audio"),
        caption_path=dl.caption_path,
        whisper_provider="groq" if args.whisper == "off" else args.whisper,
        allow_whisper=args.whisper != "off",
    )

    # If user gave us a window, clip the transcript to it for compactness.
    if start is not None or end is not None:
        s = start if start is not None else 0
        e = end if end is not None else float("inf")
        transcript_lines = [l for l in transcript_lines if s <= l.start <= e]

    # 6) Emit the structured block.
    if args.json:
        _emit_json(work_dir, dl, mode, chapter_list, chapter_source,
                   frame_list, ocr_results, transcript_lines, transcript_source)
    else:
        _emit_human(work_dir, dl, mode, chapter_list, chapter_source,
                    frame_list, ocr_results, transcript_lines, transcript_source)
    return 0


# ---------- output formatters ----------

def _emit_human(work_dir, dl, mode, chapter_list, chapter_source,
                frame_list, ocr_results, transcript_lines, transcript_source):
    print("=== scope output ===")
    print(f"working_dir: {work_dir}")
    print(f"source: {dl.video_path}")
    if dl.title:
        print(f"title: {dl.title}")
    print(f"duration: {dl.duration:.1f}s")
    print(f"mode: {mode.name}")
    print()

    print(f"chapters ({chapter_source}):")
    if chapter_list:
        for c in chapter_list:
            print(f"  [{c.start_mmss} - {c.end_mmss}] {c.title}")
    else:
        print("  (none)")
    print()

    print(f"frames ({len(frame_list)}):")
    for f in frame_list:
        print(f"  [t={f.t_mmss}] {f.path}")
    print()

    if ocr_results:
        print(f"ocr ({len(ocr_results)} frames):")
        for r in ocr_results:
            m, s = divmod(int(r.t_seconds), 60)
            print(f"  [t={m:02d}:{s:02d}] {r.text}")
        print()

    print(f"transcript ({transcript_source}, {len(transcript_lines)} lines):")
    for l in transcript_lines:
        print(f"  [{l.start_mmss}] {l.text}")
    print()

    print("prompt_template:")
    for line in mode.template.splitlines():
        print(f"  {line}")
    print("=== end scope output ===")


def _emit_json(work_dir, dl, mode, chapter_list, chapter_source,
               frame_list, ocr_results, transcript_lines, transcript_source):
    out = {
        "working_dir": str(work_dir),
        "source": dl.video_path,
        "title": dl.title,
        "duration": dl.duration,
        "mode": mode.name,
        "chapters": {
            "source": chapter_source,
            "items": [asdict(c) for c in chapter_list],
        },
        "frames": [
            {"t_seconds": f.t_seconds, "t_mmss": f.t_mmss, "path": f.path}
            for f in frame_list
        ],
        "ocr": [asdict(r) for r in ocr_results],
        "transcript": {
            "source": transcript_source,
            "lines": [asdict(l) for l in transcript_lines],
        },
        "prompt_template": mode.template,
    }
    print(json.dumps(out, indent=2))


# ---------- entry ----------

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
