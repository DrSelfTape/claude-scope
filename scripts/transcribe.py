"""Transcript orchestration.

Two paths, in order of preference:

1. **VTT captions from yt-dlp.** If the video has captions (creator-uploaded
   or YouTube auto-generated), we parse the .vtt file directly. Free, instant,
   no API key.

2. **Whisper fallback.** When no VTT is available, we extract a mono 16 kHz
   audio track with ffmpeg and ship it to Groq's whisper-large-v3 (preferred)
   or OpenAI's whisper-1. The 25 MB upload cap is enforced upstream.

VTT parsing has one big gotcha: YouTube auto-captions emit overlapping cues
("rolling" subtitles where each cue contains the previous one plus new words).
The dedupe step here strips that out so we don't render the same words 3-4
times in the final transcript.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Importable as module or run as script.
try:
    from . import whisper as whisper_client  # type: ignore
except ImportError:
    import whisper as whisper_client  # type: ignore


@dataclass
class TranscriptLine:
    start: float
    text: str

    @property
    def start_mmss(self) -> str:
        m, s = divmod(int(self.start), 60)
        h, m = divmod(m, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_VTT_TIMESTAMP = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
)


def _vtt_ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _strip_vtt_inline_tags(text: str) -> str:
    # Remove things like <00:00:01.500><c> and </c>.
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def parse_vtt(vtt_path: str) -> list[TranscriptLine]:
    """Parse a .vtt file into TranscriptLine entries, de-duplicated.

    YouTube's "rolling" auto-caption format means cue N's text often contains
    cue N-1's text. We handle this by keeping only the *new* tail of each cue.
    """
    raw = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
    cues: list[TranscriptLine] = []
    current_start: float | None = None
    current_text: list[str] = []

    def flush():
        nonlocal current_start, current_text
        if current_start is not None and current_text:
            text = _strip_vtt_inline_tags(" ".join(current_text)).strip()
            if text:
                cues.append(TranscriptLine(start=current_start, text=text))
        current_start = None
        current_text = []

    for line in raw.splitlines():
        line = line.strip()
        m = _VTT_TIMESTAMP.match(line)
        if m:
            flush()
            current_start = _vtt_ts_to_seconds(m.group(1), m.group(2),
                                               m.group(3), m.group(4))
            continue
        if not line or line.startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")):
            continue
        if current_start is not None:
            current_text.append(line)
    flush()

    # Dedupe rolling captions.
    deduped: list[TranscriptLine] = []
    last_text = ""
    for cue in cues:
        text = cue.text
        if last_text and text.startswith(last_text):
            new_part = text[len(last_text):].strip()
            if new_part:
                deduped.append(TranscriptLine(start=cue.start, text=new_part))
            last_text = text
        elif text == last_text:
            continue
        else:
            deduped.append(cue)
            last_text = text
    return deduped


def extract_audio(video_path: str, out_path: str) -> str:
    """ffmpeg extract: mono 16 kHz MP3 — Whisper's sweet spot, well under 25 MB."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def transcribe_with_whisper(
    video_path: str,
    work_dir: str,
    provider: str = "groq",
) -> list[TranscriptLine]:
    audio_out = str(Path(work_dir) / "audio.mp3")
    extract_audio(video_path, audio_out)
    segs = whisper_client.transcribe(audio_out, provider=provider)
    return [TranscriptLine(start=s.start, text=s.text) for s in segs]


def get_transcript(
    video_path: str,
    work_dir: str,
    caption_path: str | None,
    whisper_provider: str = "groq",
    allow_whisper: bool = True,
) -> tuple[list[TranscriptLine], str]:
    """Return (lines, source). Source is one of: 'vtt', 'whisper', 'none'."""
    if caption_path and Path(caption_path).exists():
        lines = parse_vtt(caption_path)
        if lines:
            return lines, "vtt"
    if not allow_whisper:
        return [], "none"
    try:
        return transcribe_with_whisper(video_path, work_dir, whisper_provider), "whisper"
    except Exception as e:
        sys.stderr.write(f"[scope] Whisper transcription failed: {e}\n")
        return [], "none"


def _cli() -> int:
    p = argparse.ArgumentParser(description="Get a timestamped transcript.")
    p.add_argument("video")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--caption-path", default=None)
    p.add_argument("--whisper", choices=["groq", "openai", "off"], default="groq")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    lines, source = get_transcript(
        args.video, args.work_dir, args.caption_path,
        whisper_provider="groq" if args.whisper == "off" else args.whisper,
        allow_whisper=args.whisper != "off",
    )

    if args.json:
        print(json.dumps({
            "source": source,
            "lines": [asdict(l) for l in lines],
        }, indent=2))
    else:
        print(f"source: {source}")
        for l in lines:
            print(f"[{l.start_mmss}] {l.text}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
