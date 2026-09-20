# IR Gesture Detection System

Real-time IR-reflector wand gesture recognition for a Raspberry Pi 3B+. Tracks a
retroreflective wand tip via an IR camera, pattern-matches the trajectory against
configurable gestures (circle, line, dwell, figure-8, zigzag), and triggers actions
(MP3, video, GPIO, webhook) — no ML, fully deterministic.

See [`CLAUDE.md`](CLAUDE.md) for the full architecture, design decisions, and
configuration reference.

## Quick start (local dev, no camera required)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

With no camera attached, the detection loop idles and the FastAPI admin server still
comes up at `http://localhost:8000`:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/gestures
curl http://localhost:8000/api/actions
curl http://localhost:8000/api/stats
```

## On the Raspberry Pi (headless, Raspberry Pi OS Lite)

```bash
pip3 install -r requirements.txt -r requirements-rpi.txt
python3 main.py
```

See `CLAUDE.md` → **Setup & Running** for the `systemd` unit to run this on boot.
