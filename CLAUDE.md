# IR Gesture Detection System

**Project**: Real-time IR reflector wand gesture recognition on Raspberry Pi 3B+  
**Goal**: Detect gestures (circular motion, flicks, dwells, etc.) via IR tracking and trigger actions (MP3, video, GPIO)  
**Owner**: Dan (Daniel John Stach) / Deep Current Technologies LLC  
**Timezone**: America/Chicago (UTC-05:00)

---

## Tech Stack

**Core**:
- Python 3.9+
- OpenCV 4.8 (blob detection, real-time processing)
- FastAPI (web admin interface)
- AsyncIO (non-blocking execution)

**Hardware**:
- Raspberry Pi 3B+
- OS: Raspberry Pi OS Lite (32-bit armhf, Debian 13 "Trixie") — headless, no desktop environment
- Arducam IR Camera (5MP, OV5647, 1080p)
- IR reflector-tipped wand (retroreflective material)

**Deployment**:
- RPi GPIO library (servo, LED, relay control)
- mpg123/ffplay (mp3 audio; `aplay`/`paplay` are WAV-only fallbacks)
- ffplay/mpv (HDMI video; omxplayer does not exist on Trixie)

---

## Architecture

```
Detection Loop (async)
  ↓
  Camera → Grayscale Frame → IR Blob Detector → BlobTracker
                                                    ↓
                                            Trajectory Classifier
                                                    ↓
                                            GestureClassifier
                                                    ↓
                                            ActionRegistry → ActionExecutor
                                                    ↓
                                    [MP3 | Video | GPIO | Webhook]

Parallel: FastAPI Web Server
  ├─ GET/POST /api/gestures → Gesture CRUD
  ├─ GET/POST /api/actions → Action mapping
  └─ GET /api/stats → Live FPS, blob count, trajectory
```

**Key Design Decisions**:
1. **No ML**: Pattern matching over SVM training. Faster iteration, no data collection needed.
2. **Async queue**: Actions don't block detection loop. MP3/video playback is non-blocking.
3. **JSON config**: Gestures and actions are fully configurable without code changes.
4. **SimpleBlobDetector**: Proven for IR reflectors, lightweight, deterministic.

---

## Project Layout

```
ir-gesture-system/
├── camera/
│   ├── __init__.py
│   └── detector.py              # IRDetector, BlobTracker classes
│
├── gestures/
│   ├── __init__.py
│   ├── patterns.py              # GesturePattern dataclass, DEFAULT_GESTURES
│   └── classifier.py            # GestureClassifier (pattern matching)
│
├── actions/
│   ├── __init__.py
│   └── executor.py              # ActionExecutor, ActionRegistry
│
├── web/
│   ├── __init__.py
│   └── server.py                # FastAPI app, config I/O
│
├── config/
│   ├── gestures.json            # Gesture definitions
│   └── actions.json             # Action mappings
│
├── main.py                      # System orchestrator, detection_loop()
├── requirements.txt
├── run.sh
├── README.md
└── CLAUDE.md                    # This file
```

---

## Core Modules

### `camera/detector.py`

**IRDetector**:
- Wraps OpenCV SimpleBlobDetector
- Tuned for IR reflectors (bright, circular, high contrast)
- `detect(frame)` → BlobPoint or None (~5-10ms per frame)

**BlobTracker**:
- Maintains trajectory deque (last N points)
- Tracks centroid over time
- `start()`, `update()`, `stop()` lifecycle
- Computes trajectory length, avg speed, bounding box

**BlobPoint** (dataclass):
- `x, y`: Centroid coordinates
- `area`: Blob area (pixels²)
- `frame_index`: Frame number

### `gestures/patterns.py`

**GesturePattern** (dataclass):
- `type`: GestureType enum (CIRCLE, LINE, DWELL, FIGURE8, ZIGZAG)
- Detection thresholds (speed, distance, circularity, etc.)
- Fully serializable to JSON
- `to_dict()`, `from_dict()` for config I/O

**DEFAULT_GESTURES**: Pre-configured set of 5 common gestures.

### `gestures/classifier.py`

**GestureClassifier**:
- Pattern-matches trajectory against all enabled gestures
- Returns best match with confidence (0.0-1.0)
- No training, fully deterministic
- Implements specific matchers for each gesture type:
  - `_match_circle()`: Rotation count + radius consistency
  - `_match_line()`: Deviation from ideal line
  - `_match_dwell()`: Minimal motion + duration
  - `_match_figure8()`: Two rotation cycles
  - `_match_zigzag()`: Direction change count

### `actions/executor.py`

**ActionExecutor**:
- Async queue-based action processing
- Prevents blocking detection loop
- Supports:
  - **MP3**: `mpg123` (preferred), `ffplay`, or `afplay` (macOS dev); `aplay`/`paplay` only for `.wav`
  - **Video**: `omxplayer` (RPi HW accel) or `ffplay`
  - **GPIO**: Simple toggles or PWM (servo, LED)
  - **Webhook**: HTTP POST via curl

**GestureAction** (dataclass):
- Maps gesture → action trigger
- Serializable to JSON

**ActionRegistry**:
- Gesture ID → GestureAction lookup
- `from_dict()` / `to_dict()` for config loading

### `web/server.py`

**FastAPI app** created by `create_app()`:
- REST API for gesture/action CRUD
- Config persistence to JSON
- Live stats for monitoring
- No built-in HTML UI (frontend optional)

**Endpoints**:
- `GET /api/gestures`, `POST /api/gestures`, `PUT /api/gestures/{id}`, `DELETE /api/gestures/{id}`
- `GET /api/actions`, `POST /api/actions`, `DELETE /api/actions/{gesture_id}`
- `GET /api/stats` (FPS, blobs, active gesture, trajectory length)
- `GET /health`

### `main.py`

**GestureDetectionSystem**:
- Orchestrates all components
- Runs detection loop + web server in parallel
- Loads/saves gesture & action configs

**detection_loop()**:
- Real-time camera processing
- Detects blobs, tracks trajectory
- Classifies gestures on completion
- Triggers actions via executor
- Target: 20 fps on RPi 3B+

---

## Configuration

### `config/gestures.json`

Defines available gestures. Example:

```json
{
  "wand_spin": {
    "id": "wand_spin",
    "name": "Wand Spin",
    "type": "circle",
    "enabled": true,
    "min_rotations": 1.0,
    "min_radius": 25.0,
    "circularity_tolerance": 0.3,
    "min_speed": 5.0,
    "max_speed": 30.0,
    "min_distance": 60.0,
    "timeout_ms": 3000
  },
  "quick_flick": {
    "id": "quick_flick",
    "name": "Quick Flick",
    "type": "line",
    "enabled": true,
    "min_speed": 15.0,
    "max_deviation": 15.0,
    "min_linearity": 0.75,
    "min_distance": 60.0,
    "timeout_ms": 2000
  }
}
```

### `config/actions.json`

Maps gestures to actions:

```json
{
  "wand_spin": {
    "gesture_id": "wand_spin",
    "action_type": "mp3",
    "target": "/home/pi/sounds/spell_cast.mp3",
    "duration_ms": null
  },
  "quick_flick": {
    "gesture_id": "quick_flick",
    "action_type": "gpio",
    "target": "12:pwm:50:75",
    "duration_ms": 1500
  }
}
```

**Action types**:
- `mp3`: Play audio file
- `video`: Play video on HDMI
- `gpio`: Control GPIO pin (simple or PWM)
- `webhook`: HTTP POST to URL

**GPIO spec format**:
- `"12"` → Toggle pin 12 (BOARD numbering)
- `"12:simple"` → Same, explicit
- `"12:pwm:50:75"` → PWM on pin 12, 50Hz, 75% duty cycle

---

## Performance Notes

| Metric | Target | Actual (RPi 3B+) |
|--------|--------|------------------|
| FPS | 20 | 15-25 fps |
| Blob detection latency | <10ms | 5-8ms |
| Classification latency | <20ms | 8-15ms |
| Total gesture latency | <100ms | 50-80ms |
| Memory baseline | — | ~80MB |

**Bottlenecks**:
- Frame resize (640×480 optimized)
- SimpleBlobDetector thresholding
- Trajectory classification (scales with gesture complexity)

---

## Setup & Running

### Local Development (without RPi)

```bash
# Clone/init repo
cd ir-gesture-system

# Install deps
pip install -r requirements.txt

# Run (no camera, web server only for testing)
python main.py
```

### On Raspberry Pi (OS Lite 32-bit, Trixie, headless)

Trixie marks system Python as externally managed (PEP 668), so `pip3 install` system-wide fails. Take the hardware-bound libs (picamera2, OpenCV, numpy, GPIO) from apt and use a venv with `--system-site-packages` for the rest. One-shot script: `scripts/setup-pi.sh`.

```bash
# SSH into RPi (Lite has no desktop — SSH/CLI only)
ssh <user>@<rpi-ip>

sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-picamera2 python3-opencv python3-numpy \
  python3-rpi-lgpio alsa-utils ffmpeg mpv mpg123

git clone <repo-url> ~/WandGestureDetector && cd ~/WandGestureDetector
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" pydantic

# Verify camera (Trixie uses rpicam-*, not libcamera-*; power off before seating the ribbon)
rpicam-hello --list-cameras

# Run (detection + web server)
./run.sh
```

Do NOT `pip install -r requirements.txt` on the Pi: it pins `opencv-python-headless`/`numpy`, which would shadow the apt builds.

No local display is available, so all monitoring happens remotely:
- Web UI / API at `http://<rpi-ip>:8000` (stats, gesture/action CRUD)
- SSH for logs (`journalctl` once running as a service, or `detection.log`)

For a permanent headless deployment, run via `systemd` (starts on boot without a login session) rather than a shell left open over SSH:

A ready-made unit lives in `deploy/ir-gesture.service` (edit `User`/paths if your account isn't `pi`):

```bash
sudo cp deploy/ir-gesture.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ir-gesture.service
sudo journalctl -u ir-gesture.service -f
```

---

## Development Workflow

### Adding a New Gesture Type

1. Add to `GestureType` enum in `gestures/patterns.py`
2. Implement `_match_<type>()` in `GestureClassifier`
3. Add parameters to `GesturePattern` dataclass
4. Add default instance to `DEFAULT_GESTURES`
5. Test via `classify()` method

### Tuning Detection

**For weak blob detection**:
- Increase `min_threshold` / `max_threshold` in `detector.py`
- Adjust `min_circularity`, `min_area`

**For low FPS**:
- Reduce frame resolution (target: 480p or lower)
- Disable `filterByConvexity` / `filterByInertia`
- Profile with `cProfile` to identify bottleneck

**For false positives**:
- Tighten gesture thresholds (e.g., `min_rotations`, `max_deviation`)
- Increase `min_distance` / `min_trajectory_length`

### Testing Without Hardware

Create mock detector for unit tests:

```python
class MockDetector:
    def detect(self, frame):
        # Return synthetic trajectory for testing
        return BlobPoint(x=320, y=240, area=100, frame_index=...)
```

---

## Next Steps / Roadmap

**v1.0 (MVP)**:
- [x] Core blob detection
- [x] Pattern matching classifier
- [x] Action executor (MP3, GPIO)
- [x] FastAPI web interface
- [ ] React admin UI (visualization)

**v1.1**:
- [ ] Multi-wand tracking (multiple reflectors)
- [ ] Gesture event logging (JSON logs)
- [ ] Auto-tuning thresholds via calibration wizard
- [ ] Gesture "learn mode" (record trajectory for pattern)

**v2.0**:
- [ ] Optional pose estimation (hand tracking)
- [ ] Conditional actions (if/then logic)
- [ ] Gesture sequencing (multi-step spells)
- [ ] MQTT integration (home automation)

---

## Constraints & Assumptions

- **Lighting**: Works in low light (IR LEDs built into camera)
- **Wand**: Requires IR reflective material (retroreflective tape or beads)
- **FPS**: Target 20 fps; lower on RPi Zero
- **Latency**: ~100ms from gesture end to action start (acceptable for UI feedback)
- **Single wand**: Current code tracks one reflector; multi-wand requires modification
- **No internet**: System runs fully local (optional webhooks for integrations)
- **Headless OS**: Raspberry Pi OS Lite has no desktop/X11 — no `cv2.imshow()` debug windows on-device. Use the FastAPI `/api/stats` endpoint (and optionally a saved-frame/MJPEG debug endpoint) for live visualization instead. Use `picamera2` (libcamera-based), not the legacy `picamera`/`PiRGBArray` API, since Lite images since Bullseye ship with libcamera. Run the system as a `systemd` service (not a desktop autostart) so it starts headless on boot.

---

## Key Files to Review First

1. **`main.py`** — System entry point, orchestration
2. **`camera/detector.py`** — Blob detection (core algorithm)
3. **`gestures/classifier.py`** — Pattern matching (where gestures are recognized)
4. **`config/gestures.json`** & **`config/actions.json`** — Configuration examples

---

## Useful Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run system
python main.py

# Check web API
curl http://localhost:8000/api/gestures
curl http://localhost:8000/api/stats
curl http://localhost:8000/health

# Run with verbose output
python -u main.py 2>&1 | tee detection.log

# Profile performance
python -m cProfile -s cumtime main.py
```

---

## References

- OpenCV SimpleBlobDetector: https://docs.opencv.org/4.8.0/d0/d7a/classcv_1_1SimpleBlobDetector.html
- FastAPI: https://fastapi.tiangolo.com/
- RPi.GPIO: https://sourceforge.net/projects/raspberry-gpio-python/
- Arducam IR Camera: https://www.arducam.com/

---

## Contact / Questions

Dan (SDET/QA automation professional)  
Deep Current Technologies LLC  
Texas, USA  
Timezone: America/Chicago (UTC-05:00)

**Skills**: Playwright, Cypress, Selenium, Python, FastAPI, OpenCV, GitHub Actions
