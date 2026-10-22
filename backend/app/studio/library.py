from fractions import Fraction
from sqlalchemy import select

from ..database import Collection, CollectionItem, MediaAsset, MediaLocation, Segment, Resource
from ..media import asset_dict
from ..segments import segment_dict, output_bounds


def media_item(db, media_id: str, segment_id: str | None = None, fps: Fraction = Fraction(25)) -> dict:
    asset = db.get(MediaAsset, media_id)
    location = db.scalar(select(MediaLocation).where(MediaLocation.media_id == media_id))
    if not asset or not location:
        raise ValueError(f"Unknown or unlinked media: {media_id}")
    item = {"id": media_id, "position": 0, "media": asset_dict(asset, location), "segment": None, "transition": {}}
    if segment_id:
        segment = db.get(Segment, segment_id)
        if not segment or segment.media_id != media_id:
            raise ValueError("Unknown segment or mismatched source")
        item["segment"] = segment_dict(segment)
        first, last = output_bounds(item["segment"], fps)
        item["duration_frames"] = last - first
    else:
        duration = Fraction(item["media"]["metadata"].get("duration") or "0")
        frames = duration * fps
        item["duration_frames"] = -(-frames.numerator // frames.denominator)
    if item["duration_frames"] <= 0 or item["media"]["missing"] or item["media"]["error"]:
        raise ValueError(f"Unavailable media or unknown duration: {asset.title}")
    item["duration_seconds"] = float(Fraction(item["duration_frames"], 1) / fps)
    return item


def members(db, collection_id: str, fps: Fraction) -> list[dict]:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise ValueError("Unknown collection")
    if collection.query:
        tags = collection.query.get("tags", [])
        kind = collection.query.get("kind")
        candidates = list(db.scalars(select(MediaAsset).order_by(MediaAsset.title, MediaAsset.id)))
        selected = [(a.id, 1) for a in candidates if all(t in a.tags for t in tags) and (not kind or a.kind == kind)]
    else:
        selected = [(i.media_id, i.weight) for i in db.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.position))]
    result = []
    for media_id, weight in selected:
        try:
            result.append(media_item(db, media_id, fps=fps) | {"weight": weight})
        except ValueError:
            # Selection excludes unavailable members; API includes excluded IDs separately.
            continue
    return result


def document(db, resource_id: str, kind: str | None = None) -> Resource:
    resource = db.get(Resource, resource_id)
    if not resource or kind and resource.kind != kind:
        raise ValueError(f"Unknown {kind or 'resource'}: {resource_id}")
    return resource
