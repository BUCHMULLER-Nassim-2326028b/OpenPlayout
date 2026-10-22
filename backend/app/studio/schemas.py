from typing import Literal
from pydantic import BaseModel, Field, model_validator


class BoundaryInput(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    in_frame: int = Field(ge=0)
    out_frame: int | None = Field(default=None, ge=1)
    fps_num: int = Field(default=25, ge=1, le=120000)
    fps_den: int = Field(default=1, ge=1, le=10000)
    kind: str = Field(default="custom", max_length=80)
    notes: str = Field(default="", max_length=4000)
    triggers: list[str] = Field(default_factory=list, max_length=20)


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    media_ids: list[str] = Field(default_factory=list, max_length=2000)
    query: dict = Field(default_factory=dict)
    weights: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_weights(self):
        if any(key not in self.media_ids or not 1 <= value <= 1000 for key, value in self.weights.items()):
            raise ValueError("Weights must reference selected media and be between 1 and 1000")
        return self


class RuleConfig(BaseModel):
    collection_id: str
    policy: Literal["sequential", "shuffle", "weighted_random", "least_recently_played", "consecutive"] = "sequential"
    seed: int = 0
    min_items: int = Field(default=1, ge=1, le=10)
    preferred_items: int = Field(default=1, ge=1, le=10)
    max_items: int = Field(default=1, ge=1, le=10)
    allow_new_group: bool = True
    max_groups: int = Field(default=12, ge=1, le=50)
    no_repeat_hours: int = Field(default=0, ge=0, le=8760)
    max_plays_per_day: int | None = Field(default=None, ge=1, le=1000)
    prefer_unwatched: bool = False
    priority_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    seasonal_tags: dict[str, list[int]] = Field(default_factory=dict)
    manual_priority: dict[str, int] = Field(default_factory=dict)
    break_id: str | None = None
    filler_collection_id: str | None = None

    @model_validator(mode="after")
    def groups(self):
        if not self.min_items <= self.preferred_items <= self.max_items:
            raise ValueError("Group sizes must satisfy min <= preferred <= max")
        return self


class BreakStage(BaseModel):
    collection_id: str
    required: bool = True
    min_items: int = Field(default=1, ge=0, le=10)
    max_items: int = Field(default=1, ge=0, le=10)

    @model_validator(mode="after")
    def limits(self):
        if self.min_items > self.max_items or self.required and self.max_items == 0:
            raise ValueError("Invalid break stage item limits")
        return self


class BreakConfig(BaseModel):
    stages: list[BreakStage] = Field(min_length=1, max_length=12)
    target_seconds: str = "120"
    minimum_seconds: str = "0"
    maximum_seconds: str | None = None
    strict: bool = False
    cooldown_seconds: int = Field(default=0, ge=0, le=31536000)
    avoid_duplicates: bool = True
    priority_tags: list[str] = Field(default_factory=list)
    filler_collection_id: str | None = None
    seed: int = 0


class SequenceStep(BaseModel):
    kind: Literal["media", "segment", "sequence", "break", "graphics"]
    reference: str
    enabled: bool = True
    transition: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)
    when: dict = Field(default_factory=dict)


class SequenceConfig(BaseModel):
    items: list[SequenceStep] = Field(default_factory=list, max_length=1000)
    expected_duration_seconds: str | None = None


class GraphicsConfig(BaseModel):
    source: Literal["builtin", "html", "remote", "file"] = "builtin"
    layout: Literal["logo", "lower_third", "now_next", "countdown"] = "logo"
    content: str = Field(default="", max_length=300000)
    url: str = Field(default="", max_length=2048)
    filename: str = Field(default="", max_length=255)
    theme: dict = Field(default_factory=dict)
    offline: Literal["hide", "freeze"] = "hide"


class AutomationConfig(BaseModel):
    hook: Literal["media.indexed", "playlist.generated", "schedule.created", "media.loaded", "media.cued", "media.started", "media.ended", "segment.started", "chapter.reached", "break.requested", "break.started", "break.ended", "program.changed", "graphics.requested", "playback.error", "engine.disconnected"]
    actions: list[dict] = Field(min_length=1, max_length=20)


RESOURCE_TYPES = {"rule": RuleConfig, "break": BreakConfig, "sequence": SequenceConfig, "graphics": GraphicsConfig, "automation": AutomationConfig}


class ResourceInput(BaseModel):
    kind: Literal["rule", "break", "sequence", "graphics", "automation"]
    name: str = Field(min_length=1, max_length=120)
    version: Literal[1] = 1
    payload: dict

    @model_validator(mode="after")
    def validate_document(self):
        self.payload = RESOURCE_TYPES[self.kind].model_validate(self.payload).model_dump()
        return self


class GenerateInput(BaseModel):
    target_seconds: str = "120"
    strict: bool = False
    deadline: str | None = None
    start_at: str | None = None


class RecoveryConfig(BaseModel):
    policy: Literal["manual", "resume_expected"] = "manual"
    emergency_sequence_id: str | None = None
    on_playback_error: Literal["suspend", "emergency"] = "suspend"
