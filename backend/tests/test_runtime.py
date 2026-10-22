from fractions import Fraction
import io
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.playout.engine import EngineError
from app.playout.runtime import CasparCGRuntime, render_config
from app.schemas import ChannelSettings


def test_generated_config_respects_paths_and_rational_output(tmp_path):
    cfg = ChannelSettings(media_root=str(tmp_path / "media & clips"), fps_num=30000, fps_den=1001, channel=2, port=5260)
    root = ET.fromstring(render_config(cfg, tmp_path / "data"))
    assert root.findtext("paths/media-path").endswith("media & clips/")
    assert root.findtext("controllers/tcp/port") == "5260"
    assert len(root.findall("channels/channel")) == 2
    assert len(root.findall(".//screen")) == 1
    assert root.findtext("channels/channel[2]/consumers/screen/windowed") == "true"
    cadence = [int(n) for n in root.findtext("video-modes/video-mode/cadence").split(",")]
    assert Fraction(sum(cadence), len(cadence)) == Fraction(48000 * 1001, 30000)
    assert not root.findall(".//producer")  # Booting the server never starts a program.


async def test_external_server_reused_without_spawning_or_stopping(tmp_path):
    runtime = CasparCGRuntime(Settings(data_dir=tmp_path))
    runtime.handshake = AsyncMock(return_value="2.5.1 STABLE")
    with patch("app.playout.runtime.subprocess.Popen") as launch:
        await runtime.start(ChannelSettings())
        assert runtime.state == "external"
        launch.assert_not_called()
        await runtime.stop()
    assert runtime.version == "2.5.1 STABLE"


async def test_missing_runtime_fails_with_install_instructions(tmp_path):
    runtime = CasparCGRuntime(Settings(data_dir=tmp_path, caspar_server_dir=tmp_path / "missing"))
    runtime.handshake = AsyncMock(side_effect=EngineError("not listening"))
    with pytest.raises(EngineError, match="install-casparcg"):
        await runtime.start(ChannelSettings())


async def test_owned_child_hidden_ready_and_stopped(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "casparcg.exe").write_bytes(b"test stub; never executed")
    cfg = ChannelSettings(media_root=str(tmp_path / "media"))
    settings = Settings(data_dir=tmp_path / "data", caspar_server_dir=bundle)
    runtime = CasparCGRuntime(settings)
    runtime.handshake = AsyncMock(side_effect=[EngineError("not listening"), "2.5.1 STABLE"])

    class Child:
        pid = 1234
        stdin = io.BytesIO()
        returncode = None
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            self.returncode = 0
            return 0
    child = Child()
    with patch("app.playout.runtime.subprocess.Popen", return_value=child) as launch:
        await runtime.start(cfg)
        assert runtime.status()["state"] == "running"
        assert launch.call_args.kwargs["stdin"] is not None
        assert "shell" not in launch.call_args.kwargs
        assert (settings.data_dir / "casparcg/openplayout.config").is_file()
        await runtime.stop()
        assert runtime.state == "stopped"
        assert child.returncode == 0


async def test_disabled_and_remote_do_not_spawn(tmp_path):
    with patch("app.playout.runtime.subprocess.Popen") as launch:
        disabled = CasparCGRuntime(Settings(data_dir=tmp_path, caspar_autostart=False))
        await disabled.start(ChannelSettings())
        assert disabled.state == "disabled"
        remote = CasparCGRuntime(Settings(data_dir=tmp_path))
        await remote.start(ChannelSettings(host="192.0.2.1"))
        assert remote.state == "external"
        launch.assert_not_called()
