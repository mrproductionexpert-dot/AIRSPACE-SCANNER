"""FastAPI backend — Wi-Fi Airspace Scanner (Camera & Drone Detector)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .classifier import DeviceTracker, generate_simulation_devices
from .network_probe import NetworkProbe
from .wlan_win32 import WifiScanner

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


class AppState:
    def __init__(self) -> None:
        self.scanner = WifiScanner()
        self.tracker = DeviceTracker()
        self.probe = NetworkProbe()
        self.simulation = False
        self.scanning = False
        self.locked_bssid: Optional[str] = None
        self.scan_interval = 2.0
        self.lan_probe_enabled = True
        self._clients: set[WebSocket] = set()
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.last_error: Optional[str] = None
        self.last_scan_at: float = 0.0
        self.scan_count: int = 0
        self.last_client_left_at: Optional[float] = None
        self.auto_shutdown_seconds: float = 20.0
        self._idle_task: Optional[asyncio.Task] = None
        self.last_ui_activity_at: float = time.time()

    def snapshot(self) -> dict[str, Any]:
        devices = [d.to_dict() for d in self.tracker.devices()]
        adapters = [a.to_dict() for a in self.scanner.list_adapters()]
        selected = self.scanner.get_selected()
        locked = None
        if self.locked_bssid:
            d = self.tracker.get(self.locked_bssid)
            locked = d.to_dict() if d else {"bssid": self.locked_bssid}
        threats = [d for d in devices if d["score"] >= 60]
        return {
            "simulation": self.simulation,
            "scanning": self.scanning,
            "adapters": adapters,
            "selected_adapter": selected.to_dict() if selected else None,
            "devices": devices,
            "threats": threats,
            "locked": locked,
            "last_error": self.last_error,
            "last_scan_at": self.last_scan_at,
            "scan_count": self.scan_count,
            "scan_interval": self.scan_interval,
            "stats": {
                "device_count": len(devices),
                "threat_count": len(threats),
                "drone_count": sum(1 for d in devices if d["category"] == "DRONE"),
                "camera_count": sum(
                    1
                    for d in devices
                    if d["category"] in ("HIDDEN_CAM", "IP_CAMERA", "IOT_CAMERA")
                ),
            },
        }


state = AppState()


async def broadcast(payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    data = json.dumps(payload)
    for ws in list(state._clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state._clients.discard(ws)


async def scan_once() -> dict[str, Any]:
    async with state._lock:
        now = time.time()
        if state.simulation:
            entries = generate_simulation_devices(now)
            error = None
            adapter_info = {
                "guid": "{SIMULATION}",
                "description": "Simulation Mode (synthetic airspace)",
                "state": 1,
                "preferred": True,
            }
        else:
            result = await asyncio.to_thread(state.scanner.scan, 1.0)
            entries = result.networks
            error = result.error
            adapter_info = result.adapter.to_dict() if result.adapter else None

        for entry in entries:
            state.tracker.classify_bss(entry, now)

        if state.lan_probe_enabled and not state.simulation:
            try:
                hosts = await asyncio.to_thread(state.probe.scan_lan, False, 24)
                state.tracker.merge_lan(hosts, now)
            except Exception as exc:
                error = (error + "; " if error else "") + f"LAN probe: {exc}"

        state.tracker.prune(max_age_sec=60.0, now=now)
        state.last_error = error
        state.last_scan_at = now
        state.scan_count += 1

        snap = state.snapshot()
        snap["selected_adapter"] = adapter_info or snap["selected_adapter"]
        return snap


async def scan_loop() -> None:
    while state.scanning:
        try:
            snap = await scan_once()
            await broadcast({"type": "telemetry", "data": snap})
        except Exception as exc:
            state.last_error = str(exc)
            await broadcast(
                {"type": "error", "message": str(exc), "data": state.snapshot()}
            )
        await asyncio.sleep(state.scan_interval)


async def idle_shutdown_loop() -> None:
    """Auto-stop the hidden background process after all UI clients disconnect."""
    while True:
        await asyncio.sleep(2.0)
        # Keep alive while there is active UI heartbeat traffic.
        if time.time() - state.last_ui_activity_at < state.auto_shutdown_seconds:
            continue
        state.scanning = False
        if state._task:
            state._task.cancel()
            try:
                await state._task
            except Exception:
                pass
            state._task = None
        # Process is launched in hidden/background mode. Exit cleanly when UI is closed.
        os._exit(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-select preferred USB adapter if present
    try:
        state.scanner.select_adapter()
    except Exception:
        pass
    state._idle_task = asyncio.create_task(idle_shutdown_loop())
    yield
    state.scanning = False
    if state._task:
        state._task.cancel()
        try:
            await state._task
        except Exception:
            pass
    if state._idle_task:
        state._idle_task.cancel()
        try:
            await state._idle_task
        except Exception:
            pass
    state.scanner.close()


app = FastAPI(
    title="Wi-Fi Airspace Scanner",
    description="Hidden Wi-Fi Camera & Drone Detector (Windows Native)",
    version="1.0.0",
    lifespan=lifespan,
)

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class SelectAdapterBody(BaseModel):
    guid: Optional[str] = None


class SimulationBody(BaseModel):
    enabled: bool = True


class LockBody(BaseModel):
    bssid: Optional[str] = Field(default=None, description="BSSID to lock, or null to unlock")


class ScanIntervalBody(BaseModel):
    seconds: float = Field(ge=1.0, le=60.0, default=2.0)


class PingBody(BaseModel):
    t: Optional[float] = None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "scanning": state.scanning, "simulation": state.simulation}


@app.get("/api/snapshot")
async def snapshot() -> dict[str, Any]:
    return state.snapshot()


@app.get("/api/adapters")
async def adapters() -> dict[str, Any]:
    items = [a.to_dict() for a in state.scanner.list_adapters()]
    selected = state.scanner.get_selected()
    return {
        "adapters": items,
        "selected": selected.to_dict() if selected else None,
    }


@app.post("/api/adapters/select")
async def select_adapter(body: SelectAdapterBody) -> dict[str, Any]:
    chosen = state.scanner.select_adapter(body.guid)
    return {
        "ok": chosen is not None,
        "selected": chosen.to_dict() if chosen else None,
        "adapters": [a.to_dict() for a in state.scanner.list_adapters()],
    }


@app.post("/api/simulation")
async def set_simulation(body: SimulationBody) -> dict[str, Any]:
    state.simulation = body.enabled
    # Always reset so fake/demo entries disappear immediately when toggled off.
    state.tracker.reset()
    return state.snapshot()


@app.post("/api/scan/start")
async def start_scan() -> dict[str, Any]:
    if not state.scanning:
        state.scanning = True
        state._task = asyncio.create_task(scan_loop())
    return state.snapshot()


@app.post("/api/scan/stop")
async def stop_scan() -> dict[str, Any]:
    state.scanning = False
    if state._task:
        state._task.cancel()
        try:
            await state._task
        except Exception:
            pass
        state._task = None
    return state.snapshot()


@app.post("/api/scan/once")
async def scan_once_endpoint() -> dict[str, Any]:
    snap = await scan_once()
    await broadcast({"type": "telemetry", "data": snap})
    return snap


@app.post("/api/lock")
async def lock_target(body: LockBody) -> dict[str, Any]:
    state.locked_bssid = body.bssid.upper() if body.bssid else None
    return state.snapshot()


@app.post("/api/interval")
async def set_interval(body: ScanIntervalBody) -> dict[str, Any]:
    state.scan_interval = body.seconds
    return {"ok": True, "seconds": state.scan_interval}


@app.post("/api/ping")
async def ping(body: PingBody) -> dict[str, Any]:
    state.last_ui_activity_at = time.time()
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    state._clients.add(ws)
    state.last_client_left_at = None
    try:
        await ws.send_text(json.dumps({"type": "telemetry", "data": state.snapshot()}))
        while True:
            # Keepalive / client commands
            msg = await ws.receive_text()
            try:
                payload = json.loads(msg)
            except json.JSONDecodeError:
                continue
            cmd = payload.get("cmd")
            if cmd == "ping":
                state.last_ui_activity_at = time.time()
                await ws.send_text(json.dumps({"type": "pong", "t": time.time()}))
            elif cmd == "lock":
                state.last_ui_activity_at = time.time()
                state.locked_bssid = (payload.get("bssid") or "").upper() or None
                await broadcast({"type": "telemetry", "data": state.snapshot()})
            elif cmd == "unlock":
                state.last_ui_activity_at = time.time()
                state.locked_bssid = None
                await broadcast({"type": "telemetry", "data": state.snapshot()})
    except WebSocketDisconnect:
        pass
    finally:
        state._clients.discard(ws)
        if not state._clients:
            state.last_client_left_at = time.time()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
