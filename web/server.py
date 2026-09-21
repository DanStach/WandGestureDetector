"""FastAPI admin app: gesture/action CRUD, live stats (web/server.py)."""

from __future__ import annotations

import asyncio
from typing import Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
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
    preview_provider: Optional[Callable[[], Optional[bytes]]] = None,
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

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PREVIEW_PAGE

    @app.get("/stream.mjpg")
    async def stream():
        if preview_provider is None:
            raise HTTPException(status_code=404, detail="Preview not available")

        async def frames():
            last = None
            while True:
                jpeg = preview_provider()
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app


PREVIEW_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>IR Gesture Live</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;background:#111;color:#eee;font:16px system-ui,sans-serif;text-align:center}
img{max-width:100%;background:#000}
.bars{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;padding:12px}
.bar{width:220px;text-align:left}
.track{height:14px;background:#333;border-radius:7px;overflow:hidden}
.fill{height:100%;width:0;background:#3c9;transition:width .3s}
#info{padding:0 12px 16px;color:#aaa}
</style></head><body>
<img src="/stream.mjpg" alt="live camera">
<div class="bars">
  <div class="bar">CPU <span id="cpu">-</span>%<div class="track"><div class="fill" id="cpuf"></div></div></div>
  <div class="bar">Memory <span id="mem">-</span>%<div class="track"><div class="fill" id="memf"></div></div></div>
</div>
<div id="info"></div>
<script>
function bar(id,v){document.getElementById(id).textContent=v.toFixed(0);
  const f=document.getElementById(id+'f');f.style.width=v+'%';f.style.background=v>85?'#e55':v>65?'#ec4':'#3c9'}
async function tick(){try{const s=await (await fetch('/api/stats')).json();
  bar('cpu',s.cpu_percent);bar('mem',s.mem_percent);
  const g=s.last_gesture?s.last_gesture.name+' ('+s.last_gesture.confidence.toFixed(2)+')':'-';
  document.getElementById('info').textContent='FPS '+s.fps.toFixed(0)+' | blob: '+(s.blob_detected?'yes':'no')+
   ' | tracking: '+(s.tracking?'yes':'no')+' | last gesture: '+g+(s.cpu_temp_c!=null?' | '+s.cpu_temp_c.toFixed(0)+'\u00b0C':'')}catch(e){}}
setInterval(tick,1000);tick();
</script></body></html>"""
