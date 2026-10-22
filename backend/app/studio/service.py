import asyncio
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from uuid import uuid4

from ..database import Resource, GraphicsInstance
from ..playout.caspar import CasparCGEngine
from .fitting import fit_break, generate, frames
from .library import document
from .sequences import expand


class StudioService:
    def __init__(self, sessions, controller, runner, read_settings, events, recovery):
        self.sessions, self.controller, self.runner, self.read_settings = sessions, controller, runner, read_settings
        self.events, self.recovery = events, recovery

    def preview(self, resource_id, request):
        cfg = self.read_settings()
        fps = Fraction(cfg.fps_num, cfg.fps_den)
        now = datetime.fromisoformat(request.start_at) if request.start_at else datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Start time must include a UTC offset")
        target = request.target_seconds
        if request.deadline:
            deadline = datetime.fromisoformat(request.deadline)
            if deadline.tzinfo is None:
                raise ValueError("Deadline must include a UTC offset")
            delta = deadline - now
            target = str(Fraction(delta.days * 86400 + delta.seconds, 1) + Fraction(delta.microseconds, 1000000))
        with self.sessions() as db:
            resource = document(db, resource_id)
            if resource.kind == "sequence":
                result = expand(db, resource_id, fps, getattr(request, "context", {}))
                if request.deadline and result["duration_frames"] > frames(target, fps):
                    raise ValueError("Template would overrun the hard deadline")
            elif resource.kind == "break":
                result = fit_break(db, resource_id, fps, frames(target, fps), now)
            elif resource.kind == "rule":
                result = generate(db, resource_id, fps, target, request.strict, now, cfg.timezone)
            else:
                raise ValueError("Only sequences, rules and break templates generate playout plans")
            for position, item in enumerate(result["items"]):
                self.controller().clip(item)
                CasparCGEngine.transition_args(item.get("transition"))
                item["id"], item["position"] = f"studio-{resource_id}-{position}-{uuid4()}", position
                for action in item.get("on_start_actions", []) + item.get("on_end_actions", []):
                    if not db.get(GraphicsInstance, action["instance_id"]):
                        raise ValueError("Template references an unknown graphics instance")
            signature_items = [{k: v for k, v in item.items() if k != "id"} for item in result["items"]]
            signature = hashlib.sha256(json.dumps({"items": signature_items, "actions": result.get("actions", [])}, sort_keys=True).encode()).hexdigest()
            return result | {"signature": signature, "source_id": resource_id}

    async def run(self, resource_id, request, emergency=False):
        async with self.runner().lock:
            if self.runner().armed_id and not emergency:
                raise ValueError("Disarm scheduled automation before manual sequence playback")
            result = await asyncio.to_thread(self.preview, resource_id, request)
            if getattr(request, "signature", None) and request.signature != result["signature"]:
                raise ValueError("Source data changed since preview; review a new preview before running")
            if emergency:
                self.runner().disarm(interrupt=True)
            if result["items"]:
                await self.controller().action("play", sequence_items=result["items"])
            elif result.get("actions"):
                self.events.publish("graphics.requested", {"actions": result["actions"]})
            else:
                raise ValueError("The expanded template contains no enabled actions")
            self.events.publish("playlist.generated", {"source_id": resource_id, "items": len(result["items"])})
            return {"started": True, "items": len(result["items"]), "duration_seconds": result["duration_seconds"]}

    async def emergency_hook(self, hook, payload):
        config = self.recovery.config()
        if config.on_playback_error == "emergency" and config.emergency_sequence_id and not self.recovery.emergency_attempted and self.controller().engine.is_connected():
            self.recovery.emergency_attempted = True
            from .api import PreviewInput
            await self.run(config.emergency_sequence_id, PreviewInput(), emergency=True)
