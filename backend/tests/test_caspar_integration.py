"""Opt-in, read-only handshake against an installed server. No output certification."""
import os
import asyncio
from pathlib import Path
import pytest

from app.playout.caspar import AMCPConnection, CasparCGEngine, clip_key


@pytest.mark.caspar
@pytest.mark.skipif(os.environ.get("OPENPLAYOUT_TEST_CASPAR") != "1", reason="Real CasparCG server not requested")
async def test_real_server_handshake():
    connection = AMCPConnection(os.environ.get("OPENPLAYOUT_CASPAR_HOST", "127.0.0.1"), int(os.environ.get("OPENPLAYOUT_CASPAR_PORT", "5250")))
    try:
        await connection.connect()
        assert await connection.command("VERSION")
        assert await connection.command("INFO")
    finally:
        await connection.disconnect()


@pytest.mark.caspar
@pytest.mark.skipif(os.environ.get("OPENPLAYOUT_TEST_PLAYBACK") != "1", reason="Live output test must be explicitly requested")
async def test_real_two_clip_auto_playback():
    """Uses only test layer 9900; synthetic samples are supplied by the operator script."""
    first = Path(os.environ["OPENPLAYOUT_TEST_CLIP_A"]).resolve()
    second = Path(os.environ["OPENPLAYOUT_TEST_CLIP_B"]).resolve()
    assert first.is_file() and second.is_file()
    engine = CasparCGEngine(os.environ.get("OPENPLAYOUT_CASPAR_HOST", "127.0.0.1"), int(os.environ.get("OPENPLAYOUT_CASPAR_PORT", "5250")), layer=9900)

    async def wait_for_clip(path, timeout):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            observed = await engine.observe()
            if observed.clip and clip_key(observed.clip) == clip_key(str(path)):
                assert observed.duration_seconds > 0
                assert observed.position_seconds >= 0
                return observed
            await asyncio.sleep(0.1)
        pytest.fail(f"Expected producer was not observed: {path.name}")

    await engine.connect()
    try:
        await engine.play(first.as_posix())
        assert (await wait_for_clip(first, 5)).state == "playing"
        await engine.preload(second.as_posix(), auto=True)
        assert (await wait_for_clip(second, 8)).state == "playing"
    finally:
        await engine.stop()
        await engine.disconnect()
