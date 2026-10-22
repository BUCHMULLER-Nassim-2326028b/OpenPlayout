# Implementation roadmap

## Phase 1 — full application technical acceptance passed

- [x] Architecture and incremental implementation checklist
- [x] Backend, SQLite schema and initial Alembic migration
- [x] Persistent settings, read-only FFprobe indexing and search
- [x] Typed playback interface, AMCP transport and CasparCG adapter
- [x] Persistent sequential rundown, preload and observed automatic advancement (simulated tests)
- [x] React control interface and REST/WebSocket synchronization
- [x] Deterministic simulated-engine and protocol tests
- [x] Windows setup/start scripts and operator documentation
- [x] Tests, frontend build and local API/browser smoke checks
- [x] Full real-server API path: index two generated MP4s, build rundown, AUTO advance, EOF and restart persistence
- [ ] Operator visual inspection and measured transition continuity on the target output

The technical path passes with real CasparCG, FFprobe and generated MP4s in an
isolated data directory. Screen/audio consumers initialize. Physical output quality
and transition continuity still require an operator/measurement check.

## Phase 2 — first working scheduling milestone

- [x] Alembic 0002: persistent schedules, UTC events and execution ledger
- [x] Hard reservations and deterministic soft placement within bounded delays
- [x] Rational durations normalized conservatively to output-frame occupancy
- [x] Daily timeline, drag editing, conflict display and explicit arm/disarm
- [x] Local-time resolution, DST ambiguity validation and 23/25-hour days
- [x] CSV/versioned JSON preview, import as new schedule, and export
- [x] Monotonic backend dispatch, lateness tolerance, no program cutting or silent replay
- [x] Planned/commanded/observed timestamps and persisted no-replay recovery
- [x] Real timed-start application test; ~61 ms command delay / ~186 ms observation delay in one run
- [x] Chrome create/edit/drag/export/mobile/reload checks and production build
- [x] 40 unit/API tests plus two live adapter tests and one full real-app acceptance test
- [x] Phase 1 database migration preserves existing library/rundown; import preview order survives commit
- [ ] Weekly recurrence, flexible blocks and native timed preloading (not part of this first milestone)

Schedules are one-time explicit events across any dates. Timing is software-based,
not frame-certified. No files are converted, split or overwritten. See
[scheduler.md](scheduler.md) for operator instructions and limitations.

Phases 3–6 are implemented in the working milestones below.

## Bundled server milestone — 2026-10-22

- [x] Official Windows CasparCG 2.5.1 installed locally with pinned SHA-256
- [x] FFmpeg/FFprobe from the complete upstream archive; original license retained
- [x] Automatic backend-owned startup, AMCP readiness and controller connection
- [x] Generated output config, default local media root and screen/system audio
- [x] Existing-server reuse, owned-process shutdown and manual external mode
- [x] Real 2.5.1 empty-channel INFO support and runtime diagnostics in the UI
- [x] 22 unit/API tests plus 2 opt-in live integration tests pass
- [x] Real FFprobe metadata read verified without altering the synthetic source
- [x] Real red-to-blue MP4 AUTO switch verified on dedicated test layer 9900
- [x] TypeScript/Vite build and Chrome navigation smoke pass
- [ ] Physical output quality and measured transition continuity (full rundown technical test now passes)

Autoboot means at OpenPlayout launch, not at Windows login. No media is automatically
played at application startup. See [casparcg-runtime.md](casparcg-runtime.md).

## Initial foundation verification (before bundled runtime)

Python 3.12.15 is installed inside `.tools/python`, with a project-local backend
environment. Windows start script launches successfully; health returns 200 and
OpenAPI exposes bearer authentication. Backend: 17 passed, 1 optional CasparCG
test skipped. Frontend: TypeScript + Vite production build passed. Chrome smoke
passed unlock, WebSocket updates, control room, library search, settings, mobile
layout and locking. Settings/library/rundown persistence across a fresh application
instance is covered by an automated restart test.

FFprobe and CasparCG were not found in PATH; no server listened on 127.0.0.1:5250.
Real metadata extraction and actual video output were therefore not accepted.
The adapter is implemented against official AMCP documentation and server state
code, with synthetic protocol fixtures; it is not certified against a live build.
One upstream Starlette deprecation warning for the HTTPX test client remains.

The full-rundown technical acceptance was subsequently completed with the bundled
runtime, and the first Phase 2 milestone is implemented above. Physical output
inspection and transition measurements remain open. File inventory and validation notes are
in [validation.md](validation.md).

## Phase 3 — verified native segment / break / resume

- [x] Alembic 0003 preserves existing data while adding studio models
- [x] Chapter metadata import, editor, notes and targeted automation markers
- [x] Scoped browser source preview, Range requests and frame IN/OUT controls
- [x] Virtual segments, rational frame conversion and bounded seek
- [x] Native CasparCG PLAY/LOAD/LOADBG SEEK/LENGTH and segment-aware INFO identity
- [x] Real 0–3 s segment → blue bumper → 3–6 s segment; source hash unchanged
- [x] Output PNG inspection confirms red before / green after the break
- [ ] Frame/audio continuity measurement on target broadcast hardware

## Phase 4 — rules and break automation

- [x] Ordered and smart collections, tags and API weights
- [x] Rule editor, seeded policies, priorities, history cooldown and daily limits
- [x] Required/optional staged breaks, duplicate avoidance and automatic fillers
- [x] Integer-frame bounded search, strict fit and explicit impossible-fit errors
- [x] Repeated two-item groups with an interstitial break fit a 50-second hard deadline
- [x] Generate, review and create a new disarmed timed schedule from a template
- [x] Native sequence execution with source/preview revalidation
- [x] Playback history shared by full media and its segments
- [ ] Weekly recurrence and unlimited large-library optimization remain follow-up work

## Phase 5 — real HTML graphics compositing verified

- [x] Builtin logo, lower third, NOW/NEXT and countdown
- [x] Custom HTML, local file and remote HTTPS bridge with hide/freeze policy
- [x] Graphics instance/layer controls, themes and dynamic variables
- [x] Separate engine connection, observed NOW/NEXT context and graphics hooks
- [x] Real CEF producer and output IMAGE capture: logo and NEXT over program
- [x] Inspected screenshots show NEXT updates across program progression
- [ ] Device-specific output and third-party remote overlay compatibility checks

## Phase 6 — extended automation and recovery groundwork

- [x] Versioned reusable nested templates, conditions, transitions and cycle checks
- [x] Event actions, bounded asynchronous hooks, audit log and operator diagnostics
- [x] Opt-in trusted Python plugin SDK/example, timeout/error isolation and path checks
- [x] Channel-scoped records and inactive channel configurations
- [x] Observed checkpoints, expected-position/paused recovery, explicit emergency policy
- [x] Configuration/template JSON portability and checked online SQLite backup
- [x] Offline restore tool preserves old database and validates archive/SQLite integrity
- [x] Automated backup → offline restore → restored library/rundown check
- [x] Final combined run: 57 passed / 2 optional adapter tests skipped; production build and real Chrome acceptance pass
- [ ] Simultaneous independent channel workers and redundant-server failover
- [ ] Long-running 24/7 soak, output precision and disaster-recovery rehearsals on target system

The phases have working implementations and the concrete acceptance paths above;
this does not certify a finished 24/7 broadcast appliance. Shorter-than-two-second
items and identical adjacent full producers remain outside reliable observation.
Recovery defaults to manual. Native cut sequences are tested; dissolve continuity
and arbitrary remote pages require their own output checks. Physical signal output
has not been certified. See automation.md and graphics-and-plugins.md.
