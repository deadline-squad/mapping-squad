// Checks the own minimap of gameplay layers in the Deadline SquadCalc in Chromium: a Seed or Skirmish layer ships a
// 4096 px game texture over a part of the map (tools/maptiles, step layer-minimaps); SquadCalc draws it above the
// map image where the game's corners put it, only on the upstream basemap, and removes it with the layer.
//
//     node layer_minimap_check.mjs <site URL>
//
// Needs the layer API and the images under /maptiles/. Mutaha Seed v1 (1300 m square, 634 m east and 581 m south of
// the image corner), Mutaha RAAS v1 (no own texture: nothing), Tallil Seed v1. Environment as browser_check.mjs.
// SHOT_DIR=<dir> also saves a screenshot of Mutaha Seed v1. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node layer_minimap_check.mjs <site URL>");
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
const requested = [];
page.on("request", (request) => { if (request.url().includes("/maptiles/") && request.url().includes("_minimap_")) requested.push(new URL(request.url()).pathname); });

const ready = () => page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !window.__App.minimap._spinning, null, { timeout: 120000 });
const loadLayer = async (map, layer) => {
    await page.goto(`${base}/?map=${map}`, { waitUntil: "load" });
    await ready();
    await page.evaluate((name) => window.__App.LAYER_SELECTOR.val(name).trigger("change"), layer);
    await page.waitForFunction((name) => window.__App?.minimap?.layer?.layerData?.rawName === name, layer, { timeout: 120000 });
    await ready();
};
/** The layer minimap image: its Leaflet bounds in metres east/south of the map image's corner, size, opacity */
const overlay = () => page.evaluate(() => {
    const map = window.__App.minimap;
    const image = map.layerMinimapImage;
    if (!image) return null;
    const element = image.getElement();
    const b = image.getBounds();
    return {
        src: element.getAttribute("src"),
        west: b.getWest() * map.mapToGameScale, east: b.getEast() * map.mapToGameScale,
        north: -b.getNorth() * map.mapToGameScaleY, south: -b.getSouth() * map.mapToGameScaleY,
        naturalWidth: element.naturalWidth, opacity: Number(getComputedStyle(element).opacity),
        inDom: document.body.contains(element),
    };
});
const waitOverlayLoaded = () => page.waitForFunction(() => {
    const image = window.__App.minimap.layerMinimapImage;
    const element = image?.getElement();
    return element && element.complete && element.naturalWidth > 0 && Number(getComputedStyle(element).opacity) === 1;
}, null, { timeout: 60000 });
const near = (a, b, tolerance) => Math.abs(a - b) <= tolerance;

await loadLayer("Mutaha", "Mutaha_Seed_v1");
await waitOverlayLoaded();
let state = await overlay();
check("Mutaha Seed v1: own minimap above the map image, at the layer's corners",
    state && /mutaha_minimap_seed_v1\/0\/0_0\.webp\?v=/.test(state.src) && near(state.west, 633.6, 0.1) && near(state.north, 581.5, 0.1)
    && near(state.east - state.west, 1299.97, 0.1) && near(state.south - state.north, 1299.97, 0.1) && state.naturalWidth === 4096, JSON.stringify(state));
if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/layer_minimap_mutaha_seed.png` });

await page.evaluate(() => { document.querySelector("#mapLayerMenu .btn-topomap").click(); });
await page.waitForFunction(() => window.__App.minimap.layerMinimapImage === null, null, { timeout: 10000 });
check("another map image layer (topographic) shows no layer minimap", (await overlay()) === null, "removed");
await page.evaluate(() => { document.querySelector("#mapLayerMenu .btn-basemap").click(); });
await waitOverlayLoaded();
check("back on the basemap the layer minimap returns", (await overlay()) !== null, "shown");

await page.evaluate(() => window.__App.minimap.layer.clear());
check("clearing the layer removes the layer minimap", (await overlay()) === null && !(await page.evaluate(() => !!document.querySelector("img[src*='_minimap_seed']"))), "removed");

await loadLayer("Mutaha", "Mutaha_RAAS_v1");
await page.waitForTimeout(1500);
check("Mutaha RAAS v1 uses the map's own texture: no layer minimap", (await overlay()) === null, "none");

await loadLayer("Tallil", "Tallil_Seed_v1");
await waitOverlayLoaded();
state = await overlay();
check("Tallil Seed v1: own minimap", state && /tallil_outskirts_minimap_skirmish_v1\/0\/0_0\.webp/.test(state.src) && near(state.east - state.west, 1130, 0.5), JSON.stringify(state));

await page.goto(`${base}/?map=Anvil`, { waitUntil: "load" });
await ready();
check("a map change leaves no layer minimap behind", (await overlay()) === null, "none");

check("only the images of layers with their own texture were requested", requested.every((path) => /\/(mutaha_minimap_seed_v1|tallil_outskirts_minimap_skirmish_v1)\//.test(path)), requested.join(", "));
check("no page error, no console error", problems.length === 0, problems.join(" | ") || "clean");
await browser.close();
process.exit(failures ? 1 : 0);
