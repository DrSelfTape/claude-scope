"""Analysis modes — opinionated configs and prompt templates.

A mode bundles together: a frame budget, a default time window, an OCR
preference, a scene-detection threshold, and a prompt template that Claude
should follow when writing the final answer. The orchestrator looks up the
mode and uses it to populate flag defaults; the prompt template is included
verbatim in the `scope.py` output block so Claude reads it together with the
frames and transcript.

Adding a mode = adding a `ModeConfig` to MODES below. Keep templates tight:
Claude doesn't need extensive guidance, it needs structure to follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModeConfig:
    name: str
    description: str
    # Time window override. (start, end) in seconds, or None to use the full video.
    window: tuple[float | None, float | None] = (None, None)
    # Frame budget. None means "use duration-based default."
    max_frames: int | None = None
    # Scene-detection threshold (0.0–1.0). Lower = more frames.
    scene_threshold: float = 0.3
    # OCR setting: "on", "off", or "auto" (decide based on video content).
    ocr: str = "auto"
    # Frame width in pixels.
    resolution: int = 512
    # Output template Claude should follow.
    template: str = ""


HOOK = ModeConfig(
    name="hook",
    description="Break down the first 10 seconds of a video — opening visual, line, on-screen text, pattern interrupts.",
    window=(0.0, 10.0),
    max_frames=30,
    scene_threshold=0.2,
    ocr="on",
    resolution=1024,  # creators put text on screen in hooks — need to read it
    template="""**Opening frame ([t=00:00]):** [describe what's visually on screen]
**Opening line:** "[exact quoted words from transcript at 00:00–00:03]"
**On-screen text:** [comma-separated OCR text from the 10s window]
**Pattern interrupts:**
- [MM:SS] [what changes — cut, zoom, new shot, text appears]
- [MM:SS] [...]
**Why it works:** [2–3 sentences on what hooks the viewer]
**What to steal:** [1–2 transferable tactics, named concretely]""",
)


SUMMARIZE = ModeConfig(
    name="summarize",
    description="Chapter-aware summary. TL;DR + per-chapter bullets + key takeaways.",
    max_frames=40,
    scene_threshold=0.4,  # sparser — we mostly trust the transcript here
    ocr="off",
    template="""**TL;DR:** [2 lines, no more]

**Chapter breakdown:**
- [MM:SS] **[Chapter title]** — [1–2 sentence summary grounded in transcript + frames]
- [MM:SS] **[Chapter title]** — [...]

**Key takeaways:**
- [Specific, actionable insight]
- [Specific, actionable insight]
- [Specific, actionable insight]

**Notable moments:** [MM:SS] [...], [MM:SS] [...]""",
)


BUG = ModeConfig(
    name="bug",
    description="Diagnose a bug from a screen recording. OCR is critical — error messages live in pixels.",
    max_frames=60,
    scene_threshold=0.25,  # screen recordings change less; lower threshold
    ocr="on",
    resolution=1024,  # need to read error text
    template="""**What's on screen:** [app name, current UI state, relevant context]
**Action that fails:** [MM:SS] [what the user does — click, input, navigation]
**Error / symptom:** "[exact text from screen or transcript, quoted]"
**Suspected cause:** [reasoning from what's visible]
**Next debug step:** [one concrete thing to try first]""",
)


CREATOR = ModeConfig(
    name="creator",
    description="Reverse-engineer why a video worked. Hook, structure, retention tactics, CTA, transferable moves.",
    max_frames=80,
    scene_threshold=0.25,
    ocr="on",
    template="""**Hook (0:00–0:10):**
- Opening visual: [describe]
- Opening line: "[exact quote]"
- Why it works: [1 sentence]

**Structure beats:**
- [MM:SS] [beat] — *function:* [hook / setup / payoff / pattern-interrupt / callback / CTA]
- [MM:SS] [beat] — *function:* [...]

**Retention tactics:**
- Pattern interrupts at: [MM:SS, MM:SS, ...]
- Open loops introduced: [MM:SS] [what's promised but not yet delivered]
- Visual rhythm: [jump cut density, B-roll usage, on-screen text frequency]

**Call to action:** [MM:SS] "[exact CTA]" — *placement strategy:* [start / mid / end]

**What to steal (top 3 transferable moves):**
1. [Move] — [why it works, how to apply]
2. [Move] — [...]
3. [Move] — [...]""",
)


LECTURE = ModeConfig(
    name="lecture",
    description="Extract a concept map from a lecture or tutorial. Quoted definitions, worked examples, by chapter.",
    max_frames=60,
    scene_threshold=0.35,
    ocr="on",  # slides
    resolution=1024,  # read slide text
    template="""**Concept map:**

- **[Chapter 1 title]** ([MM:SS]–[MM:SS])
  - **[Concept]:** [1-line definition grounded in transcript or slide]
  - **[Concept]:** [...]
- **[Chapter 2 title]** ([MM:SS]–[MM:SS])
  - **[Concept]:** [...]

**Quoted definitions:**
- [MM:SS] "[verbatim quote of a definition]"
- [MM:SS] "[...]"

**Worked examples:**
- [MM:SS] [Example title] — [what was demonstrated, with on-screen specifics from OCR]

**Open questions / unclear points:** [if any]""",
)


DEFAULT = ModeConfig(
    name="default",
    description="Free-form analysis. Use when no specific mode fits.",
    template="""Answer the user's question grounded in what you actually see and hear.

When you reference a moment, cite the timestamp: [MM:SS] or [HH:MM:SS].
When you quote dialogue, quote it verbatim.
When you describe what's on screen, describe what's in the frames — not what
you assume the video probably contains.
If the transcript and the frames seem to disagree, surface that disagreement.""",
)


MODES: dict[str, ModeConfig] = {
    m.name: m for m in [DEFAULT, HOOK, SUMMARIZE, BUG, CREATOR, LECTURE]
}


def get(name: str) -> ModeConfig:
    """Look up a mode by name. Falls back to DEFAULT on unknown names."""
    return MODES.get(name.lower(), DEFAULT)


def infer_from_question(question: str) -> str:
    """Best-effort mode inference from the user's question text.

    The orchestrator calls this when the user didn't pass --mode explicitly.
    Conservative: when in doubt, return 'default'.
    """
    q = (question or "").lower()

    # Hook analysis
    if any(kw in q for kw in [
        "hook", "opening", "first few seconds", "first 3 seconds",
        "first 10 seconds", "the open", "intro"
    ]):
        return "hook"

    # Bug diagnosis
    if any(kw in q for kw in [
        "bug", "broken", "error", "failing", "crash", "doesn't work",
        "isn't working", "what's wrong", "diagnose"
    ]):
        return "bug"

    # Creator analysis
    if any(kw in q for kw in [
        "why did this work", "why is this viral", "structure", "retention",
        "competitor", "creator", "viral", "what's the formula", "reverse engineer"
    ]):
        return "creator"

    # Lecture
    if any(kw in q for kw in [
        "lecture", "tutorial", "teach", "concept", "definition", "explain this"
    ]):
        return "lecture"

    # Summarize
    if any(kw in q for kw in [
        "summarize", "summary", "tl;dr", "tldr", "what's this about",
        "what happens in", "recap", "overview"
    ]):
        return "summarize"

    return "default"
