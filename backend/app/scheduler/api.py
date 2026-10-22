import csv
from datetime import datetime
from fractions import Fraction
import io
import json
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..database import MediaAsset, MediaLocation, Schedule, ScheduledEvent, ScheduleExecution
from ..media import asset_dict
from .planner import build_plan, day_window, instant, iso, local_instant


class ScheduleInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Europe/Paris"

    @field_validator("timezone")
    @classmethod
    def validate_zone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value


class EventInput(BaseModel):
    media_id: str
    segment_id: str | None = None
    label: str = Field(default="", max_length=200)
    kind: Literal["hard", "soft"] = "hard"
    preferred_start: str
    max_delay_seconds: int = Field(default=0, ge=0, le=604800)
    user_fields: dict = Field(default_factory=dict)

    @field_validator("preferred_start")
    @classmethod
    def validate_start(cls, value):
        return iso(instant(value))


class LocalTimeInput(BaseModel):
    local_time: str
    timezone: str
    fold: Literal[0, 1] | None = None


class ImportInput(BaseModel):
    format: Literal["json", "csv"]
    content: str = Field(max_length=1_000_000)
    name: str = Field(default="Imported schedule", min_length=1, max_length=120)
    timezone: str = "Europe/Paris"
    commit: bool = False


def make_router(sessions, get_controller, get_runner, read_settings):
    router = APIRouter(prefix="/api/schedules", tags=["Schedules"])

    def event_dict(row):
        return {"id": row.id, "media_id": row.media_id, "segment_id": row.segment_id, "label": row.label, "kind": row.kind,
            "preferred_start": row.preferred_start, "max_delay_seconds": row.max_delay_seconds, "user_fields": row.user_fields}

    def require_schedule(db, schedule_id):
        row = db.get(Schedule, schedule_id)
        if not row:
            raise HTTPException(404, "Unknown schedule")
        return row

    def editable(db, schedule_id):
        if get_runner().armed_id == schedule_id or db.scalar(select(ScheduleExecution.id).join(ScheduledEvent).where(ScheduledEvent.schedule_id == schedule_id).limit(1)):
            raise HTTPException(409, "Executed or armed schedules are read-only. Export/import as a new schedule to revise them.")

    def plan_events(db, events):
        expanded = []
        for event in events:
            asset = db.get(MediaAsset, event["media_id"])
            location = db.scalar(select(MediaLocation).where(MediaLocation.media_id == event["media_id"]))
            if not asset or not location:
                raise HTTPException(400, f"Unknown or unlinked media: {event['media_id']}")
            media = asset_dict(asset, location)
            if event.get("segment_id"):
                from ..studio.library import media_item
                cfg = read_settings()
                item = media_item(db, event["media_id"], event["segment_id"], Fraction(cfg.fps_num, cfg.fps_den))
                media = media | {"metadata": media["metadata"] | {"duration": str(Fraction(item["duration_frames"], 1) / Fraction(cfg.fps_num, cfg.fps_den))}, "duration_seconds": item["duration_seconds"]}
                event = event | {"segment": item["segment"]}
            expanded.append(event | {"media": media})
        cfg = read_settings()
        return build_plan(expanded, Fraction(cfg.fps_num, cfg.fps_den))

    def plan(db, schedule_id):
        schedule = require_schedule(db, schedule_id)
        events = [event_dict(row) for row in db.scalars(select(ScheduledEvent).where(ScheduledEvent.schedule_id == schedule_id))]
        return plan_events(db, events) | {"id": schedule.id, "name": schedule.name, "timezone": schedule.timezone}

    @router.get("")
    def list_schedules():
        with sessions() as db:
            return [{"id": s.id, "name": s.name, "timezone": s.timezone} for s in db.scalars(select(Schedule).order_by(Schedule.name, Schedule.id))]

    @router.post("")
    async def create(body: ScheduleInput):
        async with get_runner().lock:
            with sessions() as db:
                schedule = Schedule(**body.model_dump())
                db.add(schedule)
                db.commit()
                if get_controller().events:
                    get_controller().events.publish("schedule.created", {"schedule_id": schedule.id})
                return {"id": schedule.id}

    @router.post("/resolve-time")
    def resolve(body: LocalTimeInput):
        try:
            return {"utc": local_instant(body.local_time, body.timezone, body.fold)}
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/day")
    def day(date: str, timezone: str):
        try:
            return day_window(date, timezone)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/import")
    async def import_schedule(body: ImportInput):
        try:
            if body.format == "json":
                payload = json.loads(body.content)
                if payload.get("version") != 1:
                    raise ValueError("Expected schedule JSON version 1")
                header = ScheduleInput(name=payload["name"], timezone=payload["timezone"])
                imported = payload["events"]
            else:
                header = ScheduleInput(name=body.name, timezone=body.timezone)
                imported = []
                for row in csv.DictReader(io.StringIO(body.content)):
                    extras = {k: v for k, v in row.items() if k not in EventInput.model_fields}
                    values = {k: v for k, v in row.items() if k in EventInput.model_fields and v != ""}
                    values["user_fields"] = json.loads(values.get("user_fields", "{}")) | extras
                    imported.append(values)
            if not isinstance(imported, list) or not 1 <= len(imported) <= 1000:
                raise ValueError("Import between 1 and 1000 events")
            events = [EventInput.model_validate(row).model_dump() for row in imported]
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(400, f"Invalid import: {exc}") from exc
        async with get_runner().lock:
            with sessions() as db:
                preview = plan_events(db, [e | {"id": f"import-{i:04d}"} for i, e in enumerate(events)])
                if not body.commit:
                    return preview | {"preview": True, "count": len(events)}
                if not preview["valid"]:
                    raise HTTPException(400, preview["errors"])
                schedule = Schedule(**header.model_dump())
                db.add(schedule)
                db.flush()
                for index, event in enumerate(events):
                    # Preserve preview order for equal requested times after IDs change.
                    db.add(ScheduledEvent(id=f"{schedule.id}-{index:04d}", schedule_id=schedule.id, **event))
                db.commit()
                return {"id": schedule.id, "created": len(events)}

    @router.get("/{schedule_id}")
    def detail(schedule_id: str):
        with sessions() as db:
            result = plan(db, schedule_id)
            result["source_events"] = [event_dict(r) for r in db.scalars(select(ScheduledEvent).where(ScheduledEvent.schedule_id == schedule_id).order_by(ScheduledEvent.preferred_start, ScheduledEvent.id))]
            result["executions"] = [{"id": r.id, "event_id": r.event_id, "status": r.status, "planned_start": r.planned_start,
                "planned_end": r.planned_end, "command_at": r.command_at, "observed_at": r.observed_at,
                "ended_at": r.ended_at, "error": r.error} for r in db.scalars(select(ScheduleExecution).join(ScheduledEvent).where(ScheduledEvent.schedule_id == schedule_id).order_by(ScheduleExecution.planned_start))]
            result["editable"] = not result["executions"] and get_runner().armed_id != schedule_id
            return result

    @router.post("/{schedule_id}/events")
    async def add(schedule_id: str, body: EventInput):
        async with get_runner().lock:
            with sessions() as db:
                require_schedule(db, schedule_id)
                editable(db, schedule_id)
                if not db.get(MediaAsset, body.media_id):
                    raise HTTPException(404, "Unknown media")
                count = len(list(db.scalars(select(ScheduledEvent.id).where(ScheduledEvent.schedule_id == schedule_id))))
                if count >= 1000:
                    raise HTTPException(400, "Maximum 1000 events per schedule")
                row = ScheduledEvent(schedule_id=schedule_id, **body.model_dump())
                db.add(row)
                db.commit()
                return {"id": row.id}

    @router.put("/{schedule_id}/events/{event_id}")
    async def update(schedule_id: str, event_id: str, body: EventInput):
        async with get_runner().lock:
            with sessions() as db:
                editable(db, schedule_id)
                row = db.get(ScheduledEvent, event_id)
                if not row or row.schedule_id != schedule_id:
                    raise HTTPException(404, "Unknown event")
                if not db.get(MediaAsset, body.media_id):
                    raise HTTPException(404, "Unknown media")
                for key, value in body.model_dump().items():
                    setattr(row, key, value)
                db.commit()
                return {"saved": True}

    @router.delete("/{schedule_id}/events/{event_id}")
    async def remove(schedule_id: str, event_id: str):
        async with get_runner().lock:
            with sessions() as db:
                editable(db, schedule_id)
                row = db.get(ScheduledEvent, event_id)
                if not row or row.schedule_id != schedule_id:
                    raise HTTPException(404, "Unknown event")
                db.delete(row)
                db.commit()
                return {"deleted": True}

    @router.post("/{schedule_id}/arm")
    async def arm(schedule_id: str):
        runner = get_runner()
        async with runner.lock:
            with sessions() as db:
                preview = plan(db, schedule_id)
            if not preview["valid"]:
                raise HTTPException(400, preview["errors"])
            try:
                for event in preview["events"]:
                    get_controller().clip({"media": event["media"]})
                runner.arm(schedule_id, preview)
            except (ValueError, RuntimeError, OSError) as exc:
                raise HTTPException(409, str(exc)) from exc
        return runner.status()

    @router.post("/{schedule_id}/disarm")
    async def disarm(schedule_id: str):
        runner = get_runner()
        async with runner.lock:
            if runner.armed_id not in (None, schedule_id):
                raise HTTPException(409, "A different schedule is armed")
            runner.disarm()
        return runner.status()

    @router.get("/{schedule_id}/export")
    def export(schedule_id: str, format: Literal["json", "csv"] = "json"):
        with sessions() as db:
            schedule = require_schedule(db, schedule_id)
            events = [{k: v for k, v in event_dict(r).items() if k != "id"} for r in db.scalars(select(ScheduledEvent).where(ScheduledEvent.schedule_id == schedule_id).order_by(ScheduledEvent.preferred_start, ScheduledEvent.id))]
            if format == "json":
                content = json.dumps({"version": 1, "name": schedule.name, "timezone": schedule.timezone, "events": events}, indent=2)
            else:
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=list(EventInput.model_fields))
                writer.writeheader()
                writer.writerows(e | {"user_fields": json.dumps(e["user_fields"])} for e in events)
                content = output.getvalue()
            return {"filename": f"schedule-{schedule_id}.{format}", "content": content}

    return router
