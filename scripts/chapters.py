"""Chapter detection for long-form video handling.

Brad's skill prints a "sparse scan" warning when a video is over 10 minutes and
calls it a day. That's the right diagnosis but the wrong fix. The real fix:
detect the structure of the video and analyze each chapter on its own terms.

Four sources, in order of reliability:

1. **yt-dlp metadata** — many YouTube creators set explicit chapters via
   description timestamps; yt-dlp extracts them into `info.json["chapters"]`.
   This is the gold standard: titles and exact ranges, set by the creator.

2. **Description timestamp parsing** — older or less-polished videos use a
   "table of contents" in the description with `MM:SS Topic` lines but no
   YouTube-recognized chapter markers. We parse those.

3. **Silence-based segmentation** — for screen recordings, local files, and
   anything without metadata. We use ffmpeg's `silencedetect` filter to find
   long pauses, retrying with progressively looser thresholds for tightly
   edited talking-head videos.

4. **Even-time split** — last resort when nothing else yields signal (heavily
   edited videos with no metadata and no silences). Divides the video into
   roughly equal segments so downstream summarize/lecture analysis still has
   structure to anchor against.

The result is a list of Chapter objects with start/end timestamps and a title.
Downstream code uses these to scope frame extraction and to drive
chapter-by-chapter analysis in `summarize` and `lecture` modes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Chapter:
    start: float
    end: float
    title: str

    @property
    def start_mmss(self) -> str:
        return _mmss(self.start)

    @property
    def end_mmss(self) -> str:
        return _mmss(self.end)


def _mmss(s: float) -> str:
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ---------- Source 1: yt-dlp metadata ----------

def from_info_json(info: dict) -> list[Chapter]:
    """Pull chapters from yt-dlp's info dict. Returns [] if none present."""
    raw = info.get("chapters") or []
    chapters: list[Chapter] = []
    for ch in raw:
        try:
            chapters.append(Chapter(
                start=float(ch["start_time"]),
                end=float(ch["end_time"]),
                title=str(ch.get("title") or "Untitled chapter"),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return chapters


# ---------- Source 2: description parsing ----------

_TS_LINE = re.compile(
    r"""
    ^\s*
    (?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2})    # HH:MM:SS or MM:SS
    \s*[—–\-:\)]?\s*
    (?P<title>.+?)
    \s*$
    """,
    re.VERBOSE,
)


def _parse_ts(s: str) -> float | None:
    parts = s.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def from_description(description: str, total_duration: float) -> list[Chapter]:
    """Parse a description block looking for MM:SS-prefixed lines.

    YouTube's chapter detection requires the first line to start at 0:00 and
    have at least 3 chapters with 10+ seconds between them. When that fails,
    creators still drop timestamps in their description — we pick them up.
    """
    if not description:
        return []

    candidates: list[tuple[float, str]] = []
    for line in description.splitlines():
        m = _TS_LINE.match(line)
        if not m:
            continue
        ts = _parse_ts(m.group("ts"))
        title = m.group("title").strip()
        if ts is None or not title or ts > total_duration:
            continue
        candidates.append((ts, title))

    # Need at least 2 timestamps to constitute a chapter list.
    if len(candidates) < 2:
        return []

    # Sort and build start/end ranges.
    candidates.sort(key=lambda x: x[0])
    chapters: list[Chapter] = []
    for i, (ts, title) in enumerate(candidates):
        end = candidates[i + 1][0] if i + 1 < len(candidates) else total_duration
        chapters.append(Chapter(start=ts, end=end, title=title))
    return chapters


# ---------- Source 3: silence-based segmentation ----------

_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")


_SILENCE_PASSES = [
    # (silence_db, min_silence_s) — tried in order until we get boundaries.
    (-35, 2.0),  # default: clear pauses in normally-spoken content
    (-30, 1.2),  # looser: tighter-edited podcast/long-form
    (-25, 0.8),  # loosest: rapid-cut talking-head / vlog
]


def from_silence(
    video_path: str,
    total_duration: float,
    target_chapters: int = 8,
) -> list[Chapter]:
    """Detect long silences in the audio track and treat them as topic boundaries.

    Retries with progressively looser thresholds before giving up. Returns []
    when no boundaries are found at any threshold — callers should fall back
    to even-time-splitting.
    """
    if total_duration < 60:
        return [Chapter(start=0, end=total_duration, title="Full video")]

    boundaries: list[float] = []
    for silence_db, min_silence_s in _SILENCE_PASSES:
        cmd = [
            "ffmpeg", "-hide_banner", "-i", video_path,
            "-af", f"silencedetect=noise={silence_db}dB:d={min_silence_s}",
            "-f", "null", "-",
        ]
        proc = _run(cmd)
        boundaries = []
        for line in proc.stderr.splitlines():
            m = _SILENCE_END.search(line)
            if m:
                try:
                    boundaries.append(float(m.group(1)))
                except ValueError:
                    continue
        if boundaries:
            break

    if not boundaries:
        return []

    # Thin the boundary list to roughly target_chapters segments.
    if len(boundaries) > target_chapters - 1:
        step = len(boundaries) / (target_chapters - 1)
        boundaries = [boundaries[int(i * step)] for i in range(target_chapters - 1)]

    boundaries = [0.0, *boundaries, total_duration]
    chapters: list[Chapter] = []
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        if e - s < 30:  # collapse short segments into the previous one
            if chapters:
                chapters[-1] = Chapter(start=chapters[-1].start, end=e,
                                       title=chapters[-1].title)
            continue
        chapters.append(Chapter(start=s, end=e, title=f"Segment {len(chapters) + 1}"))
    return chapters


# ---------- Source 4: even-time split (last resort) ----------

def from_even_split(total_duration: float, target_seconds: float = 240.0,
                    min_chapters: int = 3, max_chapters: int = 10) -> list[Chapter]:
    """Last-resort: divide the video into roughly equal time chunks.

    Used when no metadata, description, or silence signal is available.
    Chapter titles are generic ("Segment N") — Claude's downstream prompt is
    expected to relabel them from the transcript.
    """
    if total_duration < 60:
        return [Chapter(start=0, end=total_duration, title="Full video")]

    n = max(min_chapters, min(max_chapters, round(total_duration / target_seconds)))
    chunk = total_duration / n
    return [
        Chapter(start=i * chunk,
                end=(i + 1) * chunk if i < n - 1 else total_duration,
                title=f"Segment {i + 1}")
        for i in range(n)
    ]


# ---------- Orchestrator ----------

def detect(
    info_json_path: str | None,
    video_path: str,
    total_duration: float,
) -> tuple[list[Chapter], str]:
    """Try each source in order. Returns (chapters, source_used)."""
    info: dict = {}
    if info_json_path and Path(info_json_path).exists():
        try:
            info = json.loads(Path(info_json_path).read_text())
        except json.JSONDecodeError:
            info = {}

    # 1. yt-dlp chapters.
    chapters = from_info_json(info)
    if chapters:
        return chapters, "yt-dlp"

    # 2. Description parsing.
    description = info.get("description") or ""
    chapters = from_description(description, total_duration)
    if chapters:
        return chapters, "description"

    # 3. Silence detection.
    chapters = from_silence(video_path, total_duration)
    if chapters:
        return chapters, "silence"

    # 4. Even-time split (no signal available).
    return from_even_split(total_duration), "even-split"


def _cli() -> int:
    p = argparse.ArgumentParser(description="Chapter detection.")
    p.add_argument("video")
    p.add_argument("--info-json", default=None)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    chapters, source = detect(args.info_json, args.video, args.duration)

    if args.json:
        print(json.dumps({
            "source": source,
            "chapters": [asdict(c) for c in chapters],
        }, indent=2))
    else:
        print(f"source: {source}")
        for c in chapters:
            print(f"[{c.start_mmss} - {c.end_mmss}] {c.title}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
