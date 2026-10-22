# API

OpenAPI: http://127.0.0.1:8000/docs. Protected requests require
`Authorization: Bearer <local token>`. Use **Authorize** in Swagger or the header
in your HTTP tooling; the token is not a URL parameter. Health and static
UI are public; media, settings and all control/state endpoints require the token.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Process health and version |
| GET | `/api/status` | Observed playout state, error and scan status |
| GET/PUT | `/api/settings` | Persist channel/engine/directories; disconnect first |
| POST | `/api/media/scan` | `{"directory":"C:/CasparCG/media"}`; must be configured |
| GET | `/api/media?q=clip&folder=shows&limit=500` | Search title, filter relative path |
| GET | `/api/playlists/main` | Ordered items with media metadata |
| POST | `/api/playlists/main/items` | `{"media_id":"..."}` |
| PUT | `/api/playlists/main/order` | `{"item_ids":["...","..."]}`; exact permutation |
| DELETE | `/api/playlists/main/items/{id}` | Remove reference only |
| POST | `/api/playout` | `{"action":"connect"}`; see actions below |
| GET | `/api/history` | Latest 200 as-run records |
| GET/POST | `/api/schedules` | List/create one-time schedules |
| GET | `/api/schedules/{id}` | Source events, dry-run plan, conflicts and execution ledger |
| POST | `/api/schedules/{id}/events` | Add media, requested UTC start, hard/soft and delay |
| PUT/DELETE | `/api/schedules/{id}/events/{event_id}` | Edit/remove an unexecuted draft event |
| POST | `/api/schedules/{id}/arm` | Validate and explicitly activate future events |
| POST | `/api/schedules/{id}/disarm` | Cancel waiting events; current media continues |
| POST | `/api/schedules/resolve-time` | Resolve local clock + IANA zone, rejecting DST ambiguity |
| GET | `/api/schedules/day?date=2026-10-25&timezone=Europe/Paris` | Actual local-day bounds |
| GET | `/api/schedules/{id}/export?format=json` | JSON/CSV content and filename |
| POST | `/api/schedules/import` | Preview; commit:true creates a new schedule |

Actions: connect, disconnect, play, cue, next, pause, resume, stop, seek.
Play/cue accept an optional `item_id`; omitted play begins at rundown item 1.
Seek requires `frame` (nonnegative integer). Invalid commands are rejected.
Errors use FastAPI's `detail` format. Queue edits during playback return 409.

Scan runs in a worker and holds the HTTP request until finished. Clients can poll
status or use WebSockets while scanning. Missing executable returns 503. Individual
file failures appear in the scan report and the media error field, not as skipped
playout events. Re-scan detects missing paths and re-probes changed/failed files.

WebSocket `/ws`: use an allowed Origin. Send `{"token":"..."}` within five seconds
after opening. The server returns `{"type":"status","data":{...}}` snapshots
twice per second. `observation` contains actual producer filename, state, seconds
position/duration and connection; unknown values are null. The current rundown
reference can be stale during a disconnection and must not be treated as live
output evidence. `connection_requested` indicates reconnect monitoring is enabled.
`runtime` reports managed-server state, ownership, PID, version and process errors.
The server and connection start with the app; media playback still requires an
operator action. Owned server configuration changes apply after an app restart.
`scheduler` reports the armed schedule, next event, active execution, error and
dispatch tolerance. Stop/disconnect disarm it; other manual controls return 409
while armed. Execution preserves the operator rundown. See [scheduler policies](scheduler.md).

Services bind to localhost by default. To deliberately deploy on a network, use
an authenticated TLS reverse proxy and an explicit `OPENPLAYOUT_ORIGINS` allowlist;
control clients still need the token. Graphics render/context routes use read-only
instance capabilities. Source preview uses an authenticated asset-scoped cookie.
There is no arbitrary path/file read or arbitrary AMCP execution endpoint.

## Chapters, automation and operations

All routes below require the bearer token except the two scoped display routes.
Schemas and request examples are available in the running `/docs` OpenAPI UI.

| Method | Route | Purpose |
|---|---|---|
| GET/POST | `/api/media/{id}/chapters` | Embedded/custom chapters and virtual segments; create chapter |
| PUT/DELETE | `/api/chapters/{id}` | Edit/delete chapter metadata |
| POST | `/api/media/{id}/chapters/import` | Import embedded chapters into application metadata |
| GET | `/api/segments` | List virtual segments |
| POST | `/api/media/{id}/segments` | Save integer-frame IN/OUT |
| POST | `/api/segments/{id}/preview` | Play segment on actual program output |
| POST | `/api/media/{id}/preview-session` | Issue asset-scoped preview cookie |
| GET | `/api/media/{id}/content` | Range-capable indexed source; scoped cookie required |
| GET/POST | `/api/collections` | Ordered media or smart tag query; optional per-ID weights 1–1000 |
| PUT | `/api/media/{id}/tags` | Application title/tags |
| GET/POST | `/api/resources` | Versioned rule/break/sequence/graphics/automation documents |
| PUT/DELETE | `/api/resources/{id}` | Edit/delete unused templates |
| GET | `/api/resources/{id}/export` | Portable JSON document |
| POST | `/api/resources/import` | Import document as new ID |
| POST | `/api/resources/{id}/preview` | Expand, fit and preflight without changing output |
| POST | `/api/resources/{id}/run` | Explicit program execution, optional preview signature |
| POST | `/api/resources/{id}/schedule` | Validate and create a disarmed timed schedule |
| GET/POST | `/api/graphics` | List/create graphics instances |
| POST | `/api/graphics/{id}` | show/hide/variables, isolated from program connection |
| GET | `/api/graphics/{id}/preview` | Read-only display URL |
| GET | `/graphics/render/{id}` and `/context` | HTML/context with instance key, no control privilege |
| GET | `/api/automation/events`, `/api/diagnostics` | Audit and operator diagnostics |
| GET/PUT | `/api/recovery` | Checkpoint preview and explicit policies |
| POST | `/api/recovery/resume`, `/api/recovery/emergency` | Recover idle output / take emergency sequence |
| POST | `/api/backups` | Create consistent SQLite ZIP |
| GET | `/api/backups/{id}` | Authenticated backup download |
| GET | `/api/configuration/export` | Portable channel/recovery settings, no API token |
| POST | `/api/configuration/import` | Validate/replace settings with confirm_replace_settings=true |
| GET/POST | `/api/channels` | Main and inactive channel configurations; no second worker |
