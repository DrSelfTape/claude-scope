# Changelog

## 0.1.1 — 2026-05-12

- Fix hooks.json schema (wrap events in top-level `hooks` record so Claude Code's loader accepts them)
- Fix docs: scope.py is invoked directly (it has a python3 shebang), not via `bash`

## 0.1.0 — 2026-05-12

Initial release.

- `/scope` slash command for Claude Code
- Scene-aware frame extraction (ffmpeg scene-detect + perceptual-hash dedup) replaces fixed-fps sampling
- Chapter-aware long-video handling: yt-dlp chapters → description timestamps → silence segmentation
- Five opinionated analysis modes:
  - `hook` — first-10-seconds breakdown with OCR
  - `summarize` — chapter-aware TL;DR + takeaways
  - `bug` — screen-recording diagnosis with OCR
  - `creator` — viral video reverse-engineering
  - `lecture` — concept map with quoted definitions
- Auto mode inference from the user's question
- VTT caption parsing with rolling-caption dedupe
- Whisper fallback via Groq (preferred) or OpenAI
- Optional Tesseract OCR pass on frames
- JSON output mode (`--json`) for pipeline use
- Cross-platform setup script (brew on macOS; prints commands elsewhere)
