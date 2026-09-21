#!/usr/bin/env bash
# Prepare Raspberry Pi OS Lite (Trixie, 32-bit) to run the gesture system.
# Run from the repo root on the Pi: ./scripts/setup-pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt update
sudo apt install -y git python3-venv python3-picamera2 python3-opencv python3-numpy \
  python3-rpi-lgpio alsa-utils ffmpeg mpv mpg123

# --system-site-packages so the venv sees the apt-provided picamera2/cv2/numpy/GPIO
python3 -m venv --system-site-packages .venv
# Plain uvicorn: the [standard] extra pulls uvloop, which has no armv7 wheel and needs python3-dev to build
.venv/bin/pip install fastapi uvicorn pydantic

echo "Camera check:"
rpicam-hello --list-cameras || echo "No camera detected - check ribbon cable (power off first)."
echo "Done. Start with ./run.sh"
