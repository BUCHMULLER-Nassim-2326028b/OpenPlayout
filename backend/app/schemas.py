from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from .config import ROOT


class ChannelSettings(BaseModel):
    name: str = Field(default="Main channel", min_length=1, max_length=120)
    timezone: str = "Europe/Paris"
    width: int = Field(default=1920, ge=16, le=8192)
    height: int = Field(default=1080, ge=16, le=8192)
    fps_num: int = Field(default=25, ge=1, le=120000)
    fps_den: int = Field(default=1, ge=1, le=10000)
    host: str = Field(default="127.0.0.1", min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9.:_-]+$")
    port: int = Field(default=5250, ge=1, le=65535)
    channel: int = Field(default=1, ge=1, le=64)
    layer: int = Field(default=10, ge=0, le=9999)
    media_root: str = Field(default=str(ROOT / "media"), min_length=1)
    ffprobe: str = Field(default="ffprobe", min_length=1)
    directories: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone") from exc
        return value


class ScanRequest(BaseModel):
    directory: str = Field(min_length=1)


class AddItem(BaseModel):
    media_id: str
    segment_id: str | None = None
    transition: dict = Field(default_factory=dict)


class Reorder(BaseModel):
    item_ids: list[str]


class Control(BaseModel):
    action: Literal["connect", "disconnect", "play", "cue", "next", "pause", "resume", "stop", "seek"]
    item_id: str | None = None
    frame: int | None = Field(default=None, ge=0)
