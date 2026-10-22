"""AMCP transport and INFO adapters. No raw-command API is exposed to clients."""
import asyncio
import re
from fractions import Fraction
from pathlib import Path

from defusedxml import ElementTree as ET

from .engine import EngineError, Observation, PlayoutEngine


def quote(value: str) -> str:
    if any(ord(c) < 32 for c in value):
        raise EngineError("Control characters are forbidden in AMCP parameters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def clip_key(value: str) -> str:
    path = Path(value.replace("\\", "/"))
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".mxf", ".avi", ".webm", ".ts", ".m4v"}:
        path = path.with_suffix("")
    return str(path).replace("\\", "/").casefold()


class AMCPConnection:
    def __init__(self, host: str, port: int, timeout: float = 3):
        self.host, self.port, self.timeout = host, port, timeout
        self.reader = None
        self.writer = None
        self.lock = asyncio.Lock()

    @property
    def connected(self):
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self):
        if not self.connected:
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port, limit=2**22), self.timeout)
            except (OSError, TimeoutError) as exc:
                raise EngineError(f"Cannot connect to CasparCG at {self.host}:{self.port}: {exc}") from exc

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
        self.reader = self.writer = None

    async def command(self, command: str) -> str:
        if "\r" in command or "\n" in command:
            raise EngineError("Invalid AMCP command")
        async with self.lock:
            if not self.connected:
                raise EngineError("CasparCG is disconnected")
            try:
                async with asyncio.timeout(self.timeout):
                    self.writer.write((command + "\r\n").encode("utf-8"))
                    await self.writer.drain()
                    header = (await self.reader.readline()).decode("utf-8").strip()
                    # XML writers may leave one trailing empty line after the document.
                    if not header:
                        header = (await self.reader.readline()).decode("utf-8").strip()
                    # Some server versions send a connection banner.
                    if header.startswith("100 "):
                        header = (await self.reader.readline()).decode("utf-8").strip()
                    if not re.match(r"^\d{3} ", header):
                        raise ConnectionError("Invalid or closed AMCP response")
                    code = int(header[:3])
                    body = ""
                    if code == 200:
                        lines = []
                        while True:
                            line = await self.reader.readline()
                            if not line:
                                raise ConnectionError("Truncated AMCP response")
                            if line == b"\r\n":
                                break
                            lines.append(line.decode("utf-8"))
                        body = "".join(lines)
                    elif code in (201, 101, 400):
                        line = await self.reader.readline()
                        if not line:
                            raise ConnectionError("Truncated AMCP response")
                        body = line.decode("utf-8").strip()
                        # INFO XML uses 201 with formatted multiline XML on recent servers.
                        if code == 201 and body.startswith("<?xml"):
                            while True:
                                try:
                                    ET.fromstring(body)
                                    break
                                except ET.ParseError:
                                    line = await self.reader.readline()
                                    if not line:
                                        raise ConnectionError("Truncated INFO XML")
                                    body += "\n" + line.decode("utf-8").strip()
                    if code >= 400:
                        raise EngineError(f"{header}: {body}".strip(": "))
                    if code not in (200, 201, 202):
                        raise ConnectionError(f"Unexpected AMCP response: {header}")
                    return body
            except (OSError, TimeoutError, UnicodeError, ValueError) as exc:
                await self.disconnect()
                raise EngineError(f"AMCP communication failed; command outcome may be unknown: {exc}") from exc


def parse_info(xml: str, layer: int) -> Observation:
    try:
        root = ET.fromstring(xml)
        # 2.1/2.3 layer response, or full channel state in newer versions.
        foreground = root.find(f".//layer_{layer}/foreground")
        if foreground is None:
            for candidate in root.findall(".//layer"):
                if candidate.findtext("index") == str(layer):
                    foreground = candidate.find("foreground")
                    break
        if foreground is None and root.tag == "layer":
            foreground = root.find("foreground")
        if foreground is None:
            if root.tag == "channel" and (root.find("stage") is not None or root.find("layers") is not None or root.find("format") is not None):
                return Observation(True, "stopped")
            raise EngineError("Unsupported INFO XML: target foreground is absent")
        producer = foreground.find("producer")
        node = producer if producer is not None and len(producer) else foreground
        kind = node.findtext("type") or foreground.findtext("producer")
        if kind in ("empty-producer", "empty"):
            return Observation(True, "stopped")
        filename = node.findtext("filename") or node.findtext("file/path") or node.findtext("file/name")
        if not filename:
            raise EngineError("Unsupported producer: no identifiable media filename")
        paused = foreground.findtext("paused") or node.findtext("paused")
        if paused is None:
            raise EngineError("Unsupported INFO XML: pause state is absent")
        # Legacy schemas report source frames. Current schemas report two time values in seconds.
        frame = node.findtext("file-frame-number")
        total = node.findtext("file-nb-frames")
        fps = node.findtext("fps")
        if frame is not None and total is not None and (fps or node.find("fps") is not None):
            numerator = node.findtext("fps/numerator")
            denominator = node.findtext("fps/denominator")
            rate = float(numerator) / float(denominator) if numerator and denominator else float(Fraction(fps))
            position, duration = float(frame) / rate, float(total) / rate
        else:
            times = node.findall("file/time")
            values = [c.text for c in times[0]] if len(times) == 1 and len(times[0]) else [c.text for c in times]
            if len(values) != 2:
                raise EngineError("Unsupported INFO timing schema; position is unavailable")
            position, duration = map(float, values)
        if duration <= 0 or position < 0:
            raise EngineError("Invalid producer timing")
        state = "paused" if paused.lower() in ("true", "1") else "playing"
        clips = node.findall("file/clip")
        clip_values = [c.text for c in clips[0]] if len(clips) == 1 and len(clips[0]) else [c.text for c in clips]
        clip_in, clip_duration = (map(float, clip_values) if len(clip_values) == 2 else (0.0, duration))
        if state == "playing" and position >= clip_in + clip_duration:
            state = "ended"
        return Observation(True, state, filename, position, duration, clip_in, clip_duration)
    except (ET.ParseError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise EngineError(f"Invalid INFO response: {exc}") from exc


class CasparCGEngine(PlayoutEngine):
    def __init__(self, host: str, port: int, channel: int = 1, layer: int = 10):
        self.connection = AMCPConnection(host, port)
        self.channel, self.layer = channel, layer
        self.target = f"{channel}-{layer}"

    def is_connected(self) -> bool:
        return self.connection.connected

    def matches_media(self, observed: str | None, expected: str | None, media_root: str) -> bool:
        if not observed or not expected:
            return False
        return clip_key(observed) in (clip_key(expected), clip_key(str(Path(media_root) / expected)))

    async def connect(self):
        await self.connection.connect()
        await self.connection.command("VERSION")

    async def disconnect(self):
        await self.connection.disconnect()

    async def load(self, clip: str):
        await self.connection.command(f"LOAD {self.target} {quote(clip)}")

    async def preload(self, clip: str, auto: bool = True):
        await self.connection.command(f"LOADBG {self.target} {quote(clip)} CUT 0" + (" AUTO" if auto else ""))

    async def play(self, clip: str | None = None):
        await self.connection.command(f"PLAY {self.target}" + (f" {quote(clip)}" if clip else ""))

    async def pause(self):
        await self.connection.command(f"PAUSE {self.target}")

    async def resume(self):
        await self.connection.command(f"RESUME {self.target}")

    async def stop(self):
        # Clear both producers so a stale AUTO item cannot start later.
        await self.connection.command(f"CLEAR {self.target}")

    async def seek(self, frame: int):
        if frame < 0:
            raise EngineError("Seek frame must be nonnegative")
        await self.connection.command(f"CALL {self.target} SEEK {frame}")

    @staticmethod
    def transition_args(transition: dict | None) -> str:
        transition = transition or {}
        kind = transition.get("type", "cut")
        frames = transition.get("frames", 0)
        if kind not in ("cut", "dissolve") or not isinstance(frames, int) or not 0 <= frames <= 500:
            raise EngineError("Supported transitions: cut or dissolve with 0–500 output frames")
        return "CUT 0" if kind == "cut" else f"MIX {frames}"

    async def play_segment(self, clip: str, in_frame: int, out_frame: int):
        if in_frame < 0 or out_frame <= in_frame:
            raise EngineError("Invalid segment boundaries")
        await self.connection.command(f"PLAY {self.target} {quote(clip)} SEEK {in_frame} LENGTH {out_frame - in_frame}")

    async def load_segment(self, clip: str, in_frame: int, out_frame: int):
        if in_frame < 0 or out_frame <= in_frame:
            raise EngineError("Invalid segment boundaries")
        await self.connection.command(f"LOAD {self.target} {quote(clip)} SEEK {in_frame} LENGTH {out_frame - in_frame}")

    async def preload_segment(self, clip: str, in_frame: int, out_frame: int, auto: bool = True, transition: dict | None = None):
        if in_frame < 0 or out_frame <= in_frame:
            raise EngineError("Invalid segment boundaries")
        await self.connection.command(f"LOADBG {self.target} {quote(clip)} {self.transition_args(transition)} SEEK {in_frame} LENGTH {out_frame - in_frame}" + (" AUTO" if auto else ""))

    async def preload_transition(self, clip: str, transition: dict):
        await self.connection.command(f"LOADBG {self.target} {quote(clip)} {self.transition_args(transition)} AUTO")

    async def graphic(self, action: str, layer: int, data: dict):
        if not 1 <= layer <= 9999 or layer == self.layer:
            raise EngineError("Graphics must use a different, valid output layer")
        target = f"{self.channel}-{layer}"
        if action == "show":
            await self.connection.command(f"PLAY {target} [HTML] {quote(data['url'])}")
        elif action == "hide":
            await self.connection.command(f"CLEAR {target}")
        else:
            raise EngineError("Unsupported graphics action")

    async def observe(self) -> Observation:
        return parse_info(await self.connection.command(f"INFO {self.channel}"), self.layer)
