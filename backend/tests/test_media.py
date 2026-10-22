import json
from fractions import Fraction
from unittest.mock import patch

from app.database import Base, MediaAsset, MediaLocation, make_database
from app.media import index_directory, parse_probe
from sqlalchemy import select


def fixture_probe():
    return {"format": {"duration": "10.040000", "format_name": "mov,mp4"},
        "streams": [{"codec_type": "video", "codec_name": "h264", "avg_frame_rate": "25/1", "r_frame_rate": "25/1", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2}, {"codec_type": "subtitle", "codec_name": "mov_text"}],
        "chapters": [{"start": 0, "end": 251, "time_base": "1/25", "tags": {"title": "Act 1"}}]}


def test_rational_metadata_and_chapters():
    kind, metadata = parse_probe(fixture_probe())
    assert kind == "video"
    assert Fraction(metadata["duration"]) == Fraction(251, 25)
    assert metadata["fps"] == "25"
    assert metadata["audio_channels"] == 2
    assert metadata["chapters"][0]["end"] == 251
    assert len(metadata["subtitles"]) == 1
    assert metadata["possible_vfr"] is False


def test_index_read_only_incremental_missing_and_duplicate_paths(tmp_path):
    engine, sessions = make_database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    root = tmp_path / "media"
    root.mkdir()
    path = root / "clip.mp4"
    source = b"original source bytes"
    path.write_bytes(source)
    stamp = path.stat().st_mtime_ns
    with patch("app.media.probe", return_value=parse_probe(fixture_probe())) as probe:
        assert index_directory(root, sessions, "ffprobe")["indexed"] == 1
        assert index_directory(root, sessions, "ffprobe")["unchanged"] == 1
        assert index_directory(tmp_path, sessions, "ffprobe")["unchanged"] == 1
        assert probe.call_count == 1
    assert path.read_bytes() == source and path.stat().st_mtime_ns == stamp
    with sessions() as db:
        assert len(list(db.scalars(select(MediaAsset)))) == 1
    path.unlink()  # Test fixture only; the indexer never deletes source files.
    assert index_directory(root, sessions, "ffprobe")["missing"] == 1
    with sessions() as db:
        assert db.scalar(select(MediaLocation)).missing
    engine.dispose()


def test_probe_invokes_no_shell(tmp_path):
    from app.media import probe
    from subprocess import CompletedProcess
    path = tmp_path / 'a & b.mp4'
    with patch("app.media.subprocess.run", return_value=CompletedProcess([], 0, json.dumps(fixture_probe()), "")) as run:
        probe(path, "custom-ffprobe")
        assert run.call_args.args[0][-1] == str(path)
        assert "shell" not in run.call_args.kwargs
