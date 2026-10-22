# Delivery and validation record — 2026-10-22

## Phases 3–6

Final combined run: **57 passed, 2 skipped**, including the full real application
and real studio/Chrome acceptance; the two external adapter-only tests remain opt-in.
The standard isolated suite has 55 passing tests. TypeScript and Vite production
build pass. New tests cover chapter/segment bounds and unchanged sources,
asset-scoped Range preview, segment/break/resume, cycles, exact repeated-group fit
with breaks and hard deadline, disarmed schedule creation, fillers/cooldowns,
stale preview refusal, dynamic graphics context/hooks, plugin failure isolation,
expected/paused recovery, emergency actions, inactive channels, configuration
round trip, online SQLite integrity and actual offline ZIP restoration.

Real CasparCG 2.5.1 acceptance used fresh generated media and an isolated database,
private AMCP/HTTP ports, the actual CEF HTML producer and channel IMAGE output
captures. A 10-second source played 0–3 s, a three-second bumper, then 3–6 s.
INFO confirmed the resumed source bounds. SHA-256 confirmed no source writes.
PNG inspection showed a composited logo and NOW/NEXT, red source before and green
after the break, and NEXT updated to empty at the final segment. These are real
server output captures, not browser simulations. Reference successful artifacts:
`.tools/studio-acceptance/ee6ab041-23b1-4279-a6ff-b4d6e50258cb/` (ignored local files).

Chrome checked chapter creation, saved sequence expansion, HTML bridge rendering
and diagnostics. The extended suite additionally exercises collection creation,
strict rule fitting and disarmed schedule creation through the UI. It uses only
isolated synthetic assets. Scripts: test_studio_live.py and studio-smoke.mjs.

The final combined run uses a fresh project-local --basetemp under .tools/test-runs.
An earlier elevated run hit Windows permissions on the system pytest Temp parent;
re-running with the isolated project path resolved all fixture setup errors.

Material limits: no physical SDI/HDMI certification, audio/gap measurement,
frame-accuracy certification, multichannel workers, redundant-server failover or
24/7 soak. Remote HTML services and native dissolves need target-specific checks.
The Starlette TestClient HTTPX deprecation warning is upstream and non-failing.

Changed areas: backend models/migration 0003, segment-aware adapter/controller,
studio services/API, recovery/events/graphics, React Chapters/Studio pages, browser
and backend acceptance tests, offline restore scripts, plugin example and guides.
The original phase records below are retained as historical evidence.

## Full application acceptance and first scheduling milestone

The full isolated live test now creates its own synthetic MP4s, uses real FFprobe
through the API, adds them to the persistent rundown, plays via the actual
controller/CasparCG adapter, observes AUTO progression and EOF, then restarts the
application and verifies the media/rundown survive without replay. It also arms a
real future hard event and verifies commanded/observed timestamps and completion
survive restart. A private free AMCP port and a fresh `.tools/acceptance/<uuid>`
directory keep tests separate from the operator database and source media.

One run measured 60.516 ms command delay and 185.516 ms first observation delay.
These validate the software dispatch path on this machine; physical output quality,
transition continuity and frame-perfect performance are not certified.

40 unit/API tests cover phase 1 plus scheduler exact fit, hard conflicts, soft
placement/windows, rational mixed-rate occupancy, midnight, 23/25-hour days,
nonexistent/repeated local times, JSON/CSV roundtrip and preview, manual-control
guards, no-replay execution, occupied output, late deadlines, crash recovery and
changed media, migration of existing data and stable import preview/commit order.
Two live adapter tests and the full real-app test also pass.
One upstream Starlette/HTTPX deprecation warning remains.

Chrome verifies schedule creation, hard/soft events, automatic soft placement,
timeline drag, JSON download, mobile layout and deep-route reload. TypeScript and
Vite build pass. Screenshot: `.tools/screenshots/schedule.png` (generated/ignored).
The browser acceptance database is isolated; no schedules were inserted into the
operator database.

New files for this milestone:

```text
backend/migrations/versions/0002_schedules.py
backend/app/scheduler/__init__.py
backend/app/scheduler/api.py
backend/app/scheduler/planner.py
backend/app/scheduler/runner.py
backend/tests/test_scheduler.py
backend/tests/test_full_live.py
backend/tests/test_migrations.py
apps/web/src/SchedulePage.tsx
apps/web/scripts/schedule-smoke.mjs
```

Changed: backend database/config/main/media/controller, controller/INFO tests,
frontend router/dashboard/types/styles, environment example, README, architecture,
scheduler/API docs and roadmap. Schedule arithmetic uses rational durations; actual
execution uses explicit software timing and never cuts current footage to fit.

## Bundled server update

CasparCG 2.5.1 Stable is now installed at `.tools/casparcg/2.5.1` from the official
Windows archive. Its SHA-256 matches the pinned release digest. Its bundled
FFprobe reads real metadata (3 seconds, 25 fps, MPEG-4) without changing the
synthetic source's SHA-256. No global installation was performed.

The Windows launcher now starts CasparCG with the application, waits for readiness
and connects automatically. Actual API status reports `runtime.state=running`,
`runtime.managed=true`, version `2.5.1 ec38d94 Stable`, connected playback and no
error. The generated configuration initializes a 1080p25 screen and system-audio
consumer. Existing servers are reused; only an owned child is stopped on shutdown.

Checks: 22 unit/API tests, two opt-in live CasparCG tests (handshake and a red/blue
MP4 AUTO producer switch on layer 9900), frontend build, idempotent installer and
Chrome smoke. The live test clears its own layer and leaves the application
rundown/library unchanged. Physical screen quality and transition continuity
remain unmeasured; these results do not certify frame accuracy.

New files: `scripts/install-casparcg.ps1`, `scripts/test-casparcg.ps1`,
`backend/app/playout/runtime.py`, `backend/tests/test_runtime.py`, and
`docs/casparcg-runtime.md`. Changed files: startup/setup scripts, backend config,
schemas, lifespan/status API and INFO adapter, integration/INFO tests, frontend
status types/control room, `.env.example`, `.gitignore`, README and relevant docs.

The following section records the original foundation checks before this update.

## Working and checked

- Windows startup launches FastAPI on 127.0.0.1:8000 and serves the built React UI.
- HTTP health 200 and documented bearer security in OpenAPI.
- 17 backend tests pass; one real CasparCG handshake test is skipped by default.
- TypeScript compilation and Vite production build pass.
- Installed Chrome smoke passes token unlock, WebSocket synchronization,
  control room, empty library/search, settings, responsive width and interface lock.
- Deterministic tests cover as-run records, native-AUTO observation, preloading,
  delayed initial INFO state, missing media, failed preload, manual skip,
  pause/resume, API seek, invalid commands, connection loss without replay,
  authentication/origins, persistent restart, read-only incremental indexing,
  embedded chapter metadata and AMCP response framing/timeouts.

The FFprobe process invocation is mocked in unit tests; actual FFprobe is absent
from PATH. The playback simulator produces no output. Loopback AMCP tests verify
transport behavior against a synthetic server, not CasparCG output quality.
No CasparCG executable was found in PATH and the default AMCP port was closed.
Real two-MP4 output acceptance is outstanding. Physical output, transition gaps,
EOF behavior, frame accuracy and 24/7 reliability are not certified.

## Commands used

```powershell
# This workspace's private Python environment:
.\.tools\backend-venv\Scripts\python.exe -m pytest backend\tests -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
# From apps/web with the app running and an empty rundown/library:
node scripts/smoke.mjs
```

Test/build scripts now run successfully. Initial issues fixed during verification:
Windows timezone data missing (added tzdata), Vite sandbox ancestor-read restriction
(build run with reviewed execution permission), isolated test-directory creation,
and connection-retry cancellation. One upstream Starlette warning recommends its
new HTTPX2 test transport; the current HTTPX tests pass.

The browser test uses the installed Chrome without downloading a browser. Set
`OPENPLAYOUT_CHROME` for a different executable and `OPENPLAYOUT_URL` for a
different local URL. Screenshot: `.tools/screenshots/control-room.png` (generated,
ignored). The script reads the local token but never prints it.

## Created source/configuration files

All project source files were created in the initially empty workspace.

```text
.gitignore
.env.example
README.md
docs/architecture.md
docs/roadmap.md
docs/development.md
docs/playout-engine.md
docs/scheduler.md
docs/media-segments.md
docs/api.md
docs/troubleshooting.md
docs/validation.md
backend/pyproject.toml
backend/requirements.lock
backend/alembic.ini
backend/migrations/env.py
backend/migrations/versions/0001_foundation.py
backend/app/__init__.py
backend/app/config.py
backend/app/database.py
backend/app/schemas.py
backend/app/media.py
backend/app/main.py
backend/app/playout/__init__.py
backend/app/playout/engine.py
backend/app/playout/caspar.py
backend/app/playout/controller.py
backend/tests/conftest.py
backend/tests/test_api.py
backend/tests/test_media.py
backend/tests/test_amcp.py
backend/tests/test_controller.py
backend/tests/test_restart.py
backend/tests/test_caspar_integration.py
apps/web/package.json
apps/web/package-lock.json
apps/web/index.html
apps/web/tsconfig.json
apps/web/vite.config.ts
apps/web/src/main.tsx
apps/web/src/api.ts
apps/web/src/types.ts
apps/web/src/styles.css
apps/web/scripts/smoke.mjs
scripts/setup.ps1
scripts/start.ps1
scripts/test.ps1
```

Generated `.tools`, `.venv`, `node_modules`, `dist`, Python caches/package metadata,
and local `data` are ignored. No source media was provided or modified. Future
phase documentation describes planned behavior and clearly marks unimplemented
features.
