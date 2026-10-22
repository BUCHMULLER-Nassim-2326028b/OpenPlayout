"""Owned local server lifecycle. Existing AMCP servers are observed, never killed."""
import asyncio
from fractions import Fraction
import logging
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from ..config import Settings
from ..schemas import ChannelSettings
from .caspar import AMCPConnection
from .engine import EngineError

log = logging.getLogger(__name__)


def render_config(cfg: ChannelSettings, data_dir: Path, screen: bool = True) -> bytes:
    root = ET.Element("configuration")
    paths = ET.SubElement(root, "paths")
    locations = {"media-path": Path(cfg.media_root), "log-path": data_dir / "casparcg" / "log",
        "data-path": data_dir / "casparcg" / "data", "template-path": data_dir / "casparcg" / "templates"}
    for name, path in locations.items():
        ET.SubElement(paths, name).text = path.resolve().as_posix() + "/"
    ET.SubElement(root, "log-level").text = "warning"
    # An explicit rational video mode avoids guessing names for mixed frame rates.
    rate = Fraction(cfg.fps_num, cfg.fps_den)
    samples = Fraction(48000, 1) / rate
    if samples.denominator > 120:
        raise EngineError("The managed output frame rate requires an unsupported audio cadence")
    mode = ET.SubElement(ET.SubElement(root, "video-modes"), "video-mode")
    for name, value in {"id": "openplayout-output", "width": cfg.width, "height": cfg.height,
        "time-scale": rate.numerator, "duration": rate.denominator,
        "cadence": ",".join(str((i + 1) * samples.numerator // samples.denominator - i * samples.numerator // samples.denominator) for i in range(samples.denominator))}.items():
        ET.SubElement(mode, name).text = str(value)
    channels = ET.SubElement(root, "channels")
    for index in range(1, cfg.channel + 1):
        channel = ET.SubElement(channels, "channel")
        ET.SubElement(channel, "video-mode").text = "openplayout-output"
        consumers = ET.SubElement(channel, "consumers")
        if index == cfg.channel and screen:
            consumer = ET.SubElement(consumers, "screen")
            ET.SubElement(consumer, "name").text = "OpenPlayout - Program output"
            ET.SubElement(consumer, "windowed").text = "true"
            ET.SubElement(consumer, "vsync").text = "false"
            ET.SubElement(consumers, "system-audio")
    tcp = ET.SubElement(ET.SubElement(root, "controllers"), "tcp")
    ET.SubElement(tcp, "port").text = str(cfg.port)
    ET.SubElement(tcp, "protocol").text = "AMCP"
    ET.SubElement(ET.SubElement(root, "osc"), "disable-send-to-amcp-clients").text = "true"
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class CasparCGRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: subprocess.Popen | None = None
        self.output = None
        self.state = "disabled"
        self.error: str | None = None
        self.version: str | None = None

    async def handshake(self, cfg: ChannelSettings) -> str:
        connection = AMCPConnection(cfg.host, cfg.port, timeout=1)
        try:
            await connection.connect()
            return await connection.command("VERSION")
        finally:
            await connection.disconnect()

    async def start(self, cfg: ChannelSettings):
        if not self.settings.caspar_autostart:
            return
        if cfg.host not in ("127.0.0.1", "localhost", "::1"):
            self.state = "external"
            return
        self.state = "starting"
        # Reuse only a server answering AMCP VERSION, not just any open port.
        try:
            self.version = await self.handshake(cfg)
            self.state = "external"
            return
        except EngineError:
            pass
        executable = self.settings.caspar_server_dir.resolve() / "casparcg.exe"
        if not executable.is_file():
            raise EngineError("Bundled CasparCG is missing. Run scripts/install-casparcg.ps1, or set OPENPLAYOUT_CASPAR_AUTOSTART=false for an external server.")
        configuration = render_config(cfg, self.settings.data_dir, self.settings.caspar_screen)
        runtime_data = self.settings.data_dir / "casparcg"
        for path in [Path(cfg.media_root), runtime_data / "log", runtime_data / "data", runtime_data / "templates"]:
            path.mkdir(parents=True, exist_ok=True)
        config_path = runtime_data / "openplayout.config"
        config_path.write_bytes(configuration)
        self.output = (runtime_data / "console.log").open("ab", buffering=0)
        try:
            # No shell, inherited console, or system-wide service registration.
            self.process = subprocess.Popen([str(executable), str(config_path)], cwd=executable.parent,
                stdin=subprocess.PIPE, stdout=self.output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = asyncio.get_running_loop().time() + self.settings.caspar_start_timeout
            while asyncio.get_running_loop().time() < deadline:
                if self.process.poll() is not None:
                    raise EngineError(f"CasparCG exited with code {self.process.returncode}; see {runtime_data / 'console.log'}")
                try:
                    self.version = await self.handshake(cfg)
                    self.state = "running"
                    log.info("managed_casparcg_started", extra={"pid": self.process.pid})
                    return
                except EngineError:
                    await asyncio.sleep(0.25)
            raise EngineError(f"CasparCG startup timed out; see {runtime_data / 'console.log'} (GPU / Visual C++ runtime may be required)")
        except BaseException:
            await self.stop()
            raise

    def status(self) -> dict:
        if self.process and self.process.poll() is not None and self.state == "running":
            self.state = "failed"
            self.error = f"CasparCG exited with code {self.process.returncode}; inspect data/casparcg logs"
        return {"state": self.state, "managed": self.process is not None,
            "pid": self.process.pid if self.process and self.process.poll() is None else None,
            "version": self.version, "error": self.error}

    async def stop(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    # stdin belongs to this exact child. A reused external server is never sent KILL.
                    self.process.stdin.write(b"q\n\n")
                    self.process.stdin.flush()
                    await asyncio.to_thread(self.process.wait, 8)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    await asyncio.to_thread(self.process.wait, 5)
            if self.process.stdin:
                self.process.stdin.close()
            self.process = None
            self.state = "stopped"
        if self.output:
            self.output.close()
            self.output = None
