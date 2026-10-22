from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict


class EngineError(RuntimeError):
    pass


@dataclass
class Observation:
    connected: bool = False
    state: str = "disconnected"
    clip: str | None = None
    position_seconds: float | None = None
    duration_seconds: float | None = None
    clip_in_seconds: float = 0
    clip_duration_seconds: float | None = None

    def to_dict(self):
        return asdict(self)


class PlayoutEngine(ABC):
    """Engine-owned timing. Unsupported capabilities must raise EngineError."""

    async def initialize(self):
        pass

    @abstractmethod
    def is_connected(self) -> bool: ...

    def matches_media(self, observed: str | None, expected: str | None, media_root: str) -> bool:
        return bool(observed and expected and observed == expected)

    @abstractmethod
    async def connect(self): ...
    @abstractmethod
    async def disconnect(self): ...
    @abstractmethod
    async def load(self, clip: str): ...
    @abstractmethod
    async def preload(self, clip: str, auto: bool = True): ...
    @abstractmethod
    async def play(self, clip: str | None = None): ...
    @abstractmethod
    async def pause(self): ...
    @abstractmethod
    async def resume(self): ...
    @abstractmethod
    async def stop(self): ...
    @abstractmethod
    async def seek(self, frame: int): ...
    @abstractmethod
    async def observe(self) -> Observation: ...

    async def cue(self, clip: str):
        await self.load(clip)

    async def play_next(self):
        await self.play()

    async def play_segment(self, clip: str, in_frame: int, out_frame: int):
        raise EngineError("This engine does not support bounded segments")

    async def preload_segment(self, clip: str, in_frame: int, out_frame: int, auto: bool = True, transition: dict | None = None):
        raise EngineError("This engine does not support preloading bounded segments")

    async def load_segment(self, clip: str, in_frame: int, out_frame: int):
        raise EngineError("This engine does not support cueing bounded segments")

    async def preload_transition(self, clip: str, transition: dict):
        if transition.get("type", "cut") != "cut":
            raise EngineError("This engine does not support this transition")
        await self.preload(clip)

    async def graphic(self, action: str, layer: int, data: dict):
        raise EngineError("Graphics control is not enabled in Phase 1")

    async def recover(self):
        await self.disconnect()
        await self.connect()
        return await self.observe()
