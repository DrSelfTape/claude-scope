"""Scene-aware frame extraction.

The key idea: don't extract frames on a fixed clock. Use ffmpeg's scene-change
detector to extract frames *where the image actually changes*, then de-duplicate
near-identical frames using a perceptual hash. This gives much better coverage
of fast-cut content (creator hooks, ads, tutorials with quick demos) and stops
wasting the token budget on 10-second-long talking-head shots.

Pipeline:
1. ffmpeg scene-detection pass writes candidate frames with `t=<seconds>` in filename.
2. Perceptual-hash dedup pass drops frames within `hash_distance` of a neighbor.
3. Budget-cap pass evenly subsamples if we still exceed `max_frames`.

If scene detection finds fewer than `min_frames` frames (e.g. a static lecture),
we top up with a uniform-time pass so the user isn't left with a sparse output.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Frame:
    """A single extracted frame, identified by its timestamp in the source video."""

    t_seconds: float
    path: str

    @property
    def t_mmss(self) -> str:
        m, s = divmod(int(self.t_seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


def _budget_for_duration(duration_s: float, focused: bool) -> int:
    """Default frame budget given total duration. Focused mode (start/end) is denser."""
    if focused:
        if duration_s <= 15:
            return 25
        if duration_s <= 60:
            return 40
        return 60
    if duration_s <= 30:
        return 30
    if duration_s <= 60:
        return 40
    if duration_s <= 180:
        return 60
    if duration_s <= 600:
        return 80
    return 100


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _probe_duration(video_path: str) -> float:
    """Return duration in seconds via ffprobe."""
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ])
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _ffmpeg_scene_extract(
    video_path: str,
    out_dir: Path,
    scene_threshold: float,
    width: int,
    start: float | None,
    end: float | None,
) -> list[Frame]:
    """Single ffmpeg pass: keep frames whose scene-change score exceeds threshold.

    Uses `showinfo` filter to print the timestamp of each kept frame; we parse
    those out of stderr to build the Frame list.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "scene_%05d.jpg")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "info"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", video_path]
    if end is not None and start is not None:
        cmd += ["-t", f"{end - start:.3f}"]
    elif end is not None:
        cmd += ["-t", f"{end:.3f}"]

    vf = f"select='gt(scene,{scene_threshold})',showinfo,scale={width}:-2"
    cmd += ["-vf", vf, "-vsync", "vfr", "-q:v", "3", pattern]

    proc = _run(cmd)
    # showinfo lines look like: "[Parsed_showinfo_1 @ 0x...] n:0 pts:..  pts_time:1.234 ..."
    timestamps: list[float] = []
    for line in proc.stderr.splitlines():
        if "pts_time:" in line and "Parsed_showinfo" in line:
            try:
                ts = float(line.split("pts_time:")[1].split()[0])
                # ffmpeg's -ss before -i makes pts_time relative to the cut,
                # so add `start` back to get absolute video time.
                if start is not None:
                    ts += start
                timestamps.append(ts)
            except (IndexError, ValueError):
                continue

    files = sorted(out_dir.glob("scene_*.jpg"))
    # Pair timestamps with files. ffmpeg writes them in order, so zip is safe;
    # if counts mismatch, truncate to the shorter — better than guessing.
    frames = [Frame(t_seconds=t, path=str(p)) for t, p in zip(timestamps, files)]
    return frames


def _ffmpeg_uniform_extract(
    video_path: str,
    out_dir: Path,
    n: int,
    width: int,
    start: float | None,
    end: float | None,
    duration_s: float,
) -> list[Frame]:
    """Fallback: extract `n` evenly-spaced frames. Used when scene detection
    produces too few results (typical for static lectures, screen recordings)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    s = start if start is not None else 0.0
    e = end if end is not None else duration_s
    if e <= s or n <= 0:
        return []
    step = (e - s) / n
    frames: list[Frame] = []
    for i in range(n):
        t = s + step * i + step / 2  # center of each bin
        out_path = out_dir / f"uniform_{i:05d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{t:.3f}", "-i", video_path,
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out_path),
        ]
        _run(cmd)
        if out_path.exists():
            frames.append(Frame(t_seconds=t, path=str(out_path)))
    return frames


def _perceptual_dedup(frames: list[Frame], min_distance: int = 4) -> list[Frame]:
    """Drop frames whose dHash is within `min_distance` of the previous keeper.

    dHash is a 64-bit perceptual hash: compare pixel-wise differences in an 8x9
    grid, output a bit per comparison. Tiny implementation in pure Python via
    Pillow — installed transitively by most ffmpeg setups; if missing, we skip.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return frames  # dedup is best-effort

    def dhash(path: str) -> int:
        with Image.open(path) as im:
            im = im.convert("L").resize((9, 8))
            px = list(im.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                left = px[row * 9 + col]
                right = px[row * 9 + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return bits

    kept: list[Frame] = []
    last_hash: int | None = None
    for f in frames:
        try:
            h = dhash(f.path)
        except Exception:
            kept.append(f)
            continue
        if last_hash is None or bin(h ^ last_hash).count("1") >= min_distance:
            kept.append(f)
            last_hash = h
    return kept


def _budget_cap(frames: list[Frame], max_frames: int) -> list[Frame]:
    """If we still have too many frames, evenly subsample to fit the budget."""
    if len(frames) <= max_frames:
        return frames
    step = len(frames) / max_frames
    return [frames[int(i * step)] for i in range(max_frames)]


def extract(
    video_path: str,
    out_dir: str,
    scene_threshold: float = 0.3,
    max_frames: int | None = None,
    width: int = 512,
    start: float | None = None,
    end: float | None = None,
    min_frames: int = 8,
) -> list[Frame]:
    """Main entry. Returns a list of Frame objects with absolute timestamps."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration(video_path)
    focused = start is not None or end is not None
    if max_frames is None:
        effective_duration = (end or duration) - (start or 0)
        max_frames = _budget_for_duration(effective_duration, focused)

    # 1) Scene-change pass.
    scene_frames = _ffmpeg_scene_extract(
        video_path, out / "scene", scene_threshold, width, start, end,
    )

    # 2) If too sparse, top up with uniform sampling.
    frames = scene_frames
    if len(frames) < min_frames:
        topup = _ffmpeg_uniform_extract(
            video_path, out / "uniform",
            n=max_frames - len(frames),
            width=width, start=start, end=end, duration_s=duration,
        )
        frames = sorted(frames + topup, key=lambda f: f.t_seconds)

    # 3) Perceptual-hash dedup.
    frames = _perceptual_dedup(frames)

    # 4) Final budget cap.
    frames = _budget_cap(frames, max_frames)

    # Rename to a clean sequential pattern so downstream output is tidy.
    final_dir = out / "frames"
    final_dir.mkdir(exist_ok=True)
    final: list[Frame] = []
    for i, f in enumerate(frames):
        new_path = final_dir / f"{i+1:04d}.jpg"
        try:
            shutil.copy2(f.path, new_path)
        except FileNotFoundError:
            continue
        final.append(Frame(t_seconds=f.t_seconds, path=str(new_path)))
    return final


def _cli() -> int:
    p = argparse.ArgumentParser(description="Scene-aware frame extraction.")
    p.add_argument("video", help="Path to local video file")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--scene-threshold", type=float, default=0.3)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--resolution", type=int, default=512)
    p.add_argument("--start", type=float, default=None)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    frames = extract(
        args.video, args.out_dir,
        scene_threshold=args.scene_threshold,
        max_frames=args.max_frames,
        width=args.resolution,
        start=args.start, end=args.end,
    )

    if args.json:
        print(json.dumps([asdict(f) for f in frames], indent=2))
    else:
        for f in frames:
            print(f"[t={f.t_mmss}] {f.path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
