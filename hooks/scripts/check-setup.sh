#!/usr/bin/env bash
# Lightweight startup check — print a one-line status if dependencies are missing.
# Non-blocking: we just inform the user; the skill's setup.py handles actual install.

set -u

MISSING=()
command -v yt-dlp >/dev/null 2>&1 || MISSING+=("yt-dlp")
command -v ffmpeg >/dev/null 2>&1 || MISSING+=("ffmpeg")

if [ "${#MISSING[@]}" -gt 0 ]; then
  printf '[claude-scope] missing: %s — run `/scope --setup` to install\n' "${MISSING[*]}" >&2
fi

exit 0
