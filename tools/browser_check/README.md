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
node browser_check.mjs <site URL> [--maps]
```

Console and requests clean, precise heightmaps (`--maps`: on every map), regression checks for
the bugs fixed in 45.5.1 and after the walkthrough review, the `window.squadBallistics` bridge the
Squad Ballistics app reads (targets, weapon, weapon selection) and the absence of the removed device
link (settings controls, relay requests, leftover localStorage keys). Exits with 1 on any failure.

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
