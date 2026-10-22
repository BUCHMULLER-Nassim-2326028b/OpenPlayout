from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.database import PlaybackHistory
from app.main import create_app
from conftest import SimulatedEngine
from test_api import add_asset


def test_restart_persists_library_and_rundown_without_replay(tmp_path):
    cfg = Settings(data_dir=tmp_path / "data", api_token="test-token-with-more-than-24-chars", caspar_media_root=str(tmp_path))
    first_engine = SimulatedEngine()
    first_app = create_app(cfg, engine_factory=lambda _: first_engine)
    auth = {"Authorization": "Bearer " + cfg.api_token}
    with TestClient(first_app) as client:
        media_id = add_asset(first_app, tmp_path)
        item_id = client.post("/api/playlists/main/items", json={"media_id": media_id}, headers=auth).json()["id"]
        client.post("/api/playout", json={"action": "connect"}, headers=auth)
        client.post("/api/playout", json={"action": "play"}, headers=auth)
    second_engine = SimulatedEngine()
    second_app = create_app(cfg, engine_factory=lambda _: second_engine)
    with TestClient(second_app) as client:
        assert client.get("/api/media", headers=auth).json()[0]["id"] == media_id
        assert client.get("/api/playlists/main", headers=auth).json()[0]["id"] == item_id
        assert client.get("/api/status", headers=auth).json()["current"] is None
        assert second_engine.calls == []
        with second_app.state.sessions() as db:
            record = db.scalar(select(PlaybackHistory))
            assert record.outcome == "interrupted_by_restart"
            assert record.ended_at is None
