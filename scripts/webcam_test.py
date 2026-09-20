"""Laptop webcam test harness: live preview + gesture recognition, no actions fired.

Uses the real IRDetector / BlobTracker / GestureClassifier. A laptop webcam has no IR
illumination, so use a bright point instead of the wand: a phone flashlight or a bright
screen pointed at the camera. Tune with --min-threshold if the blob isn't picked up.

Keys: q/Esc quit, r reset trajectory.
Requires the GUI build of OpenCV (pip install opencv-python), not -headless.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera.detector import BlobDetectorConfig, BlobTracker, IRDetector  # noqa: E402
from gestures.classifier import GestureClassifier  # noqa: E402
from gestures.patterns import GestureStore  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
MOVEMENT_EPSILON_PX = 1.5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="cv2.VideoCapture index")
    parser.add_argument("--min-threshold", type=float, default=150)
    parser.add_argument("--max-threshold", type=float, default=250)
    parser.add_argument("--min-area", type=float, default=20)
    parser.add_argument("--max-area", type=float, default=2000)
    parser.add_argument("--mirror", action="store_true", help="flip horizontally (selfie view)")
    args = parser.parse_args()

    store = GestureStore(CONFIG_DIR / "gestures.json")
    store.load()
    classifier = GestureClassifier(store.list())
    timeout_ms = min((p.timeout_ms for p in store.list() if p.enabled), default=2000)

    detector = IRDetector(
        BlobDetectorConfig(
            min_threshold=args.min_threshold,
            max_threshold=args.max_threshold,
            min_area=args.min_area,
            max_area=args.max_area,
        )
    )
    tracker = BlobTracker()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(
            "Could not open the camera. On macOS, grant camera access to your terminal/app in "
            "System Settings > Privacy & Security > Camera.",
            file=sys.stderr,
        )
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    last_activity = time.monotonic()
    last_result = "none yet"
    result_until = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if args.mirror:
                frame = cv2.flip(frame, 1)
            now = time.monotonic()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            point = detector.detect(gray)

            if point is not None:
                prev = tracker.trajectory[-1] if tracker.active and tracker.trajectory else None
                tracker.update(point)
                if prev is None or math.hypot(point.x - prev.x, point.y - prev.y) > MOVEMENT_EPSILON_PX:
                    last_activity = now

            if tracker.active and (now - last_activity) * 1000 > timeout_ms:
                trajectory = tracker.stop()
                classifier.patterns = store.list()
                result = classifier.classify(trajectory) if len(trajectory) >= 2 else None
                if result:
                    last_result = f"{result.gesture_name} ({result.confidence:.2f})"
                else:
                    last_result = f"no match ({len(trajectory)} pts)"
                print(f"[gesture] {last_result}")
                result_until = now + 3.0
                last_activity = now

            # -- overlay --
            traj = tracker.trajectory
            for a, b in zip(traj, traj[1:]):
                cv2.line(frame, (int(a.x), int(a.y)), (int(b.x), int(b.y)), (0, 255, 255), 2)
            if point is not None:
                cv2.circle(frame, (int(point.x), int(point.y)), 12, (0, 255, 0), 2)
            status = f"blob: {'yes' if point else 'no'}  pts: {len(traj)}  timeout: {timeout_ms:.0f}ms"
            cv2.putText(frame, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            color = (0, 255, 0) if now < result_until else (180, 180, 180)
            cv2.putText(frame, f"last: {last_result}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("wand test (q to quit, r to reset)", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                tracker.stop()
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
