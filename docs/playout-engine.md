# Playout engine

`PlayoutEngine` defines connect/disconnect, load/cue, preload, play/next, pause,
resume, stop, seek, observation, recovery and capability errors for segments and
graphics. The controller owns the sequential rundown; the adapter owns protocol
commands. The simulator exists only in tests and produces no broadcast output.

The CasparCG adapter uses documented commands: VERSION, INFO, LOAD, LOADBG CUT 0
AUTO, PLAY, PAUSE, RESUME, CLEAR and CALL SEEK. See the
[official AMCP reference](https://casparcg.com/docs/wiki/protocols/amcp-protocol)
and [current server implementation](https://github.com/CasparCG/server/blob/master/src/protocol/amcp/AMCPCommandsImpl.cpp).
Only cut transitions are enabled in Phase 1. Seek is an integer producer frame
command, not a verified frame-exact segment boundary operation.

Response handling covers 200 multiline data, 201 single-line or formatted XML,
202 acknowledgements, 400 command echo and error status codes. Each command has a
three-second timeout. Transport failure closes the socket. Mutations are never
retried automatically because their result may be unknown. Reconnection uses a
1–30 second backoff, while operator controls can cancel the connection request.

INFO supports the legacy `foreground/producer` file-frame fields and newer
`layer_N/foreground/file/time` seconds fields. Unknown producers or timing schemas
raise an explicit error. Status is polled every 250 ms; WebSocket snapshots are
sent every 500 ms. As-run timestamps are controller observations/acknowledgements,
not measured output timestamps. AUTO is server-controlled; browser clocks do not
trigger transitions. Polling cannot reliably distinguish adjacent identical files
or very short clips, so Phase 1 rejects them.

At most one successor is preloaded. On its observed appearance, the controller
records completion of the previous item and queues the next successor. Media must
be inside the configured root and accessible both locally and to CasparCG. No
extension stripping, transcoding, renaming or source edits occur.

On failure automation is suspended, an error is visible, and files are not skipped.
Already queued content can continue in CasparCG after loss of control. Reconnection
observes but never replays/rearms automatically. Restart launches/connects the
managed server and requires operator intervention to start media. External-server
mode begins disconnected. Current sessions interrupted by restart retain an
unknown end time and `interrupted_by_restart` outcome. Use Stop to clear stale
producer state before selecting a new rundown position.

The official bundled 2.5.1 build now passes a real AMCP handshake and a two-file
AUTO producer-switch test with synthetic MP4s. Verification still required: actual
screen/device quality, EOF handling, long-running reconnection and transition
continuity. Tests do not certify frame-perfect or 24/7 operation.
