from fractions import Fraction

from .database import Segment


def segment_dict(segment: Segment) -> dict:
    return {name: getattr(segment, name) for name in ("id", "media_id", "label", "in_frame", "out_frame", "fps_num", "fps_den")}


def output_bounds(segment: dict, fps: Fraction) -> tuple[int, int]:
    source_rate = Fraction(segment["fps_num"], segment["fps_den"])
    start = Fraction(segment["in_frame"], 1) / source_rate * fps
    end = Fraction(segment["out_frame"], 1) / source_rate * fps
    if start.denominator != 1 or end.denominator != 1:
        raise ValueError("Segment boundaries cannot be represented exactly at the channel frame rate; choose aligned boundaries")
    if end <= start or start < 0:
        raise ValueError("IN must be nonnegative and OUT strictly greater than IN")
    return int(start), int(end)


def validate_bounds(data: dict, duration: Fraction):
    rate = Fraction(data["fps_num"], data["fps_den"])
    if data["in_frame"] < 0 or Fraction(data["in_frame"], 1) / rate >= duration:
        raise ValueError("IN lies outside the source duration")
    end = data.get("out_frame")
    if end is not None and (end <= data["in_frame"] or Fraction(end, 1) / rate > duration):
        raise ValueError("OUT must be exclusive, greater than IN and within the source duration")
