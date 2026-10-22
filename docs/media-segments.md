# Chapters and segments — future milestone

Phase 1 preserves FFprobe chapter metadata and subtitle stream details in SQLite
and displays them in the metadata inspector. It does not write chapters into media,
provide chapter editing, or claim precise segment playout.

Phase 3 will add editable chapters and virtual segments with inclusive IN and
exclusive OUT, integer boundaries and an explicit rational timebase. A program
split around a break remains one source file. Boundary precision must be tested
against the configured backend before segment playback can be enabled.
