"""IR blob detection and trajectory tracking (camera/detector.py)."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class BlobPoint:
    x: float
    y: float
    area: float
    frame_index: int
    timestamp: float  # time.monotonic() seconds, needed for speed/duration math


@dataclass
class BlobDetectorConfig:
    min_threshold: float = 150
    max_threshold: float = 250
    filter_by_color: bool = True
    blob_color: int = 255
    filter_by_circularity: bool = True
    min_circularity: float = 0.5
    filter_by_area: bool = True
    min_area: float = 20
    max_area: float = 2000
    filter_by_convexity: bool = False
    min_convexity: float = 0.5
    filter_by_inertia: bool = False
    min_inertia_ratio: float = 0.3


class IRDetector:
    """Wraps OpenCV SimpleBlobDetector, tuned for bright IR reflectors."""

    def __init__(self, config: Optional[BlobDetectorConfig] = None):
        self.config = config or BlobDetectorConfig()
        self._detector = self._build_detector(self.config)
        self._frame_index = 0

    @staticmethod
    def _build_detector(config: BlobDetectorConfig) -> cv2.SimpleBlobDetector:
        params = cv2.SimpleBlobDetector_Params()
        params.minThreshold = config.min_threshold
        params.maxThreshold = config.max_threshold
        params.filterByColor = config.filter_by_color
        params.blobColor = config.blob_color
        params.filterByCircularity = config.filter_by_circularity
        params.minCircularity = config.min_circularity
        params.filterByArea = config.filter_by_area
        params.minArea = config.min_area
        params.maxArea = config.max_area
        params.filterByConvexity = config.filter_by_convexity
        params.minConvexity = config.min_convexity
        params.filterByInertia = config.filter_by_inertia
        params.minInertiaRatio = config.min_inertia_ratio
        return cv2.SimpleBlobDetector_create(params)

    def detect(self, frame: np.ndarray) -> Optional[BlobPoint]:
        """Detect the wand tip in a grayscale frame. Single-wand: picks the largest blob."""
        keypoints = self._detector.detect(frame)
        index = self._frame_index
        self._frame_index += 1
        if not keypoints:
            return None
        best = max(keypoints, key=lambda kp: kp.size)
        radius = best.size / 2.0
        area = math.pi * radius * radius
        return BlobPoint(
            x=best.pt[0],
            y=best.pt[1],
            area=area,
            frame_index=index,
            timestamp=time.monotonic(),
        )


@dataclass
class TrajectoryStats:
    length: float
    avg_speed: float
    duration_ms: float
    bounding_box: Tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)


class BlobTracker:
    """Maintains a bounded trajectory buffer for the currently-tracked wand tip."""

    def __init__(self, max_points: int = 200):
        self.max_points = max_points
        self._points: Deque[BlobPoint] = deque(maxlen=max_points)
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def trajectory(self) -> List[BlobPoint]:
        return list(self._points)

    def start(self, point: Optional[BlobPoint] = None) -> None:
        self._points.clear()
        self._active = True
        if point is not None:
            self._points.append(point)

    def update(self, point: BlobPoint) -> None:
        if not self._active:
            self.start(point)
            return
        self._points.append(point)

    def stop(self) -> List[BlobPoint]:
        trajectory = self.trajectory
        self._points.clear()
        self._active = False
        return trajectory

    @property
    def centroid(self) -> Optional[Tuple[float, float]]:
        if not self._points:
            return None
        xs = [p.x for p in self._points]
        ys = [p.y for p in self._points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def stats(self) -> Optional[TrajectoryStats]:
        points = self.trajectory
        if len(points) < 2:
            return None
        length = sum(
            math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(points, points[1:])
        )
        duration_s = points[-1].timestamp - points[0].timestamp
        avg_speed = length / duration_s if duration_s > 0 else 0.0
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        bounding_box = (min(xs), min(ys), max(xs), max(ys))
        return TrajectoryStats(
            length=length,
            avg_speed=avg_speed,
            duration_ms=duration_s * 1000,
            bounding_box=bounding_box,
        )
