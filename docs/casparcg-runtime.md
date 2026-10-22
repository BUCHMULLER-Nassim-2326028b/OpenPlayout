# Bundled CasparCG and automatic startup

OpenPlayout includes the official Windows CasparCG **2.5.1 Stable** distribution
under `.tools/casparcg/2.5.1`. The first setup/start downloads it if missing. The
version and archive SHA-256 are pinned in `scripts/install-casparcg.ps1`; repeated
installation reuses a completed installation. A partial/custom directory is never
overwritten. FFprobe and FFmpeg are included in the upstream archive. No system
PATH, Windows service, registry startup entry or automatic media conversion is used.

Provenance: [official release](https://github.com/CasparCG/server/releases/tag/v2.5.1-stable),
[matching source](https://github.com/CasparCG/server/tree/v2.5.1-stable).
Archive SHA-256: `c0756f53f49908fba94f17a43b83d45fd275201e24ab1676530d7bb26832efc6`.
The complete upstream archive, LICENSE and notices are preserved; installation
metadata is recorded in `.tools/casparcg/2.5.1/openplayout-install.json`. Binaries
and media are excluded from Git. Use the installer when copying the source project.

## Lifecycle

`scripts/start.ps1` starts the API. During backend startup, the runtime manager:

1. Uses the persisted channel's AMCP host/port and media root.
2. Reuses an already responding AMCP server without spawning a duplicate.
3. Otherwise starts the local bundled executable with a generated configuration,
   no console window and no shell. A remote host is never spawned locally.
4. Waits up to 45 seconds for an AMCP VERSION response, then connects the controller.
5. Starts no media automatically. The existing manual playback recovery policy remains.

A generated `data/casparcg/openplayout.config` references the selected media root,
frame rate and resolution, a windowed screen output and system audio. Rational
frame rates receive an explicit audio cadence. The original bundled config is
not edited. Saved output changes apply at the next application restart.

The only migrated path is the untouched old `C:/CasparCG/media` placeholder when
the library and configured directory list are both empty. It becomes the local
`media/` directory. Custom roots and indexed file locations are preserved. A
settings backup is written before adopting bundled defaults. FFprobe falls back
to the bundled executable only when the default `ffprobe` cannot be found in PATH.

Closing the application gracefully closes its owned CasparCG process, first via
its private stdin, then terminating that exact child if shutdown times out. An
external/reused server is never stopped or sent KILL. An abrupt parent crash can
leave the server running; the next launch reuses it. No automatic server restart
or replay after a server crash is implemented. A crash is reported in status.
Development reload also restarts an owned server; use external mode when preserving
continuous output through source reloads matters.

## Configuration

Root `.env` supports:

```dotenv
OPENPLAYOUT_CASPAR_AUTOSTART=true
OPENPLAYOUT_CASPAR_SERVER_DIR=./.tools/casparcg/2.5.1
OPENPLAYOUT_CASPAR_START_TIMEOUT=45
OPENPLAYOUT_CASPAR_SCREEN=true
OPENPLAYOUT_CASPAR_MEDIA_ROOT=./media
```

`scripts/start.ps1 -NoCasparCG` disables managed startup for that invocation. The
controller remains manual and can connect to a separately started server.
`OPENPLAYOUT_CASPAR_SCREEN=false` omits the screen/audio consumers for headless use;
this is not proof of physical output. No Windows login/boot task is installed:
automatic startup here means **when OpenPlayout starts**.

The API itself stays on localhost. The upstream CasparCG TCP listener binds all
IPv4 interfaces and has no bearer authentication; do not grant inbound network
access to it in Windows Firewall. OpenPlayout adds no firewall allow rule and
does not claim the upstream AMCP listener is loopback-only. See the upstream
[controller implementation](https://github.com/CasparCG/server/blob/v2.5.1-stable/src/shell/server.cpp).

## Diagnostics and verification

Startup failure reports the local console log path. Inspect
`data/casparcg/console.log` and `data/casparcg/log` for missing Visual C++ runtime,
GPU/OpenGL or consumer initialization errors. The API status includes runtime
state, ownership, PID and version; the UI shows whether it started with the app.
Changing an existing custom configuration may require editing settings before
switching back to managed mode.

Checked on this machine: official archive checksum, executable startup, actual
AMCP VERSION/INFO, screen/audio consumer initialization, bundled FFprobe metadata,
and two synthetic MP4s switching through real LOADBG AUTO on test layer 9900.
The live test is opt-in:

```powershell
# Start OpenPlayout in another terminal first.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-casparcg.ps1
```

It generates its own red/blue media under `.tools`, never overwrites source media,
and clears only test layer 9900 afterwards. It verifies server observations, not
physical screen quality, frame accuracy or gap-free output.
