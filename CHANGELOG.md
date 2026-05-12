# Changelog

## 0.1.2 — 2026-05-12

- Chapter detection no longer degrades to a single "Full video" block on tightly
  edited talking-head content. `from_silence` now retries with progressively
  looser thresholds (-35dB/2.0s → -30dB/1.2s → -25dB/0.8s) before giving up,
  and a new `from_even_split` source kicks in as the final fallback so
  summarize/lecture modes always get usable structure.

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
