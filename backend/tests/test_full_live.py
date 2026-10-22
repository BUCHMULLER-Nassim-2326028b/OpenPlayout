"""Opt-in application acceptance with isolated data and generated media only."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import socket
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.config import ROOT, Settings
from app.main import create_app


@pytest.mark.caspar
@pytest.mark.skipif(os.environ.get("OPENPLAYOUT_TEST_FULL_APP") != "1", reason="Full real-server application acceptance is opt-in")
def test_full_index_rundown_auto_and_restart():
    workspace = ROOT / ".tools" / "acceptance" / str(uuid4())
    media = workspace / "media"
    media.mkdir(parents=True)
    bundle = ROOT / ".tools" / "casparcg" / "2.5.1"
    for color in ("red", "blue"):
        subprocess.run([str(bundle / "ffmpeg.exe"), "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=25", "-t", "3", "-c:v", "mpeg4", str(media / f"{color}.mp4")], check=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    cfg = Settings(data_dir=workspace / "data", caspar_port=port, caspar_media_root=str(media), caspar_autostart=True)
    app = create_app(cfg)
    samples = []
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + cfg.api_token
        assert client.post("/api/playout", json={"action": "disconnect"}).status_code == 200
        channel = client.get("/api/settings").json()["channel"]
        channel["directories"] = [str(media)]
        assert client.put("/api/settings", json=channel).status_code == 200
        assert client.post("/api/media/scan", json={"directory": str(media)}).json()["indexed"] == 2
        assets = client.get("/api/media").json()
        for asset in sorted(assets, key=lambda a: a["title"], reverse=True):
            assert client.post("/api/playlists/main/items", json={"media_id": asset["id"]}).status_code == 200
        assert client.post("/api/playout", json={"action": "connect"}).status_code == 200
        response = client.post("/api/playout", json={"action": "play"})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 9
        titles = set()
        while time.monotonic() < deadline:
            state = client.get("/api/status").json()
            samples.append({"time": datetime.now(timezone.utc).isoformat(), "state": state})
            assert state["error"] is None, state["error"]
            if state["current"]:
                titles.add(state["current"]["media"]["title"])
            if state["observation"]["state"] == "ended":
                break
            time.sleep(0.1)
        (workspace / "observations.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
        assert titles == {"red", "blue"}
        assert state["observation"]["state"] == "ended", state
        assert not state["automation"]
        assert client.post("/api/playout", json={"action": "stop"}).status_code == 200
        schedule_id = client.post("/api/schedules", json={"name": "Live timed acceptance", "timezone": "Europe/Paris"}).json()["id"]
        target = datetime.now(timezone.utc) + timedelta(seconds=3)
        assert client.post(f"/api/schedules/{schedule_id}/events", json={"media_id": assets[0]["id"], "preferred_start": target.isoformat(), "kind": "hard"}).status_code == 200
        armed = client.post(f"/api/schedules/{schedule_id}/arm")
        assert armed.status_code == 200, armed.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            record = client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]
            if record["status"] == "completed":
                break
            assert record["status"] not in ("missed", "blocked", "error"), record
            time.sleep(0.1)
        assert record["status"] == "completed", record
        command_delay = (datetime.fromisoformat(record["command_at"]) - target).total_seconds()
        observation_delay = (datetime.fromisoformat(record["observed_at"]) - target).total_seconds()
        assert 0 <= command_delay <= 0.5, record
        assert 0 <= observation_delay < 1, record
        (workspace / "schedule-timing.json").write_text(json.dumps(record | {"command_delay_seconds": command_delay, "observation_delay_seconds": observation_delay}, indent=2), encoding="utf-8")
        assert client.post("/api/playout", json={"action": "stop"}).status_code == 200
    restarted = create_app(cfg)
    with TestClient(restarted) as client:
        client.headers["Authorization"] = "Bearer " + cfg.api_token
        assert len(client.get("/api/media").json()) == 2
        assert len(client.get("/api/playlists/main").json()) == 2
        assert client.get("/api/status").json()["current"] is None
        assert client.get("/api/status").json()["scheduler"]["armed_schedule_id"] is None
        assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "completed"
