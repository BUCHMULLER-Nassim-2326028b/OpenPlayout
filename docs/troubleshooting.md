# Troubleshooting

**Python 3.10 found:** install Python 3.12+ or pass its absolute executable path to
`scripts/setup.ps1 -Python`. This workspace also contains a private Python 3.12 in
`.tools/python`; setup detects it. Nothing requires a global PATH change.

**FFprobe not found:** run `scripts/install-casparcg.ps1`; the official archive
includes FFprobe and it is selected automatically when the default tool is absent.
A custom executable path can still be set in Settings. FFmpeg is not invoked for indexing. Unsupported files
and probe errors remain visible in the library; original files are unchanged.

**No files indexed:** add the directory and save before scanning. Supported
extensions are explicitly listed in `backend/app/media.py`. Symlinks/junctions
are not intentionally traversed; inaccessible paths appear as scan errors.
The library displays up to 2,000 search matches. Search to narrow larger libraries.

**Cannot connect:** managed startup waits for the local server and connects automatically.
Inspect `data/casparcg/console.log` if startup fails. For external servers, verify AMCP is configured on the chosen
host/port. Use `Test-NetConnection 127.0.0.1 -Port 5250`. Cancel retries using
**Disconnect / cancel retry** before changing Settings.

**Media outside root / file not found:** OpenPlayout's media root must match the
server's media-path, including subfolders. Both processes must be able to read
the source. Do not move files to satisfy the software without deciding to do so.
Correct configuration or re-index their actual location instead.

**Unsupported INFO response:** stop automation and inspect the server version and
INFO XML. Do not infer live output from stale UI metadata. The bundled 2.5.1 build
has now been tested with real VERSION/INFO and synthetic two-file AUTO playback.

**Black output despite commands succeeding:** configure a real screen/device
consumer and matching video mode in CasparCG, confirm the correct server channel
and layer, and check server logs. The control UI has no video return and cannot
prove that a physical consumer is functioning.

**Lost connection / failed preload:** automation is suspended; already loaded
server content may continue. No automatic skip or emergency filler occurs. Inspect
the output, reconnect, Stop to clear the layer, then Cue/Resume or select playback.
Stop intentionally clears foreground and background of the program layer only.

**Restart:** library/settings/rundown persist. The bundled server and control
connection start automatically, while media playback is never restarted
automatically. Unfinished history records are marked interrupted with unknown end
times. This is a manual playback recovery policy, not schedule-position recovery.
Graceful application shutdown closes its owned server. See [runtime lifecycle](casparcg-runtime.md).

**401 / WebSocket rejected:** use the token in `data/api-token`, the root `.env`
override if configured, and an allowed localhost Origin. The token is generated at
first startup. It is deliberately not included in static JavaScript or URLs.

**Diagnostics:** `data/openplayout.log` contains rotating JSON records. Uvicorn
also prints startup/request errors in the terminal. Settings backups are under
`data/backups`; restore through the settings API after reviewing their contents.
For a full backup, stop OpenPlayout and copy the entire data directory. Never copy
only the SQLite main file from a running WAL database.
