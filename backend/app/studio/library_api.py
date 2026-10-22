from fractions import Fraction
import hashlib
import hmac
from pathlib import Path
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..database import Chapter, Segment, Collection, CollectionItem, MediaAsset, MediaLocation
from ..segments import segment_dict, validate_bounds, output_bounds
from .library import media_item
from .schemas import BoundaryInput, CollectionInput


def router(sessions, controller, runner, read_settings, settings, authorize):
    api = APIRouter(tags=["Chapters and collections"])

    def boundaries(db, media_id, body, is_segment=False):
        asset = db.get(MediaAsset, media_id)
        if not asset:
            raise HTTPException(404, "Unknown media")
        value = body.model_dump()
        try:
            validate_bounds(value, Fraction((asset.metadata_json | asset.overrides).get("duration") or "0"))
            if is_segment:
                if body.out_frame is None:
                    raise ValueError("A virtual segment requires OUT")
                cfg = read_settings()
                output_bounds(value, Fraction(cfg.fps_num, cfg.fps_den))
        except (ValueError, ZeroDivisionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return value

    @api.get("/api/media/{media_id}/chapters", dependencies=[authorize])
    def list_chapters(media_id: str):
        with sessions() as db:
            asset = db.get(MediaAsset, media_id)
            if not asset:
                raise HTTPException(404, "Unknown media")
            return {"embedded": asset.metadata_json.get("chapters", []), "chapters": [{**segment_dict(row), "kind": row.kind, "notes": row.notes, "triggers": row.triggers} for row in db.scalars(select(Chapter).where(Chapter.media_id == media_id).order_by(Chapter.in_frame))],
                "segments": [segment_dict(row) for row in db.scalars(select(Segment).where(Segment.media_id == media_id).order_by(Segment.in_frame))]}

    @api.post("/api/media/{media_id}/chapters", dependencies=[authorize])
    def add_chapter(media_id: str, body: BoundaryInput):
        with sessions() as db:
            row = Chapter(media_id=media_id, **boundaries(db, media_id, body))
            db.add(row)
            db.commit()
            return {"id": row.id}

    @api.put("/api/chapters/{chapter_id}", dependencies=[authorize])
    def update_chapter(chapter_id: str, body: BoundaryInput):
        with sessions() as db:
            row = db.get(Chapter, chapter_id)
            if not row:
                raise HTTPException(404, "Unknown chapter")
            for name, value in boundaries(db, row.media_id, body).items():
                setattr(row, name, value)
            db.commit()
            return {"saved": True}

    @api.delete("/api/chapters/{chapter_id}", dependencies=[authorize])
    def delete_chapter(chapter_id: str):
        with sessions() as db:
            row = db.get(Chapter, chapter_id)
            if not row:
                raise HTTPException(404, "Unknown chapter")
            db.delete(row)
            db.commit()
            return {"deleted": True}

    @api.post("/api/media/{media_id}/chapters/import", dependencies=[authorize])
    def import_embedded(media_id: str):
        with sessions() as db:
            asset = db.get(MediaAsset, media_id)
            if not asset:
                raise HTTPException(404, "Unknown media")
            cfg = read_settings()
            rate = Fraction(cfg.fps_num, cfg.fps_den)
            count = 0
            for chapter in asset.metadata_json.get("chapters", []):
                start = Fraction(str(chapter.get("start_time", "0"))) * rate
                end = Fraction(str(chapter.get("end_time", "0"))) * rate
                # Explicit application frame quantization; original embedded metadata remains intact.
                first, last = round(start), round(end)
                if last <= first:
                    continue
                label = chapter.get("tags", {}).get("title", f"Chapter {count + 1}")
                if db.scalar(select(Chapter).where(Chapter.media_id == media_id, Chapter.in_frame == first, Chapter.out_frame == last, Chapter.label == label)):
                    continue
                value = BoundaryInput(label=label, in_frame=first, out_frame=last, fps_num=cfg.fps_num, fps_den=cfg.fps_den)
                db.add(Chapter(media_id=media_id, **boundaries(db, media_id, value)))
                count += 1
            db.commit()
            return {"imported": count, "quantization": "nearest channel frame; original metadata unchanged"}

    @api.post("/api/media/{media_id}/segments", dependencies=[authorize])
    def add_segment(media_id: str, body: BoundaryInput):
        with sessions() as db:
            value = boundaries(db, media_id, body, True)
            row = Segment(media_id=media_id, **{k: v for k, v in value.items() if k not in ("kind", "notes", "triggers")})
            db.add(row)
            db.commit()
            return {"id": row.id}

    @api.get("/api/segments", dependencies=[authorize])
    def list_segments():
        with sessions() as db:
            return [segment_dict(row) for row in db.scalars(select(Segment).order_by(Segment.media_id, Segment.in_frame))]

    @api.post("/api/segments/{segment_id}/preview", dependencies=[authorize])
    async def play_segment(segment_id: str):
        async with runner().lock:
            if runner().armed_id:
                raise HTTPException(409, "Disarm scheduling before on-air segment playback")
            with sessions() as db:
                row = db.get(Segment, segment_id)
                if not row:
                    raise HTTPException(404, "Unknown segment")
                cfg = read_settings()
                item = media_item(db, row.media_id, row.id, Fraction(cfg.fps_num, cfg.fps_den))
                item["id"] = "segment-" + row.id
            await controller().action("play", sequence_items=[item])
            return controller().status()

    @api.post("/api/media/{media_id}/preview-session", dependencies=[authorize])
    def preview_session(media_id: str, response: Response):
        with sessions() as db:
            if not db.get(MediaAsset, media_id):
                raise HTTPException(404, "Unknown media")
        expiry = str(int(time.time()) + 900)
        signature = hmac.new(settings.api_token.encode(), f"{media_id}:{expiry}".encode(), hashlib.sha256).hexdigest()
        path = f"/api/media/{media_id}/content"
        response.set_cookie("preview", expiry + "." + signature, max_age=900, httponly=True, samesite="strict", path=path)
        return {"url": path, "expires_in": 900}

    @api.get("/api/media/{media_id}/content")
    def content(media_id: str, request: Request):
        raw = request.cookies.get("preview", "")
        try:
            expiry, signature = raw.split(".")
            expected = hmac.new(settings.api_token.encode(), f"{media_id}:{expiry}".encode(), hashlib.sha256).hexdigest()
            if int(expiry) < time.time() or not hmac.compare_digest(signature, expected):
                raise ValueError()
        except ValueError:
            raise HTTPException(401, "Create an authenticated, asset-scoped preview session first")
        if request.headers.get("origin") and request.headers["origin"] not in settings.allowed_origins:
            raise HTTPException(403, "Origin not allowed")
        with sessions() as db:
            row = db.scalar(select(MediaLocation).where(MediaLocation.media_id == media_id))
            if not row or not Path(row.path).is_file() or not Path(row.path).resolve().is_relative_to(Path(row.root).resolve()):
                raise HTTPException(404, "Indexed media is unavailable")
            return FileResponse(row.path, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @api.get("/api/collections", dependencies=[authorize])
    def list_collections():
        with sessions() as db:
            return [{"id": row.id, "name": row.name, "query": row.query, "media_ids": list(db.scalars(select(CollectionItem.media_id).where(CollectionItem.collection_id == row.id).order_by(CollectionItem.position)))} for row in db.scalars(select(Collection).order_by(Collection.name))]

    @api.post("/api/collections", dependencies=[authorize])
    def create_collection(body: CollectionInput):
        with sessions() as db:
            if len(set(body.media_ids)) != len(body.media_ids) or any(not db.get(MediaAsset, key) for key in body.media_ids):
                raise HTTPException(400, "Select unique, existing media IDs")
            row = Collection(name=body.name, query=body.query)
            db.add(row)
            db.flush()
            for position, media_id in enumerate(body.media_ids):
                db.add(CollectionItem(collection_id=row.id, media_id=media_id, position=position))
            db.commit()
            return {"id": row.id}

    class TagsInput(BaseModel):
        title: str | None = Field(default=None, min_length=1, max_length=200)
        tags: list[str] = Field(default_factory=list, max_length=100)

    @api.put("/api/media/{media_id}/tags", dependencies=[authorize])
    def update_tags(media_id: str, body: TagsInput):
        with sessions() as db:
            row = db.get(MediaAsset, media_id)
            if not row:
                raise HTTPException(404, "Unknown media")
            row.tags = list(dict.fromkeys(body.tags))
            if body.title:
                row.title = body.title
            db.commit()
            return {"saved": True}

    return api
