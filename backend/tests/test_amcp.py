import asyncio
import pytest

from app.playout.caspar import AMCPConnection, clip_key, parse_info, quote
from app.playout.engine import EngineError


def test_info_current_and_legacy():
    xml = '<channel><stage><layer><layer_10><foreground><producer>ffmpeg</producer><paused>false</paused><file><path>C:/media/one.mp4</path><time>1.5</time><time>10</time></file></foreground></layer_10></layer></stage></channel>'
    observation = parse_info(xml, 10)
    assert observation.position_seconds == 1.5 and observation.duration_seconds == 10
    assert observation.state == "playing"
    old = '<layer><foreground><producer><type>ffmpeg-producer</type><filename>one.mp4</filename><file-frame-number>50</file-frame-number><file-nb-frames>250</file-nb-frames><fps>25</fps></producer><paused>true</paused></foreground></layer>'
    assert parse_info(old, 10).position_seconds == 2
    assert parse_info(old, 10).state == "paused"
    assert parse_info('<channel><stage><layer/></stage></channel>', 10).state == "stopped"
    # Captured on the bundled 2.5.1 server before any layer has been created.
    assert parse_info('<channel><format>openplayout-output</format><framerate>25</framerate><framerate>1</framerate><output/></channel>', 10).state == "stopped"
    with pytest.raises(EngineError, match="Unsupported"):
        parse_info('<not-a-channel/>', 10)
    with pytest.raises(EngineError, match="Control"):
        quote('clip\r\nCLEAR 1')
    assert quote('a "b"') == '"a \\"b\\""'.replace('\\\\', '\\')
    assert clip_key("folder/show.ep01.mp4") == clip_key("folder/show.ep01")


async def test_response_framing_serialization_and_error():
    seen = []
    async def peer(reader, writer):
        try:
            while line := await reader.readline():
                seen.append(line.decode().strip())
                if line.startswith(b"VERSION"):
                    writer.write(b"201 VERSION OK\r\n2.3.3\r\n")
                elif line.startswith(b"INFO"):
                    writer.write(b"200 INFO OK\r\n<channel/>\r\n\r\n")
                elif line.startswith(b"BAD"):
                    writer.write(b"400 ERROR\r\nBAD\r\n")
                else:
                    writer.write(b"202 PLAY OK\r\n")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    connection = AMCPConnection("127.0.0.1", server.sockets[0].getsockname()[1])
    try:
        await connection.connect()
        assert await connection.command("VERSION") == "2.3.3"
        results = await asyncio.gather(connection.command("INFO 1"), connection.command("PLAY 1-10"))
        assert results == ["<channel/>\r\n", ""]
        with pytest.raises(EngineError, match="400"):
            await connection.command("BAD")
        assert await connection.command("VERSION") == "2.3.3"
        assert len(seen) == 5
    finally:
        await connection.disconnect()
        server.close()
        await server.wait_closed()


async def test_timeout_disconnects_and_does_not_retry():
    seen = []
    async def peer(reader, writer):
        seen.append(await reader.readline())
        await reader.read()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    connection = AMCPConnection("127.0.0.1", server.sockets[0].getsockname()[1], timeout=0.05)
    try:
        await connection.connect()
        with pytest.raises(EngineError, match="outcome may be unknown"):
            await connection.command("PLAY 1-10 clip")
        assert not connection.connected
        assert len(seen) == 1
    finally:
        await connection.disconnect()
        server.close()
        await server.wait_closed()


async def test_formatted_201_xml_does_not_desynchronize_next_command():
    async def peer(reader, writer):
        try:
            while line := await reader.readline():
                if line.startswith(b"INFO"):
                    writer.write(b'201 INFO OK\r\n<?xml version="1.0"?>\r\n<channel>\r\n<stage/>\r\n</channel>\r\n\r\n')
                else:
                    writer.write(b'201 VERSION OK\r\n2.4.0\r\n')
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    connection = AMCPConnection("127.0.0.1", server.sockets[0].getsockname()[1])
    try:
        await connection.connect()
        assert parse_info(await connection.command("INFO 1"), 10).state == "stopped"
        assert await connection.command("VERSION") == "2.4.0"
    finally:
        await connection.disconnect()
        server.close()
        await server.wait_closed()
