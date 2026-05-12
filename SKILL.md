---
name: scope
description: Watch any video and analyze it. Trigger when the user pastes a YouTube/TikTok/Vimeo/Loom URL or a local video path and asks a question, requests a summary, asks about a specific moment, wants a hook breakdown, or hands over a screen recording with a bug. Also triggers on "watch this", "scope this video", "what happens at MM:SS", "summarize this video", "analyze the hook", or any creator-style video analysis ask.
---

# scope — watch any video with Claude

Claude can't natively see video. This skill closes the gap: it downloads the video, picks frames where the image actually changes (not on a fixed clock), pulls a timestamped transcript, optionally runs OCR on the frames, and hands all of that to Claude as images + text. Claude then `Read`s each frame and answers grounded in what's actually on screen and in the audio.

The skill is opinionated about *what* it returns. There are modes — `hook`, `summarize`, `bug`, `creator`, `lecture`, `default` — each tuned for a different use case. Modes change the frame budget, the time window, whether OCR runs, and the prompt structure Claude should follow.

## When to invoke

Any of these patterns:

- The user pastes a video URL or path and asks a question
- "Watch this video", "scope this", "what's in this video"
- "What happens at 2:30", "summarize the last minute"
- "Analyze the hook on this", "break down the opening"
- "What's going wrong" + a screen recording
- "Summarize this lecture", "what tools does she mention"

Don't invoke for: audio-only files (just transcribe directly), images (use Read), or content that's already a transcript.

## Invocation

```
$CLAUDE_PLUGIN_ROOT/scripts/scope.py <URL_OR_PATH> [--mode MODE] [--start MM:SS] [--end MM:SS] [other flags]
```

The script prints a structured block to stdout containing: working directory, mode, chapter list, frame paths with `t=MM:SS` markers, timestamped transcript, optional per-frame OCR text, and a mode-specific prompt template. **Read every frame path it prints** — those are JPEGs and render as images in your context. Then follow the mode's prompt template to write the answer.

## Modes

| Mode | When to use | Frame budget | Time window | OCR | Output shape |
|------|-------------|--------------|-------------|-----|--------------|
| `default` | User asks an open-ended question | Auto (scene-aware) | Full | Off | Free-form answer grounded in frames + transcript |
| `hook` | "Analyze the hook", "break down the opening" | Dense (~30 frames) | 0:00–0:10 forced | On | Opening visual, opening line, pattern interrupts, on-screen text, why it works/doesn't |
| `summarize` | "Summarize this", "what's this about" | Sparse (~40 frames) | Full | Off | TL;DR (2 lines) + chapter-by-chapter bullets + key takeaways |
| `bug` | Screen recording + "what's broken" | Dense around scene changes | Full | On | What's on screen, what action fails, what the error says, suspected cause |
| `creator` | "Why did this video work", "competitor analysis" | Sparse | Full | On | Hook (0–10s), structure beats, retention tactics, CTA, what to steal |
| `lecture` | "What did she teach", "key concepts" | Sparse | Full | On | Chapter-by-chapter concept map + quoted definitions + worked examples |

If the user doesn't name a mode, infer it. "Summarize" → `summarize`. "Hook" or "opening" → `hook`. Screen recording + words like "broken/error/bug" → `bug`. Otherwise use `default`.

## Mode-specific behavior

### `hook`
Forces `--start 0:00 --end 0:10` unless user overrides. Forces OCR on (creators put text on screen in hooks). Output template:

```
**Opening frame (0:00):** [what's visually on screen]
**Opening line:** "[exact words from transcript]"
**On-screen text:** [OCR results, comma-separated]
**Pattern interrupts:** [scene changes in the 10s window, by timestamp]
**Why it works:** [2–3 sentence analysis]
**What to steal:** [1–2 transferable tactics]
```

### `summarize`
Reads YouTube chapters if present. If chapters exist, the summary is structured per-chapter. If not, it segments by transcript-density gaps. Output template:

```
**TL;DR:** [2 lines max]

**Chapter breakdown:**
- [MM:SS] [Chapter title] — [1–2 sentence summary]
- ...

**Key takeaways:**
- [Bullet 1]
- [Bullet 2]
- [Bullet 3]
```

### `bug`
OCR is critical here — error messages live in pixels. Output template:

```
**What's on screen:** [app, UI state]
**Action that fails:** [MM:SS] [what the user does]
**Error/symptom:** "[exact text from screen or transcript]"
**Suspected cause:** [reasoning]
**Next debug step:** [one concrete thing to try]
```

### `creator`
This is the money mode for content analysis. Output template:

```
**Hook (0–10s):** [opening visual + line + why]
**Structure beats:**
- [MM:SS] [beat] — [function: hook / setup / payoff / callback / CTA]
**Retention tactics:** [pattern interrupts, open loops, jump cuts noted by timestamp]
**Call to action:** [MM:SS] "[exact CTA]"
**What to steal:** [3 transferable moves]
```

### `lecture`
Output template:

```
**Concept map:**
- [Chapter 1 title]
  - [Concept]: [1-line definition]
  - [Concept]: [1-line definition]
- [Chapter 2 title]
  ...
**Quoted definitions:** [verbatim from transcript with MM:SS]
**Worked examples:** [if any, with timestamps]
```

## Flags the script accepts

- `--mode {default,hook,summarize,bug,creator,lecture}` — see table above.
- `--start MM:SS` / `--end MM:SS` — focused window. Denser frame budget per second.
- `--max-frames N` — cap total frames. Defaults to mode budget.
- `--scene-threshold F` — ffmpeg scene-change sensitivity (0.0–1.0). Default 0.3. Lower → more frames.
- `--resolution W` — frame width in px. Default 512, bump to 1024 for slide/code-heavy videos.
- `--ocr {auto,on,off}` — auto follows the mode default. Force on for unreadable creator videos.
- `--no-chapters` — skip chapter detection (faster, useful for short videos).
- `--whisper {groq,openai,off}` — transcript fallback when captions unavailable. Default `groq`.
- `--out-dir DIR` — working directory. Defaults to an auto tmp dir; printed at end.
- `--setup` — run the preflight installer (yt-dlp, ffmpeg, API keys).
- `--json` — emit machine-readable JSON to stdout instead of human-readable blocks. Useful when chaining into other tools.

## Workflow Claude should follow

1. Parse the user's message: pull out the URL/path, infer the mode, extract any time window they mentioned ("around 2:30" → `--start 2:15 --end 2:45`).
2. Run `scripts/scope.py` with the inferred args.
3. The script prints a block like:

   ```
   === scope output ===
   working_dir: /tmp/.scope-work/abc123
   mode: hook
   chapters: [{"start": 0, "end": 47, "title": "Intro"}, ...]
   frames:
     [t=00:01] /tmp/.scope-work/abc123/frames/0001.jpg
     [t=00:03] /tmp/.scope-work/abc123/frames/0002.jpg
     ...
   transcript:
     [00:00] "Hey everyone, today I want to show you..."
     [00:04] "...the exact prompt I used to..."
     ...
   ocr:
     [t=00:01] "MAKE $5K/MONTH WITH CLAUDE"
     ...
   prompt_template:
     [the mode's output template]
   === end scope output ===
   ```

4. `Read` every frame path printed. Each is a JPEG — Claude renders these directly as images.
5. Write the answer using the mode's `prompt_template`. Be grounded — when you cite a moment, include the timestamp.
6. After answering, if the user is unlikely to follow up, delete the `working_dir` (the script doesn't auto-delete to support follow-ups).

## Constraints

- **Frames dominate token cost.** Default cap is 100 frames; modes adjust this down. Don't override upward unless the user explicitly asks for more detail.
- **Long videos** (>10 min) without chapters get a "sparse scan" warning. When you see this, suggest the user re-run with `--mode summarize` (chapter-aware) or a focused `--start`/`--end`.
- **Whisper has a 25 MB upload cap.** That's ~50 min of mono 16 kHz audio. The script splits longer audio, but if you see a transcription failure, fall back to chapters + frames only.
- **No private platforms.** No auth. If yt-dlp can't reach the URL anonymously, neither can scope.
- **Cite by timestamp.** Every claim about what's in the video should come with a `[MM:SS]` so the user can verify.

## Failure modes & recovery

- `yt-dlp` not installed → run `scripts/scope.py --setup`, then retry.
- Whisper API key missing AND no captions → re-run with `--whisper off`; you'll get frames + chapters only, no spoken-word transcript.
- Scene detection finds <5 frames in a long video → re-run with `--scene-threshold 0.15` to pick up subtler cuts.
- OCR returns garbage → drop `--ocr off` and rely on Claude reading the frames at `--resolution 1024`.

## Output discipline

Don't paraphrase the transcript — quote it with `"..."` and a timestamp. Don't invent timestamps. Don't claim a frame shows something it doesn't. If you didn't `Read` a frame, don't reference it. If the transcript and the frames disagree, say so.
