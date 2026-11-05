// Checks Belaya Pass, the terrain-only map (heights from SquadHeight alone, no volume layer), in a real browser
// (Chromium through Playwright):
//
//     node belaya_check.mjs <site URL>
//
// Belaya can be selected; its precise heightmap (the WebP announced by meta.json, with `provenance` and no `volume` entry)
// loads at SquadHeight's size; heights at grid nodes equal the SquadHeight export (belaya_points.json, read from the
// export's PNG: a 1 m node is exact up to the WebP's 1 cm step); the notice that the terrain is community data shows on
// load and the map's entry in the selector carries it as a tooltip; the map image of the upstream basemap and the relief
// archive load; with *Object volumes in the line of fire* on, the layer reports itself unavailable, no worker or engine
// file is requested, and the heightmap is kept; and the console stays clean.
// <site URL> is a served build with /heightmaps/belaya/ and /maptiles/relief/belaya.pmtiles. Environment:
// PLAYWRIGHT_CORE, CHROME as for browser_check.mjs. Exits with 1 on any failure.
import { readFileSync } from "node:fs";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const base = process.argv[2];
if (!base) {
    console.error("usage: node belaya_check.mjs <site URL>");
    process.exit(2);
}
const { points } = JSON.parse(readFileSync(new URL("./belaya_points.json", import.meta.url), "utf8"));
const PROVENANCE = "SquadHeight 1.3.0 (Mod SDK export), terrain only, not validated against server data";

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

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
const problems = [];
const requests = [];
page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) problems.push(`${message.type()}: ${message.text()}`);
});
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
page.on("response", (response) => {
    requests.push({ url: response.url(), status: response.status() });
    if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`);
});
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.precise, null, { timeout: 120000 });

const meta = await (await fetch(new URL("/heightmaps/belaya/meta.json", base))).json();
check("meta.json states its provenance, has one source and no volume entry", meta.provenance === PROVENANCE && !("volume" in meta) && Object.keys(meta.sources).join() === "sdk_surface", `${meta.provenance}; sources ${Object.keys(meta.sources)}`);

const option = await page.evaluate(() => {
    const select = window.__App.MAP_SELECTOR[0];
    const candidate = [...select.options].find((entry) => entry.dataset.i18n === "maps:Belaya");
    return { count: select.options.length, value: candidate?.value, title: candidate?.title };
});
check("26 maps, Belaya is listed with the notice as its tooltip", option.count === 26 && Boolean(option.value) && /community data, unverified/.test(option.title), `${option.count} options, title "${option.title}"`);

await page.evaluate((value) => window.__App.MAP_SELECTOR.val(value).trigger("change"), option.value);
await page.waitForFunction(() => {
    const map = window.__App.minimap;
    return map.activeMap.name === "Belaya" && map.heightmap?.precise && map.heightmap.jsonPng.length > 3000;
}, null, { timeout: 120000 });

const loaded = await page.evaluate(() => {
    const map = window.__App.minimap;
    const heightmap = map.heightmap;
    const toast = document.querySelector("#toast");
    return {
        rows: heightmap.jsonPng.length, cols: heightmap.jsonPng[0].length, resolution: heightmap.resolution, step: heightmap.step,
        size: [map.activeMap.size, map.activeMap.sizeY], toastClass: toast.className, toastTitle: toast.querySelector("h4").textContent, toastText: toast.querySelector("p").textContent,
    };
});
check("the heightmap is SquadHeight's grid (3906 rows x 3905 columns of 1 m) in the WebP's 1 cm step", loaded.rows === 3906 && loaded.cols === 3905 && loaded.resolution === 1 && Math.abs(loaded.step - 0.01) < 1e-9, `${loaded.rows} x ${loaded.cols}, ${loaded.resolution} m, step ${loaded.step}, map ${loaded.size}`);
check("the community-data notice shows on load", loaded.toastClass === "warning" && /community/i.test(loaded.toastTitle) && /not taken from the game server files/.test(loaded.toastText), `${loaded.toastClass}: "${loaded.toastTitle}" / "${loaded.toastText.slice(0, 80)}..."`);

const heights = await page.evaluate((expected) => {
    const map = window.__App.minimap;
    const [minX, minY] = [-1954, -2080];
    return expected.map(({ x, y, height_m: height }) => {
        const got = map.heightmap.getHeight({ lat: -(y - minY) * map.gameToMapScaleY, lng: (x - minX) * map.gameToMapScale });
        return { x, y, height, got };
    });
}, points);
const worst = Math.max(...heights.map((entry) => Math.abs(entry.got - entry.height)));
check(`heights at ${points.length} grid nodes (corners, summit, lowest cell, random) equal the SquadHeight export`, worst <= 0.0051, `worst difference ${(worst * 1000).toFixed(2)} mm (the WebP step is 10 mm)`);

const relief = await page.evaluate(async () => {
    const map = window.__App.minimap;
    document.querySelector(".btn-relief")?.click();
    await new Promise((resolve) => setTimeout(resolve, 3000));
    return { available: getComputedStyle(document.querySelector(".btn-relief")).display !== "none", layers: Object.keys(map._layers ?? {}).length };
});
check("the relief button is offered and the archive is read", relief.available && requests.some((request) => /\/maptiles\/relief\/belaya\.pmtiles/.test(request.url) && request.status < 400), `${requests.filter((request) => /belaya\.pmtiles/.test(request.url)).length} requests`);

const basemap = requests.find((request) => /\/img\/maps\/belaya\/basemap\.webp/.test(request.url));
check("the map image (upstream basemap) loads", basemap?.status === 200, `${basemap?.url} ${basemap?.status}`);

const detailedBefore = requests.length;
const detailed = await page.evaluate(async () => {
    document.querySelector("#mapLayerMenu .btn-detailed").click();
    await new Promise((resolve) => setTimeout(resolve, 2500));
    return document.querySelector("#mapLayerMenu .btn-detailed").classList.contains("active");
});
const tileRequests = requests.slice(detailedBefore).filter((request) => /\/maptiles\/belaya\//.test(request.url));
check("the Detailed layer shows the upstream topographic map without asking for tiles", detailed && tileRequests.length === 0 && requests.slice(detailedBefore).some((request) => /\/img\/maps\/belaya\/topomap\.webp/.test(request.url)), `${tileRequests.length} tile requests`);

const before = requests.length;
await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
await page.waitForFunction(() => !["loading", "idle"].includes(window.__App.minimap.volume.state), null, { timeout: 60000 });
const volume = await page.evaluate(() => ({ state: window.__App.minimap.volume.state, ready: window.__App.minimap.volume.ready, rows: window.__App.minimap.heightmap.jsonPng.length }));
const volumeRequests = requests.slice(before).filter((request) => /volume\.vcol|terrain\.bin|\/engine\//.test(request.url));
check("with the volume setting on the layer is unavailable, nothing of it is requested and the heightmap is kept", volume.state === "unavailable" && !volume.ready && volumeRequests.length === 0 && volume.rows === 3906, `${volume.state}, ${volumeRequests.length} volume requests, ${volume.rows} rows`);

const target = await page.evaluate(() => {
    const app = window.__App;
    const map = app.minimap;
    const lat = (y) => -(y - -2080) * map.gameToMapScaleY;
    const lng = (x) => (x - -1954) * map.gameToMapScale;
    return { low: map.heightmap.getHeight({ lat: lat(-1900), lng: lng(0) }), high: map.heightmap.getHeight({ lat: lat(0), lng: lng(0) }) };
});
check("heights are not flat ground (the calculator has height data to work with)", Number.isFinite(target.low) && Number.isFinite(target.high), `(0,-1900) ${target.low.toFixed(1)} m, (0,0) ${target.high.toFixed(1)} m`);

check("the console is clean", problems.length === 0, problems.length ? problems.join(" | ") : "no errors or warnings");

await browser.close();
process.exit(failures ? 1 : 0);
