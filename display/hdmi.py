"""HDMI preview for headless Pi: pipes raw BGR frames to `mpv --vo=drm` (display/hdmi.py)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger("ir_gesture_system.hdmi")


class HdmiDisplay:
    """Renders frames on the HDMI output without X11/Wayland via mpv's DRM/KMS backend.

    Frames go through a single-slot buffer and a writer thread, so a slow display drops
    frames instead of stalling the detection loop.
    """

    def __init__(self, width: int, height: int, fps: int = 20):
        self.width = width
        self.height = height
        self.fps = fps
        self._proc: Optional[subprocess.Popen] = None
        self._latest: Optional[bytes] = None
        self._cond = threading.Condition()
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        mpv = shutil.which("mpv")
        if mpv is None:
            logger.warning("mpv not installed (sudo apt install mpv) - HDMI preview disabled")
            return False
        cmd = [
            mpv, "--no-config", "--vo=drm", "--no-audio", "--no-terminal", "--really-quiet",
            "--profile=low-latency", "--untimed", "--video-unscaled=yes", "--framedrop=vo",
            "--demuxer=rawvideo",
            f"--demuxer-rawvideo-w={self.width}",
            f"--demuxer-rawvideo-h={self.height}",
            "--demuxer-rawvideo-mp-format=bgr24",
            f"--demuxer-rawvideo-fps={self.fps}",
            "-",
        ]
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logger.warning("Could not start mpv (%s) - HDMI preview disabled", exc)
            return False
        self._thread = threading.Thread(target=self._writer, name="hdmi-writer", daemon=True)
        self._thread.start()
        logger.info("HDMI preview started (%dx%d via mpv --vo=drm)", self.width, self.height)
        return True

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def show(self, frame_bgr: np.ndarray) -> None:
        if not self.active:
            return
        data = frame_bgr.tobytes()
        with self._cond:
            self._latest = data
            self._cond.notify()

    def _writer(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        while True:
            with self._cond:
                while self._latest is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                data, self._latest = self._latest, None
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                logger.warning("mpv exited - HDMI preview stopped (is the user in the 'video' group?)")
                return

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
