# /scope — Watch any video with Claude

Hand Claude a video URL or local path, ask a question, get an answer grounded in frames *and* transcript. Built for Claude Code as a `/scope` slash command.

**Latest: [v0.1.4](https://github.com/DrSelfTape/claude-scope/releases/tag/v0.1.4)** — `--start` / `--end` now constrain the yt-dlp download itself, so scoping a 3-minute slice of a 4-hour video fetches in seconds instead of minutes. Plus chapter-detection fixes for tightly edited talking-head content. See [CHANGELOG.md](CHANGELOG.md).

```
/scope https://youtu.be/<id> what's the hook?
/scope https://youtu.be/<id> summarize this
/scope ~/Movies/screen-recording.mp4 what's broken?
/scope https://youtu.be/<id> --start 2:15 --end 2:45 what happens here?
```

## Install

```
/plugin marketplace add yourname/claude-scope
/plugin install scope@claude-scope
```

First run installs `yt-dlp` and `ffmpeg` via Homebrew on macOS (commands printed on Linux/Windows). Captions cover most public videos for free; a Groq or OpenAI API key only matters when a video has no captions.

## What's different

This started as "I want to build my own version of [Brad's claude-video skill](https://github.com/bradautomates/claude-video) but better." Three deliberate improvements:

**Scene-aware frames, not fixed-fps.** Brad samples at a duration-scaled fps. That over-samples talking-head shots where nothing changes for 8 seconds, and under-samples viral content where a frame can flash for half a second. Scope uses ffmpeg's scene-detection filter to extract frames *where the image actually changes*, then perceptual-hash dedupes near-identical neighbors. Same token budget, much better coverage.

**Chapter-aware long videos.** Brad's "sparse scan" warning for >10 min videos is the right diagnosis but the wrong fix. Scope detects structure: YouTube chapters → description timestamps → silence-based segmentation. The `summarize` and `lecture` modes go chapter-by-chapter instead of scattering 100 frames across 30 minutes.

**Opinionated analysis modes.** Brad's skill answers free-form questions over frames + transcript. Scope ships with `hook`, `summarize`, `bug`, `creator`, and `lecture` modes — each tuned with the right frame budget, time window, OCR setting, and an output template Claude follows. The `creator` mode in particular exists to reverse-engineer why a viral video worked: hook, structure beats, retention tactics, CTA, transferable moves. The mode is inferred from your question if you don't pass `--mode`.

OCR comes along for the ride — Tesseract runs on extracted frames in modes where on-screen text matters (hooks, bugs, lectures), so slide content, code, and error messages get pulled into the text channel rather than being trapped in pixels.

## How it works

```
URL or path
    ↓
yt-dlp  ──→  video file + info.json + .vtt captions (if available)
    ↓
chapters.py  ──→  yt-dlp chapters || description timestamps || silence segments
    ↓
frames.py  ──→  ffmpeg scene-detect → perceptual-hash dedup → budget cap
    ↓
ocr.py  ──→  tesseract pass (when mode demands it)
    ↓
transcribe.py  ──→  parse VTT (de-dupe rolling captions) || Whisper fallback
    ↓
scope.py emits a structured block: frames + OCR + transcript + prompt template
    ↓
Claude `Read`s every frame as an image and follows the mode's template
```

## Modes

| Mode | When to use | Output |
|------|-------------|--------|
| `default` | Open-ended question | Free-form answer grounded in frames + transcript |
| `hook` | "Break down the opening" | Opening visual, line, on-screen text, pattern interrupts, why it works, what to steal |
| `summarize` | "What's this about" | TL;DR + chapter-by-chapter + key takeaways |
| `bug` | Screen recording of broken software | What's on screen, action that fails, error text, suspected cause, next debug step |
| `creator` | "Why did this work" | Hook + structure beats + retention tactics + CTA + 3 moves to steal |
| `lecture` | "Teach me what's in this" | Concept map per chapter + quoted definitions + worked examples |

If you don't pass `--mode`, scope picks one from your question. Keywords: "hook/opening" → `hook`, "broken/error/bug" → `bug`, "viral/structure/retention" → `creator`, "lecture/concept" → `lecture`, "summarize/tl;dr" → `summarize`. Otherwise → `default`.

## Flags

```
--mode {default,hook,summarize,bug,creator,lecture}
--start MM:SS            # Focus on a window
--end MM:SS
--max-frames N           # Cap total frames; defaults from mode
--scene-threshold F      # 0.0–1.0; lower = more frames
--resolution W           # Frame width in px (default 512; bump to 1024 for slide/code)
--ocr {auto,on,off}
--no-chapters            # Skip detection for short videos
--whisper {groq,openai,off}
--out-dir DIR            # Pin working dir (default: auto tmp)
--json                   # Machine-readable output
--setup                  # Install deps + scaffold env
```

## Bring your own keys

| Capability | What you need | Cost |
|------------|---------------|------|
| Download + native captions | `yt-dlp` + `ffmpeg` | Free |
| Whisper fallback (preferred) | [Groq API key](https://console.groq.com/keys) | Cheap, fast |
| Whisper fallback (alt) | [OpenAI API key](https://platform.openai.com/api-keys) | Standard pricing |
| OCR | `tesseract` (free, local) | Free |
| Disable Whisper entirely | `--whisper off` | Free, frames + captions only |

Keys live in `~/.config/scope/.env` (mode 0600). The setup script scaffolds it with commented placeholders.

## Structure

```
claude-scope/
├── SKILL.md                  # skill contract Claude reads on every /scope call
├── README.md
├── CHANGELOG.md
├── LICENSE                   # MIT
├── commands/
│   └── scope.md              # /scope slash command
├── scripts/
│   ├── scope.py              # orchestrator (entry point)
│   ├── download.py           # yt-dlp wrapper
│   ├── frames.py             # scene-aware frame extraction
│   ├── chapters.py           # chapter detection (yt-dlp / description / silence)
│   ├── ocr.py                # tesseract pass on frames
│   ├── transcribe.py         # VTT parse + Whisper fallback
│   ├── whisper.py            # Groq + OpenAI clients (pure stdlib)
│   ├── modes.py              # mode configs + prompt templates
│   ├── setup.py              # preflight + installer
│   └── build-skill.sh        # bundle dist/scope.skill for claude.ai
├── hooks/
│   ├── hooks.json
│   └── scripts/check-setup.sh
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
└── .github/workflows/
    └── release.yml
```

## Limits

- **Best accuracy under 10 minutes.** Past that, use `--mode summarize` (chapter-aware) or `--start`/`--end` to scope a window. Since 0.1.4, `--start`/`--end` triggers a partial download via yt-dlp's `--download-sections`, so windowed scoping on multi-hour videos is fast.
- **Frame ceiling: 100.** Hard cap, even when scene detection finds more.
- **Whisper upload cap: 25 MB.** ~50 min of mono 16 kHz audio. For longer transcription-required videos, use chapters + frames only.
- **No private platforms.** Public URLs or local files. If yt-dlp can't reach it anonymously, neither can scope.

## License

MIT. See [LICENSE](LICENSE).

Built on `yt-dlp`, `ffmpeg`, Tesseract, and Claude's multimodal `Read` tool. Whisper transcription via Groq or OpenAI.

Inspired by Brad Bonanno's [claude-video](https://github.com/bradautomates/claude-video) (MIT). Architecture and code here are original; the conceptual debt is acknowledged.
