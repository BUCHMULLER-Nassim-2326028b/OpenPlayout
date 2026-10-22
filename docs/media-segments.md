# Chapters and virtual segments

Open **Chapters & segments**, select an indexed video and create a browser preview
session. The source preview supports byte ranges with an HttpOnly, asset-scoped,
15-minute cookie; the API token is never included in a media URL. Unsupported
browser codecs may fail to preview even when CasparCG can play the file.

Mark IN/OUT from the playhead or enter exact integer frame numbers. Boundaries
use the configured channel timebase, IN inclusive and OUT exclusive. Save chapters,
edit their notes/triggers, delete them, or import embedded FFprobe chapters.
Import rounds to the nearest channel frame and preserves the original metadata.
Chapters and segments live in SQLite. No remux, conversion, splitting or source writes occur.

Save virtual segments, then build a Studio sequence: first segment, another video
or break template, next segment. **Play on program** directly replaces the program
producer; the browser preview does not affect output. Disarm schedules before
manual program playback. Segments require representable output-frame boundaries;
playout plans require each item to last at least two seconds for reliable observation.

The CasparCG adapter sends native SEEK/LENGTH with LOAD, PLAY or LOADBG AUTO.
CasparCG 2.5.1 defaults IN to SEEK. INFO file/clip identifies clip IN and length,
allowing different segments of one source to be distinguished. Source position
remains absolute. Manual seeks cannot escape the active segment. Dissolves use
native MIX with an explicit frame count; cuts use CUT 0.

Real acceptance used a 10-second red/green source: frames 0–75, a three-second blue
bumper, then frames 75–150. INFO confirmed IN=3 seconds and length=3 on the resumed
segment. Output PNGs showed red before the break and green after it, with logo and
updated NEXT composited. SHA-256 confirmed the source was unchanged. This verifies
the tested path; frame-perfect boundaries, audio continuity and physical broadcast
hardware still need measurement on the target setup.
