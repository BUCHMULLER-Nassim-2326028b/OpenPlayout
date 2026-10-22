"""Deterministic hard reservations and bounded soft placement, in rational seconds."""
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from zoneinfo import ZoneInfo

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def instant(value: str | datetime) -> Fraction:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Scheduled instants must include a UTC offset")
    delta = stamp.astimezone(timezone.utc) - EPOCH
    return Fraction((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds, 1_000_000)


def iso(value: Fraction, ceiling: bool = False) -> str:
    micros = value * 1_000_000
    count = -(-micros.numerator // micros.denominator) if ceiling else micros.numerator // micros.denominator
    return (EPOCH + timedelta(microseconds=count)).isoformat()


def local_instant(value: str, zone: str, fold: int | None = None) -> str:
    naive = datetime.fromisoformat(value)
    if naive.tzinfo is not None:
        raise ValueError("Local clock input must not contain an offset")
    timezone_info = ZoneInfo(zone)
    candidates = {}
    for choice in (0, 1):
        candidate = naive.replace(tzinfo=timezone_info, fold=choice)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(timezone_info).replace(tzinfo=None) == naive:
            candidates[choice] = utc
    if not candidates:
        raise ValueError("This local time does not exist because of a timezone transition")
    if len(set(candidates.values())) > 1 and fold is None:
        raise ValueError("This local time occurs twice; choose the first or second occurrence")
    selected = candidates.get(fold if fold is not None else 0)
    if selected is None:
        raise ValueError("Invalid occurrence for this local time")
    return selected.isoformat()


def day_window(day: str, zone: str) -> dict:
    local_date = date.fromisoformat(day)
    start = local_instant(local_date.isoformat() + "T00:00:00", zone, 0)
    end = local_instant((local_date + timedelta(days=1)).isoformat() + "T00:00:00", zone, 0)
    return {"start": start, "end": end, "seconds": float(instant(end) - instant(start))}


def build_plan(events: list[dict], fps: Fraction) -> dict:
    slots = []
    errors = []
    prepared = []
    for event in events:
        try:
            media = event["media"]
            if media["missing"] or media["error"] or media["kind"] != "video":
                raise ValueError("Media must be an available, successfully probed video")
            duration = Fraction(media["metadata"].get("duration") or "0")
            if duration < 2:
                raise ValueError("Scheduled video must be at least two seconds")
            frames = -(-(duration * fps).numerator // (duration * fps).denominator)
            prepared.append(event | {"start": instant(event["preferred_start"]), "duration": Fraction(frames, 1) / fps, "frames": frames})
        except (ValueError, ZeroDivisionError) as exc:
            errors.append({"event_id": event["id"], "message": str(exc)})
    for event in sorted(prepared, key=lambda e: (e["kind"] != "hard", e["start"], e["id"])):
        start = event["start"]
        duration = event["duration"]
        if event["kind"] == "soft":
            for occupied in sorted(slots, key=lambda s: s["start"]):
                if start + duration <= occupied["start"]:
                    break
                if start < occupied["end"] and start + duration > occupied["start"]:
                    start = occupied["end"]
            if start > event["start"] + event["max_delay_seconds"]:
                errors.append({"event_id": event["id"], "message": "No free slot inside the soft-event delay window. Increase its window, move it or choose shorter media."})
                continue
        end = start + duration
        if any(start < s["end"] and end > s["start"] for s in slots):
            errors.append({"event_id": event["id"], "message": "Hard events overlap. Move an event or select shorter media; content will not be truncated."})
            continue
        slots.append(event | {"start": start, "end": end})
    rows = []
    for slot in sorted(slots, key=lambda s: (s["start"], s["id"])):
        rows.append({key: value for key, value in slot.items() if key not in ("start", "end", "duration")} | {
            "planned_start": iso(slot["start"]), "planned_end": iso(slot["end"], ceiling=True),
            "start_rational": str(slot["start"]), "end_rational": str(slot["end"]),
            "duration_rational": str(slot["duration"]), "duration_seconds": float(slot["duration"]),
            "delay_seconds": float(slot["start"] - instant(slot["preferred_start"]))})
    return {"valid": not errors, "events": rows, "errors": errors,
        "timing": "Software dispatch; no frame-accuracy guarantee. Current media is never cut to recover a deadline."}
