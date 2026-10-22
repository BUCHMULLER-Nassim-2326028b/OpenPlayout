import asyncio
import json
from pathlib import Path
import secrets
from fractions import Fraction
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..database import Resource, GraphicsInstance, AutomationEvent, ApplicationSettings, Channel, Schedule, ScheduledEvent
from .library import document
from .schemas import ResourceInput, GenerateInput, GraphicsConfig, RecoveryConfig


class PreviewInput(GenerateInput):
    context: dict = Field(default_factory=dict)
    signature: str | None = None


class InstanceInput(BaseModel):
    template_id: str
    layer: int = Field(default=200, ge=1, le=9999)
    parameters: dict = Field(default_factory=dict)


class ConfigImport(BaseModel):
    version: int = 1
    channel: dict
    recovery: dict = Field(default_factory=dict)
    confirm_replace_settings: bool = False


def router(service, graphics, events, recovery, settings, save_settings):
    api = APIRouter(prefix="/api", tags=["Automation studio"])
    sessions = service.sessions

    def resource_dict(row):
        return {"id": row.id, "kind": row.kind, "name": row.name, "version": row.version, "payload": row.payload}

    def validate_refs(db, body):
        if body.kind == "automation":
            for action in body.payload["actions"]:
                if action.get("type") not in ("graphics.show", "graphics.hide", "graphics.variables") or not db.get(GraphicsInstance, action.get("instance_id", "")):
                    raise ValueError("Automation actions require a supported action and existing graphics instance")
        if body.kind == "graphics":
            config = GraphicsConfig.model_validate(body.payload)
            if config.source == "remote":
                from urllib.parse import urlparse
                parsed = urlparse(config.url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("Use a credential-free HTTPS overlay URL")

    @api.get("/resources")
    def resources(kind: str | None = None):
        with sessions() as db:
            query = select(Resource).order_by(Resource.kind, Resource.name)
            if kind:
                query = query.where(Resource.kind == kind)
            return [resource_dict(r) for r in db.scalars(query)]

    @api.post("/resources")
    @api.post("/resources/import")
    def create_resource(body: ResourceInput):
        with sessions() as db:
            try:
                validate_refs(db, body)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            row = Resource(**body.model_dump())
            db.add(row)
            db.commit()
            return resource_dict(row)

    @api.put("/resources/{resource_id}")
    def update_resource(resource_id: str, body: ResourceInput):
        with sessions() as db:
            row = document(db, resource_id)
            if row.kind != body.kind:
                raise HTTPException(400, "Resource type cannot change")
            try:
                validate_refs(db, body)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            row.name, row.payload = body.name, body.payload
            db.commit()
            return resource_dict(row)

    @api.delete("/resources/{resource_id}")
    def remove_resource(resource_id: str):
        with sessions() as db:
            row = document(db, resource_id)
            if db.scalar(select(GraphicsInstance.id).where(GraphicsInstance.template_id == resource_id)) or any(resource_id in json.dumps(other.payload) for other in db.scalars(select(Resource).where(Resource.id != resource_id))):
                raise HTTPException(409, "Other templates/instances reference this resource")
            db.delete(row)
            db.commit()
            return {"deleted": True}

    @api.get("/resources/{resource_id}/export")
    def export_resource(resource_id: str):
        with sessions() as db:
            row = resource_dict(document(db, resource_id))
            row.pop("id")
            return JSONResponse(row, headers={"Content-Disposition": f'attachment; filename="template-{resource_id}.json"'})

    @api.post("/resources/{resource_id}/preview")
    async def preview_resource(resource_id: str, body: PreviewInput):
        try:
            return await asyncio.to_thread(service.preview, resource_id, body)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @api.post("/resources/{resource_id}/run")
    async def run_resource(resource_id: str, body: PreviewInput):
        try:
            return await service.run(resource_id, body)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.get("/graphics")
    def instances():
        return graphics.active()

    @api.post("/resources/{resource_id}/schedule")
    async def schedule_plan(resource_id: str, body: PreviewInput):
        from ..scheduler.planner import build_plan, instant, iso
        if not body.start_at:
            raise HTTPException(400, "Choose an explicit start time before creating a schedule")
        async with service.runner().lock:
            try:
                result = await asyncio.to_thread(service.preview, resource_id, body)
                if body.signature and body.signature != result["signature"]:
                    raise ValueError("Source data changed; generate a fresh preview")
                if not result["items"]:
                    raise ValueError("A timed schedule requires media")
                cfg = service.read_settings()
                fps, offset = Fraction(cfg.fps_num, cfg.fps_den), 0
                events, expanded = [], []
                for index, item in enumerate(result["items"]):
                    if item.get("on_start_actions") or item.get("on_end_actions") or item.get("transition", {}).get("type", "cut") != "cut":
                        raise ValueError("Timed event export supports cut-only media/segments. Run graphics/transitions as a native sequence.")
                    event = {"id": str(index), "media_id": item["media"]["id"], "segment_id": (item.get("segment") or {}).get("id"),
                        "label": (item.get("segment") or {}).get("label") or item["media"]["title"], "kind": "hard", "max_delay_seconds": 0,
                        "preferred_start": iso(instant(body.start_at) + Fraction(offset, 1) / fps, ceiling=True),
                        "user_fields": {"source_template_id": resource_id, "break_id": item.get("break_id")}}
                    duration = str(Fraction(item["duration_frames"], 1) / fps)
                    expanded.append(event | {"media": item["media"] | {"metadata": item["media"]["metadata"] | {"duration": duration}}})
                    events.append(event)
                    offset += item["duration_frames"]
                plan = build_plan(expanded, fps)
                if not plan["valid"]:
                    raise ValueError(str(plan["errors"]))
                with sessions() as db:
                    source = document(db, resource_id)
                    schedule = Schedule(name=source.name + " · generated", timezone=cfg.timezone)
                    db.add(schedule); db.flush()
                    for event in events:
                        event.pop("id")
                        db.add(ScheduledEvent(schedule_id=schedule.id, **event))
                    db.commit()
                    identifier = schedule.id
                events_bus = service.events
                events_bus.publish("schedule.created", {"schedule_id": identifier, "source_id": resource_id})
                return {"id": identifier, "created": len(events), "armed": False}
            except (ValueError, RuntimeError, OSError) as exc:
                raise HTTPException(400, str(exc)) from exc

    @api.post("/graphics")
    def create_instance(body: InstanceInput):
        if body.layer <= service.read_settings().layer:
            raise HTTPException(400, "Place graphics above the program layer")
        with sessions() as db:
            document(db, body.template_id, "graphics")
            if db.scalar(select(GraphicsInstance.id).where(GraphicsInstance.layer == body.layer, GraphicsInstance.state == "active")):
                raise HTTPException(409, "That graphics layer is already active")
            row = GraphicsInstance(**body.model_dump(), access_key=secrets.token_urlsafe(24))
            db.add(row)
            db.commit()
            return {"id": row.id}

    class GraphicAction(BaseModel):
        action: str = "show"
        parameters: dict = Field(default_factory=dict)

    @api.post("/graphics/{instance_id}")
    async def graphic_action(instance_id: str, body: GraphicAction):
        if body.action not in ("show", "hide", "variables"):
            raise HTTPException(400, "Choose show, hide or variables")
        try:
            if body.action == "variables":
                await events.action({"type": "graphics.variables", "instance_id": instance_id, "parameters": body.parameters})
            else:
                await graphics.command(instance_id, body.action, body.parameters)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"accepted": True}

    @api.get("/graphics/{instance_id}/preview")
    def graphic_preview(instance_id: str):
        with sessions() as db:
            row = db.get(GraphicsInstance, instance_id)
            if not row:
                raise HTTPException(404, "Unknown instance")
            return {"url": f"/graphics/render/{row.id}?key={row.access_key}"}

    @api.get("/automation/events")
    def event_log():
        with sessions() as db:
            return [{"id": row.id, "hook": row.hook, "created_at": row.created_at, "outcome": row.outcome} for row in db.scalars(select(AutomationEvent).order_by(AutomationEvent.created_at.desc()).limit(200))]

    @api.get("/diagnostics")
    def diagnostics():
        return {"automation": {"queued": events.queue.qsize(), "dropped": events.dropped, "errors": events.errors}, "plugins": events.plugin_status,
            "engine": service.controller().status(), "scheduler": service.runner().status(), "recovery": recovery.config().model_dump()}

    @api.get("/recovery")
    def get_recovery():
        return {"config": recovery.config().model_dump(), "preview": recovery.preview()}

    @api.put("/recovery")
    def set_recovery(body: RecoveryConfig):
        with sessions() as db:
            if body.emergency_sequence_id:
                document(db, body.emergency_sequence_id, "sequence")
            row = db.get(ApplicationSettings, "recovery")
            if row is None:
                row = ApplicationSettings(key="recovery")
                db.add(row)
            row.value = body.model_dump()
            db.commit()
        return {"saved": True}

    @api.post("/recovery/resume")
    async def recover_position():
        async with service.runner().lock:
            if service.runner().armed_id or service.controller().observation.state not in ("stopped", "ended"):
                raise HTTPException(409, "Stop/disarm current output before recovery")
            try:
                return await recovery.resume()
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(409, str(exc)) from exc

    @api.post("/recovery/emergency")
    async def emergency():
        config = recovery.config()
        if not config.emergency_sequence_id:
            raise HTTPException(400, "Configure an emergency sequence first")
        return await service.run(config.emergency_sequence_id, PreviewInput(), emergency=True)

    @api.post("/backups")
    async def backup():
        return await asyncio.to_thread(recovery.backup)

    @api.get("/backups/{backup_id}")
    def download_backup(backup_id: str):
        try:
            UUID(backup_id)
        except ValueError:
            raise HTTPException(404, "Unknown backup")
        path = settings.data_dir / "backups" / f"{backup_id}.zip"
        if not path.is_file():
            raise HTTPException(404, "Unknown backup")
        return FileResponse(path, filename=path.name)

    @api.get("/configuration/export")
    def export_configuration():
        return {"version": 1, "channel": service.read_settings().model_dump(), "recovery": recovery.config().model_dump()}

    @api.post("/configuration/import")
    async def import_configuration(body: ConfigImport):
        if body.version != 1 or not body.confirm_replace_settings:
            raise HTTPException(400, "Version 1 and explicit confirm_replace_settings are required")
        from ..schemas import ChannelSettings
        recovery_config = RecoveryConfig.model_validate(body.recovery)
        cfg = ChannelSettings.model_validate(body.channel)
        with sessions() as db:
            if recovery_config.emergency_sequence_id:
                document(db, recovery_config.emergency_sequence_id, "sequence")
        await save_settings(cfg)
        set_recovery(recovery_config)
        return {"saved": True, "restart_required": True}

    @api.get("/channels")
    def channels():
        with sessions() as db:
            return [{"id": row.id, "name": row.name, "timezone": row.timezone, "active": row.id == "main"} for row in db.scalars(select(Channel))]

    return api
