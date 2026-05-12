"""Whisper API clients — pure stdlib, no heavy deps.

Two providers:
- Groq (preferred): cheaper, faster, uses `whisper-large-v3`.
- OpenAI (fallback): uses `whisper-1`.

Both expose a `transcribe(audio_path)` returning a list of (start_seconds, text)
segments. The caller (`transcribe.py`) renders those into a unified timestamped
transcript regardless of which provider answered.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Segment:
    start: float
    text: str


def _multipart_encode(fields: dict[str, str], file_field: str, file_path: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body. Returns (body_bytes, content_type)."""
    boundary = f"----scopeBoundary{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value.encode())
    lines.append(f"--{boundary}".encode())
    fname = Path(file_path).name
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{fname}"'.encode()
    )
    lines.append(b"Content-Type: audio/mpeg")
    lines.append(b"")
    lines.append(Path(file_path).read_bytes())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def _call(url: str, api_key: str, body: bytes, content_type: str) -> dict:
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"Whisper API error {e.code}: {body_text}") from e


def transcribe_groq(audio_path: str, model: str = "whisper-large-v3") -> list[Segment]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    body, ctype = _multipart_encode(
        {"model": model, "response_format": "verbose_json", "temperature": "0"},
        "file", audio_path,
    )
    result = _call(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        api_key, body, ctype,
    )
    return [Segment(start=float(s["start"]), text=s["text"].strip())
            for s in result.get("segments", [])
            if s.get("text", "").strip()]


def transcribe_openai(audio_path: str, model: str = "whisper-1") -> list[Segment]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    body, ctype = _multipart_encode(
        {"model": model, "response_format": "verbose_json", "temperature": "0"},
        "file", audio_path,
    )
    result = _call(
        "https://api.openai.com/v1/audio/transcriptions",
        api_key, body, ctype,
    )
    return [Segment(start=float(s["start"]), text=s["text"].strip())
            for s in result.get("segments", [])
            if s.get("text", "").strip()]


def transcribe(audio_path: str, provider: str = "groq") -> list[Segment]:
    """Dispatch to a provider. 'groq' falls back to 'openai' if no Groq key."""
    if provider == "groq":
        if os.environ.get("GROQ_API_KEY"):
            return transcribe_groq(audio_path)
        if os.environ.get("OPENAI_API_KEY"):
            sys.stderr.write("[scope] GROQ_API_KEY missing, falling back to OpenAI.\n")
            return transcribe_openai(audio_path)
        raise RuntimeError(
            "No Whisper API key set. Set GROQ_API_KEY (preferred) or OPENAI_API_KEY, "
            "or pass --whisper off to skip transcription."
        )
    if provider == "openai":
        return transcribe_openai(audio_path)
    raise ValueError(f"Unknown provider: {provider}")


def _cli() -> int:
    p = argparse.ArgumentParser(description="Whisper transcription.")
    p.add_argument("audio")
    p.add_argument("--provider", choices=["groq", "openai"], default="groq")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    segs = transcribe(args.audio, args.provider)
    if args.json:
        print(json.dumps([asdict(s) for s in segs], indent=2))
    else:
        for s in segs:
            m, sec = divmod(int(s.start), 60)
            print(f"[{m:02d}:{sec:02d}] {s.text}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
