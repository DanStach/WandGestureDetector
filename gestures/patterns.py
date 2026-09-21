"""Gesture definitions: GesturePattern dataclass, DEFAULT_GESTURES, GestureStore (gestures/patterns.py)."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class GestureType(str, Enum):
    CIRCLE = "circle"
    LINE = "line"
    DWELL = "dwell"
    FIGURE8 = "figure8"
    ZIGZAG = "zigzag"


@dataclass
class GesturePattern:
    id: str
    name: str
    type: GestureType
    enabled: bool = True
    min_distance: float = 60.0
    timeout_ms: int = 3000
    min_speed: Optional[float] = None
    max_speed: Optional[float] = None

    # circle / figure8
    min_rotations: Optional[float] = None
    min_radius: Optional[float] = None
    circularity_tolerance: Optional[float] = None

    # line
    max_deviation: Optional[float] = None
    min_linearity: Optional[float] = None

    # dwell
    max_movement: Optional[float] = None
    min_duration_ms: Optional[int] = None

    # zigzag
    min_direction_changes: Optional[int] = None
    min_turn_angle_deg: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data["type"] = self.type.value
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GesturePattern":
        data = dict(data)
        raw_type = data["type"]
        data["type"] = raw_type if isinstance(raw_type, GestureType) else GestureType(raw_type)
        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


DEFAULT_GESTURES: Dict[str, GesturePattern] = {
    "wand_spin": GesturePattern(
        id="wand_spin",
        name="Wand Spin",
        type=GestureType.CIRCLE,
        min_rotations=1.0,
        min_radius=25.0,
        circularity_tolerance=0.3,
        min_speed=5.0,
        max_speed=30.0,
        min_distance=60.0,
        timeout_ms=3000,
    ),
    "lumos": GesturePattern(
        id="lumos",
        name="Lumos",
        type=GestureType.LINE,
        min_speed=18.0,
        max_deviation=12.0,
        min_linearity=0.80,
        min_distance=50.0,
        timeout_ms=1500,
    ),
    "quick_flick": GesturePattern(
        id="quick_flick",
        name="Quick Flick",
        type=GestureType.LINE,
        min_speed=15.0,
        max_deviation=15.0,
        min_linearity=0.75,
        min_distance=60.0,
        timeout_ms=2000,
    ),
    "hold_still": GesturePattern(
        id="hold_still",
        name="Hold Still",
        type=GestureType.DWELL,
        max_movement=10.0,
        min_duration_ms=800,
        min_distance=0.0,
        timeout_ms=2000,
    ),
    "infinity_loop": GesturePattern(
        id="infinity_loop",
        name="Infinity Loop",
        type=GestureType.FIGURE8,
        min_rotations=2.0,
        min_radius=20.0,
        circularity_tolerance=0.4,
        min_speed=5.0,
        max_speed=35.0,
        min_distance=100.0,
        timeout_ms=4000,
    ),
    "lightning_bolt": GesturePattern(
        id="lightning_bolt",
        name="Lightning Bolt",
        type=GestureType.ZIGZAG,
        min_direction_changes=3,
        min_turn_angle_deg=45.0,
        min_speed=10.0,
        min_distance=80.0,
        timeout_ms=2000,
    ),
}


class GestureStore:
    """JSON-backed CRUD store for GesturePatterns, used by the web API and main.py."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._patterns: Dict[str, GesturePattern] = {}

    def load(self) -> None:
        if self.path.exists():
            with open(self.path) as f:
                raw = json.load(f)
            self._patterns = {gid: GesturePattern.from_dict(data) for gid, data in raw.items()}
        else:
            self._patterns = dict(DEFAULT_GESTURES)
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({gid: p.to_dict() for gid, p in self._patterns.items()}, f, indent=2)
            f.write("\n")

    def list(self) -> List[GesturePattern]:
        return list(self._patterns.values())

    def get(self, gesture_id: str) -> Optional[GesturePattern]:
        return self._patterns.get(gesture_id)

    def upsert(self, pattern: GesturePattern) -> None:
        self._patterns[pattern.id] = pattern
        self.save()

    def delete(self, gesture_id: str) -> bool:
        if gesture_id in self._patterns:
            del self._patterns[gesture_id]
            self.save()
            return True
        return False
