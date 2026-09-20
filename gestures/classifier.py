"""Deterministic trajectory pattern matching (gestures/classifier.py). No training, no ML."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from camera.detector import BlobPoint
from gestures.patterns import GesturePattern, GestureType


@dataclass
class ClassificationResult:
    gesture_id: str
    gesture_name: str
    confidence: float


class GestureClassifier:
    """Pattern-matches a trajectory against all enabled gestures, returns the best match."""

    def __init__(self, patterns: Sequence[GesturePattern]):
        self.patterns: List[GesturePattern] = list(patterns)

    def classify(self, trajectory: List[BlobPoint]) -> Optional[ClassificationResult]:
        best: Optional[ClassificationResult] = None
        for pattern in self.patterns:
            if not pattern.enabled:
                continue
            confidence = self._match(pattern, trajectory)
            if confidence is None:
                continue
            if best is None or confidence > best.confidence:
                best = ClassificationResult(pattern.id, pattern.name, confidence)
        return best

    def _match(self, pattern: GesturePattern, trajectory: List[BlobPoint]) -> Optional[float]:
        matchers: Dict[GestureType, Callable[[GesturePattern, List[BlobPoint]], Optional[float]]] = {
            GestureType.CIRCLE: self._match_circle,
            GestureType.LINE: self._match_line,
            GestureType.DWELL: self._match_dwell,
            GestureType.FIGURE8: self._match_figure8,
            GestureType.ZIGZAG: self._match_zigzag,
        }
        return matchers[pattern.type](pattern, trajectory)

    # -- shared geometry helpers --

    @staticmethod
    def _path_length(points: Sequence[BlobPoint]) -> float:
        return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(points, points[1:]))

    @staticmethod
    def _duration_s(points: Sequence[BlobPoint]) -> float:
        if len(points) < 2:
            return 0.0
        return max(points[-1].timestamp - points[0].timestamp, 1e-6)

    @staticmethod
    def _centroid(points: Sequence[BlobPoint]) -> tuple[float, float]:
        n = len(points)
        return (sum(p.x for p in points) / n, sum(p.y for p in points) / n)

    @classmethod
    def _avg_speed(cls, points: Sequence[BlobPoint]) -> float:
        return cls._path_length(points) / cls._duration_s(points)

    @staticmethod
    def _signed_angle_deltas(points: Sequence[BlobPoint], cx: float, cy: float) -> List[float]:
        deltas: List[float] = []
        prev_angle: Optional[float] = None
        for p in points:
            angle = math.atan2(p.y - cy, p.x - cx)
            if prev_angle is not None:
                delta = angle - prev_angle
                while delta > math.pi:
                    delta -= 2 * math.pi
                while delta < -math.pi:
                    delta += 2 * math.pi
                deltas.append(delta)
            prev_angle = angle
        return deltas

    @staticmethod
    def _count_reversals(deltas: Sequence[float], window: int = 3) -> int:
        """Counts sign changes in the windowed rotation direction (smoothed to ignore jitter)."""
        if len(deltas) < window * 2:
            return 0
        signs: List[int] = []
        for i in range(len(deltas) - window + 1):
            window_sum = sum(deltas[i : i + window])
            if abs(window_sum) < 1e-6:
                continue
            signs.append(1 if window_sum > 0 else -1)
        return sum(1 for a, b in zip(signs, signs[1:]) if a != b)

    # -- matchers --

    def _match_circle(self, pattern: GesturePattern, points: List[BlobPoint]) -> Optional[float]:
        if len(points) < 8:
            return None
        distance = self._path_length(points)
        if distance < pattern.min_distance:
            return None
        cx, cy = self._centroid(points)
        radii = [math.hypot(p.x - cx, p.y - cy) for p in points]
        mean_radius = sum(radii) / len(radii)
        if mean_radius <= 0:
            return None
        radius_std = math.sqrt(sum((r - mean_radius) ** 2 for r in radii) / len(radii))
        radius_variation = radius_std / mean_radius
        tolerance = pattern.circularity_tolerance if pattern.circularity_tolerance is not None else 0.3
        if radius_variation > tolerance:
            return None
        rotations = sum(abs(d) for d in self._signed_angle_deltas(points, cx, cy)) / (2 * math.pi)
        min_rotations = pattern.min_rotations or 1.0
        if rotations < min_rotations:
            return None
        speed = self._avg_speed(points)
        if pattern.min_speed is not None and speed < pattern.min_speed:
            return None
        if pattern.max_speed is not None and speed > pattern.max_speed:
            return None
        circularity_score = max(0.0, 1.0 - radius_variation / tolerance)
        rotation_score = min(rotations / min_rotations, 1.5) / 1.5
        return round(min(1.0, 0.5 * circularity_score + 0.5 * rotation_score), 3)

    def _match_line(self, pattern: GesturePattern, points: List[BlobPoint]) -> Optional[float]:
        if len(points) < 4:
            return None
        start, end = points[0], points[-1]
        dx, dy = end.x - start.x, end.y - start.y
        distance = math.hypot(dx, dy)
        if distance < pattern.min_distance or distance == 0:
            return None
        ux, uy = dx / distance, dy / distance
        deviations = []
        for p in points:
            vx, vy = p.x - start.x, p.y - start.y
            proj = vx * ux + vy * uy
            perp_x, perp_y = vx - proj * ux, vy - proj * uy
            deviations.append(math.hypot(perp_x, perp_y))
        max_deviation = max(deviations)
        allowed_deviation = pattern.max_deviation if pattern.max_deviation is not None else 15.0
        if max_deviation > allowed_deviation:
            return None
        linearity = max(0.0, 1.0 - (max_deviation / allowed_deviation))
        min_linearity = pattern.min_linearity if pattern.min_linearity is not None else 0.6
        if linearity < min_linearity:
            return None
        speed = self._avg_speed(points)
        if pattern.min_speed is not None and speed < pattern.min_speed:
            return None
        if pattern.max_speed is not None and speed > pattern.max_speed:
            return None
        distance_score = min(distance / pattern.min_distance, 1.5) / 1.5
        return round(min(1.0, 0.6 * linearity + 0.4 * distance_score), 3)

    def _match_dwell(self, pattern: GesturePattern, points: List[BlobPoint]) -> Optional[float]:
        if len(points) < 3:
            return None
        duration_ms = self._duration_s(points) * 1000
        min_duration_ms = pattern.min_duration_ms or 500
        if duration_ms < min_duration_ms:
            return None
        cx, cy = self._centroid(points)
        max_movement = max(math.hypot(p.x - cx, p.y - cy) for p in points)
        allowed_movement = pattern.max_movement if pattern.max_movement is not None else 12.0
        if max_movement > allowed_movement:
            return None
        stillness_score = max(0.0, 1.0 - max_movement / allowed_movement)
        duration_score = min(duration_ms / min_duration_ms, 1.5) / 1.5
        return round(min(1.0, 0.5 * stillness_score + 0.5 * duration_score), 3)

    def _match_figure8(self, pattern: GesturePattern, points: List[BlobPoint]) -> Optional[float]:
        if len(points) < 12:
            return None
        distance = self._path_length(points)
        if distance < pattern.min_distance:
            return None
        cx, cy = self._centroid(points)
        deltas = self._signed_angle_deltas(points, cx, cy)
        total_rotation = sum(abs(d) for d in deltas) / (2 * math.pi)
        min_rotations = pattern.min_rotations or 2.0
        if total_rotation < min_rotations:
            return None
        reversals = self._count_reversals(deltas)
        if reversals < 1:
            return None
        speed = self._avg_speed(points)
        if pattern.min_speed is not None and speed < pattern.min_speed:
            return None
        if pattern.max_speed is not None and speed > pattern.max_speed:
            return None
        rotation_score = min(total_rotation / min_rotations, 1.5) / 1.5
        reversal_score = min(reversals / 1.0, 1.0)
        return round(min(1.0, 0.6 * rotation_score + 0.4 * reversal_score), 3)

    def _match_zigzag(self, pattern: GesturePattern, points: List[BlobPoint]) -> Optional[float]:
        if len(points) < 6:
            return None
        distance = self._path_length(points)
        if distance < pattern.min_distance:
            return None
        turn_threshold = math.radians(pattern.min_turn_angle_deg or 45.0)
        segment_angles = [
            math.atan2(b.y - a.y, b.x - a.x)
            for a, b in zip(points, points[1:])
            if math.hypot(b.x - a.x, b.y - a.y) >= 2.0
        ]
        direction_changes = 0
        for a, b in zip(segment_angles, segment_angles[1:]):
            delta = b - a
            while delta > math.pi:
                delta -= 2 * math.pi
            while delta < -math.pi:
                delta += 2 * math.pi
            if abs(delta) >= turn_threshold:
                direction_changes += 1
        min_changes = pattern.min_direction_changes or 3
        if direction_changes < min_changes:
            return None
        speed = self._avg_speed(points)
        if pattern.min_speed is not None and speed < pattern.min_speed:
            return None
        if pattern.max_speed is not None and speed > pattern.max_speed:
            return None
        return round(min(1.0, direction_changes / min_changes / 1.5), 3)
