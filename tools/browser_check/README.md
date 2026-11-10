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
hold-laid ones show a hold time), the map's spinner after layer changes (one superseded by another, a tile
layer replaced while it loaded, a map image that failed to load, a layer with no tile in view: the spinner
stops and one map image is left), the circles a gameplay layer decides (needs the layer API: the exclusion
circle of FOB markers is the map's 400 m on Al Basrah without a layer, 300 m once Al Basrah RAAS v3 has loaded,
also for a marker placed before it, 400 m after RAAS v1 replaced it and after the layer was cleared; on Goose
Bay AAS v1 the first main's protection zone, negative in the layer data, is drawn with 236 m and 386 m and the
second main's with 150 m and 300 m; the capsule zone of Kohat TC v1 is its footprint, 1199 m by 400 m, and the
three boxes of Fallujah Invasion v2's zone of three each have the game's size and turn, all without a dashed
no-deploy outline; the point of 0.44 m of Sumari Invasion v1 has its no-deploy box of 50.44 m; the settings that
restyle a layer switch without an error while none is loaded) and the absence of the removed device
link (settings controls, relay requests, leftover localStorage keys). The checks run in groups, each on a
page of its own. A page that does not open (the page itself, its heightmap or its map image, each given
120 s) is one FAIL under the group's name: it says which of the three failed and why, with the spinner's count
and the requests left without an answer. A step that throws later is one FAIL with its message. The other
groups still run. The last line gives the totals (`all N browser checks passed` or `F of N browser checks
failed`). Exits with 1 on any failure.

Chromium fails every request in flight with `net::ERR_NETWORK_CHANGED` when an interface of the host comes or
goes, as when Docker starts or stops a container. The script counts those requests and names them above the
totals: a FAIL that lists the error, or lost a request to it, says nothing about the site. On a host where
containers start all the time, run the check where the network does not change (a container has a network
namespace of its own).

## grid_check.mjs: the grid, its keypad text and entry as the game's

```sh
node grid_check.mjs <site URL>
```

Skorpo without a layer: the grid starts 9.5 m east of the map image (`SDK_data.minimap.game`); Chora with the layer
`Chora_Skirmish_v1` (needs the layer API): 1007 m east and 1222 m south of it, the corner of the layer's own minimap; clearing
the layer returns it to the map's corner and the map's letters and numbers. On Skorpo, Chora Skirmish v1 and Al Basrah the
check compares the page with the game's grid (Squad server build 26005357): the keypad text 1 m inside the corners and at
the middle and the box under the cursor at zoom 4 (`C03-3-7` for the game's `C3 - 3 - 7`), no keypad outside the grid, the
game's text typed with its spaces, without them and padded landing in the 33.3 m square it names, the letters and numbers
with the last one at the middle of the strip left after the last whole keypad, along the grid's north and west edges, and no
line or label outside the grid. Exits with 1 on any failure.

## coords_check.mjs: the bearing as the game's compass, circles in metres

```sh
node coords_check.mjs <site URL> [--shots <dir>]
```

On Skorpo (6849 m by 6869 m, the one map with corners far from square). The bearing reads as the game's HUD compass reads
it (native `USQCompassMK2`, Squad server build 26005357: cut to a whole degree, three digits, north as 360), with the tenth
after it: a target 800 m away at 45.96 degrees shows 045.9 in its popup, its summary and the target dialog, one due north
360.0, and the keypad panel 026.6 from B03-5-5 to C01-5-5. The help of the bearing (panel, target dialog) says the compass
cuts off the tenth; the help of the distance in the target dialog says the game's marker distance is slant and cut to 50 m
steps. The Mortar's and UB-32's range rings, the FOB marker's 150 m and 400 m circles and a target's damage radii are their
radius east to west and north to south within 1 cm (bounds and drawn radii) and within half a pixel on their SVG path.
Screenshots (popup, dialog with each help, panel with its help, the UB-32 ring) go to `--shots` (default `./shots`). Exits
with 1 on any failure.

## layer_minimap_check.mjs: the own minimap of Seed and Skirmish layers

```sh
node layer_minimap_check.mjs <site URL>
```

Needs the layer API and the images of `tools/maptiles` (step `layer-minimaps`) under `/maptiles/`. Mutaha Seed v1: its 4096 px
texture is drawn above the map image at the layer's corners (633.6 m east and 581.5 m south of the image corner, 1300 m
square), the topographic layer removes it and the basemap brings it back, clearing the layer removes it; Mutaha RAAS v1
(the map's own texture) shows nothing; Tallil Seed v1 shows its texture; a map change leaves none; only the images of layers
with a texture of their own are requested; console clean. `SHOT_DIR=<dir>` also saves a screenshot. Exits with 1 on any failure.

## home_server_check.mjs: the Deadline server in the servers list

```sh
node home_server_check.mjs <site URL>
```

Needs the layer API and the site's `/live/servers.json` (`deploy/live_servers.py`). With the site's own feed,
`/?server=deadline` opens the layer the game server plays with its map and both factions, and the menu's dropdown offers
the server. Every other step answers the feed itself (a route of the browser, the site's file is not touched):

- Mutaha Seed v1, then Al Basrah Seed v1: the page follows the layer change within the 20 s it asks again, and the
  refreshed servers browser lists the home server and no other.
- The feed cannot be read (it answers 502): after two failed reads the page still follows the server; it leaves server
  mode, with one message, only once the feed it last read is two minutes old (95 to 135 s later).
- The followed server leaves the feed (the feed grows ten minutes old): at its next read the page leaves server mode
  (no `server` in the URL, no choice in the dropdown, the servers button and the sync timer off, the layer left as it
  was), shows one message, and the dropdown no longer offers the server. Back in the feed, the server is offered again
  without a reload, and the page does not follow it by itself.
- The dropdown is cleared (no message), the server moves to another layer, the server is chosen again: the only layer
  the page opens is the one played now.
- The followed server moves to a layer of a map the calculator does not have, then, followed again, to an entry without
  factions: each time the page leaves server mode with the "no data for the layer" message and the dropdown lists the
  server as unavailable.
- A feed ten minutes old at page load: the server is not offered and `/?server=deadline` falls back to the plain page.
- The server moves to a layer of another map, and server mode is left while that map's list of layers is held back:
  when the list arrives, the page opens none of the server's layers and shows no message.
- The request for the server's layer fails once: the page still follows and opens the layer at its next read.
- A page opened on another map with `?server=`, whose own list of layers arrives after the server's layer has loaded:
  the layer selector keeps the server map's layers.

Each step that waits for the page's next read of the feed gives it 90 s. Exits with 1 on any failure.

## standard_hd_check.mjs: the Standard HD layer

```sh
node standard_hd_check.mjs <site URL> [map ...]
```

Needs the tiles of `tools/maprender` under `/maptiles/<map>-hd/`. On every map of the selector (or the named ones): Standard HD is the
layer shown by default, its finest tiles load at 256 px and at most 0.33 m per pixel, the map goes two zooms past them. A map whose
`meta.json` answers 404 shows the detailed layer; a link with `type=basemap` keeps the basemap; no tile is missing, console clean.
`SHOT_DIR=<dir>` also saves a screenshot per map at the finest zoom. Exits with 1 on any failure.

## volume_check.mjs: the volume layer

```sh
node volume_check.mjs <site URL>
```

A build with `npm run build:engine` done and the maps' `volume.vcol` / `terrain.bin` under `/heightmaps/`. Nothing of the layer is
requested before the setting is on; then the engine, the voxel file and the landscape file load, six walls block and six
openings pass (`volume_cases.json`, Jensen and Kokan, from the engine's parity data), the layer's landscape equals the
heightmap's on open ground, the line of fire and the fire coverage use it, the nine largest volume files (Fallujah, Goose Bay, Kamdesh,
Skorpo, Black Coast, Chora, Gorodok, Harju, Yehorivka) load and finish a coverage (reported: the load time from the setting to
"ready" and the resident memory of the browser's process tree before, at the peak and after), and a map whose volume file
answers 404 keeps the heightmap with only the 404 and the layer's warning in the console. Exits with 1 on any failure.

## targets_check.mjs: target heights and structure damage

```sh
node targets_check.mjs <site URL> [--shots <dir>]
```

(deadline-squad/deadline-squadcalc#22 C3, C4, C7b; a build with the engine and the volume files). The *Object volumes*
setting is off by default and the target dialog has no height control while it is off; with it on, a target inside a Jensen
building lists the floors, ceilings, roof, windows and doorways of the vertical ray and the landscape under it, the chosen
height changes the target height, the height difference, the dialog and popup, and the line-of-fire answer; dragging or
turning the setting off puts the target back on the ground. A FOB and a HAB marker open the shells-to-destroy popup, a target
on the FOB shows the row in its dialog (2 mortar rounds, "no structure damage" for AP ammunition), the tooltip says the
formula is inferred, and the Russian locale has the strings. Screenshots (target dialog with the list, with a floor chosen,
the structure row with its tooltip, AP, Russian, the marker popup) go to `--shots` (default `./shots`). Exits with 1 on any
failure.

## heatmap_check.mjs: firing positions and the damage zone with cover

```sh
node heatmap_check.mjs <site URL> --reference <dir> [--shots <dir>] [--height <kind>:<index>]
```

(deadline-squad/deadline-squadcalc#22 C5, C6; a build with the engine, the volume files and the Jensen precision region under
`/heightmaps/`; `--reference` is the output of SquadCalc's `engine/tools/js/heatmap_validate.mjs` for the Jensen target (131, -199)).
The heatmap is off by default: no button in the target dialog without the volume layer or for a weapon that is not direct fire,
and nothing of it (module, region) is requested before the button is pressed. On the target in a Jensen window the button loads the
module on demand, the region is fetched and used (legend: *Exact triangles within 56 m of the target*), a target without region says
*Voxels only*, and hiding, dragging, deleting the target and turning the volume layer off remove the image. The page's own run
with the validation's parameters gives the validation's clear, blocked and out positions (at most 0.05 % flip on the last bit of a
float) and, against the exact triangle tracer's output, no worse than the validation's own run (no false clear and no false blocked
position for the window of the sample-lattice file). `--height` (default `window:1`) names the height the reference holds: the
exact-voxeliser `volume.vcol` closes the windows of that building (the dialog offers `Roof +6.3m` only), so after it is published
use `--height roof:0 --reference <heat-val-exact>`, a reference written by `heatmap_validate.mjs --height roof:0,ground` on the new
file; its 8 false blocked positions are all beyond 100 m from the target, outside the 56 m the region covers. The damage zone of the same
target is computed by the layer's worker with the voxels as cover and differs from the heightmap's. Screenshots (the dialog button,
the heatmap of the window, of a target on open ground, the damage zone) go to `--shots`. Exits with 1 on any failure.

## heatmap_timing.mjs: how long the heatmap takes per map

```sh
node heatmap_timing.mjs <site URL> [--maps Jensen,Fallujah,...] [--ranges 600,2000] [--out timings.json]
```

(C9) On every map with volume files: a target inside a building nearest the map's centre, DF_M2A1_50, the heatmap at each range with
the voxel walk and, where the target has a region, with it; prints the map's side, the voxel file's size, the positions, the
wall time, the worker's trace time per position and the region load, and the load average of the host and the browser's WebGL
renderer (this host has no GPU: SwiftShader, so there is no GPU timing). Results: SquadCalc `engine/README.md`, "Position heatmap".

## precision_browser.mjs: precision checks on the served build

```sh
node precision_browser.mjs <site URL> <SquadCalc checkout for node_modules/fast-png>
```

The audit's precision checks in the browser, against oracles computed from the served files: distance and
bearing on a non-square map (Skorpo) from the world coordinates, the page's heights against the bilinear
interpolation of the served 16-bit heightmap, mortar and UB-32 solutions in a simulation with the game's
values, a session peer's height padding as a number, and the warning when the heightmaps fail to load.
`tools/direct_fire/precision_check.mjs` holds the same checks on the modules, without a browser.

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

## netcost.mjs: what a visit costs on the network

```sh
node netcost.mjs <site URL> [--json <file>]
```

Bytes on the wire (Chromium's own count over the DevTools protocol, for the page, its workers and the service
worker), requests and the time to the precise heightmap in each scenario: cold first visit (until the service
worker has precached), warm revisit in a new tab and after restarting the browser, a map switch to Yehorivka,
Skorpo and Al Basrah (empty HTTP cache, then again with the files cached), on the detailed layer one zoom
step and a half-screen pan, and a drag at about 600 px/s (visible tiles still blank, frame rate, dropped frames
of a Chromium trace). Each scenario runs in a profile with a real on-disk HTTP cache, and the page is not
intercepted, so the browser cache works as for a visitor. `decodeMs` is the time from the end of the heightmap
download to the page holding the heights.

## heightmap_exact.mjs: the WebP against the PNG

```sh
node heightmap_exact.mjs <site URL> --maps albasrah,chora,skorpo [--dist <dir>] [--fast-png <package dir>] [--webp-meta <dir>]
```

Loads each map's heightmap in the site's worker through the WebP and through the PNG and compares them in the
page pixel by pixel (identical where the step is the same, within half a step of each where it was coarsened);
`--dist` with `--fast-png` also checks the worker's PNG decode against fast-png's. Exits with 1 on a difference.

## heightmap_native.mjs: maps finer than 1 m

```sh
node heightmap_native.mjs <site URL> --maps chora,kokan [--points points.json] [--runs 5]
```

Chora and Kokan have 0.5 m heightmaps (`tools/heightmaps`, "Grid size"). For each map the site's worker loads the
heightmap `--runs` times and the script prints its grid (samples, `resolution`, step) and the worker's time (the
first run is cold, the rest read the browser cache, so they are the decoding). `--points` is a file written by
`tools/heightmaps/py/compare_native_vertices.py --points-out`: the page's own `getHeight` is read at landscape
vertices of the game and must agree to half the height step. Exits with 1 on a failure.

## fonts_check.mjs: the fonts come from the site

```sh
node fonts_check.mjs <site URL> [--measure <runs>] [--shots <dir>]
```

In each of the six languages as a first-time visitor: no request to fonts.googleapis.com or fonts.gstatic.com, a clean
console, the self-hosted Montserrat and Oswald loaded, the cyrillic subsets requested for ru and uk only, the two
preloaded latin files fetched once, the precache holding the three latin files and no other font; then offline after a
reload: a subset used before comes from the service worker's `fonts` cache, one never used is not available. `--measure`
repeats a cold visit on Slow 4G with a 4x slower CPU and prints FCP and the font requests; `--shots` saves a screenshot
of the page and of the settings dialog per language, to compare two builds. Exits with 1 on a failure.

## sb_bridge_races.mjs: the bridge against Squad Ballistics' own scripts

```sh
python3 -c "import json, maplink, ballistics; json.dump({'bridge': maplink.bridge_script(None), 'watch': maplink.WATCH_SCRIPT, 'renamed': ballistics.RENAMED_WEAPONS}, open('/tmp/sb_scripts.json', 'w'))"   # in a Squad Ballistics checkout
node sb_bridge_races.mjs <site URL> [/tmp/sb_scripts.json]
```

A model of SB's map host (known revision, last targets, last weapon) polls with SB's real poll script after every kind of
change (target added, moved, deleted; weapon marker moved, raised, removed; weapon and shell switched; heights loading
late; two quick map switches) and must end each step with the page's newest target, profile and weapon. Every name of
`RENAMED_WEAPONS` must also select its current weapon through `selectWeapon`.

## sw_upgrade_check.mjs: the service worker across a deploy

```sh
node sw_upgrade_check.mjs <site URL> --old <dist> --new <dist> --link <symlink the server root is> [--hm-link <symlink of /heightmaps/> --heightmaps <dir>]
```

Upgrade and rollback between two builds (precache holds exactly the new bundle, the page runs it, opens offline),
an open tab asking for a chunk of the old bundle, a precache missing entries, and old-format against current
heightmaps with both builds. See the header of the script for the Caddy setup.

## offline_app_check.mjs: the app without a network

```sh
node offline_app_check.mjs <site URL> [--no-fonts]
```

After one visit: the page, translations and the seen precise heightmap open offline (also after a browser restart),
fonts stay, online the page and translations come from the network first, and a regenerated heightmap (new `generated` in
meta.json) is fetched under its new `?v=` URL. The Google Fonts caches are checked only when the page requests them.

## offline_check.mjs: the service worker's caches

```sh
node offline_check.mjs <site URL> --vehicles <dir of the vehicle images>
```

With a profile that survives a browser restart: the precache holds no vehicle image except the placeholder and no
README screenshot; a vehicle image shown once is served from the service worker's cache afterwards, with the network
gone and after a restart; one never shown fails offline (the page shows the placeholder, which is precached).

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

## a11y_check.mjs: accessibility of the controls

```sh
node a11y_check.mjs <site URL>
```

Reads Chromium's accessibility tree: every button, combobox, checkbox and slider is named (map page, settings and
factions dialogs), ids are unique, the layer, help map, coverage and HD buttons carry `aria-pressed` in step with
their `active` class, header selects and their select2 widgets are named, weapon and target markers are reached with
Tab and opened with Enter or Space with the focus returning to them, and the map buttons are named in each language.
