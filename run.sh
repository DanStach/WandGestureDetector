#!/usr/bin/env bash
# Usage: ./run.sh [--hdmi]   (--hdmi shows the annotated camera feed on the Pi's HDMI output)
set -euo pipefail
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

if [ "${1:-}" = "--hdmi" ]; then
  export WAND_HDMI=1
fi

exec python3 main.py
