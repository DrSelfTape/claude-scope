#!/usr/bin/env bash
# Build dist/scope.skill for claude.ai upload.
#
# A .skill bundle is just a zip with SKILL.md at the root plus any scripts the
# skill calls. We mirror Brad's convention so it's drop-in compatible with the
# "Skills" UI under claude.ai Settings → Capabilities.

set -euo pipefail

cd "$(dirname "$0")/.."

OUT="dist/scope.skill"
rm -rf dist
mkdir -p dist staging

cp SKILL.md staging/
cp -r scripts staging/
cp LICENSE staging/

# Strip pycache before bundling.
find staging -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

(cd staging && zip -r "../${OUT}" .)
rm -rf staging

echo "Built: ${OUT}"
ls -lh "${OUT}"
