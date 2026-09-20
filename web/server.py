"""FastAPI admin app: gesture/action CRUD, live stats (web/server.py)."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from actions.executor import ActionRegistry, ActionType, GestureAction
from gestures.patterns import GesturePattern, GestureStore, GestureType


class GesturePatternIn(BaseModel):
    id: str
    name: str
    type: GestureType
    enabled: bool = True
    min_distance: float = 60.0
    timeout_ms: int = 3000
    min_speed: Optional[float] = None
    max_speed: Optional[float] = None
    min_rotations: Optional[float] = None
    min_radius: Optional[float] = None
    circularity_tolerance: Optional[float] = None
    max_deviation: Optional[float] = None
    min_linearity: Optional[float] = None
    max_movement: Optional[float] = None
    min_duration_ms: Optional[int] = None
    min_direction_changes: Optional[int] = None
    min_turn_angle_deg: Optional[float] = None


class GestureActionIn(BaseModel):
    gesture_id: str
    action_type: ActionType
    target: str
    duration_ms: Optional[int] = None


def create_app(
    gesture_store: GestureStore,
    action_registry: ActionRegistry,
    stats_provider: Callable[[], Dict],
) -> FastAPI:
    app = FastAPI(title="IR Gesture Detection System")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/gestures")
    def list_gestures():
        return [p.to_dict() for p in gesture_store.list()]

    @app.post("/api/gestures", status_code=201)
    def create_gesture(gesture: GesturePatternIn):
        if gesture_store.get(gesture.id) is not None:
            raise HTTPException(status_code=400, detail=f"Gesture '{gesture.id}' already exists")
        pattern = GesturePattern.from_dict(gesture.model_dump(exclude_none=True))
        gesture_store.upsert(pattern)
        return pattern.to_dict()

    @app.put("/api/gestures/{gesture_id}")
    def update_gesture(gesture_id: str, gesture: GesturePatternIn):
        if gesture_store.get(gesture_id) is None:
            raise HTTPException(status_code=404, detail=f"Gesture '{gesture_id}' not found")
        data = gesture.model_dump(exclude_none=True)
        data["id"] = gesture_id
        pattern = GesturePattern.from_dict(data)
        gesture_store.upsert(pattern)
        return pattern.to_dict()

    @app.delete("/api/gestures/{gesture_id}", status_code=204)
    def delete_gesture(gesture_id: str):
        if not gesture_store.delete(gesture_id):
            raise HTTPException(status_code=404, detail=f"Gesture '{gesture_id}' not found")

    @app.get("/api/actions")
    def list_actions():
        return [a.to_dict() for a in action_registry.list()]

    @app.post("/api/actions", status_code=201)
    def create_action(action: GestureActionIn):
        gesture_action = GestureAction(**action.model_dump())
        action_registry.upsert(gesture_action)
        return gesture_action.to_dict()

    @app.delete("/api/actions/{gesture_id}", status_code=204)
    def delete_action(gesture_id: str):
        if not action_registry.delete(gesture_id):
            raise HTTPException(status_code=404, detail=f"Action for gesture '{gesture_id}' not found")

    @app.get("/api/stats")
    def get_stats():
        return stats_provider()

    return app
