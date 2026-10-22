from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from app.config import ROOT
from app.database import Channel, MediaAsset, MediaLocation, Playlist, PlaylistItem, make_database


def test_phase_one_database_upgrades_without_losing_library_or_playlist(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    configuration = Config(str(ROOT / "backend/alembic.ini"))
    configuration.attributes["database_url"] = url
    command.upgrade(configuration, "0001")
    engine, sessions = make_database(url)
    with sessions() as db:
        db.add(Channel(id="main"))
        db.flush()
        db.add(Playlist(id="main"))
        asset = MediaAsset(title="Existing media", metadata_json={"duration": "10"})
        db.add(asset)
        db.flush()
        db.add(MediaLocation(media_id=asset.id, path=str(tmp_path / "clip.mp4"), root=str(tmp_path), relative_path="clip.mp4", size=123, mtime_ns=456))
        db.execute(text("INSERT INTO playlist_items (id, playlist_id, media_id, position) VALUES ('old-item', 'main', :media, 0)"), {"media": asset.id})
        db.commit()
        media_id = asset.id
    command.upgrade(configuration, "head")
    with sessions() as db:
        assert db.get(MediaAsset, media_id).title == "Existing media"
        assert db.scalar(select(PlaylistItem)).media_id == media_id
        assert db.scalar(select(MediaLocation)).mtime_ns == 456
    assert {"schedules", "scheduled_events", "schedule_executions"}.issubset(inspect(engine).get_table_names())
    engine.dispose()
