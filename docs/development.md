# Development

Backend requires Python 3.12+. Frontend requires Node 22.12+ or current LTS.
Use `scripts/setup.ps1`, `scripts/start.ps1 -Dev`, and `scripts/test.ps1` from the
repository root. Development UI port is 5173 and backend is 8000. Vite proxies
REST and WebSocket traffic. Production assets are served by FastAPI after build.

Backend source is in `backend/app`. Media indexing runs in a worker thread;
playout commands and observation share an asyncio lock. The AMCP socket has its
own lock to preserve request/response ordering. SQLite connections enable foreign
keys, WAL and a five-second busy timeout. Do not run multiple backend workers:
the playout controller is process-local and there must be one owner of the layer.
The bundled CasparCG lifecycle also belongs to that process; see
[runtime configuration](casparcg-runtime.md). Use `-NoCasparCG` for development
against an independently managed server when API reload should preserve output.

Migrations run on application startup. Add explicit, immutable Alembic revisions
for schema changes; do not replace migrations with `create_all` in production.
Tests use isolated temporary SQLite files and deterministic simulated producers.
Scheduling tests cover exact fit, conflicts, soft delays, rational occupancy,
midnight and timezone transitions. An explicit upgrade test migrates a populated
0001 database to 0002 without losing the library or operator rundown.
Opt-in integration tests cover a read-only VERSION/INFO handshake and synthetic
two-file AUTO playback on dedicated layer 9900. The full real-app acceptance test
generates its own media, scans through the API, checks rundown/timed playback and
restarts with isolated data and a private AMCP port. Flags and commands are in
README.md. Physical output quality still needs operator inspection.

Configuration precedence: process environment, root `.env`, defaults. Persisted UI
settings take precedence over initial environment defaults after first startup.
`OPENPLAYOUT_DATA_DIR` selects SQLite, logs, token and backups. Do not commit that
directory. Filesystem access follows the Windows user account running the backend.

Backend dependency ranges are in `backend/pyproject.toml`; the tested exact
resolution is recorded in `backend/requirements.lock`. Frontend uses
`apps/web/package-lock.json`. For reproducible backend installation use
`python -m pip install -r backend/requirements.lock` then
`python -m pip install --no-deps -e backend` inside the environment.

Opt-in plugins in plugins/ are trusted Python code. The event SDK is documented
in graphics-and-plugins.md; callbacks are queued, timed and audited, not sandboxed.
Alembic 0003 adds chapters, segments, collections, documents, graphics instances,
event audits and observed playback checkpoints. Keep media scanning read-only;
write derived application metadata to SQLite, never to source media.
