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
all clients still need the token. There is no public file serving, arbitrary AMCP
execution or remote graphics bridge.
