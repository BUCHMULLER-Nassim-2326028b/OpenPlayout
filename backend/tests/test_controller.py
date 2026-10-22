import pytest
from sqlalchemy import select

from app.database import Base, Channel, Playlist, PlaylistItem, PlaybackHistory, make_database
from app.playout.controller import PlayoutController
from app.playout.engine import EngineError
from conftest import SimulatedEngine
from test_api import add_asset


def make_controller(tmp_path):
    engine, sessions = make_database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add(Channel(id="main"))
        db.flush()
        db.add(Playlist(id="main"))
        db.commit()
    class App:
        class state:
            pass
    App.state.sessions = sessions
    ids = []
    for index in range(3):
        media_id = add_asset(App, tmp_path, f"clip-{index}.mp4")
        with sessions() as db:
            item = PlaylistItem(media_id=media_id, position=index)
            db.add(item)
            db.commit()
            ids.append(item.id)
    fake = SimulatedEngine()
    return PlayoutController(fake, sessions, str(tmp_path)), fake, ids, engine


async def test_native_auto_advancement_and_as_run(tmp_path):
    controller, fake, ids, db_engine = make_controller(tmp_path)
    await controller.action("connect")
    await controller.action("play")
    assert controller.current_id == ids[0]
    assert fake.background == "clip-1.mp4"
    fake.finish()
    await controller.poll()
    assert controller.current_id == ids[1]
    assert fake.background == "clip-2.mp4"
    assert [c for c in fake.calls if c[0] == "play"] == [("play", "clip-0.mp4")]
    with controller.sessions() as db:
        history = list(db.scalars(select(PlaybackHistory).order_by(PlaybackHistory.started_at)))
        assert history[0].outcome == "completed"
        assert history[1].outcome == "playing"
    db_engine.dispose()


async def test_manual_skip_missing_media_and_preload_failure(tmp_path):
    controller, fake, ids, db_engine = make_controller(tmp_path)
    await controller.action("connect")
    await controller.action("play")
    await controller.action("next")
    assert controller.current_id == ids[1]
    await controller.action("stop")
    (tmp_path / "clip-0.mp4").unlink()
    with pytest.raises(EngineError, match="missing"):
        await controller.action("play")
    assert controller.error and not controller.automation
    fake.fail_preload = True
    with pytest.raises(EngineError, match="preload"):
        await controller.action("play", ids[1])
    assert not controller.automation
    db_engine.dispose()


async def test_disconnect_never_replays_on_reconnect(tmp_path):
    controller, fake, _, db_engine = make_controller(tmp_path)
    await controller.action("connect")
    await controller.action("play")
    fake.connected = False
    await controller.poll()
    assert controller.automation is False
    plays = len([c for c in fake.calls if c[0] == "play"])
    controller.retry_at = 0
    await controller.poll()
    assert len([c for c in fake.calls if c[0] == "play"]) == plays
    assert controller.automation is False
    db_engine.dispose()


async def test_delayed_first_render_does_not_suspend_automation(tmp_path):
    controller, fake, _, db_engine = make_controller(tmp_path)
    await controller.action("connect")
    await controller.action("play")
    first_clip = fake.foreground
    fake.foreground = None  # INFO still reflects the render cycle before PLAY.
    await controller.poll()
    assert controller.automation
    fake.foreground = first_clip
    await controller.poll()
    assert controller.automation and controller.error is None
    db_engine.dispose()


async def test_stale_eof_is_not_treated_as_new_clip_completion(tmp_path):
    controller, fake, ids, db_engine = make_controller(tmp_path)
    await controller.action("connect")
    await controller.action("play")
    controller.playback_confirmed = False
    fake.state, fake.position = "ended", 10
    await controller.poll()
    assert controller.automation and controller.current_id == ids[0]
    fake.state, fake.position = "playing", 0
    await controller.poll()
    assert controller.playback_confirmed
    db_engine.dispose()
