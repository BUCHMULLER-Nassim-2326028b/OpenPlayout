# Scheduling — first working Phase 2 milestone

The Schedule screen creates persistent one-time schedules with a daily timeline,
hard reservations, soft events with a maximum delay, validation, JSON/CSV exchange
and explicitly armed execution. Creating, opening, dragging, importing or exporting
never starts media. Native sequential rundown playback remains available separately.

## Operator workflow

1. Index media and connect to CasparCG (managed startup connects automatically).
2. Open Schedule, create a named schedule, and select indexed media and a local time.
3. Choose Hard for a fixed planned time, or Soft with an allowed maximum delay.
4. Inspect the computed event list, durations and conflicts. Drag blocks in five-minute
   steps or use the editor for exact local clock input. Resolve all errors before arming.
5. Stop manual playback, then click Arm schedule. At least one event must be more
   than one second in the future. Past/imminent events are excluded with a visible
   message and never replayed.
6. Disarm cancels waiting entries and lets current media finish. Manual Stop disarms
   and clears output. Other manual controls require disarming first.

Schedules with execution records are read-only. Export/import a new copy to revise
them. Future cancelled/interrupted events that were never dispatched can be explicitly
re-armed; sent commands are never blindly retried. Restart always begins disarmed.

## Planning and time arithmetic

Stored instants are canonical UTC with an offset; each schedule retains an IANA
calendar timezone. Nonexistent local clock inputs are rejected. A repeated local
time requires choosing its first or second occurrence. Local days use two local
midnights and can be 23, 24 or 25 hours; the UI uses the actual interval length.

Durations use FFprobe rational metadata, rounded upwards to a whole output frame
for occupancy. Files are never modified to normalize frame rates. The deterministic
planner reserves all hard events first, then greedily fits soft events by preferred
time and stable ID. A soft event never moves earlier or beyond its maximum delay.
Conflicts produce errors and suggested corrections, with no silent truncation.
This is a first-fit planner, not a global optimizer or collection generator.

Gaps remain unscheduled, with no black/silence/filler generator. The previous ended
image may remain until the next event. Clips shorter than two seconds, failed probes,
missing media and files changed since indexing are rejected. Re-index changed files.

## Execution and accuracy

One backend monitor observes the engine and dispatches due entries. An explicit arm
anchors UTC to the backend monotonic clock. A wall-clock step over one second
suspends future dispatch for operator review. Browser timers never trigger playback.

Default dispatch tolerance: 0.5 seconds. Configure
OPENPLAYOUT_SCHEDULER_LATENESS_SECONDS between zero (exclusive) and ten seconds.
The dispatcher waits for occupied output to finish within that window. If still
occupied, the event is blocked; if idle but already outside tolerance, it is missed.
Programs are never cut or sped up to recover deadlines. Errors remain in the ledger;
future armed events can still run if output becomes available.

The ledger is committed as dispatching before any command, then records running,
completed, interrupted or error. Separate timestamps retain planned start, command
dispatch, first observed playing state and observed end. A crash with an ambiguous
command outcome does not cause a retry. Pending/in-flight entries become interrupted
on restart. The operator rundown is never overwritten by schedule execution.

Dispatch is software-timed per scheduled file. Dense back-to-back hard events can
exceed tolerance due to render/command latency. Use the native AUTO rundown for
continuous sequences until timed native preloading is implemented. No frame accuracy
or gap-free scheduled transitions are claimed. One isolated real-server test measured
command dispatch about 61 ms after target and first observed playback about 186 ms
after target. These are measurements on this machine, not a performance guarantee.

## Import/export

Version 1 JSON contains name, timezone and events. Example:

```json
{
  "version": 1,
  "name": "Evening",
  "timezone": "Europe/Paris",
  "events": [{
    "media_id": "existing-library-media-id",
    "preferred_start": "2030-01-01T18:00:00+00:00",
    "kind": "hard",
    "label": "Opening",
    "max_delay_seconds": 0,
    "user_fields": {"producer": "studio"}
  }]
}
```

CSV requires media_id and preferred_start. Optional columns: label, kind (hard/soft),
max_delay_seconds, user_fields (JSON object). Unknown CSV columns become custom
user_fields. IDs must reference the current library; import does not load arbitrary
file paths or download media. Clock values require UTC offsets. Limits: 1 MB and
1,000 events per schedule/import. Validate import first, then Import as new schedule.
Existing schedules are never overwritten. Exports retain requested times; plans are
recalculated from current metadata and output frame rate.

## Deferred

Weekly recurrence, date overrides, flexible blocks, sequence templates, grouping,
collection policies, global fitting, emergency recovery and timed native preloading
remain later milestones. The current editor shows one local day at a time, while
schedules can contain explicit events across multiple days.
