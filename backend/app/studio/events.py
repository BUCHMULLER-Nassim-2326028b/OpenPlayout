import asyncio
from collections import defaultdict
import importlib.util
import inspect
import logging
from pathlib import Path
from fractions import Fraction

from sqlalchemy import select

from ..database import AutomationEvent, Resource, Chapter

log = logging.getLogger(__name__)


class EventBus:
    """Bounded asynchronous hooks. Plugins are trusted code, not sandboxed."""
    def __init__(self, sessions, graphics):
        self.sessions, self.graphics = sessions, graphics
        self.queue = asyncio.Queue(maxsize=512)
        self.listeners = defaultdict(list)
        self.dropped = 0
        self.errors = 0
        self.plugin_status = []
        self.marker_item = None
        self.markers_fired = set()

    def pulse(self, controller):
        item = controller.current_item()
        if not item or controller.observation.state != "playing":
            return
        if item["id"] != self.marker_item:
            self.marker_item, self.markers_fired = item["id"], set()
        position = Fraction(str(controller.observation.position_seconds or 0))
        clip_in = Fraction(str(controller.observation.clip_in_seconds))
        with self.sessions() as db:
            for marker in db.scalars(select(Chapter).where(Chapter.media_id == item["media"]["id"])):
                point = Fraction(marker.in_frame * marker.fps_den, marker.fps_num)
                if clip_in <= point <= position and marker.id not in self.markers_fired:
                    self.markers_fired.add(marker.id)
                    self.publish("chapter.reached", {"item": item, "chapter_id": marker.id, "label": marker.label, "triggers": marker.triggers})

    def subscribe(self, hook, callback):
        if not callable(callback):
            raise ValueError("A hook callback must be callable")
        self.listeners[hook].append(callback)

    def publish(self, hook: str, payload: dict):
        try:
            self.queue.put_nowait((hook, payload))
        except asyncio.QueueFull:
            self.dropped += 1
            log.error("automation_queue_full")

    def load_plugins(self, paths, root: Path):
        for filename in paths:
            path = (root / filename).resolve()
            if not path.is_relative_to(root.resolve()) or path.suffix != ".py":
                self.plugin_status.append({"name": filename, "state": "error", "error": "Plugin must be a Python file inside plugins/"})
                continue
            try:
                spec = importlib.util.spec_from_file_location("openplayout_plugin_" + path.stem, path)
                module = importlib.util.module_from_spec(spec)
                import sys
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                module.register(self)
                self.plugin_status.append({"name": filename, "state": "loaded"})
            except Exception as exc:
                self.plugin_status.append({"name": filename, "state": "error", "error": str(exc)})

    async def action(self, action):
        kind = action.get("type")
        if kind in ("graphics.show", "graphics.hide"):
            await self.graphics.command(action["instance_id"], "show" if kind.endswith("show") else "hide", action.get("parameters"))
        elif kind == "graphics.variables":
            with self.sessions() as db:
                from ..database import GraphicsInstance
                row = db.get(GraphicsInstance, action["instance_id"])
                if not row:
                    raise ValueError("Unknown graphics instance")
                row.parameters = row.parameters | action.get("parameters", {})
                db.commit()
        else:
            raise ValueError("Only documented built-in graphics actions are allowed")

    async def worker(self):
        while True:
            hook, payload = await self.queue.get()
            outcome = "completed"
            try:
                item = payload.get("item") or {}
                actions = item.get("on_start_actions", []) if hook == "media.started" else item.get("on_end_actions", []) if hook == "media.ended" else payload.get("actions", []) if hook == "graphics.requested" else []
                for action in actions:
                    await asyncio.wait_for(self.action(action), 5)
                with self.sessions() as db:
                    rules = [r.payload for r in db.scalars(select(Resource).where(Resource.kind == "automation")) if r.payload["hook"] == hook]
                    if hook == "chapter.reached":
                        rules += [r.payload for key in payload.get("triggers", []) if (r := db.get(Resource, key)) is not None and r.kind == "automation" and r.payload not in rules]
                for rule in rules:
                    for action in rule["actions"]:
                        await asyncio.wait_for(self.action(action), 5)
                for callback in self.listeners[hook] + self.listeners["*"]:
                    if inspect.iscoroutinefunction(callback):
                        await asyncio.wait_for(callback(hook, payload), 2)
                    else:
                        await asyncio.wait_for(asyncio.to_thread(callback, hook, payload), 2)
            except Exception as exc:
                self.errors += 1
                outcome = "error: " + str(exc)
                log.exception("automation_hook_failed")
            finally:
                with self.sessions() as db:
                    db.add(AutomationEvent(hook=hook, payload=payload, outcome=outcome))
                    db.commit()
                self.queue.task_done()
