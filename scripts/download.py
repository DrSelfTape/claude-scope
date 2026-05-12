"""yt-dlp wrapper.

Pulls the video file, native captions (when present), and the full info JSON
(which carries chapters, description, duration, title) in one pass. Returns
absolute paths so the orchestrator doesn't have to guess what yt-dlp wrote.

For local files we skip the download entirely — `download.local()` just
verifies the file exists and probes duration.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DownloadResult:
    video_path: str          # absolute path to the downloaded media file
    info_json_path: str | None  # absolute path to the info JSON, if present
    caption_path: str | None    # absolute path to a .vtt subtitle, if any
    title: str | None
    duration: float
    window_start: float | None = None  # original-video offset (seconds) when a slice was downloaded
    window_end: float | None = None


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)


def _probe_duration(path: str) -> float:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def remote(url: str, out_dir: str,
           start: float | None = None, end: float | None = None) -> DownloadResult:
    """Download via yt-dlp. Writes into `out_dir`.

    If `start` and/or `end` are set, passes `--download-sections "*S-E"` so only
    the requested slice is fetched. The returned `DownloadResult` records the
    window so callers can shift downstream timestamps back into original-video
    coordinates.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # yt-dlp output template: deterministic filename so we can find it after.
    output_tmpl = str(out / "video.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720]+ba/b[height<=720]/best",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--write-subs", "--write-auto-subs",
        "--sub-lang", "en.*,en",
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--restrict-filenames",
        "-o", output_tmpl,
    ]

    if start is not None or end is not None:
        s = max(0.0, start if start is not None else 0.0)
        # yt-dlp accepts open-ended ranges via "*START-inf" — but the safer form
        # is to always specify both ends, so default end to a very large number
        # when None.
        e = end if end is not None else 99999.0
        cmd += ["--download-sections", f"*{s}-{e}", "--force-keyframes-at-cuts"]

    cmd.append(url)
    proc = _run(cmd)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"yt-dlp failed (exit {proc.returncode}) for url={url}")

    video_files = sorted(out.glob("video.*"))
    media_exts = {".mp4", ".mkv", ".webm", ".mov", ".m4a"}
    media_candidates = [p for p in video_files if p.suffix.lower() in media_exts]
    if not media_candidates:
        raise RuntimeError("yt-dlp succeeded but no media file was written.")
    video_path = str(media_candidates[0].resolve())

    info_candidates = list(out.glob("video.info.json"))
    info_path: str | None = str(info_candidates[0].resolve()) if info_candidates else None

    sub_candidates = sorted(out.glob("video.*.vtt"))
    caption_path: str | None = str(sub_candidates[0].resolve()) if sub_candidates else None

    title: str | None = None
    if info_path:
        try:
            info = json.loads(Path(info_path).read_text())
            title = info.get("title")
        except json.JSONDecodeError:
            info = {}

    duration = _probe_duration(video_path)

    return DownloadResult(
        video_path=video_path,
        info_json_path=info_path,
        caption_path=caption_path,
        title=title,
        duration=duration,
        window_start=start,
        window_end=end,
    )


def local(path: str) -> DownloadResult:
    """Use a local file as the source. No download."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")
    return DownloadResult(
        video_path=str(p),
        info_json_path=None,
        caption_path=None,
        title=p.stem,
        duration=_probe_duration(str(p)),
    )


def fetch(source: str, out_dir: str,
          start: float | None = None, end: float | None = None) -> DownloadResult:
    """Dispatch on URL vs local path. `start`/`end` only apply to remote URLs."""
    if "://" in source:
        return remote(source, out_dir, start=start, end=end)
    return local(source)


def _cli() -> int:
    p = argparse.ArgumentParser(description="Download a video for downstream processing.")
    p.add_argument("source", help="URL or local file path")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    r = fetch(args.source, args.out_dir)
    payload = {
        "video_path": r.video_path,
        "info_json_path": r.info_json_path,
        "caption_path": r.caption_path,
        "title": r.title,
        "duration": r.duration,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for k, v in payload.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
