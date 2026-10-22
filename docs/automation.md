# Rules, breaks, reusable sequences and recovery

Create ordered collections in Studio. Manual order is selection order. Smart
collections use tags and optional kind; unavailable indexed members are excluded.
Set application tags in Collections. The API also accepts weights by media ID for
weighted selection. All media must remain below the configured engine media root.

Rule templates support sequential, seeded shuffle, weighted random, least recently
played and consecutive ordering. Set minimum/preferred/maximum group size, whether
additional groups are allowed, maximum groups, history cooldown and daily limits.
Advanced JSON supports priority/excluded tags, seasonal tag/month restrictions,
manual media priority and preference for never-played content. History is recorded
per media; separate segments share history. Daily limits use the channel timezone.

Break templates contain ordered required/optional collection stages with item
count bounds, target/minimum/maximum duration, strict target, duplicate avoidance,
cooldown, priority tags and optional filler. Required stages are never silently
dropped. A non-strict target is a preference; an explicit maximum or the remaining
deadline capacity is a hard limit. Strict requests reject nonrepresentable frames
or impossible fits. The solver never truncates footage to force a fit.

Preview rules with a target or explicit start/deadline. Output durations use
integer channel frames. The search considers group sizes, staged breaks and fillers
jointly, never overruns capacity and fails explicitly after 150,000 search states.
Narrow collections if search exceeds this bound. It prevents planned repeats of
program media, so repeat groups require enough distinct eligible items. The seeded
selection order breaks ties; this is not an unlimited global optimizer.

Save edits, generate a preview, then run on program or create a timed schedule.
Preflight checks current source availability, stat fingerprints, transition syntax
and graphics references. A preview signature detects changed source data. Schedule
creation requires a start time, writes a new draft and never arms it. Review/arm
in Schedule. Timed export accepts cut-only media/segments; graphics/transitions
remain native sequence actions. Adjacent timed events use software dispatch and
may incur the scheduler's documented latency; native AUTO sequences provide the
tested continuous segment/break path. Nominal duration fit is not a promise of a
frame-certified wall-clock finish. Busy output is never cut to meet a deadline.

Sequence templates contain enabled media, segment, break, nested sequence and
graphics steps. Advanced JSON supports simple `{key, equals}` conditions against
explicit preview/run context, per-step variables, expected duration and cut/MIX
transitions. Cycles, depth above 16 and expansions above 1000 actions are rejected.
Graphics before a clip execute when its start is observed; trailing actions execute
on observed EOF. These hooks are not synchronous frame-level events.

Operations defaults to manual restart recovery. Once per second the backend
persists observed position, producer bounds and active queue. Preview estimates the
expected source position by elapsed UTC time if playing, or preserves paused
position. A passed OUT is not replayed. Explicit recovery requires idle/disarmed
output and revalidates files. `resume_expected` is opt-in and only runs on idle
output; missing/changed sources surface an error while the app remains available.
An emergency sequence can be taken explicitly, or once per app lifetime after a
playback error when configured. That explicit policy may interrupt scheduled work.
The default error policy suspends and alerts. This is recovery groundwork, not
automatic redundant server failover or a tested 24/7 availability guarantee.

SQLite online backup creates a checked ZIP without media, API token or plugin code.
Stop OpenPlayout, use scripts/restore-backup.ps1 -Archive PATH -ConfirmStopped, then
restart. Restore validates archive members, manifest, integrity and foreign keys,
refuses live WAL/SHM sidecars, retains the previous database and never extracts
arbitrary ZIP paths. Restore is an operator-declared offline operation. Settings
JSON import requires a disconnected controller and a restart for engine changes.
Resource JSON retains references to local IDs: cross-install imports need referenced
collections/media/templates already present or IDs remapped manually. Full database
backups preserve those IDs.
