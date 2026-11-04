// Measures how long the reverse-position heatmap (C5) takes in a real browser (headless Chromium through Playwright, the
// real WebAssembly engine in the volume layer's worker) on every map that has volume files, deadline-squad/deadline-squadcalc#22 C9.
//
//     node heatmap_timing.mjs <site URL> [--maps Jensen,Fallujah,...] [--ranges 600,2000] [--out timings.json]
//
// For each map: the target is the position nearest the map's centre (within 400 m, 20 m apart) where the vertical ray of
// the volume layer finds a floor, window or doorway, i.e. inside a building; the weapon is the DF_M2A1_50 (heavy machine
// gun, a numeric trajectory). For each range (default 600 and 2000 m; the page draws at most 2000 m) the heatmap is
// computed with the voxel walk alone (no precision region) and, where the target has one, with the region. Reported: the
// map's side, the voxel file's size, the number of positions, the share of them clear/blocked/out, the wall time from the
// request to the values in the page, the worker's own trace time and the time it spent loading a region. The timings are of
// this machine and of its load at the time (see `load` in the output), and of CPU: this host has no GPU, so there is no GPU
// timing (the WebGL renderer the browser reports is printed). Environment: PLAYWRIGHT_CORE, CHROME as for browser_check.mjs.
import { writeFileSync } from "node:fs";
import { loadavg } from "node:os";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const base = process.argv[2];
const argument = (name, fallback) => (process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback);
if (!base) {
    console.error("usage: node heatmap_timing.mjs <site URL> [--maps a,b] [--ranges 600,2000] [--out file]");
    process.exit(2);
}
const MAPS = argument("--maps", "Jensen,Kokan,Logar,Sumari,Kohat,Pacific,FoolsRoad,Mestia,Fallujah,Kamdesh,GooseBay").split(",");
const RANGES = argument("--ranges", "600,2000").split(",").map(Number);
const out = argument("--out");

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
    if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
    await route.fulfill({ response, body: patched });
});
const page = await context.newPage();
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.precise, null, { timeout: 120000 });

const renderer = await page.evaluate(() => {
    const gl = document.createElement("canvas").getContext("webgl");
    const info = gl?.getExtension("WEBGL_debug_renderer_info");
    return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "no WebGL";
});
console.log(`browser ${browser.version()}, WebGL renderer: ${renderer}, ${await page.evaluate(() => navigator.hardwareConcurrency)} logical CPUs, load average ${loadavg().map((value) => value.toFixed(1)).join(" ")}`);

await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
const results = [];
for (const name of MAPS) {
    await page.evaluate(async (mapName) => {
        const app = window.__App;
        const option = [...app.MAP_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `maps:${mapName}`);
        app.MAP_SELECTOR.val(option.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 0));
    }, name);
    await page.waitForFunction((mapName) => {
        const map = window.__App.minimap;
        return map.activeMap.name === mapName && map.heightmap?.precise && !map._spinning && map.volume.ready;
    }, name, { timeout: 600000 });

    const result = await page.evaluate(async ({ mapName, ranges }) => {
        const app = window.__App;
        const map = app.minimap;
        const volume = map.volume;
        const b = volume.bounds;
        const toLatLng = (x, y) => ({ lng: ((x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize });
        const meta = await (await fetch(`/heightmaps/${map.activeMap.mapURL.split("/").filter(Boolean).pop()}/meta.json`)).json();

        // The nearest point to the centre inside a building
        const centre = { x: (b.min_x + b.max_x) / 2, y: (b.min_y + b.max_y) / 2 };
        let found = null;
        const candidates = [];
        for (let dx = -400; dx <= 400; dx += 20) for (let dy = -400; dy <= 400; dy += 20) candidates.push({ x: centre.x + dx, y: centre.y + dy, d: Math.hypot(dx, dy) });
        candidates.sort((a, c) => a.d - c.d);
        const searchStarted = performance.now();
        for (const point of candidates) {
            const heights = await volume.heightsAt(toLatLng(point.x, point.y));
            const choice = heights?.choices.find((candidate) => ["floor", "window", "doorway"].includes(candidate.kind));
            if (choice) {
                found = { ...point, choice, landscape: heights.landscape };
                break;
            }
        }
        if (!found) return { map: mapName, error: "no building within 400 m of the centre" };

        const weapon = app.WEAPON_SELECTOR[0].options && (() => {
            const option = [...app.WEAPON_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === "weapons:DF_M2A1_50");
            app.WEAPON_SELECTOR.val(option.value).trigger("change");
            return app.activeWeapon;
        })();
        const gravity = app.gravity * weapon.gravityScale;
        const latlng = toLatLng(found.x, found.y);
        const runs = [];
        for (const range of ranges) {
            const cell = Math.max(2, range / 160);
            const rays = Math.max(360, Math.min(1440, Math.ceil((2 * Math.PI * range) / (2 * cell))));
            const params = {
                targetZ: found.choice.height, elevated: true, shot: weapon.getShot(gravity, 1.5), range, cell, rays,
                elevationLimits: weapon.minElevation, angleOffset: weapon.angleOffset || 0, lifespan: weapon.projectileLifespan, moa: weapon.moa,
            };
            for (const withRegion of [false, true]) {
                const regions = volume.regions;
                if (!withRegion) volume.regions = [];
                const hasRegion = withRegion && regions.length > 0 && regions.some((region) => Math.max(Math.abs(found.x - region.centre[0]), Math.abs(found.y - region.centre[1])) <= region.radius - 50);
                if (withRegion && !hasRegion) {
                    volume.regions = regions;
                    continue;
                }
                const started = performance.now();
                const answer = await volume.positionHeatmap(params, latlng, (from, east, north) => map.fromMeters(from, east, north), () => true);
                const wallMs = performance.now() - started;
                volume.regions = regions;
                let clear = 0;
                let blocked = 0;
                let outside = 0;
                for (const value of answer.values) {
                    if (value >= 2) clear++;
                    else if (value === 1) blocked++;
                    else outside++;
                }
                outside -= rays;
                const positions = rays * Math.floor(range / cell);
                runs.push({
                    range, cell, rays, positions, precision: Boolean(answer.exact), wallMs: Math.round(wallMs), computeMs: Math.round(answer.computeMs), loadMs: Math.round(answer.loadMs),
                    perPositionUs: Math.round((answer.computeMs * 1000) / positions * 10) / 10, clear, blocked, out: outside,
                });
            }
        }
        return {
            map: mapName, sideM: b.max_x - b.min_x, volumeBytes: meta.volume.bytes, terrainBytes: meta.volume.terrain.bytes, columns: meta.volume.columns,
            target: { x: Math.round(found.x), y: Math.round(found.y), kind: found.choice.kind, searchMs: Math.round(performance.now() - searchStarted) }, runs,
        };
    }, { mapName: name, ranges: RANGES });
    results.push(result);
    if (result.error) {
        console.log(`${name}: ${result.error}`);
        continue;
    }
    console.log(`${name} (${result.sideM} m side, volume ${(result.volumeBytes / 1e6).toFixed(1)} MB, ${result.columns} columns) target ${result.target.kind} at ${result.target.x}, ${result.target.y}`);
    for (const run of result.runs) {
        console.log(`  range ${run.range} m, ${run.positions} positions, ${run.precision ? "with precision region" : "voxels only"}: wall ${run.wallMs} ms, trace ${run.computeMs} ms (${run.perPositionUs} us per position), region load ${run.loadMs} ms; clear ${run.clear}, blocked ${run.blocked}, out ${run.out}`);
    }
}

if (out) writeFileSync(out, JSON.stringify({ renderer, load: loadavg(), results }, null, 2));
await browser.close();
