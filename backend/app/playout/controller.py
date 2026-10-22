import asyncio
import logging
from pathlib import Path
from fractions import Fraction

from sqlalchemy import select

from ..database import MediaAsset, MediaLocation, Playlist, PlaylistItem, PlaybackHistory, Segment, utcnow
from ..media import asset_dict
from ..segments import segment_dict, output_bounds
from .engine import EngineError, Observation, PlayoutEngine

log = logging.getLogger(__name__)


class PlayoutController:
    def __init__(self, engine: PlayoutEngine, sessions, media_root: str, fps: Fraction = Fraction(25)):
        self.engine, self.sessions, self.media_root = engine, sessions, Path(media_root).resolve()
        self.lock = asyncio.Lock()
        self.observation = Observation()
        self.current_id: str | None = None
        self.queued_id: str | None = None
        self.current_clip: str | None = None
        self.queued_clip: str | None = None
        self.error: str | None = None
        self.enabled = False
        self.automation = False
        self.backoff = 1
        self.retry_at = 0.0
        self.settle_until = 0.0
        self.scheduled_item: dict | None = None
        self.playback_confirmed = False
        self.fps = fps
        self.queue_override: list[dict] | None = None
        self.events = None
        self.session_touched = False
        self.active_break_id = None

    def publish(self, hook: str, item: dict | None = None):
        if self.events:
            self.events.publish(hook, {"item": item or self.current_item(), "observation": self.observation.to_dict()})

    def current_item(self):
        return self.scheduled_item or next((r for r in self.rundown() if r["id"] == self.current_id), None)

    def confirm(self):
        if not self.playback_confirmed:
            self.publish("media.started")
            self.publish("program.changed")
            if (self.current_item() or {}).get("segment"):
                self.publish("segment.started")
            break_id = (self.current_item() or {}).get("break_id")
            if self.active_break_id and self.active_break_id != break_id:
                self.publish("break.ended", {"break_id": self.active_break_id})
            if break_id and break_id != self.active_break_id:
                self.publish("break.started")
            self.active_break_id = break_id
        self.playback_confirmed = True

    def rundown(self) -> list[dict]:
        return self.queue_override if self.queue_override is not None else self.stored_rundown()

    def stored_rundown(self) -> list[dict]:
        with self.sessions() as db:
            rows = db.execute(select(PlaylistItem, MediaAsset, MediaLocation)
                .join(MediaAsset, PlaylistItem.media_id == MediaAsset.id)
                .join(MediaLocation, MediaLocation.media_id == MediaAsset.id)
                .where(PlaylistItem.playlist_id == "main").order_by(PlaylistItem.position)).all()
            result = []
            for item, asset, location in rows:
                segment = db.get(Segment, item.segment_id) if item.segment_id else None
                result.append({"id": item.id, "position": item.position, "media": asset_dict(asset, location), "segment": segment_dict(segment) if segment else None, "transition": item.transition})
            return result

    def item_matches(self, item: dict | None, clip: str | None) -> bool:
        if not item or not self.matches(self.observation.clip, clip):
            return False
        segment = item.get("segment")
        if segment:
            rate = Fraction(segment["fps_num"], segment["fps_den"])
            return abs(self.observation.clip_in_seconds - float(Fraction(segment["in_frame"], 1) / rate)) < 0.0001 and self.observation.clip_duration_seconds is not None and abs(self.observation.clip_duration_seconds - float(Fraction(segment["out_frame"] - segment["in_frame"], 1) / rate)) < 0.0001
        return abs(self.observation.clip_in_seconds) < 0.0001 and (self.observation.clip_duration_seconds is None or self.observation.duration_seconds is None or abs(self.observation.clip_duration_seconds - self.observation.duration_seconds) < 0.0001)

    def clip(self, item: dict) -> str:
        media = item["media"]
        path = Path(media["path"]).resolve()
        if media["missing"] or not path.is_file():
            raise EngineError(f"Media file is missing: {path}")
        stat = path.stat()
        if "mtime_ns" in media and (stat.st_mtime_ns != media["mtime_ns"] or stat.st_size != media["size"]):
            raise EngineError("Media changed since indexing; re-scan before playing")
        if media["error"] or not media["duration_seconds"] or media["kind"] != "video":
            raise EngineError("Automatic playback requires a probed, finite video file without indexing errors")
        try:
            return path.relative_to(self.media_root).as_posix()
        except ValueError as exc:
            raise EngineError("Media is outside the configured CasparCG media root") from exc

    def following(self, item_id: str | None) -> dict | None:
        if self.scheduled_item and item_id == self.scheduled_item["id"]:
            return None
        rows = self.rundown()
        for index, item in enumerate(rows):
            if item["id"] == item_id:
                return rows[index + 1] if index + 1 < len(rows) else None
        return None

    def history_end(self, outcome: str):
        with self.sessions() as db:
            for record in db.scalars(select(PlaybackHistory).where(PlaybackHistory.ended_at.is_(None), PlaybackHistory.outcome == "playing")):
                record.ended_at, record.outcome = utcnow(), outcome
            db.commit()

    def mark_current(self, item: dict, started: bool):
        self.current_id, self.current_clip = item["id"], self.clip(item)
        self.playback_confirmed = False
        with self.sessions() as db:
            if not self.scheduled_item and self.queue_override is None:
                db.get(Playlist, "main").cursor_id = item["id"]
            if started:
                db.add(PlaybackHistory(item_id=item["id"], media_id=item["media"]["id"]))
            db.commit()

    async def queue_following(self):
        upcoming = self.following(self.current_id)
        if upcoming:
            clip = self.clip(upcoming)
            # Identical consecutive clips cannot be disambiguated reliably through INFO polling.
            current = self.current_item() or {}
            if self.engine.matches_media(clip, self.current_clip, str(self.media_root)) and upcoming.get("segment") == current.get("segment"):
                raise EngineError("Consecutive identical media is not supported by Phase 1 observation")
            if upcoming["media"]["duration_seconds"] < 2:
                raise EngineError("Queued clips must be at least 2 seconds for reliable polling")
            if upcoming.get("segment"):
                try:
                    first, last = output_bounds(upcoming["segment"], self.fps)
                except ValueError as exc:
                    raise EngineError(str(exc)) from exc
                await self.engine.preload_segment(clip, first, last, transition=upcoming.get("transition"))
            elif upcoming.get("transition", {}).get("type", "cut") != "cut":
                await self.engine.preload_transition(clip, upcoming["transition"])
            else:
                await self.engine.preload(clip, auto=True)
            self.queued_id, self.queued_clip = upcoming["id"], clip
        else:
            self.queued_id = self.queued_clip = None

    def matches(self, observed: str | None, clip: str | None) -> bool:
        return self.engine.matches_media(observed, clip, str(self.media_root))

    async def poll(self):
        async with self.lock:
            if not self.enabled:
                return
            try:
                loop = asyncio.get_running_loop()
                if not self.observation.connected:
                    if loop.time() < self.retry_at:
                        return
                    await self.engine.connect()
                observed = await self.engine.observe()
                self.observation = observed
                self.backoff = 1
                # INFO can still contain the previous render cycle after a successful
                # PLAY/LOAD. Keep displaying that real observation while it settles.
                queued = next((r for r in self.rundown() if r["id"] == self.queued_id), None)
                if self.automation and not self.item_matches(self.current_item(), self.current_clip) and not self.item_matches(queued, self.queued_clip) and loop.time() < self.settle_until:
                    return
                if self.automation and self.queued_id and self.item_matches(queued, self.queued_clip):
                    item = next((r for r in self.rundown() if r["id"] == self.queued_id), None)
                    if item is None:
                        raise EngineError("Queued item disappeared")
                    self.history_end("completed")
                    self.publish("media.ended")
                    self.mark_current(item, True)
                    self.queued_id = self.queued_clip = None
                    await self.queue_following()
                elif self.automation and self.current_id and not self.item_matches(self.current_item(), self.current_clip):
                    raise EngineError("Unexpected foreground producer; automation suspended")
                if self.item_matches(self.current_item(), self.current_clip) and observed.state == "playing":
                    self.confirm()
                if self.automation and observed.state == "ended" and not self.playback_confirmed:
                    if loop.time() < self.settle_until:
                        return
                    raise EngineError("The selected media never entered an observed playing state")
                if self.automation and observed.state == "ended":
                    if self.queued_id:
                        raise EngineError("Queued transition did not occur; automation suspended")
                    self.history_end("completed")
                    self.publish("media.ended")
                    self.automation = False
                    if self.active_break_id:
                        self.publish("break.ended")
                        self.active_break_id = None
                # Clear a transient connection error only when observation succeeds.
                if self.error and self.error.startswith("Connection lost:"):
                    self.error = None
            except EngineError as exc:
                connected = self.engine.is_connected()
                self.error = ("Connection lost: " if not connected else "") + str(exc)
                self.observation = Observation(connected, "error" if connected else "disconnected")
                # Never replay or skip on failure. Server may finish its already queued item.
                self.automation = False
                self.history_end("observation_lost")
                if not connected:
                    self.publish("engine.disconnected")
                    self.retry_at = asyncio.get_running_loop().time() + self.backoff
                    self.backoff = min(self.backoff * 2, 30)
                log.warning("playout_observation_failed", extra={"error": self.error})
                self.publish("playback.error")

    async def action(self, action: str, item_id: str | None = None, frame: int | None = None, *, scheduled_item: dict | None = None, sequence_items: list[dict] | None = None):
        async with self.lock:
            try:
                if action == "connect":
                    self.enabled = True
                    await self.engine.connect()
                elif action == "disconnect":
                    self.enabled = False
                    self.automation = False
                    await self.engine.disconnect()
                    self.observation = Observation()
                    self.history_end("disconnected")
                    return
                elif action in ("play", "cue", "next"):
                    self.session_touched = True
                    if not self.observation.connected:
                        raise EngineError("Connect to CasparCG before playback")
                    if action != "next":
                        self.queue_override = sequence_items
                    if scheduled_item:
                        item = scheduled_item
                    elif action == "next":
                        item = self.following(self.current_id)
                    else:
                        rows = self.rundown()
                        item = next((r for r in rows if r["id"] == item_id), None) if item_id else (rows[0] if rows else None)
                    if item is None:
                        raise EngineError("No playable rundown item selected")
                    clip = self.clip(item)
                    bounds = output_bounds(item["segment"], self.fps) if item.get("segment") else None
                    if item["media"]["duration_seconds"] < 2:
                        raise EngineError("Phase 1 rundown clips must be at least 2 seconds")
                    # Remove old AUTO producers before replacing the foreground.
                    await self.engine.stop()
                    self.history_end("skipped" if action == "next" else "replaced")
                    self.queued_id = self.queued_clip = None
                    self.scheduled_item = scheduled_item
                    if item.get("segment"):
                        try:
                            first, last = bounds
                        except ValueError as exc:
                            raise EngineError(str(exc)) from exc
                        if action == "cue":
                            await self.engine.load_segment(clip, first, last)
                        else:
                            await self.engine.play_segment(clip, first, last)
                    elif action == "cue":
                        await self.engine.cue(clip)
                    else:
                        await self.engine.play(clip)
                    self.mark_current(item, action != "cue")
                    self.publish("media.cued" if action == "cue" else "media.loaded", item)
                    self.settle_until = asyncio.get_running_loop().time() + 2
                    self.automation = action != "cue"
                    if self.automation:
                        await self.queue_following()
                elif action == "pause":
                    await self.engine.pause()
                elif action == "resume":
                    if not self.current_id or not self.matches(self.observation.clip, self.current_clip):
                        raise EngineError("Cue or select a known rundown item before resuming")
                    await self.engine.resume()
                    if not self.automation:
                        item = self.scheduled_item or next(r for r in self.rundown() if r["id"] == self.current_id)
                        self.mark_current(item, True)
                        self.automation = True
                        await self.queue_following()
                elif action == "stop":
                    self.session_touched = True
                    await self.engine.stop()
                    if self.active_break_id:
                        self.publish("break.ended")
                        self.active_break_id = None
                    self.automation = False
                    self.current_id = self.current_clip = self.queued_id = self.queued_clip = None
                    self.scheduled_item = None
                    self.queue_override = None
                    self.history_end("stopped")
                elif action == "seek":
                    if frame is None or frame < 0:
                        raise EngineError("A nonnegative frame is required")
                    segment = (self.current_item() or {}).get("segment")
                    if segment:
                        first, last = output_bounds(segment, self.fps)
                        if not first <= frame < last:
                            raise EngineError("Seek must stay inside the active segment IN/OUT")
                    await self.engine.seek(frame)
                else:
                    raise EngineError("Unsupported playout action")
                self.observation = await self.engine.observe()
                if self.item_matches(self.current_item(), self.current_clip) and self.observation.state == "playing":
                    self.confirm()
                self.error = None
            except EngineError as exc:
                self.error = str(exc)
                self.automation = False
                self.publish("playback.error")
                raise

    def status(self) -> dict:
        rows = self.rundown()
        current = self.scheduled_item or next((r for r in rows if r["id"] == self.current_id), None)
        return {"engine": "CasparCG", "observation": self.observation.to_dict(),
            "current": current, "next": self.following(self.current_id),
            "automation": self.automation, "error": self.error,
            "connection_requested": self.enabled,
            "recovery_policy": "manual", "monitor_available": False}
