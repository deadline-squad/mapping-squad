// Checks the Standard HD layer of the Deadline SquadCalc in Chromium, on every map: it is the layer shown by default, its tiles from
// tools/maprender load at the finest zoom, the map goes two zooms past them, and a map without the tiles shows the detailed layer.
//
//     node standard_hd_check.mjs <site URL> [map ...]
//
// Environment as browser_check.mjs. SHOT_DIR=<dir> also saves a screenshot per map at the finest zoom. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const [site, ...only] = process.argv.slice(2);
const base = site?.replace(/\/+$/, "");
if (!base) {
    console.error("usage: node standard_hd_check.mjs <site URL> [map ...]");
    process.exit(2);
}
let failures = 0;
const check = (label, ok, detail) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
};

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
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
page.on("console", (message) => { if (message.type() === "error") problems.push(`console: ${message.text()}`); });
const missing = [];
page.on("response", (response) => {
    if (response.url().includes("/maptiles/") && response.status() >= 400) missing.push(`${response.status()} ${new URL(response.url()).pathname}`);
});

const ready = () => page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !window.__App.minimap._spinning, null, { timeout: 120000 });
const activeLayerButton = () => page.evaluate(() => document.querySelector("#mapLayerMenu .active")?.getAttribute("value"));

await page.goto(`${base}/`, { waitUntil: "load" });
await ready();
const maps = only.length ? only : await page.evaluate(() => [...document.querySelectorAll(".dropbtn option[data-i18n^='maps:']")].map((option) => option.getAttribute("data-i18n").slice(5)));
check("the map selector lists the maps", maps.length >= 25 || only.length > 0, `${maps.length} maps`);

for (const name of maps) {
    await page.goto(`${base}/?map=${encodeURIComponent(name)}`, { waitUntil: "load" });
    await ready();
    const layer = await activeLayerButton();
    const state = await page.evaluate(async () => {
        const map = window.__App.minimap;
        const folder = map.activeMap.mapURL.split("/").filter(Boolean).pop();
        const meta = await (await fetch(`/maptiles/${folder}-hd/meta.json`, { cache: "no-cache" })).json();
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        map.setView([-map.pixelSize / 2, map.pixelSize / 2], meta.maxNativeZoom, { animate: false });
        for (let attempt = 0; attempt < 60 && !document.querySelector("img.leaflet-tile-loaded"); attempt++) await wait(250);
        await wait(2500);
        const tiles = [...document.querySelectorAll("img.leaflet-tile-loaded")].filter((tile) => tile.src.includes(`/maptiles/${folder}-hd/${meta.maxNativeZoom}/`));
        const pending = [...document.querySelectorAll("img.leaflet-tile:not(.leaflet-tile-loaded)")].length;
        const bytes = performance.getEntriesByType("resource").filter((entry) => entry.name.includes(`/maptiles/${folder}-hd/${meta.maxNativeZoom}/`))
            .reduce((sum, entry) => sum + entry.encodedBodySize, 0);
        const maxZoom = map.getMaxZoom();
        return { folder, zoom: meta.maxNativeZoom, metresPerPixel: meta.metresPerPixel, tiles: tiles.length, broken: tiles.filter((tile) => tile.naturalWidth !== 256).length, pending, kilobytes: Math.round(bytes / 1024), maxZoom };
    });
    if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/standard_hd_${state.folder}.png` });
    check(`${name}: Standard HD by default, finest tiles load`,
        layer === "standard-hd" && state.tiles > 0 && state.broken === 0 && state.metresPerPixel <= 0.33 && state.maxZoom === Math.max(8, state.zoom + 2), JSON.stringify(state));
}

await page.route(/\/maptiles\/mutaha-hd\/meta\.json/, (route) => route.fulfill({ status: 404, body: "" }));
const expected404 = (entry) => entry.includes("/maptiles/mutaha-hd/meta.json");
await page.goto(`${base}/?map=Mutaha`, { waitUntil: "load" });
await ready();
const fallback = await page.evaluate(() => [...document.querySelectorAll("img.leaflet-tile")].some((tile) => /\/maptiles\/mutaha\/\d+\//.test(tile.src)));
check("a map without Standard HD tiles shows the detailed layer", (await activeLayerButton()) === "detailed" && fallback, await activeLayerButton());
await page.unroute(/\/maptiles\/mutaha-hd\/meta\.json/);

await page.goto(`${base}/?map=Mutaha&type=basemap`, { waitUntil: "load" });
await ready();
check("a link naming a layer keeps that layer", (await activeLayerButton()) === "basemap", await activeLayerButton());

const unexpected = missing.filter((entry) => !expected404(entry));
check("no tile or meta.json is missing", unexpected.length === 0, unexpected.slice(0, 10).join(" | ") || "none");
const realProblems = problems.filter((entry) => !entry.includes("404"));
check("no page error, no console error", realProblems.length === 0, realProblems.slice(0, 10).join(" | ") || "clean");
await browser.close();
process.exit(failures ? 1 : 0);
