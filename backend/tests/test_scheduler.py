from datetime import datetime, timedelta, timezone
from fractions import Fraction
import json

import pytest
from sqlalchemy import select

from app.database import ScheduleExecution
from app.scheduler.planner import build_plan, day_window, instant, local_instant
from test_api import add_asset


def event(key, start="2026-10-22T18:00:00+00:00", duration="10", kind="hard", delay=0):
    return {"id": key, "preferred_start": start, "kind": kind, "max_delay_seconds": delay,
        "media": {"missing": False, "error": None, "kind": "video", "metadata": {"duration": duration}}}


def test_exact_fit_and_hard_conflict():
    first = event("a")
    second = event("b", "2026-10-22T18:00:10Z")
    assert build_plan([first, second], Fraction(25))["valid"]
    second["preferred_start"] = "2026-10-22T18:00:09Z"
    plan = build_plan([first, second], Fraction(25))
    assert not plan["valid"] and "overlap" in plan["errors"][0]["message"]


def test_soft_placement_respects_hard_and_delay_window():
    hard = event("hard", "2026-10-22T18:00:05Z", "10")
    soft = event("soft", duration="6", kind="soft", delay=15)
    plan = build_plan([soft, hard], Fraction(25))
    assert plan["valid"]
    moved = next(e for e in plan["events"] if e["id"] == "soft")
    assert moved["planned_start"] == "2026-10-22T18:00:15+00:00"
    soft["max_delay_seconds"] = 14
    assert not build_plan([hard, soft], Fraction(25))["valid"]


def test_rational_mixed_rate_duration_and_midnight():
    plan = build_plan([event("a", "2026-10-22T23:59:59Z", "1001/300")], Fraction(25))
    assert plan["events"][0]["frames"] == 84
    assert plan["events"][0]["duration_rational"] == "84/25"
    assert plan["events"][0]["planned_end"] == "2026-10-23T00:00:02.360000+00:00"


@pytest.mark.parametrize("day,seconds", [("2026-03-29", 23*3600), ("2026-10-25", 25*3600), ("2026-10-22", 24*3600)])
def test_local_day_duration(day, seconds):
    assert day_window(day, "Europe/Paris")["seconds"] == seconds


def test_dst_nonexistent_and_ambiguous_are_explicit():
    with pytest.raises(ValueError, match="does not exist"):
        local_instant("2026-03-29T02:30", "Europe/Paris")
    with pytest.raises(ValueError, match="occurs twice"):
        local_instant("2026-10-25T02:30", "Europe/Paris")
    first = local_instant("2026-10-25T02:30", "Europe/Paris", 0)
    second = local_instant("2026-10-25T02:30", "Europe/Paris", 1)
    assert instant(second) - instant(first) == 3600
    with pytest.raises(ValueError, match="offset"):
        instant("2026-10-22T20:00")


def test_schedule_api_import_preview_and_roundtrip(harness):
    client, app, _, root = harness
    media_id = add_asset(app, root)
    schedule_id = client.post("/api/schedules", json={"name": "Evening", "timezone": "Europe/Paris"}).json()["id"]
    payload = {"media_id": media_id, "preferred_start": "2030-01-01T18:00:00Z", "user_fields": {"producer": "studio"}}
    assert client.post(f"/api/schedules/{schedule_id}/events", json=payload).status_code == 200
    detail = client.get(f"/api/schedules/{schedule_id}").json()
    assert detail["valid"] and detail["events"][0]["duration_rational"] == "10"
    exported = client.get(f"/api/schedules/{schedule_id}/export").json()
    before = len(client.get("/api/schedules").json())
    imported = {"format": "json", "content": exported["content"]}
    assert client.post("/api/schedules/import", json=imported).json()["preview"]
    assert len(client.get("/api/schedules").json()) == before
    response = client.post("/api/schedules/import", json=imported | {"commit": True})
    assert response.status_code == 200 and response.json()["id"] != schedule_id
    csv = client.get(f"/api/schedules/{schedule_id}/export?format=csv").json()["content"]
    assert client.post("/api/schedules/import", json={"format": "csv", "content": csv}).json()["valid"]
    assert detail["source_events"][0]["user_fields"] == {"producer": "studio"}
    assert client.post("/api/schedules/import", json={"format": "json", "content": '{"version":2}'}).status_code == 400
    assert client.post("/api/schedules/resolve-time", json={"timezone": "Europe/Paris", "local_time": "2026-10-25T02:30"}).status_code == 400


def make_future_schedule(client, app, root):
    media_id = add_asset(app, root)
    schedule_id = client.post("/api/schedules", json={"name": "Test dispatch"}).json()["id"]
    target = datetime.now(timezone.utc) + timedelta(minutes=1)
    event_id = client.post(f"/api/schedules/{schedule_id}/events", json={"media_id": media_id, "preferred_start": target.isoformat()}).json()["id"]
    client.post("/api/playout", json={"action": "connect"})
    assert client.post(f"/api/schedules/{schedule_id}/arm").status_code == 200
    return schedule_id, event_id, target


def test_arm_manual_guard_and_stop(harness):
    client, app, _, root = harness
    schedule_id, event_id, _ = make_future_schedule(client, app, root)
    assert client.post("/api/playout", json={"action": "pause"}).status_code == 409
    assert client.delete(f"/api/schedules/{schedule_id}/events/{event_id}").status_code == 409
    assert client.post("/api/playout", json={"action": "stop"}).status_code == 200
    assert client.get("/api/status").json()["scheduler"]["armed_schedule_id"] is None
    assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "cancelled"


def test_dispatch_once_complete_and_no_replay(harness):
    client, app, engine, root = harness
    schedule_id, event_id, target = make_future_schedule(client, app, root)
    client.portal.call(app.state.scheduler.tick, target)
    assert engine.state == "playing"
    assert client.get("/api/status").json()["current"]["id"] == event_id
    plays = len([c for c in engine.calls if c[0] == "play"])
    client.portal.call(app.state.scheduler.tick, target + timedelta(milliseconds=100))
    assert len([c for c in engine.calls if c[0] == "play"]) == plays
    engine.finish()
    client.portal.call(app.state.controller.poll)
    client.portal.call(app.state.scheduler.tick, target + timedelta(seconds=10))
    assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "completed"
    assert client.get("/api/playlists/main").json() == []  # Operator rundown was not rewritten.


@pytest.mark.parametrize("occupied,status", [(True, "blocked"), (False, "missed")])
def test_deadlines_do_not_cut_or_replay_late(harness, occupied, status):
    client, app, engine, root = harness
    schedule_id, _, target = make_future_schedule(client, app, root)
    if occupied:
        engine.state = "playing"
        client.portal.call(app.state.controller.poll)
        when = target + timedelta(milliseconds=600)
    else:
        when = target + timedelta(seconds=2)
    client.portal.call(app.state.scheduler.tick, when)
    row = client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]
    assert row["status"] == status
    assert not [call for call in engine.calls if call[0] == "play"]


def test_crash_recovery_never_replays_dispatching(harness):
    client, app, _, root = harness
    _, _, _ = make_future_schedule(client, app, root)
    with app.state.sessions() as db:
        row = db.scalar(select(ScheduleExecution))
        row.status = "dispatching"
        row.command_at = datetime.now(timezone.utc).isoformat()
        db.commit()
    app.state.scheduler.recover()
    with app.state.sessions() as db:
        assert db.scalar(select(ScheduleExecution)).status == "interrupted"


def test_busy_output_can_finish_inside_dispatch_tolerance(harness):
    client, app, engine, root = harness
    schedule_id, _, target = make_future_schedule(client, app, root)
    engine.state = "playing"
    client.portal.call(app.state.controller.poll)
    client.portal.call(app.state.scheduler.tick, target)
    assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "pending"
    engine.state = "stopped"
    client.portal.call(app.state.controller.poll)
    client.portal.call(app.state.scheduler.tick, target + timedelta(milliseconds=400))
    assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "running"


def test_changed_media_is_not_dispatched_from_stale_snapshot(harness):
    client, app, engine, root = harness
    schedule_id, _, target = make_future_schedule(client, app, root)
    (root / "one.mp4").write_bytes(b"modified since indexing")
    client.portal.call(app.state.scheduler.tick, target)
    assert client.get(f"/api/schedules/{schedule_id}").json()["executions"][0]["status"] == "error"
    assert not [call for call in engine.calls if call[0] == "play"]


def test_import_commit_preserves_equal_time_soft_preview_order(harness):
    client, app, _, root = harness
    media_id = add_asset(app, root)
    events = [{"media_id": media_id, "preferred_start": "2030-01-01T10:00:00Z", "kind": "soft", "max_delay_seconds": delay, "label": label}
        for label, delay in (("Must go first", 0), ("Can follow", 10))]
    body = {"format": "json", "content": json.dumps({"version": 1, "name": "Stable import", "timezone": "UTC", "events": events})}
    preview = client.post("/api/schedules/import", json=body).json()
    assert preview["valid"]
    imported = client.post("/api/schedules/import", json=body | {"commit": True}).json()
    committed = client.get(f"/api/schedules/{imported['id']}").json()
    assert committed["valid"]
    assert [(e["label"], e["planned_start"]) for e in preview["events"]] == [(e["label"], e["planned_start"]) for e in committed["events"]]
