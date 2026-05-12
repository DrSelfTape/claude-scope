"""Preflight + installer.

Two modes:

- `--check` (default): silent if everything's there; one-line warning otherwise.
  Designed to be called on session start by hooks/scripts/check-setup.sh.

- `--install`: actually install missing dependencies. On macOS uses Homebrew.
  On Linux/Windows we print the exact commands rather than running anything
  destructive — the caller can copy-paste.

Also scaffolds `~/.config/scope/.env` with placeholder API keys (mode 0600) so
the user has one obvious place to put them.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED = ["yt-dlp", "ffmpeg", "ffprobe"]
OPTIONAL = ["tesseract"]  # OCR — nice to have


def _missing(tools: list[str]) -> list[str]:
    return [t for t in tools if shutil.which(t) is None]


def _detect_os() -> str:
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        return "macos"
    if sys_name == "linux":
        return "linux"
    if sys_name == "windows":
        return "windows"
    return "unknown"


def _install_macos(missing: list[str]) -> None:
    if not shutil.which("brew"):
        print("Homebrew not found. Install it first: https://brew.sh")
        return
    pkgs = []
    for m in missing:
        # ffprobe ships with ffmpeg.
        if m == "ffprobe":
            pkgs.append("ffmpeg")
        else:
            pkgs.append(m)
    pkgs = sorted(set(pkgs))
    if not pkgs:
        return
    print(f"Installing via Homebrew: {' '.join(pkgs)}")
    subprocess.run(["brew", "install", *pkgs], check=False)


def _print_linux_instructions(missing: list[str]) -> None:
    pkgs = []
    for m in missing:
        if m == "ffprobe":
            pkgs.append("ffmpeg")
        elif m == "yt-dlp":
            pkgs.append("yt-dlp")
        else:
            pkgs.append(m)
    pkgs = sorted(set(pkgs))
    print("Run one of:")
    print(f"  sudo apt install {' '.join(pkgs)}")
    print(f"  sudo dnf install {' '.join(pkgs)}")
    print(f"  pipx install yt-dlp   # if yt-dlp isn't in your distro repos")


def _print_windows_instructions(missing: list[str]) -> None:
    pkgs = []
    for m in missing:
        if m == "ffprobe":
            pkgs.append("ffmpeg")
        elif m == "yt-dlp":
            pkgs.append("yt-dlp")
        else:
            pkgs.append(m)
    pkgs = sorted(set(pkgs))
    print("Run:")
    print(f"  winget install {' '.join(pkgs)}")
    print("Or with Scoop:")
    print(f"  scoop install {' '.join(pkgs)}")


def _scaffold_env() -> Path:
    """Create ~/.config/scope/.env with commented placeholders if not present."""
    cfg_dir = Path.home() / ".config" / "scope"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = cfg_dir / ".env"
    if env_path.exists():
        return env_path

    env_path.write_text(
        "# scope — Whisper API keys.\n"
        "# Only one is needed; Groq is preferred (cheaper + faster).\n"
        "# Captions cover most public videos for free; these are only used\n"
        "# as a fallback when no caption track exists.\n"
        "\n"
        "# GROQ_API_KEY=...\n"
        "# OPENAI_API_KEY=...\n"
    )
    os.chmod(env_path, 0o600)
    return env_path


def _check(quiet: bool) -> int:
    missing_req = _missing(REQUIRED)
    missing_opt = _missing(OPTIONAL)

    if quiet and not missing_req:
        return 0

    if missing_req:
        print(f"[scope] missing required: {', '.join(missing_req)}")
        print("Run: scripts/setup.py --install")
    else:
        print("[scope] required tools present.")

    if missing_opt:
        print(f"[scope] missing optional: {', '.join(missing_opt)} (OCR will be skipped)")
    return 0 if not missing_req else 1


def _install() -> int:
    missing = _missing(REQUIRED + OPTIONAL)
    if not missing:
        print("[scope] all dependencies already present.")
    else:
        sys_name = _detect_os()
        if sys_name == "macos":
            _install_macos(missing)
        elif sys_name == "linux":
            _print_linux_instructions(missing)
        elif sys_name == "windows":
            _print_windows_instructions(missing)
        else:
            print("Unknown OS. Install manually: " + ", ".join(missing))

    env_path = _scaffold_env()
    print(f"[scope] env file: {env_path}")
    if not os.environ.get("GROQ_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print(f"  Add a GROQ_API_KEY or OPENAI_API_KEY to {env_path} (optional — only used if no captions).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="scope dependency check / install.")
    p.add_argument("--check", action="store_true", help="Silent check; exit 1 if missing required deps.")
    p.add_argument("--install", action="store_true", help="Install missing dependencies (macOS only; prints commands elsewhere).")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if args.install:
        return _install()
    return _check(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
