# Changelog

## 0.1.7 — 2026-05-12

- Use yt-dlp's native `inf` for open-ended `--download-sections` ranges
  instead of a magic `99999` sentinel. Verified against yt-dlp source via
  Context7 MCP — no behavior change.

## 0.1.6 — 2026-05-12

- Add **authority stacking** to the creator-mode pattern library in SKILL.md.
  When analyzing a video, look for claims backed by 4 named signals in a
  30s window (named customer + named end-user + named source + specific
  number) instead of 1.

## 0.1.5 — 2026-05-12

- SKILL.md upgrades — Claude now reads, on every `/scope` call:
  - A pre-run windowing decision step (default to `--start`/`--end` on long
    videos when the question is about a specific section).
  - A note that frame timestamps stay in original-video coordinates on
    windowed runs.
  - A creator-mode "patterns to look for" list: dual-mode visual rhythm,
    comparison-matrix positioning, lead-magnet drip, kinetic captions,
    tone-flip cuts.

## 0.1.4 — 2026-05-12

- `--start` and `--end` now also constrain the yt-dlp download via
  `--download-sections`, so windowed runs on long-form content actually
  skip the unused portions instead of fetching the whole file. A 3-minute
  window on a 4-hour video drops download time from minutes to seconds.
- Output timestamps stay in original-video coordinates even when only a
  slice was downloaded: frames are shifted by the window offset, the
  duration line reads `180.0s (window 60s-240s of original)`, and a single
  synthesized `Window` chapter replaces silence-based chapter detection on
  windowed runs.

## 0.1.3 — 2026-05-12

- Subdivide chapters longer than 6 minutes into ~4-minute sub-segments so
  silence detection no longer leaves a 14-minute "Segment 3" when the
  speaker has a long uninterrupted middle section. Real chapter titles
  (yt-dlp / description sources) are preserved on the first sub-slice and
  suffixed with " (cont.)" on later ones.

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
