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
server content may continue. The default policy suspends; only an explicitly
configured emergency sequence may take over. Inspect
the output, reconnect, Stop to clear the layer, then Cue/Resume or select playback.
Stop intentionally clears foreground and background of the program layer only.

**Restart:** library/settings/rundown persist. The bundled server and control
connection start automatically. Manual recovery is the default; Operations can
explicitly enable expected-position recovery on idle output. Unfinished history
records are marked interrupted with unknown end times. Scheduled events are not
blindly replayed. A past OUT or remainder below two seconds is not resumed.
Graceful application shutdown closes its owned server. See [runtime lifecycle](casparcg-runtime.md).

**401 / WebSocket rejected:** use the token in `data/api-token`, the root `.env`
override if configured, and an allowed localhost Origin. The token is generated at
first startup. It is deliberately not included in static JavaScript or URLs.

**Diagnostics:** `data/openplayout.log` contains rotating JSON records. Uvicorn
also prints startup/request errors in the terminal. Settings backups are under
`data/backups`; restore through the settings API after reviewing their contents.
For a full backup, stop OpenPlayout and copy the entire data directory. Never copy
only the SQLite main file from a running WAL database.

**Invisible HTML graphics:** verify a layer above program, a reachable
OPENPLAYOUT_GRAPHICS_BASE_URL, and instance error state. Show acknowledges AMCP;
check actual output separately. Remote pages must acknowledge context messages
or use the explicitly chosen freeze policy. For custom assets, place HTML in
data/graphics. See graphics-and-plugins.md.

**No exact rule/break fit:** inspect cooldown/history, required stages, group sizes,
minimum/maximum duration and available filler. The engine does not truncate media
or omit required stages. Reduce collection size if the bounded search limit is hit.

**Restore fails:** stop all OpenPlayout instances and database viewers; use the
generated ZIP with scripts/restore-backup.ps1 -Archive PATH -ConfirmStopped. The
tool refuses unexpected ZIP members, failed integrity checks and live WAL/SHM
sidecars. It retains the previous main database under before-restore-*.sqlite.
