---
description: Scope out any video — watch it, summarize it, break down the hook, diagnose a bug, or reverse-engineer why it worked.
argument-hint: <URL or path> [question...] [--mode MODE] [--start MM:SS] [--end MM:SS]
---

# /scope

Hand Claude any video and a question. It downloads, picks frames where the image changes, transcribes, optionally OCRs, then answers — grounded in the timestamps.

Usage:

```
/scope https://youtu.be/<id> what's the hook?
/scope https://youtu.be/<id> summarize this --mode summarize
/scope ~/Movies/bug.mov what's broken? --mode bug
/scope https://youtu.be/<id> --start 2:15 --end 2:45 what happens here?
```

Behind the scenes Claude runs `bash $CLAUDE_PLUGIN_ROOT/scripts/scope.py "$ARGUMENTS"` and reads every frame the script emits.

## Modes

- `hook` — first 10 seconds, dense frames, OCR on. For analyzing openings.
- `summarize` — chapter-aware TL;DR + per-chapter bullets + takeaways.
- `bug` — for screen recordings of broken software. OCR on; error-text focused.
- `creator` — reverse-engineer why a video works. Hook + structure + retention + CTA.
- `lecture` — concept map of a tutorial or lecture. Quoted definitions.
- `default` — open-ended question, free-form answer.

If you don't pass `--mode`, scope infers from your question.

## Setup

First-time:
```
/scope --setup
```

This installs `yt-dlp` and `ffmpeg` (via Homebrew on macOS, prints commands elsewhere) and scaffolds `~/.config/scope/.env` for an optional Whisper API key (only needed when a video has no captions).
