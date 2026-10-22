"""Read-only discovery and FFprobe inspection. No shell or media writes."""
import json
import logging
import math
import os
import subprocess
from fractions import Fraction
from pathlib import Path

from sqlalchemy import select

from .database import MediaAsset, MediaLocation

log = logging.getLogger(__name__)
EXTENSIONS = {".mp4", ".mov", ".mkv", ".mxf", ".avi", ".webm", ".ts", ".m4v", ".wav", ".mp3", ".flac", ".png", ".jpg", ".jpeg"}


def rational(value: str | None) -> str | None:
    try:
        fraction = Fraction(value or "0")
        return str(fraction) if fraction > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def parse_probe(data: dict) -> tuple[str, dict]:
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = rational(data.get("format", {}).get("duration") or video.get("duration") or audio.get("duration"))
    fps = rational(video.get("avg_frame_rate"))
    nominal = rational(video.get("r_frame_rate"))
    return ("video" if video else "audio" if audio else "unknown"), {
        "duration": duration, "fps": fps, "nominal_fps": nominal,
        "width": video.get("width"), "height": video.get("height"),
        "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name"),
        "audio_channels": audio.get("channels"), "container": data.get("format", {}).get("format_name"),
        "chapters": data.get("chapters", []),
        "subtitles": [s for s in streams if s.get("codec_type") == "subtitle"],
        "possible_vfr": bool(fps and nominal and fps != nominal),
    }


def probe(path: Path, executable: str) -> tuple[str, dict]:
    result = subprocess.run(
        [executable, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", str(path)],
        capture_output=True, timeout=45, check=False, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise ValueError((result.stderr.strip() or "FFprobe failed")[:1000])
    return parse_probe(json.loads(result.stdout))


def index_directory(root: Path, sessions, executable: str) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Media root must be an existing directory")
    report = {"indexed": 0, "unchanged": 0, "failed": 0, "missing": 0, "errors": []}
    seen: set[str] = set()
    traversal_errors: list[OSError] = []
    with sessions() as db:
        for directory, folders, filenames in os.walk(root, followlinks=False, onerror=traversal_errors.append):
            folders[:] = sorted(f for f in folders if not (Path(directory) / f).is_symlink() and not (Path(directory) / f).is_junction())
            for filename in sorted(filenames):
                path = Path(directory) / filename
                if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                    continue
                path = path.resolve()
                if not path.is_relative_to(root):
                    continue
                key = str(path)
                seen.add(key)
                location = db.scalar(select(MediaLocation).where(MediaLocation.path == key))
                try:
                    stat = path.stat()
                    if location and location.size == stat.st_size and location.mtime_ns == stat.st_mtime_ns and not location.error:
                        location.missing = False
                        report["unchanged"] += 1
                        continue
                    asset = db.get(MediaAsset, location.media_id) if location else MediaAsset(title=path.stem)
                    if not location:
                        db.add(asset)
                        db.flush()
                        location = MediaLocation(media_id=asset.id, path=key, root=str(root), relative_path=path.relative_to(root).as_posix(), size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                        db.add(location)
                    location.size, location.mtime_ns, location.missing = stat.st_size, stat.st_mtime_ns, False
                    try:
                        asset.kind, asset.metadata_json = probe(path, executable)
                        location.error = None if asset.metadata_json.get("duration") else "No finite duration; automatic playback unavailable"
                        report["indexed"] += 1
                    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                        location.error = str(exc)[:1000]
                        report["failed"] += 1
                        report["errors"].append({"path": key, "error": location.error})
                except OSError as exc:
                    report["failed"] += 1
                    report["errors"].append({"path": key, "error": str(exc)})
        # An inaccessible subtree must not mark all its files missing.
        for location in db.scalars(select(MediaLocation)):
            if Path(location.path).is_relative_to(root) and location.path not in seen:
                try:
                    location.missing = not Path(location.path).exists()
                    report["missing"] += int(location.missing)
                except OSError:
                    pass
        report["errors"].extend({"path": str(e.filename), "error": str(e)} for e in traversal_errors)
        report["failed"] += len(traversal_errors)
        db.commit()
    log.info("media_scan_completed", extra={"root": str(root), "report": report})
    return report


def asset_dict(asset: MediaAsset, location: MediaLocation) -> dict:
    metadata = asset.metadata_json | asset.overrides
    duration = metadata.get("duration")
    seconds = float(Fraction(duration)) if duration else None
    return {"id": asset.id, "title": asset.title, "kind": asset.kind, "metadata": metadata,
        "duration_seconds": seconds if seconds is not None and math.isfinite(seconds) else None,
        "tags": asset.tags, "path": location.path, "root": location.root,
        "relative_path": location.relative_path, "size": location.size, "mtime_ns": location.mtime_ns,
        "missing": location.missing, "error": location.error}
