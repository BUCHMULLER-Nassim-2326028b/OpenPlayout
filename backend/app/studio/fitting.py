"""Bounded deterministic optimization; all output arithmetic uses integer frames."""
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from itertools import combinations
import random
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..database import PlaybackHistory
from .library import members, document
from .schemas import BreakConfig, RuleConfig


class SearchBudget:
    def __init__(self):
        self.count = 0

    def visit(self):
        self.count += 1
        if self.count > 150000:
            raise ValueError("Selection search exceeded 150,000 states. Narrow collections, group sizes or break stages; no partial plan was committed.")


def frames(seconds: str, fps: Fraction, exact=False) -> int:
    value = Fraction(seconds) * fps
    if value < 0 or value > fps * 172800:
        raise ValueError("Duration must be between zero and 48 hours")
    if exact and value.denominator != 1:
        raise ValueError("Exact duration must be representable as whole output frames")
    return value.numerator // value.denominator


def eligible(db, items, *, now, cooldown=0, max_daily=None, zone="UTC", excluded_tags=(), seasonal_tags=None):
    rows = list(db.scalars(select(PlaybackHistory)))
    start = datetime.combine(now.astimezone(ZoneInfo(zone)).date(), datetime.min.time(), ZoneInfo(zone)).astimezone(timezone.utc)
    recent, daily, last = set(), {}, {}
    for row in rows:
        played = datetime.fromisoformat(row.started_at)
        if played > now:
            continue
        last[row.media_id] = max(last.get(row.media_id, ""), row.started_at)
        if played >= now - timedelta(seconds=cooldown) and cooldown:
            recent.add(row.media_id)
        if played >= start:
            daily[row.media_id] = daily.get(row.media_id, 0) + 1
    accepted, rejected = [], []
    for item in items:
        key = item["media"]["id"]
        tags = item["media"]["tags"]
        if key in recent or max_daily and daily.get(key, 0) >= max_daily or any(t in tags for t in excluded_tags):
            rejected.append(key)
            continue
        if seasonal_tags and any(tag in tags and now.astimezone(ZoneInfo(zone)).month not in months for tag, months in seasonal_tags.items()):
            rejected.append(key)
            continue
        accepted.append(item | {"last_played": last.get(key), "plays_today": daily.get(key, 0)})
    return accepted, rejected


def ranked(items, policy, seed, priority_tags=(), prefer_unwatched=False, manual_priority=None):
    rng = random.Random(seed)
    values = list(items)
    if policy == "shuffle":
        rng.shuffle(values)
    elif policy == "weighted_random":
        values.sort(key=lambda item: rng.random() ** (1 / max(1, item.get("weight", 1))), reverse=True)
    elif policy == "least_recently_played":
        values.sort(key=lambda item: item.get("last_played") or "")
    # Stable sort retains the seeded policy order for equal ranking scores.
    values.sort(key=lambda item: (-(manual_priority or {}).get(item["media"]["id"], 0),
        -sum(tag in item["media"]["tags"] for tag in priority_tags), bool(item.get("last_played")) if prefer_unwatched else False))
    return values


def stage_options(pool, minimum, maximum, capacity, used, budget):
    for count in range(minimum, min(maximum, len(pool)) + 1):
        for chosen in combinations(pool, count):
            budget.visit()
            ids = {item["media"]["id"] for item in chosen}
            duration = sum(item["duration_frames"] for item in chosen)
            if ids.isdisjoint(used) and duration <= capacity:
                yield duration, list(chosen), ids


def break_options(db, config: BreakConfig, fps, capacity, now, used, budget):
    maximum = min(capacity, frames(config.maximum_seconds, fps)) if config.maximum_seconds else capacity
    target = frames(config.target_seconds, fps, config.strict)
    minimum = frames(config.minimum_seconds, fps)
    if config.strict:
        minimum = maximum = target
        if target > capacity:
            return []
    stages = []
    for stage in config.stages:
        pool, _ = eligible(db, members(db, stage.collection_id, fps), now=now, cooldown=config.cooldown_seconds)
        pool = ranked(pool, "shuffle", config.seed, config.priority_tags)
        stages.append((pool, max(1, stage.min_items) if stage.required else 0, stage.max_items))
    if config.filler_collection_id:
        pool, _ = eligible(db, members(db, config.filler_collection_id, fps), now=now, cooldown=config.cooldown_seconds)
        stages.append((pool, 0, min(10, len(pool))))
    states = [(0, [], set(used))]
    for pool, low, high in stages:
        next_states = []
        for total, items, ids in states:
            for duration, chosen, chosen_ids in stage_options(pool, low, high, maximum - total, ids if config.avoid_duplicates else set(), budget):
                next_states.append((total + duration, items + chosen, ids | chosen_ids))
        states = next_states
        if not states:
            break
    return sorted([state for state in states if minimum <= state[0] <= maximum], key=lambda state: (abs(target - state[0]), -state[0]))


def fit_break(db, resource_id, fps, capacity=None, now=None, used=None):
    config = BreakConfig.model_validate(document(db, resource_id, "break").payload)
    now = now or datetime.now(timezone.utc)
    capacity = capacity if capacity is not None else frames(config.maximum_seconds or "172800", fps)
    choices = break_options(db, config, fps, capacity, now, used or set(), SearchBudget())
    if not choices:
        raise ValueError("No valid break satisfies required stages, cooldowns and duration. Add eligible media, relax optional stages or adjust the target.")
    total, items, _ = choices[0]
    return {"items": [item | {"break_id": resource_id} for item in items], "duration_frames": total, "duration_seconds": float(Fraction(total, 1) / fps), "unused_frames": capacity - total}


def generate(db, resource_id, fps, target_seconds, strict=False, now=None, zone="UTC"):
    config = RuleConfig.model_validate(document(db, resource_id, "rule").payload)
    now = now or datetime.now(timezone.utc)
    capacity = frames(target_seconds, fps, strict)
    pool, excluded = eligible(db, members(db, config.collection_id, fps), now=now, cooldown=config.no_repeat_hours * 3600,
        max_daily=config.max_plays_per_day, zone=zone, excluded_tags=config.excluded_tags, seasonal_tags=config.seasonal_tags)
    pool = ranked(pool, config.policy if config.policy != "consecutive" else "sequential", config.seed, config.priority_tags, config.prefer_unwatched, config.manual_priority)
    if not pool:
        raise ValueError("No eligible program media remains after collection/history filters")
    groups = []
    counts = sorted(range(config.min_items, config.max_items + 1), key=lambda n: (abs(n - config.preferred_items), -n))
    for count in counts:
        for index in range(len(pool) - count + 1):
            groups.append(pool[index:index + count])
    break_config = BreakConfig.model_validate(document(db, config.break_id, "break").payload) if config.break_id else None
    fillers = eligible(db, members(db, config.filler_collection_id, fps), now=now, cooldown=config.no_repeat_hours * 3600)[0] if config.filler_collection_id else []
    budget = SearchBudget()
    best = (0, [])
    seen = set()

    def visit(total, selected, used, group_count):
        nonlocal best
        budget.visit()
        signature = (total, frozenset(used), group_count)
        if signature in seen:
            return
        seen.add(signature)
        if total > best[0]:
            best = total, selected
        if strict and total == capacity:
            return
        if fillers:
            for amount, chosen, _ in stage_options(fillers, 0, min(10, len(fillers)), capacity - total, used, budget):
                if total + amount > best[0]:
                    best = total + amount, selected + chosen
        if group_count >= (config.max_groups if config.allow_new_group else 1):
            return
        for group in groups:
            ids = {item["media"]["id"] for item in group}
            if not ids.isdisjoint(used):
                continue
            group_duration = sum(item["duration_frames"] for item in group)
            available = capacity - total - group_duration
            if available < 0:
                continue
            breaks = [(0, [], used)]
            if selected and break_config:
                breaks = break_options(db, break_config, fps, available, now, used | ids, budget)
            for break_duration, break_items, break_ids in breaks:
                items = [i | {"break_id": config.break_id} for i in break_items]
                visit(total + group_duration + break_duration, selected + items + group, used | ids | break_ids, group_count + 1)
                if strict and best[0] == capacity:
                    return
    visit(0, [], set(), 0)
    if best[0] == 0 or strict and best[0] != capacity:
        raise ValueError("No exact/eligible group plan fits the deadline. Change group sizes, supply fillers or relax strict fit; no footage was truncated.")
    return {"items": best[1], "duration_frames": best[0], "duration_seconds": float(Fraction(best[0], 1) / fps),
        "unused_frames": capacity - best[0], "excluded_media_ids": excluded, "search_states": budget.count}
