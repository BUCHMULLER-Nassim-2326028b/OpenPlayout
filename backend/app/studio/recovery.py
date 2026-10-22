from datetime import datetime, timezone
from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import zipfile
from uuid import uuid4

from sqlalchemy import select

from ..database import PlayoutSession, ApplicationSettings, utcnow
from ..segments import output_bounds
from .schemas import RecoveryConfig


class RecoveryService:
    def __init__(self, sessions, controller, settings):
        self.sessions, self.controller, self.settings = sessions, controller, settings
        self.last_checkpoint = 0
        self.emergency_attempted = False

    def config(self):
        with self.sessions() as db:
            row = db.get(ApplicationSettings, "recovery")
            return RecoveryConfig.model_validate(row.value if row else {})

    def checkpoint(self):
        import time
        now = time.monotonic()
        if now - self.last_checkpoint < 1:
            return
        controller = self.controller()
        if not controller.observation.connected or not controller.session_touched:
            return
        self.last_checkpoint = now
        with self.sessions() as db:
            row = db.get(PlayoutSession, "main")
            if row is None:
                row = PlayoutSession(id="main")
                db.add(row)
            row.updated_at = utcnow()
            row.state = controller.observation.state
            row.snapshot = {"item": controller.current_item(), "queue": controller.rundown() if controller.queue_override is not None else None,
                "observation": controller.observation.to_dict()}
            db.commit()

    def preview(self):
        with self.sessions() as db:
            row = db.get(PlayoutSession, "main")
            if not row or row.state not in ("playing", "paused") or not row.snapshot.get("item"):
                return {"available": False, "reason": "No unfinished observed playback checkpoint"}
            snapshot = row.snapshot
            item = json.loads(json.dumps(snapshot["item"]))
            observed = snapshot["observation"]
            elapsed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row.updated_at)).total_seconds()) if row.state == "playing" else 0
            source_position = Fraction(str(observed.get("position_seconds") or 0)) + Fraction(str(elapsed))
            fps = self.controller().fps
            source_end = Fraction(str(observed.get("clip_in_seconds") or 0)) + Fraction(str(observed.get("clip_duration_seconds") or observed.get("duration_seconds") or 0))
            if source_position >= source_end:
                return {"available": False, "reason": "Expected source position has already passed OUT; completed footage will not be replayed"}
            first = int(source_position * fps)
            end = int(source_end * fps)
            item["segment"] = {"id": "recovery", "media_id": item["media"]["id"], "label": "Recovered remainder", "in_frame": first, "out_frame": end, "fps_num": fps.numerator, "fps_den": fps.denominator}
            item["id"] = "recovery-" + str(uuid4())
            item["recovery"] = True
            queue = snapshot.get("queue") or []
            index = next((i for i, old in enumerate(queue) if old["id"] == snapshot["item"]["id"]), len(queue))
            remaining = [item] + queue[index + 1:]
            return {"available": True, "item": item, "queue": remaining, "paused": row.state == "paused", "source_frame": first, "remaining_frames": end - first, "policy": "elapsed wall time from last observed checkpoint"}

    async def resume(self):
        preview = self.preview()
        if not preview["available"]:
            raise ValueError(preview["reason"])
        for item in preview["queue"]:
            self.controller().clip(item)
        await self.controller().action("cue" if preview["paused"] else "play", sequence_items=preview["queue"])
        return preview

    def backup(self):
        root = self.settings.data_dir / "backups"
        root.mkdir(exist_ok=True)
        identifier = str(uuid4())
        database_path = root / f"{identifier}.sqlite"
        with closing(sqlite3.connect(str(self.settings.data_dir / "openplayout.db"))) as source, closing(sqlite3.connect(str(database_path))) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Database backup integrity check failed")
        target = root / f"{identifier}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_path, "openplayout.db")
            archive.writestr("manifest.json", json.dumps({"version": 1, "created_at": utcnow(), "contains_media": False, "restore": "Stop OpenPlayout and use scripts/restore-backup.ps1"}))
        database_path.unlink()  # Own generated staging database only.
        return {"id": identifier, "filename": target.name}
