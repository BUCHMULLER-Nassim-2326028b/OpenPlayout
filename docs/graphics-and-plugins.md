# HTML graphics and trusted plugin SDK

Create a graphics template in Studio: builtin logo/lower_third/now_next/countdown,
sandboxed custom HTML, a relative HTML file under data/graphics, or a credential-free
HTTPS remote overlay. Theme JSON accepts hex accent/background/color. Instance
variables provide text/title/subtitle or a display countdown deadline. Create
instances on distinct layers above program, then Show on output. Hide clears only
that layer. An instance cannot replace another active instance on its layer.
The UI state records AMCP command acknowledgement, not pixel-level observation.

HTML producers load a bridge using OPENPLAYOUT_GRAPHICS_BASE_URL (default local
port 8000). For a remote engine, provide an address reachable from that engine and
configure networking explicitly. The instance key grants read-only rendering and
context access. It is not the API bearer token. Private API writes are unavailable
to the bridge. Treat capability URLs as display links, not public control links.

The bridge polls context every 250 ms: channel, now title/remaining seconds, next
title, playback_state and variables. NOW/NEXT updates after actual controller
observation. Countdown is a display estimate; the browser is not a broadcast clock.
Builtins use textContent. Custom HTML runs in a sandbox with scripts and without
same-origin privilege. Local files must resolve under data/graphics. Remote HTTPS
iframes receive postMessage context to their exact origin; acknowledge updates:

```javascript
addEventListener('message', event => {
  if (event.source !== parent || event.data?.type !== 'openplayout.context') return;
  const context = event.data.context;
  document.querySelector('#next').textContent = context.next.title;
  event.source.postMessage({type:'openplayout.ack'}, event.origin);
});
```

Use hide or freeze when context is unavailable. Remote overlays without acknowledgements
hide after five seconds by default. These are trusted user-selected pages; there
is no arbitrary remote downloader or credentials injected into external URLs.

Automation templates bind documented hooks to graphics.show/hide/variables
actions with existing instance IDs. Chapter metadata can target automation IDs.
Events include media indexing/load/cue/start/end, playlist generation, schedule
creation, segment start, chapter reached, break requested/start/end, program change,
graphics requests, playback errors and engine disconnection. Chapter events fire
once per item after an observed playhead crosses the marker; they are polled, not
frame-certified.

Python SDK: place a module under plugins/ defining register(events). Enable only
explicit filenames via OPENPLAYOUT_TRUSTED_PLUGINS='["example_logger.py"]'.
See plugins/example_logger.py. `events.subscribe(hook, callback)` accepts synchronous
or async callbacks `(hook, payload)`; `*` subscribes to every event. `events.publish`
queues custom events; built-in `events.action` accepts the documented graphics
actions. Payloads include the active item and observation where relevant.

Queue capacity is 512, plugin callback timeout two seconds, built-in action timeout
five seconds. Sync callbacks run in worker threads; a timeout cannot kill arbitrary
Python code already running in a thread. Plugins are trusted code with the process's
filesystem/network privileges, not a security sandbox. No plugin upload/enable API
exists. Exceptions are audited and counted independently of the program monitor.
Diagnostics report plugin load errors, dropped events, queue size and action errors.
