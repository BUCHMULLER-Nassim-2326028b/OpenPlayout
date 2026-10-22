import asyncio
from datetime import datetime, timezone
from fractions import Fraction

from sqlalchemy import select

from ..database import ScheduleExecution, ScheduledEvent, utcnow
from ..playout.engine import EngineError
from .planner import instant, iso


class ScheduleRunner:
    """Explicitly armed, non-frame-accurate dispatcher with persistent no-replay ledger."""
    def __init__(self, sessions, controller, tolerance: float = 0.5):
        self.sessions, self.controller, self.tolerance = sessions, controller, tolerance
        self.lock = asyncio.Lock()
        self.armed_id: str | None = None
        self.active_id: str | None = None
        self.error: str | None = None
        self.anchor = instant(datetime.now(timezone.utc))
        self.monotonic_anchor = 0.0

    def recover(self):
        with self.sessions() as db:
            for row in db.scalars(select(ScheduleExecution).where(ScheduleExecution.status.in_(["pending", "dispatching", "running"]))):
                row.status = "interrupted"
                row.error = "Application restarted; re-arm future events explicitly. No media was replayed."
            db.commit()

    def status(self) -> dict:
        with self.sessions() as db:
            pending = list(db.scalars(select(ScheduleExecution).where(ScheduleExecution.status == "pending").order_by(ScheduleExecution.planned_start).limit(1)))
            return {"armed_schedule_id": self.armed_id, "active_execution_id": self.active_id,
                "next": pending[0].snapshot if pending else None, "error": self.error,
                "lateness_tolerance_seconds": self.tolerance, "timing": "software dispatch"}

    def arm(self, schedule_id: str, plan: dict):
        if not plan["valid"] or not plan["events"]:
            raise ValueError("A nonempty, conflict-free dry run is required")
        if self.armed_id or self.active_id:
            raise ValueError("Disarm the current schedule and let its active event finish first")
        if not self.controller.observation.connected:
            raise ValueError("Connect the playback engine before arming")
        if self.controller.observation.state not in ("stopped", "ended"):
            raise ValueError("Stop manual playback before arming a schedule")
        now = instant(datetime.now(timezone.utc))
        future = [event for event in plan["events"] if Fraction(event["start_rational"]) > now + 1]
        if not future:
            raise ValueError("Schedule at least one event more than one second in the future")
        with self.sessions() as db:
            for event in future:
                row = db.scalar(select(ScheduleExecution).where(ScheduleExecution.event_id == event["id"]))
                if row and row.status not in ("cancelled", "interrupted"):
                    raise ValueError("An event already has an execution record and cannot be replayed")
                if row and row.command_at:
                    raise ValueError("An already dispatched event cannot be replayed")
                if row is None:
                    row = ScheduleExecution(event_id=event["id"])
                    db.add(row)
                row.planned_start, row.planned_end, row.snapshot = event["planned_start"], event["planned_end"], event
                row.status, row.error = "pending", None
            db.commit()
        self.anchor, self.monotonic_anchor = now, asyncio.get_running_loop().time()
        self.armed_id = schedule_id
        excluded = len(plan["events"]) - len(future)
        self.error = f"{excluded} past or imminent events were excluded; no replay was requested." if excluded else None

    def disarm(self, interrupt: bool = False):
        with self.sessions() as db:
            for row in db.scalars(select(ScheduleExecution).where(ScheduleExecution.status == "pending")):
                row.status = "cancelled"
            if interrupt and self.active_id:
                row = db.get(ScheduleExecution, self.active_id)
                row.status, row.ended_at = "interrupted", utcnow()
                self.active_id = None
            db.commit()
        self.armed_id = None

    async def tick(self, now: datetime | None = None):
        async with self.lock:
            if not self.armed_id and not self.active_id:
                return
            if now is None:
                elapsed = Fraction(round((asyncio.get_running_loop().time() - self.monotonic_anchor) * 1_000_000), 1_000_000)
                current = self.anchor + elapsed
                if self.armed_id and abs(instant(datetime.now(timezone.utc)) - current) > 1:
                    self.error = "System clock changed; future dispatch suspended. Disarm and re-arm after checking times."
                    self.disarm()
                    return
            else:
                current = instant(now)
            with self.sessions() as db:
                if self.active_id:
                    running = db.get(ScheduleExecution, self.active_id)
                    observed = self.controller.observation
                    if self.controller.current_id != running.event_id:
                        running.status, running.ended_at = "interrupted", iso(current)
                        self.active_id = None
                    elif observed.state == "ended" and running.observed_at is not None:
                        running.status, running.ended_at = "completed", iso(current)
                        self.active_id = None
                    elif observed.state in ("disconnected", "error") or self.controller.error:
                        running.status, running.error = "error", self.controller.error or "Playback observation lost"
                        self.active_id = None
                        self.error = running.error
                    elif observed.state == "playing" and observed.clip and self.controller.matches(observed.clip, self.controller.current_clip) and running.observed_at is None:
                        running.observed_at = iso(current)
                    db.commit()
                if not self.armed_id:
                    return
                due = list(db.scalars(select(ScheduleExecution).join(ScheduledEvent).where(
                    ScheduledEvent.schedule_id == self.armed_id, ScheduleExecution.status == "pending").order_by(ScheduleExecution.planned_start)))
                for row in due:
                    target = Fraction(row.snapshot["start_rational"])
                    if current < target:
                        break
                    observed = self.controller.observation
                    occupied = self.active_id or observed.state not in ("stopped", "ended")
                    if current - target > Fraction(str(self.tolerance)):
                        row.status = "blocked" if occupied else "missed"
                        row.error = "Output remained occupied; current content was not cut." if occupied else "Dispatch deadline missed; event was not replayed late"
                        self.error = row.error
                        continue
                    if occupied:
                        # Allow the current clip to finish inside the explicitly
                        # configured dispatch tolerance; never cut it at the deadline.
                        break
                    row.status, row.command_at = "dispatching", iso(current)
                    db.commit()  # Commit before sending any mutating engine command.
                    try:
                        event = row.snapshot
                        item = {"id": event["id"], "position": 0, "media": event["media"], "segment": event.get("segment"), "break_id": event.get("user_fields", {}).get("break_id")}
                        await self.controller.action("play", scheduled_item=item)
                        row.status = "running"
                        self.active_id = row.id
                    except (EngineError, OSError) as exc:
                        row.status, row.error = "error", str(exc)
                        self.error = row.error
                    db.commit()
                    break
                db.commit()
                if not db.scalar(select(ScheduleExecution.id).join(ScheduledEvent).where(ScheduledEvent.schedule_id == self.armed_id, ScheduleExecution.status == "pending").limit(1)):
                    self.armed_id = None
