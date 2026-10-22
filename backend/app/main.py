import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import secrets
import shutil

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from .config import ROOT, Settings
from .database import ApplicationSettings, Channel, MediaAsset, MediaLocation, Playlist, PlaylistItem, PlaybackHistory, Segment, make_database
from fractions import Fraction
from .media import asset_dict, index_directory
from .playout.caspar import CasparCGEngine
from .playout.controller import PlayoutController
from .playout.engine import EngineError
from .playout.runtime import CasparCGRuntime
from .schemas import AddItem, ChannelSettings, Control, Reorder, ScanRequest
from .scheduler.api import make_router as schedule_router
from .scheduler.runner import ScheduleRunner
from .studio.library_api import router as library_router
from .studio.api import router as studio_router
from .studio.graphics import GraphicsService, public_router as graphics_router
from .studio.events import EventBus
from .studio.recovery import RecoveryService
from .studio.service import StudioService


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"time": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
            "logger": record.name, "message": record.getMessage(), "error": getattr(record, "error", None),
            "traceback": self.formatException(record.exc_info) if record.exc_info else None})


def create_app(settings: Settings | None = None, engine_factory=None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    database_url = f"sqlite:///{settings.data_dir / 'openplayout.db'}"
    sql_engine, sessions = make_database(database_url)
    scan_lock = asyncio.Lock()
    scan = {"running": False, "report": None, "error": None}
    factory = engine_factory or (lambda cfg: CasparCGEngine(cfg.host, cfg.port, cfg.channel, cfg.layer))

    def read_settings():
        with sessions() as db:
            row = db.get(ApplicationSettings, "channel")
            return ChannelSettings.model_validate(row.value)

    @asynccontextmanager
    async def lifespan(app):
        handler = RotatingFileHandler(settings.data_dir / "openplayout.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(JSONFormatter())
        logger = logging.getLogger("app")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        migration = Config(str(ROOT / "backend" / "alembic.ini"))
        migration.attributes["database_url"] = database_url
        command.upgrade(migration, "head")
        with sessions() as db:
            if not db.get(Channel, "main"):
                db.add(Channel(id="main"))
                db.flush()
                db.add(Playlist(id="main"))
                cfg = ChannelSettings(host=settings.caspar_host, port=settings.caspar_port,
                    media_root=settings.caspar_media_root, ffprobe=settings.ffprobe)
                db.add(ApplicationSettings(key="channel", value=cfg.model_dump()))
            # Unknown end times are retained as unknown, never rewritten as successful playback.
            for record in db.scalars(select(PlaybackHistory).where(PlaybackHistory.ended_at.is_(None), PlaybackHistory.outcome == "playing")):
                record.outcome = "interrupted_by_restart"
            db.commit()
        cfg = read_settings()
        bundled_probe = settings.caspar_server_dir.resolve() / "ffprobe.exe"
        # Upgrade only the untouched initial placeholder configuration, never a
        # configured library or an indexed media path.
        with sessions() as db:
            changed = False
            if settings.caspar_autostart and cfg.media_root.replace("\\", "/") == "C:/CasparCG/media" and not cfg.directories and db.scalar(select(MediaAsset.id).limit(1)) is None:
                cfg.media_root = settings.caspar_media_root
                changed = True
            if cfg.ffprobe == "ffprobe" and not shutil.which(cfg.ffprobe) and bundled_probe.is_file():
                cfg.ffprobe = str(bundled_probe)
                changed = True
            if changed:
                backup = settings.data_dir / "backups"
                backup.mkdir(exist_ok=True)
                (backup / "before-bundled-casparcg.json").write_text(json.dumps(db.get(ApplicationSettings, "channel").value, indent=2), encoding="utf-8")
                db.get(ApplicationSettings, "channel").value = cfg.model_dump()
                db.commit()
        runtime = CasparCGRuntime(settings)
        app.state.runtime = runtime
        app.state.controller = PlayoutController(factory(cfg), sessions, cfg.media_root, Fraction(cfg.fps_num, cfg.fps_den))
        app.state.scheduler = ScheduleRunner(sessions, app.state.controller, settings.scheduler_lateness_seconds)
        app.state.scheduler.recover()
        app.state.controller.events = events
        events.load_plugins(settings.trusted_plugins, ROOT / "plugins")
        events.subscribe("playback.error", studio.emergency_hook)
        try:
            if engine_factory is None:
                await runtime.start(cfg)
                if runtime.state in ("running", "external"):
                    await app.state.controller.action("connect")
                    if recovery.config().policy == "resume_expected" and recovery.preview()["available"] and app.state.controller.observation.state in ("stopped", "ended"):
                        await recovery.resume()
        except BaseException:
            await app.state.controller.engine.disconnect()
            await runtime.stop()
            sql_engine.dispose()
            logger.removeHandler(handler)
            handler.close()
            raise

        async def monitor():
            while True:
                try:
                    await app.state.controller.poll()
                    await app.state.scheduler.tick()
                    events.pulse(app.state.controller)
                    recovery.checkpoint()
                except Exception:
                    logger.exception("playout_monitor_failed")
                    app.state.controller.error = "Internal monitoring error; see diagnostic log"
                    app.state.controller.automation = False
                    app.state.scheduler.error = "Internal scheduler/monitor error; dispatch suspended. See diagnostic log."
                    app.state.scheduler.disarm()
                await asyncio.sleep(0.1)

        task = asyncio.create_task(monitor())
        hook_task = asyncio.create_task(events.worker())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            app.state.scheduler.disarm(interrupt=True)
            hook_task.cancel()
            with suppress(asyncio.CancelledError):
                await hook_task
            await graphics.close()
            # A managed server follows the app lifecycle. External servers are untouched.
            await app.state.controller.engine.disconnect()
            await runtime.stop()
            sql_engine.dispose()
            logger.removeHandler(handler)
            handler.close()

    app = FastAPI(title="OpenPlayout", version="0.1.0", lifespan=lifespan,
        description="Local media library and sequential CasparCG playout. Phase 1; no output accuracy certification.")
    app.state.sessions = sessions
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    bearer = HTTPBearer(auto_error=False)

    def authorize(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            raise HTTPException(403, "Origin is not allowed")
        supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
        if not secrets.compare_digest(supplied.encode("utf-8"), settings.api_token.encode("utf-8")):
            raise HTTPException(401, "A valid local API token is required")

    auth = [Depends(authorize)]
    graphics = GraphicsService(sessions, lambda: app.state.controller, read_settings, settings, factory)
    events = EventBus(sessions, graphics)
    recovery = RecoveryService(sessions, lambda: app.state.controller, settings)
    studio = StudioService(sessions, lambda: app.state.controller, lambda: app.state.scheduler, read_settings, events, recovery)
    app.state.studio = studio
    app.state.events = events
    app.state.graphics = graphics
    app.state.recovery = recovery

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/status", dependencies=auth)
    def status():
        return app.state.controller.status() | {"scan": scan, "runtime": app.state.runtime.status(), "scheduler": app.state.scheduler.status(), "graphics": graphics.active()}

    @app.get("/api/settings", dependencies=auth)
    def get_settings():
        cfg = read_settings()
        return {"channel": cfg.model_dump(), "ffprobe_available": bool(shutil.which(cfg.ffprobe)),
            "settings_apply": "Managed CasparCG applies saved output settings on the next OpenPlayout restart. Configure external servers separately."}

    @app.put("/api/settings", dependencies=auth)
    async def save_settings(cfg: ChannelSettings):
        controller = app.state.controller
        async with controller.lock:
            if controller.observation.connected or controller.enabled:
                raise HTTPException(409, "Disconnect the engine before changing settings")
            if scan["running"]:
                raise HTTPException(409, "Wait for the media scan before changing settings")
            cfg.media_root = str(Path(cfg.media_root).resolve())
            cfg.directories = list(dict.fromkeys(str(Path(p).resolve()) for p in cfg.directories))
            backup = settings.data_dir / "backups"
            backup.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            (backup / f"settings-{stamp}.json").write_text(read_settings().model_dump_json(indent=2), encoding="utf-8")
            with sessions() as db:
                db.get(ApplicationSettings, "channel").value = cfg.model_dump()
                channel = db.get(Channel, "main")
                for key in ("name", "timezone", "width", "height", "fps_num", "fps_den"):
                    setattr(channel, key, getattr(cfg, key))
                db.commit()
            await controller.engine.disconnect()
            await graphics.close()
            controller.engine = factory(cfg)
            controller.media_root = Path(cfg.media_root)
            controller.fps = Fraction(cfg.fps_num, cfg.fps_den)
        return {"saved": True}

    @app.post("/api/media/scan", dependencies=auth)
    async def scan_directory(body: ScanRequest):
        cfg = read_settings()
        root = Path(body.directory).resolve()
        if str(root) not in [str(Path(p).resolve()) for p in cfg.directories]:
            raise HTTPException(400, "Add this directory in settings before scanning")
        if not shutil.which(cfg.ffprobe):
            raise HTTPException(503, "FFprobe is not available; configure an executable path in Settings")
        if scan_lock.locked():
            raise HTTPException(409, "A scan is already running")
        async with scan_lock:
            scan.update(running=True, error=None)
            try:
                report = await asyncio.to_thread(index_directory, root, sessions, cfg.ffprobe)
                events.publish("media.indexed", {"root": str(root), "report": report})
                scan["report"] = report
                return report
            except (OSError, ValueError) as exc:
                scan["error"] = str(exc)
                raise HTTPException(400, str(exc)) from exc
            finally:
                scan["running"] = False

    @app.get("/api/media", dependencies=auth)
    def media(q: str = "", folder: str = "", limit: int = 500):
        with sessions() as db:
            query = select(MediaAsset, MediaLocation).join(MediaLocation, MediaLocation.media_id == MediaAsset.id)
            if q:
                query = query.where(MediaAsset.title.icontains(q, autoescape=True))
            if folder:
                query = query.where(MediaLocation.relative_path.startswith(folder, autoescape=True))
            rows = db.execute(query.order_by(MediaLocation.relative_path).limit(max(1, min(limit, 2000)))).all()
            return [asset_dict(a, loc) for a, loc in rows]

    @app.get("/api/playlists/main", dependencies=auth)
    def playlist():
        return app.state.controller.stored_rundown()

    def require_editable(controller):
        if controller.current_id or controller.automation:
            raise HTTPException(409, "Stop playback before editing the rundown")

    @app.post("/api/playlists/main/items", dependencies=auth)
    async def add_item(body: AddItem):
        controller = app.state.controller
        async with controller.lock:
            require_editable(controller)
            with sessions() as db:
                if not db.get(MediaAsset, body.media_id):
                    raise HTTPException(404, "Unknown media")
                if body.segment_id:
                    segment = db.get(Segment, body.segment_id)
                    if not segment or segment.media_id != body.media_id:
                        raise HTTPException(400, "Segment must belong to the selected media")
                CasparCGEngine.transition_args(body.transition)
                count = len(controller.stored_rundown())
                item = PlaylistItem(media_id=body.media_id, segment_id=body.segment_id, transition=body.transition, position=count)
                db.add(item)
                db.commit()
                return {"id": item.id}

    @app.put("/api/playlists/main/order", dependencies=auth)
    async def reorder(body: Reorder):
        controller = app.state.controller
        async with controller.lock:
            require_editable(controller)
            with sessions() as db:
                rows = list(db.scalars(select(PlaylistItem).where(PlaylistItem.playlist_id == "main")))
                ids = [r.id for r in rows]
                if len(set(body.item_ids)) != len(ids) or set(body.item_ids) != set(ids):
                    raise HTTPException(400, "Supply each existing rundown item exactly once")
                # Two passes avoid transient unique-position collisions.
                for index, row in enumerate(rows):
                    row.position = -index - 1
                db.flush()
                by_id = {r.id: r for r in rows}
                for index, item_id in enumerate(body.item_ids):
                    by_id[item_id].position = index
                db.commit()
        return {"saved": True}

    @app.delete("/api/playlists/main/items/{item_id}", dependencies=auth)
    async def remove(item_id: str):
        controller = app.state.controller
        async with controller.lock:
            require_editable(controller)
            with sessions() as db:
                item = db.get(PlaylistItem, item_id)
                if not item:
                    raise HTTPException(404, "Unknown item")
                db.delete(item)
                db.flush()
                rows = list(db.scalars(select(PlaylistItem).order_by(PlaylistItem.position)))
                for index, row in enumerate(rows):
                    row.position = -index - 1
                db.flush()
                for index, row in enumerate(rows):
                    row.position = index
                db.commit()
        return {"deleted": True}

    @app.post("/api/playout", dependencies=auth)
    async def control(body: Control):
        runner = app.state.scheduler
        async with runner.lock:
            if runner.armed_id and body.action not in ("stop", "disconnect"):
                raise HTTPException(409, "Disarm scheduled automation before manual controls")
            if body.action in ("stop", "disconnect", "play", "cue", "next"):
                runner.disarm(interrupt=True)
            try:
                await app.state.controller.action(body.action, body.item_id, body.frame)
            except EngineError as exc:
                raise HTTPException(409, str(exc)) from exc
        return app.state.controller.status() | {"scheduler": runner.status()}

    @app.get("/api/history", dependencies=auth)
    def history():
        with sessions() as db:
            return [{"id": r.id, "media_id": r.media_id, "item_id": r.item_id,
                "started_at": r.started_at, "ended_at": r.ended_at, "outcome": r.outcome}
                for r in db.scalars(select(PlaybackHistory).order_by(PlaybackHistory.started_at.desc()).limit(200))]

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if ws.headers.get("origin") not in settings.allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            message = await asyncio.wait_for(ws.receive_json(), timeout=5)
            token = message.get("token", "") if isinstance(message, dict) else ""
            if not isinstance(token, str) or not secrets.compare_digest(token.encode("utf-8"), settings.api_token.encode("utf-8")):
                await ws.close(code=1008)
                return
            while True:
                await ws.send_json({"type": "status", "data": app.state.controller.status() | {"scan": scan, "runtime": app.state.runtime.status(), "scheduler": app.state.scheduler.status(), "graphics": graphics.active()}})
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, TimeoutError, RuntimeError, ValueError):
            return

    dist = ROOT / "apps" / "web" / "dist"
    app.include_router(schedule_router(sessions, lambda: app.state.controller, lambda: app.state.scheduler, read_settings), dependencies=auth)
    app.include_router(library_router(sessions, lambda: app.state.controller, lambda: app.state.scheduler, read_settings, settings, Depends(authorize)))
    app.include_router(studio_router(studio, graphics, events, recovery, settings, save_settings), dependencies=auth)
    app.include_router(graphics_router(graphics))

    @app.exception_handler(ValueError)
    async def invalid_domain_request(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        @app.get("/library", include_in_schema=False)
        @app.get("/settings", include_in_schema=False)
        @app.get("/schedule", include_in_schema=False)
        @app.get("/chapters", include_in_schema=False)
        @app.get("/studio", include_in_schema=False)
        def frontend():
            return FileResponse(dist / "index.html")

    return app


# Factory mode keeps tests and command-line tooling from creating databases at import time.
