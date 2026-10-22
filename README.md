# OpenPlayout

Local broadcast automation foundation for Windows 11. FastAPI + SQLite control a
real CasparCG AMCP connection; React provides a persistent media library and
sequential rundown, hard/soft schedules, chapters and virtual segments, rules,
breaks, nested templates, HTML graphics, trusted plugins and recovery controls.
Segment/break/resume and logo/NOW-NEXT compositing have been verified on real CasparCG.
Physical output quality remains an operator check. This is not a finished 24/7 product.

## Start on this workspace

Python 3.12 and backend dependencies are installed locally under `.tools`.
The frontend production build and official CasparCG 2.5.1 Windows runtime are
present. CasparCG and its bundled FFprobe stay inside this project. From the repository root:

```powershell
.\scripts\start.ps1
```

Open http://127.0.0.1:8000. In another terminal, obtain the local token and paste it
into the unlock form (do not share or commit it):

```powershell
Get-Content .\data\api-token
```

If PowerShell blocks scripts, invoke them for this process only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

## Fresh installation

Install Python 3.12+ and Node.js 22.12+ (or current LTS). No Docker or cloud
service is required. Initial dependency installation needs internet access.

```powershell
.\scripts\setup.ps1 -Python 'C:\Path\To\Python312\python.exe'
.\scripts\start.ps1
```

`setup.ps1` creates `.venv312`, installs backend/test dependencies, uses `npm ci`,
builds the UI, copies `.env.example` only if `.env` does not exist, and installs the
official CasparCG archive locally with a pinned SHA-256 check. No system PATH,
Windows service, login startup task, or user media is changed. The first download
is approximately 296 MB (713 MiB extracted). Use `-SkipCasparCG` to skip download.

## Connect real output

1. Run `scripts/start.ps1`. The backend starts the bundled CasparCG server hidden
   (its console), opens a windowed **OpenPlayout - Program output** screen with
   system audio, waits for AMCP readiness, and connects automatically. Default
   output is 1920×1080 at 25 fps. No media starts merely by opening the app.
2. The local `media/` directory is created as the default CasparCG media root.
   Bundled FFprobe is detected automatically when no custom executable is set.
3. Unlock the UI. To edit settings, disconnect the controller in **Control room**.
   You can change the media root, frame rate, output size, AMCP port and layer.
   Restart OpenPlayout to apply settings to its managed CasparCG process.
4. Add a directory under the media root, **Save settings**, then **Scan**.
5. In **Media library**, add two different finite MP4s, each at least two seconds,
   to the rundown. In **Control room**, connect and click **Play rundown**.
6. Observe the actual CasparCG output. The browser deliberately displays no fake
   program video. Check the server position and the automatic change to item 2.
7. Stop, restart OpenPlayout, and verify the library and rundown remain.

Use only one controller for the configured program layer. **Cue**, **Play rundown**,
**Next**, and **Stop** affect that output layer. Cue replaces the current foreground
with a paused first frame. Play rundown starts at the first item; Resume continues
the current cued/paused item. Stop clears foreground and background. Disconnect
leaves server playback running and disarms local automation. Application shutdown
closes a CasparCG process started by OpenPlayout; a pre-existing external server
is left running. See [runtime lifecycle and configuration](docs/casparcg-runtime.md).

## Current scope

- Persistent channel settings, media assets/locations, ordered rundown and as-run
  records; versioned Alembic schema and automatic settings backups.
- Read-only recursive indexing, duration as rational metadata, codecs, dimensions,
  audio, embedded chapters, subtitle metadata, possible VFR warning and missing files.
- Search/folder filter, metadata inspector, add/remove and pointer/keyboard reorder.
- Real AMCP commands, timeouts, serialized responses, reconnection with backoff,
  LOADBG AUTO preloading, pause/resume, cue, skip, stop and API seek.
- Authenticated REST and WebSocket status. Localhost binding; token stays in browser
  session storage. JSON diagnostics rotate at 5 MB, retaining three backups.

Open **Schedule** to create a daily timed plan, inspect conflicts, import/export
CSV or JSON and explicitly arm playback. Opening/editing never arms it. Hard
events reserve fixed times; soft events move within a configured window. See the
[scheduler guide](docs/scheduler.md) for the software dispatch tolerance and limits.

Open **Chapters & segments** to edit application chapter metadata and define IN/OUT
without modifying the original. In **Automation studio**, build collections, break
templates and rules, preview an exact fit against a deadline, then create a timed
schedule or run a native sequence. Saved sequences can nest media, segments,
breaks and graphics actions. Add a logo and NOW/NEXT template under Graphics,
create instances on different layers above program, and show them on output.
**Operations** exposes recovery policies, emergency sequences, backups and diagnostics.
See [chapters](docs/media-segments.md), [automation](docs/automation.md) and
[graphics and plugin SDK](docs/graphics-and-plugins.md).

Limits: no recurring/weekly schedule generation, remote relay or video return yet.
Additional channels can store configurations; only main has an output worker. Images/audio can
be indexed but cannot enter automatic playback. Indexing is explicit via Scan;
filesystem watchers are deferred. Editing the rundown requires Stop. Adjacent
identical clips and clips shorter than two seconds are rejected. Output compatibility,
INFO variants, end-of-file behavior and gap-free transitions require testing on the
chosen CasparCG build. There is no frame-accuracy certification.

Database restoration is offline and preserves the replaced database:

```powershell
.\scripts\restore-backup.ps1 -Archive 'C:\Backups\openplayout.zip' -ConfirmStopped
```

The backup contains SQLite metadata, not source media, the API token or plugin
code. Keep original media paths accessible or revise/re-index after moving a setup.

Real phases 3–6 acceptance (isolated generated media, real CEF graphics, Chrome):

```powershell
$env:OPENPLAYOUT_TEST_STUDIO='1'
.tools\backend-venv\Scripts\python.exe -m pytest backend/tests/test_studio_live.py -q -s -p no:cacheprovider
Remove-Item Env:OPENPLAYOUT_TEST_STUDIO
```

## Development and tests

```powershell
.\scripts\start.ps1 -Dev
# In a second terminal:
Set-Location apps\web
npm.cmd run dev
# UI: http://127.0.0.1:5173
```

From the repository root:

```powershell
.\scripts\test.ps1
# Optional read-only handshake against a running CasparCG server:
$env:OPENPLAYOUT_TEST_CASPAR = '1'
.\.tools\backend-venv\Scripts\python.exe -m pytest backend\tests -m caspar -q
# Live synthetic red -> blue AUTO test on dedicated layer 9900 (app running):
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-casparcg.ps1
# Full isolated app acceptance (generated media, fresh data, private AMCP port):
$env:OPENPLAYOUT_TEST_FULL_APP = '1'
.\.tools\backend-venv\Scripts\python.exe -m pytest backend\tests\test_full_live.py -q
```

On a fresh installation replace `.tools\backend-venv` with `.venv312` in direct
Python commands. Simulated engine and loopback protocol tests do not demonstrate
real broadcast performance. See [roadmap](docs/roadmap.md),
[architecture](docs/architecture.md), [development](docs/development.md),
[playout engine](docs/playout-engine.md), [API](docs/api.md), and
[troubleshooting](docs/troubleshooting.md).
