import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.playout.engine import EngineError, Observation, PlayoutEngine


class SimulatedEngine(PlayoutEngine):
    """Explicit test double: no video output and no evidence of broadcast timing."""
    def __init__(self):
        self.connected = False
        self.foreground = None
        self.background = None
        self.state = "stopped"
        self.position = 0
        self.fail_preload = False
        self.calls = []
        self.bounds = None
        self.background_bounds = None

    def require_connection(self):
        if not self.connected:
            raise EngineError("Simulated engine disconnected")

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def load(self, clip):
        self.require_connection()
        self.foreground, self.state, self.position = clip, "paused", 0
        self.bounds = None
        self.calls.append(("load", clip))

    async def preload(self, clip, auto=True):
        self.require_connection()
        if self.fail_preload:
            raise EngineError("Simulated preload failure")
        self.background = clip
        self.background_bounds = None
        self.calls.append(("preload", clip, auto))

    async def play(self, clip=None):
        self.require_connection()
        self.foreground = clip or self.background
        self.state, self.position = "playing", 0
        self.bounds = None
        self.calls.append(("play", self.foreground))

    async def pause(self):
        self.require_connection()
        self.state = "paused"

    async def resume(self):
        self.require_connection()
        self.state = "playing"

    async def stop(self):
        self.require_connection()
        self.foreground = self.background = None
        self.state = "stopped"

    async def seek(self, frame):
        self.require_connection()
        self.position = frame / 25

    async def observe(self):
        self.require_connection()
        return Observation(True, self.state, self.foreground, self.position, 10 if self.foreground else None,
            self.bounds[0] / 25 if self.bounds else 0, (self.bounds[1] - self.bounds[0]) / 25 if self.bounds else None)

    async def play_segment(self, clip, in_frame, out_frame):
        await self.play(clip)
        self.bounds, self.position = (in_frame, out_frame), in_frame / 25

    async def load_segment(self, clip, in_frame, out_frame):
        await self.load(clip)
        self.bounds, self.position = (in_frame, out_frame), in_frame / 25

    async def preload_segment(self, clip, in_frame, out_frame, auto=True, transition=None):
        await self.preload(clip, auto)
        self.background_bounds = (in_frame, out_frame)

    async def preload_transition(self, clip, transition):
        await self.preload(clip)

    async def graphic(self, action, layer, data):
        self.require_connection()
        self.calls.append(("graphic", action, layer, data))

    def finish(self):
        if self.background:
            self.foreground, self.background = self.background, None
            self.position, self.state = 0, "playing"
            self.bounds, self.background_bounds = self.background_bounds, None
            if self.bounds:
                self.position = self.bounds[0] / 25
        else:
            self.position, self.state = self.bounds[1] / 25 if self.bounds else 10, "ended"


@pytest.fixture
def harness(tmp_path):
    engine = SimulatedEngine()
    cfg = Settings(data_dir=tmp_path / "data", api_token="test-token-with-more-than-24-chars", caspar_media_root=str(tmp_path))
    app = create_app(cfg, engine_factory=lambda _: engine)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + cfg.api_token
        yield client, app, engine, tmp_path
