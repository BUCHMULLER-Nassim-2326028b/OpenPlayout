from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def identifier() -> str:
    return str(uuid4())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="main")
    name: Mapped[str] = mapped_column(default="Main channel")
    timezone: Mapped[str] = mapped_column(default="Europe/Paris")
    fps_num: Mapped[int] = mapped_column(default=25)
    fps_den: Mapped[int] = mapped_column(default=1)
    width: Mapped[int] = mapped_column(default=1920)
    height: Mapped[int] = mapped_column(default=1080)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    title: Mapped[str]
    kind: Mapped[str] = mapped_column(default="video")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)


class MediaLocation(Base):
    __tablename__ = "media_locations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True)
    path: Mapped[str] = mapped_column(unique=True)
    root: Mapped[str]
    relative_path: Mapped[str]
    size: Mapped[int]
    mtime_ns: Mapped[int]
    missing: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None]


class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="main")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), default="main")
    name: Mapped[str] = mapped_column(default="Main rundown")
    cursor_id: Mapped[str | None]


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), default="main")
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    position: Mapped[int] = mapped_column(Integer)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id"))
    transition: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("playlist_id", "position"),)


class PlaybackHistory(Base):
    __tablename__ = "playback_history"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), default="main")
    item_id: Mapped[str | None]
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    started_at: Mapped[str] = mapped_column(default=utcnow)
    ended_at: Mapped[str | None]
    outcome: Mapped[str] = mapped_column(default="playing")


class ApplicationSettings(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), default="main")
    name: Mapped[str]
    timezone: Mapped[str]


class ScheduledEvent(Base):
    __tablename__ = "scheduled_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id"))
    label: Mapped[str] = mapped_column(default="")
    kind: Mapped[str] = mapped_column(default="hard")
    preferred_start: Mapped[str]
    max_delay_seconds: Mapped[int] = mapped_column(default=0)
    user_fields: Mapped[dict] = mapped_column(JSON, default=dict)


class ScheduleExecution(Base):
    __tablename__ = "schedule_executions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    event_id: Mapped[str] = mapped_column(ForeignKey("scheduled_events.id"), unique=True)
    planned_start: Mapped[str]
    planned_end: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    command_at: Mapped[str | None]
    observed_at: Mapped[str | None]
    ended_at: Mapped[str | None]
    error: Mapped[str | None]
    snapshot: Mapped[dict] = mapped_column(JSON)


class Chapter(Base):
    __tablename__ = "chapters"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    label: Mapped[str]
    in_frame: Mapped[int]
    out_frame: Mapped[int | None]
    fps_num: Mapped[int]
    fps_den: Mapped[int]
    kind: Mapped[str] = mapped_column(default="custom")
    notes: Mapped[str] = mapped_column(default="")
    triggers: Mapped[list] = mapped_column(JSON, default=list)


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    label: Mapped[str]
    in_frame: Mapped[int]
    out_frame: Mapped[int]
    fps_num: Mapped[int]
    fps_den: Mapped[int]


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    name: Mapped[str]
    query: Mapped[dict] = mapped_column(JSON, default=dict)


class CollectionItem(Base):
    __tablename__ = "collection_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    position: Mapped[int]
    weight: Mapped[int] = mapped_column(default=1)
    __table_args__ = (UniqueConstraint("collection_id", "media_id"),)


class Resource(Base):
    """Versioned, validated template documents; behavior lives in domain services."""
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    kind: Mapped[str]
    name: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)
    payload: Mapped[dict] = mapped_column(JSON)


class GraphicsInstance(Base):
    __tablename__ = "graphics_instances"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    template_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), default="main")
    layer: Mapped[int]
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    access_key: Mapped[str]
    state: Mapped[str] = mapped_column(default="inactive")
    error: Mapped[str | None]


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    hook: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(default="published")


class PlayoutSession(Base):
    __tablename__ = "playout_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=identifier)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), default="main")
    updated_at: Mapped[str] = mapped_column(default=utcnow)
    state: Mapped[str]
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


def make_database(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine, sessionmaker(engine, expire_on_commit=False)
