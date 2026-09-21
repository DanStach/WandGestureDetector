"""Async action execution: MP3, video, GPIO, webhook (actions/executor.py)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    MP3 = "mp3"
    VIDEO = "video"
    GPIO = "gpio"
    WEBHOOK = "webhook"


@dataclass
class GestureAction:
    gesture_id: str
    action_type: ActionType
    target: str
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["action_type"] = self.action_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GestureAction":
        raw_type = data["action_type"]
        return cls(
            gesture_id=data["gesture_id"],
            action_type=raw_type if isinstance(raw_type, ActionType) else ActionType(raw_type),
            target=data["target"],
            duration_ms=data.get("duration_ms"),
        )


class ActionRegistry:
    """Gesture ID -> GestureAction lookup, JSON-backed for config I/O."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self._actions: Dict[str, GestureAction] = {}

    def load(self) -> None:
        if self.path and self.path.exists():
            with open(self.path) as f:
                raw = json.load(f)
            self._actions = {gid: GestureAction.from_dict(data) for gid, data in raw.items()}

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({gid: a.to_dict() for gid, a in self._actions.items()}, f, indent=2)
            f.write("\n")

    def list(self) -> List[GestureAction]:
        return list(self._actions.values())

    def get(self, gesture_id: str) -> Optional[GestureAction]:
        return self._actions.get(gesture_id)

    def upsert(self, action: GestureAction) -> None:
        self._actions[action.gesture_id] = action
        self.save()

    def delete(self, gesture_id: str) -> bool:
        if gesture_id in self._actions:
            del self._actions[gesture_id]
            self.save()
            return True
        return False


class ActionExecutor:
    """Async queue-based action runner so MP3/video/GPIO playback never blocks the detection loop.

    GPIO numbering mode is set exactly once and PWM channels are created once per pin and
    reused thereafter -- repeated per-call GPIO.setup()/cleanup() and mixed BOARD/BCM modes
    across modules were a recurring source of crashes in prior-art wand projects.
    """

    def __init__(self):
        self._queue: "asyncio.Queue[GestureAction]" = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._sound_tasks: set = set()
        self._gpio = None  # lazily imported RPi.GPIO module, or False if unavailable
        self._gpio_mode_set = False
        self._pwm_channels: Dict[int, object] = {}

    async def start(self) -> None:
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._cleanup_gpio()

    def trigger(self, action: GestureAction) -> None:
        self._queue.put_nowait(action)

    def play_sound(self, target: str) -> None:
        """Fire-and-forget audio that bypasses the action queue (e.g. a beep must not wait behind an MP3)."""
        task = asyncio.create_task(self._play_audio(target))
        self._sound_tasks.add(task)
        task.add_done_callback(self._sound_tasks.discard)

    async def _worker(self) -> None:
        while self._running:
            action = await self._queue.get()
            try:
                await self._execute(action)
            except Exception:
                logger.exception("Action failed: %s", action)

    async def _execute(self, action: GestureAction) -> None:
        if action.action_type == ActionType.MP3:
            await self._play_audio(action.target)
        elif action.action_type == ActionType.VIDEO:
            await self._play_video(action.target, action.duration_ms)
        elif action.action_type == ActionType.GPIO:
            await self._handle_gpio(action.target, action.duration_ms)
        elif action.action_type == ActionType.WEBHOOK:
            await self._call_webhook(action.target)

    # -- MP3 / video --

    @staticmethod
    def _audio_command(target: str) -> Optional[List[str]]:
        """Pick a player that can decode `target`; aplay/paplay are only used for .wav files."""
        players = ["mpg123", "ffplay", "afplay"]
        if Path(target).suffix.lower() == ".wav":
            players = ["aplay", "paplay"] + players
        # ALSA device, e.g. "plughw:CARD=vc4hdmi,DEV=0" for HDMI (plughw resamples; HDMI only
        # accepts 48/24/12 kHz). Unset = system default. ffplay/afplay/paplay ignore it.
        device = os.environ.get("WAND_AUDIO_DEVICE", "").strip()
        args_for = {
            "mpg123": ["-q", *(["-a", device] if device else [])],
            "aplay": ["-D", device] if device else [],
            "ffplay": ["-nodisp", "-autoexit", "-loglevel", "quiet"],
        }
        for player in players:
            if shutil.which(player):
                return [player, *args_for.get(player, []), target]
        return None

    async def _play_audio(self, target: str) -> None:
        args = self._audio_command(target)
        if not args:
            logger.warning(
                "No suitable audio player on PATH (mpg123/ffplay/afplay for mp3; aplay/paplay for wav) - skipping audio action for %s",
                target,
            )
            return
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(
                "%s exited with code %s for %s: %s",
                args[0], process.returncode, target, stderr.decode(errors="replace").strip(),
            )

    async def _play_video(self, target: str, duration_ms: Optional[int]) -> None:
        player = next((p for p in ("omxplayer", "ffplay", "cvlc") if shutil.which(p)), None)
        if not player:
            logger.warning("No video player on PATH (omxplayer/ffplay/cvlc) - skipping video action for %s", target)
            return
        args = [player, "-autoexit", target] if player == "ffplay" else [player, target]
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        if duration_ms:
            try:
                await asyncio.wait_for(process.wait(), timeout=duration_ms / 1000)
            except asyncio.TimeoutError:
                process.terminate()
        else:
            await process.wait()

    # -- Webhook --

    async def _call_webhook(self, target: str) -> None:
        process = await asyncio.create_subprocess_exec(
            "curl", "-s", "-X", "POST", target,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

    # -- GPIO --

    def _ensure_gpio(self):
        if self._gpio is None:
            try:
                import RPi.GPIO as GPIO
            except ImportError:
                logger.warning("RPi.GPIO not available (not running on a Raspberry Pi?) - GPIO actions are no-ops")
                self._gpio = False
            else:
                self._gpio = GPIO
        if self._gpio and not self._gpio_mode_set:
            self._gpio.setmode(self._gpio.BOARD)
            self._gpio_mode_set = True
        return self._gpio or None

    async def _handle_gpio(self, target: str, duration_ms: Optional[int]) -> None:
        """Parses GPIO specs: "12" / "12:simple" (toggle) or "12:pwm:<freq>:<duty>"."""
        gpio = self._ensure_gpio()
        if gpio is None:
            return
        parts = target.split(":")
        pin = int(parts[0])
        mode = parts[1] if len(parts) > 1 else "simple"

        if mode == "pwm":
            frequency = float(parts[2]) if len(parts) > 2 else 50.0
            duty_cycle = float(parts[3]) if len(parts) > 3 else 50.0
            pwm = self._pwm_channels.get(pin)
            if pwm is None:
                gpio.setup(pin, gpio.OUT)
                pwm = gpio.PWM(pin, frequency)
                pwm.start(0)
                self._pwm_channels[pin] = pwm
            pwm.ChangeDutyCycle(duty_cycle)
            await asyncio.sleep((duration_ms or 1000) / 1000)
            pwm.ChangeDutyCycle(0)
        else:
            gpio.setup(pin, gpio.OUT)
            gpio.output(pin, gpio.HIGH)
            await asyncio.sleep((duration_ms or 500) / 1000)
            gpio.output(pin, gpio.LOW)

    def _cleanup_gpio(self) -> None:
        if self._gpio:
            for pwm in self._pwm_channels.values():
                pwm.stop()
            self._pwm_channels.clear()
            self._gpio.cleanup()
