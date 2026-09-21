"""Draws blob, trajectory and status text onto preview frames (display/overlay.py)."""

from __future__ import annotations

from typing import Optional, Sequence

import cv2
import numpy as np

GREEN = (0, 255, 0)
YELLOW = (0, 255, 255)
WHITE = (255, 255, 255)


def draw_overlay(frame_bgr: np.ndarray, trajectory: Sequence, point, stats: dict) -> np.ndarray:
    out = frame_bgr  # drawn in place: callers hand over a fresh capture buffer

    if len(trajectory) >= 2:
        pts = np.array([(int(p.x), int(p.y)) for p in trajectory], dtype=np.int32)
        cv2.polylines(out, [pts], False, YELLOW, 2)
    if point is not None:
        cv2.circle(out, (int(point.x), int(point.y)), 14, GREEN, 2)

    last = stats.get("last_gesture")
    temp = stats.get("cpu_temp_c")
    lines = [
        f"FPS {stats.get('fps', 0):.0f}   CPU {stats.get('cpu_percent', 0):.0f}%   "
        f"MEM {stats.get('mem_percent', 0):.0f}%" + (f"   {temp:.0f}C" if temp is not None else ""),
        f"blob: {'yes' if stats.get('blob_detected') else 'no'}   "
        f"tracking: {'yes' if stats.get('tracking') else 'no'}   pts: {stats.get('trajectory_length', 0)}",
        f"gesture: {last['name']} ({last['confidence']:.2f})" if last else "gesture: -",
    ]
    cv2.rectangle(out, (0, 0), (out.shape[1], 12 + 22 * len(lines)), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        cv2.putText(out, text, (8, 22 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1, cv2.LINE_AA)
    return out
