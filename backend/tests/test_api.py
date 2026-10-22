from app.database import MediaAsset, MediaLocation


def add_asset(app, root, filename="one.mp4"):
    path = root / filename
    path.write_bytes(b"test fixture; not playable video")
    with app.state.sessions() as db:
        asset = MediaAsset(title=path.stem, kind="video", metadata_json={"duration": "10", "fps": "25"})
        db.add(asset)
        db.flush()
        db.add(MediaLocation(media_id=asset.id, path=str(path), root=str(root), relative_path=filename, size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns))
        db.commit()
        return asset.id


def test_auth_and_origins(harness):
    client, _, _, _ = harness
    assert client.get("/api/health", headers={"Authorization": ""}).status_code == 200
    assert client.get("/api/media", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/playout", json={"action": "stop"}, headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.post("/api/playout", json={"action": "raw_amcp"}).status_code == 422


def test_persistent_settings_and_playlist(harness):
    client, app, _, root = harness
    one = add_asset(app, root)
    two = add_asset(app, root, "two.mp4")
    a = client.post("/api/playlists/main/items", json={"media_id": one}).json()["id"]
    b = client.post("/api/playlists/main/items", json={"media_id": two}).json()["id"]
    assert client.put("/api/playlists/main/order", json={"item_ids": [b, a]}).status_code == 200
    assert [r["id"] for r in client.get("/api/playlists/main").json()] == [b, a]
    assert client.put("/api/playlists/main/order", json={"item_ids": [a, a]}).status_code == 400
    cfg = client.get("/api/settings").json()["channel"]
    cfg["name"] = "Independent channel"
    cfg["directories"] = [str(root)]
    assert client.put("/api/settings", json=cfg).status_code == 200
    assert client.get("/api/settings").json()["channel"]["name"] == cfg["name"]
    assert list((root / "data" / "backups").glob("settings-*.json"))
    assert client.delete(f"/api/playlists/main/items/{a}").status_code == 200
    assert len(client.get("/api/playlists/main").json()) == 1


def test_playout_controls_and_edit_guard(harness):
    client, app, engine, root = harness
    media = add_asset(app, root)
    client.post("/api/playlists/main/items", json={"media_id": media})
    assert client.post("/api/playout", json={"action": "play"}).status_code == 409
    assert client.post("/api/playout", json={"action": "connect"}).status_code == 200
    assert client.post("/api/playout", json={"action": "play"}).status_code == 200
    assert engine.state == "playing"
    assert client.post("/api/playlists/main/items", json={"media_id": media}).status_code == 409
    assert client.post("/api/playout", json={"action": "pause"}).json()["observation"]["state"] == "paused"
    assert client.post("/api/playout", json={"action": "resume"}).json()["observation"]["state"] == "playing"
    assert client.post("/api/playout", json={"action": "seek", "frame": 50}).json()["observation"]["position_seconds"] == 2
    assert client.post("/api/playout", json={"action": "stop"}).status_code == 200
    assert client.get("/api/history").json()[0]["outcome"] == "stopped"


def test_scan_requires_configured_directory(harness):
    client, _, _, root = harness
    assert client.post("/api/media/scan", json={"directory": str(root)}).status_code == 400


def test_websocket_auth(harness):
    client, _, _, _ = harness
    with client.websocket_connect("/ws", headers={"Origin": "http://127.0.0.1:5173"}) as ws:
        ws.send_json({"token": "test-token-with-more-than-24-chars"})
        payload = ws.receive_json()
        assert payload["type"] == "status"
        assert payload["data"]["observation"]["connected"] is False
