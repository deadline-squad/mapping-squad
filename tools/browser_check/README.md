# SquadCalc in a real browser

Both scripts drive the Deadline SquadCalc in Chromium through Playwright. They need `playwright-core`
and a Chromium build; on tk104 both are in the npx and Playwright caches:

```sh
export PLAYWRIGHT_CORE=~/.npm/_npx/9833c18b2d85bc59/node_modules/playwright-core
export CHROME=~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome
```

`<site URL>` is a served build with the precise heightmaps under `/heightmaps/`: the live site, or
Caddy over a local `npm run build` (one `handle /heightmaps/*` rooted at `~/apps/squadcalc/dist`, the
rest at the build's `dist`).

## browser_check.mjs: pass/fail checks

```sh
node browser_check.mjs <site URL> [--maps] [--ballistics <weapons.json>]
```

Console and requests clean, precise heightmaps (`--maps`: on every map; a dropped heightmap.png or
meta.json request is tried again, a network that keeps dropping it gives the 8-bit heightmap with a
warning, a 404 falls back at once), regression checks for
the bugs fixed in 45.5.1 and after the walkthrough review, the `window.squadBallistics` bridge the
Squad Ballistics app reads (targets, weapon, weapon selection; `--ballistics`: every weapon of
Squad Ballistics' weapons.json aimed with the overlay is selected by its name and reported back, the
hold-laid ones show a hold time) and the absence of the removed device
link (settings controls, relay requests, leftover localStorage keys). Exits with 1 on any failure.

## perf_trace.mjs, cpu_profile.mjs: main-thread cost

```sh
node perf_trace.mjs <site URL> [--label <text>] [--scenarios coverage,zones,drag] [--map <option value>]
node cpu_profile.mjs <site URL> <weapon name in weapons.js>
```

`perf_trace.mjs` takes a Chromium trace of the fire coverage of seven weapons (from the switch on to the image), of
the damage zones of ten targets redrawn, of a scripted drag of a target (120 moves, 8 ms apart) and of four map
switches (`--scenarios mapswitch`), and prints for each the wall time and the main-thread tasks: the longest one, how
many are over 16 and 50 ms, and the busy total. Run it on two builds served side by side to compare them
(`TOP_EVENTS=1`, `LONG_TASKS=1` and `FRAME_LOG=1` print more). The wall time of a coverage run includes a
fixed 0.3 s wait. `cpu_profile.mjs` samples the page's V8 profiler during one coverage (inclusive and self time;
readable on an unminified build). A local build is served by any static server that answers `/heightmaps/` from
`~/apps/squadcalc/dist/heightmaps`.

## sb_bridge_probe.mjs: Squad Ballistics' own page scripts

```sh
python3 -c "import json, maplink; json.dump({'bridge': maplink.bridge_script(None), 'watch': maplink.WATCH_SCRIPT}, open('/tmp/sb_scripts.json', 'w'))"   # in a Squad Ballistics checkout
node sb_bridge_probe.mjs <site URL> /tmp/sb_scripts.json [--clicks 12]
```

Runs SB's poll script and watcher against the page and times a double-click on the map to the poll that returns
the new target, the way SB's map host does (it is not a real SB window).

## walkthrough.mjs: recorded click-through

```sh
node walkthrough.mjs <site URL> [--out <dir>] [--only desktop|mobile]
```

Clicks through every user-facing feature and records it for a human to follow: a drawn cursor, a
yellow ring on every click or tap, the pressed keys at the bottom right and a caption per step.

* Desktop (`desktop.webm`, 1920x1080): map selector (four maps, Yehorivka as the large one), game
  layer, wheel zoom, map styles and HD images; weapon placement, the weapon selector with its groups,
  targets, hover, dragging targets and the weapon, the trajectory and obstacle view, the weapon card
  (extra height); every weapon kind (mortar, Hell Cannon, UB-32, BM-21, M1064 with its second shell,
  AGS-17 hold time, an RPG-7 from the Squad Ballistics direct-fire group); fire correction (Ctrl +
  double-click a burst, right-click removes it); the right-click context menu; fire coverage, undo,
  heatmap, focus mode, download, share; the shortcuts M, Enter, Ctrl+Z, Ctrl+M, Delete; upload of
  the saved file; faction and server dialogs; every checkbox, map-button toggle and slider of the
  settings, the popup display options shown on the map, shortcut rebinding, three languages and the
  changelog.
* Phone (`mobile.webm`, a 360x640 screen at 2x, 720x1280): taps for the weapon and targets, the
  trajectory, the weapon and map selectors, the settings.

Also written to `<dir>` (default `~/videos/squadcalc`): a screenshot per notable step in `frames/`,
and `walkthrough-log.json` with the steps and every console error or warning, page error, failed
request, coarse heightmap and unscripted outcome, each tagged with its step. Exits with 1 when there
was any.

Not clicked: the collaborative session (it would create a session on the upstream squadcalc.app
server) and the external links. The upstream statistics endpoints (`/post/*`) are answered locally.

Every request of the page is made by Playwright and handed to it: Chromium aborts requests in flight
with `ERR_NETWORK_CHANGED` whenever a network interface appears or disappears, which on a Docker
host (CI containers starting and stopping) happens every few seconds.

To look at a frame of a video, extract it with Playwright's ffmpeg (it decodes VP8 and writes PNG):

```sh
~/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux -ss 95 -i desktop.webm -frames:v 1 -c:v png -f image2 frame.png
```
