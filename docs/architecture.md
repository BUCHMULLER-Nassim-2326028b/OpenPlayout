# Architecture

OpenPlayout is a local broadcast control application. React talks to one FastAPI
process through authenticated REST and WebSocket endpoints. SQLite stores media,
locations, the sequential rundown, channel settings and as-run records. The media
indexer invokes FFprobe without a shell and never writes to source files.

The local runtime manager starts the bundled CasparCG server during API startup,
waits for AMCP readiness and connects without starting media. It reuses existing
servers and stops only its own child during graceful shutdown. The official
Windows runtime and FFprobe are installed with a pinned checksum; see
[runtime lifecycle](casparcg-runtime.md). FastAPI binds localhost; upstream AMCP
binds all IPv4 interfaces and must remain blocked for remote inbound connections.

The playout controller owns the queue and serializes operator actions with status
polling. It depends on a `PlayoutEngine` interface, not AMCP commands. The CasparCG
adapter owns a single serialized TCP connection, parses AMCP response framing,
times out commands, and reconnects with backoff. Mutating commands are never
automatically retried after an ambiguous connection failure.

CasparCG's foreground producer is the authoritative playback clock. The next
file is queued using LOADBG AUTO. The controller recognizes producer changes
using INFO and updates the persistent cursor and as-run log. Browser timers are
presentation only. Cuts are requested on the server; no frame-accuracy claim is
made until real output has been measured. Unknown INFO schemas fail explicitly.

The MVP supports finite video files (MP4, MOV, MKV, MXF) with probed durations.
Image/audio metadata can be indexed, but their automatic playout is deferred.
Media paths must map under the configured CasparCG media root. The server must
see those files at that root; a successful command does not prove physical output.

At restart, manual recovery is the default. The server and control connection
start automatically; an explicitly configured resume_expected policy may resume
an unfinished checkpoint on an idle output. Reconnection observes the server; it never blindly replays the
persisted cursor. Ambiguous producer identity, missing files, or failed preloads
stop automation and surface an error. There is no silent skip or gap filler.

Security: bind to 127.0.0.1; require a locally generated bearer token for API and
WebSocket access. The UI sends the token in an HTTP Authorization header and in
the first WebSocket message (never a URL). CORS and WebSocket origins are an
explicit allowlist. No arbitrary command or file-read endpoint is exposed.

Scheduling is now a separate planner, API router and explicitly armed dispatcher.
It stores UTC instants with IANA calendar timezones, fits soft events around hard
reservations with rational duration arithmetic, and commits an execution ledger
before issuing commands. It calls only the playback-controller interface and
never rewrites the operator rundown. Opening a schedule is read-only for playout.
See [scheduler.md](scheduler.md) for dispatch tolerances and no-replay policies.

`studio/library_api.py` manages editable chapters, virtual segments and collections.
`studio/fitting.py` optimizes integer-frame groups, staged breaks and fillers with
history filters and a bounded deterministic search. `sequences.py` expands nested
templates, detects cycles and attaches graphics actions. `service.py` preflights
files and compares preview signatures before playback or schedule creation.

Generated timed events use the existing scheduler and explicit arming. Native
sequences use an isolated controller queue and CasparCG AUTO; the persistent
operator rundown is preserved. A separate graphics engine connection prevents
HTML loads from blocking program AMCP observation. Public render/context routes
have read-only instance capabilities and expose no playout or arbitrary-file API.

The bounded asynchronous event bus executes built-in actions and explicitly
enabled trusted Python plugins outside the monitor loop. Errors are persisted
and counted without suspending unrelated video playback. Recovery stores observed
source position and the remaining queue, supports an explicit emergency policy,
and creates online SQLite backups restored by the offline tool. Channel-scoped
tables and inactive channel configurations prepare for future separate workers;
only main is controlled by this version.
