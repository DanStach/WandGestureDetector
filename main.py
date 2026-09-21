"""System orchestrator: detection_loop() + FastAPI web server, run in parallel (main.py)."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import uvicorn

from actions.executor import ActionExecutor, ActionRegistry
from camera.detector import BlobTracker, IRDetector
from display import metrics
from display.hdmi import HdmiDisplay
from display.overlay import draw_overlay
from gestures.classifier import GestureClassifier
from gestures.patterns import GestureStore
from web.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ir_gesture_system")

CONFIG_DIR = Path(__file__).parent / "config"

# Minimum pixel movement between consecutive points to count as "activity" rather than
# jitter; used to let dwell gestures complete without the wand leaving the frame.
MOVEMENT_EPSILON_PX = 1.5

FRAME_SIZE = (640, 480)
METRICS_INTERVAL_S = 1.0
# The web preview is only rendered/JPEG-encoded while someone has requested a frame recently.
STREAM_IDLE_S = 2.0
# Send every Nth frame to HDMI (mpv on a Pi 3 is costly); detection still runs on every frame.
HDMI_EVERY_N = int(os.environ.get("WAND_HDMI_EVERY", "2"))


class GestureDetectionSystem:
    def __init__(self, config_dir: Path = CONFIG_DIR, host: str = "0.0.0.0", port: int = 8000):
        self.config_dir = config_dir
        self.host = host
        self.port = port

        self.gesture_store = GestureStore(config_dir / "gestures.json")
        self.gesture_store.load()

        self.action_registry = ActionRegistry(config_dir / "actions.json")
        self.action_registry.load()

        self.detector = IRDetector()
        self.tracker = BlobTracker()
        self.classifier = GestureClassifier(self.gesture_store.list())
        self.executor = ActionExecutor()

        self._running = False
        self._stats = {
            "fps": 0.0,
            "blob_detected": False,
            "tracking": False,
            "trajectory_length": 0,
            "last_gesture": None,
            "cpu_percent": 0.0,
            "mem_percent": 0.0,
            "cpu_temp_c": None,
            "cpu_temp_f": None,
        }

        # HDMI preview: WAND_HDMI=1 (set by `./run.sh --hdmi`). Web preview is always available.
        self._hdmi_enabled = os.environ.get("WAND_HDMI", "0") == "1"
        self._latest_jpeg: Optional[bytes] = None
        self._last_stream_request = 0.0

        self.app = create_app(
            self.gesture_store, self.action_registry, self.get_stats, self.get_preview_jpeg
        )

    def get_stats(self) -> dict:
        return dict(self._stats)

    def get_preview_jpeg(self) -> Optional[bytes]:
        self._last_stream_request = time.monotonic()
        return self._latest_jpeg

    # -- camera acquisition: picamera2 on the Pi, cv2.VideoCapture for local dev, else None --

    def _open_camera(self) -> Optional[Tuple[str, object]]:
        try:
            from picamera2 import Picamera2

            camera = Picamera2()
            camera.configure(camera.create_video_configuration(main={"size": (640, 480), "format": "RGB888"}))
            camera.start()
            logger.info("Using picamera2 for capture")
            return ("picamera2", camera)
        except Exception as exc:
            logger.info("picamera2 unavailable (%s); falling back to cv2.VideoCapture", exc)

        import cv2

        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            logger.info("Using cv2.VideoCapture(0) for capture")
            return ("cv2", cap)
        cap.release()
        logger.warning("No camera available - running web server only (see CLAUDE.md local dev mode)")
        return None

    def _read_frame(self, camera: Tuple[str, object]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Returns (bgr, gray). picamera2's "RGB888" is BGR byte order, so it previews correctly as-is."""
        import cv2

        kind, handle = camera
        if kind == "picamera2":
            frame = handle.capture_array()
            return frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        ok, frame = handle.read()
        if not ok:
            return None
        if frame.shape[1] != FRAME_SIZE[0] or frame.shape[0] != FRAME_SIZE[1]:
            frame = cv2.resize(frame, FRAME_SIZE)
        return frame, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def _close_camera(self, camera: Tuple[str, object]) -> None:
        kind, handle = camera
        if kind == "picamera2":
            handle.stop()
        else:
            handle.release()

    def _current_timeout_ms(self) -> float:
        timeouts = [p.timeout_ms for p in self.gesture_store.list() if p.enabled]
        return min(timeouts) if timeouts else 2000

    def _classify_and_trigger(self, trajectory) -> None:
        if len(trajectory) < 2:
            return
        self.classifier.patterns = self.gesture_store.list()
        result = self.classifier.classify(trajectory)
        length = sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(trajectory, trajectory[1:]))
        duration = max(trajectory[-1].timestamp - trajectory[0].timestamp, 1e-6)
        logger.info(
            "Trajectory: %d pts, path %.0f px, %.2f s, %.0f px/s -> %s",
            len(trajectory), length, duration, length / duration, result.gesture_name if result else "no match",
        )
        if result is None:
            self._stats["last_gesture"] = None
            return
        logger.info("Recognized gesture '%s' (confidence=%.2f)", result.gesture_name, result.confidence)
        self._stats["last_gesture"] = {
            "id": result.gesture_id,
            "name": result.gesture_name,
            "confidence": result.confidence,
        }
        action = self.action_registry.get(result.gesture_id)
        if action:
            self.executor.trigger(action)

    async def detection_loop(self) -> None:
        camera = self._open_camera()
        if camera is None:
            return

        await self.executor.start()
        self._running = True
        last_activity_time = time.monotonic()
        frame_times: list[float] = []
        last_metrics = 0.0
        frame_count = 0

        hdmi: Optional[HdmiDisplay] = None
        if self._hdmi_enabled:
            hdmi = HdmiDisplay(*FRAME_SIZE)
            if not hdmi.start():
                hdmi = None
        metrics.sample()  # prime psutil so the first real reading is meaningful

        try:
            while self._running:
                loop_start = time.monotonic()
                frames = self._read_frame(camera)
                if frames is None:
                    await asyncio.sleep(0.01)
                    continue
                bgr, frame = frames

                point = self.detector.detect(frame)
                self._stats["blob_detected"] = point is not None

                if point is not None:
                    prev = self.tracker.trajectory[-1] if self.tracker.active and self.tracker.trajectory else None
                    self.tracker.update(point)
                    if prev is None or math.hypot(point.x - prev.x, point.y - prev.y) > MOVEMENT_EPSILON_PX:
                        last_activity_time = loop_start

                if self.tracker.active and (loop_start - last_activity_time) * 1000 > self._current_timeout_ms():
                    trajectory = self.tracker.stop()
                    self._classify_and_trigger(trajectory)
                    last_activity_time = loop_start

                self._stats["tracking"] = self.tracker.active
                self._stats["trajectory_length"] = len(self.tracker.trajectory)

                frame_times.append(loop_start)
                frame_times = [t for t in frame_times if loop_start - t < 1.0]
                self._stats["fps"] = float(len(frame_times))

                if loop_start - last_metrics >= METRICS_INTERVAL_S:
                    self._stats.update(metrics.sample())
                    last_metrics = loop_start

                frame_count += 1
                want_hdmi = hdmi is not None and frame_count % HDMI_EVERY_N == 0
                want_web = loop_start - self._last_stream_request < STREAM_IDLE_S
                if want_hdmi or want_web:
                    annotated = draw_overlay(bgr, self.tracker.trajectory, point, self._stats)
                    if want_hdmi:
                        hdmi.show(annotated)
                    if want_web:
                        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ok:
                            self._latest_jpeg = buf.tobytes()

                await asyncio.sleep(0)
        finally:
            if hdmi is not None:
                hdmi.stop()
            self._running = False
            self._close_camera(camera)
            await self.executor.stop()

    async def _run_web_server(self) -> None:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def run(self) -> None:
        await asyncio.gather(self._run_web_server(), self.detection_loop())


def main() -> None:
    system = GestureDetectionSystem()
    asyncio.run(system.run())


if __name__ == "__main__":
    main()
