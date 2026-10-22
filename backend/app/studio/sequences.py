from fractions import Fraction
from uuid import uuid4

from ..database import Segment
from .fitting import fit_break
from .library import media_item, document
from .schemas import SequenceConfig


def expand(db, resource_id: str, fps: Fraction, context=None, stack=(), budget=None):
    context, budget = context or {}, budget if budget is not None else [0]
    if resource_id in stack or len(stack) >= 16:
        raise ValueError("Nested sequence cycle or maximum nesting depth reached")
    config = SequenceConfig.model_validate(document(db, resource_id, "sequence").payload)
    result, pending_actions = [], []
    for step in config.items:
        budget[0] += 1
        if budget[0] > 1000:
            raise ValueError("Expanded sequences may contain at most 1000 actions")
        if not step.enabled or step.when and context.get(step.when.get("key")) != step.when.get("equals", True):
            continue
        items = []
        if step.kind == "media":
            items = [media_item(db, step.reference, fps=fps)]
        elif step.kind == "segment":
            segment = db.get(Segment, step.reference)
            if not segment:
                raise ValueError("Unknown segment")
            items = [media_item(db, segment.media_id, segment.id, fps)]
        elif step.kind == "sequence":
            nested = expand(db, step.reference, fps, context, stack + (resource_id,), budget)
            items = nested["items"]
            if not items:
                pending_actions += nested.get("actions", [])
        elif step.kind == "break":
            items = fit_break(db, step.reference, fps)["items"]
        elif step.kind == "graphics":
            action = step.parameters.get("action", "show")
            if action not in ("show", "hide", "variables"):
                raise ValueError("Invalid graphics event action")
            pending_actions.append({"type": "graphics." + action, "instance_id": step.reference, "parameters": step.parameters.get("variables", {})})
        if items:
            items[0]["on_start_actions"] = pending_actions + items[0].get("on_start_actions", [])
            pending_actions = []
            if step.transition:
                items[0]["transition"] = step.transition
            result.extend(items)
    if pending_actions and result:
        result[-1]["on_end_actions"] = result[-1].get("on_end_actions", []) + pending_actions
        pending_actions = []
    for position, item in enumerate(result):
        item["id"] = f"{resource_id}:{position}:{uuid4()}"
        item["position"] = position
    duration = sum(i["duration_frames"] for i in result)
    for item in result[1:]:
        if item.get("transition", {}).get("type") == "dissolve":
            duration -= item["transition"].get("frames", 0)
    if config.expected_duration_seconds is not None and Fraction(config.expected_duration_seconds) * fps != duration:
        raise ValueError("Template duration does not match its configured expected duration")
    return {"items": result, "actions": pending_actions, "duration_frames": duration, "duration_seconds": float(Fraction(duration, 1) / fps)}
