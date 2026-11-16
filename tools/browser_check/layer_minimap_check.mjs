// Checks where the Deadline SquadCalc draws the game's minimap pictures, in Chromium. A Seed or Skirmish layer ships
// a 4096 px game texture over a part of the map (tools/maptiles, step layer-minimaps: the layer's data asset overrides
// its level's texture and corners); SquadCalc draws it above the map image where the game's corners put it, only on
// the upstream basemap (asked for in the URL, it is not the default layer), and removes it with the layer. The
// basemap itself lies over the game's corners, on Skorpo over the rectangle its texture was measured to show
// (6868.8 m wide, 19.7 m past the image corner in the east), as one image and as stretched HQ tiles.
//
//     node layer_minimap_check.mjs <site URL>
//
// Needs the layer API and the images under /maptiles/ (with layer-minimaps.json). Mutaha Seed v1 (1300 m square,
// 634 m east and 581 m south of the image corner), Black Coast Seed v1 (the layer data's own texture, a 1000 m square
// 1349 m east and 927 m south of it), Narva Skirmish v1 (1070 m square, 1020 m east and 442 m south), Mutaha RAAS v1
// (no own texture: nothing), Tallil Seed v1, then Skorpo's basemap. Environment as browser_check.mjs. SHOT_DIR=<dir>
// also saves screenshots of Mutaha Seed v1, Black Coast Seed v1, Narva Skirmish v1 and Skorpo's east edge in HQ.
// Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2]?.replace(/\/+$/, "");
if (!base) {
    console.error("usage: node layer_minimap_check.mjs <site URL>");
    process.exit(2);
}
let failures = 0;
const check = (label, ok, detail) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
};

const manifest = await (await fetch(`${base}/maptiles/layer-minimaps.json`)).json();
const folders = Object.values(manifest.layers).map((entry) => entry.folder);

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
page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (folders.some((folder) => path.startsWith(`/maptiles/${folder}/`))) requested.push(path);
});

const ready = () => page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !window.__App.minimap._spinning, null, { timeout: 120000 });
const loadLayer = async (map, layer) => {
    await page.goto(`${base}/?map=${map}&type=basemap`, { waitUntil: "load" });
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
/** Whether the layer's own minimap is shown from its folder at the given place (metres east/south of the image corner) */
const atCorners = (state, folder, west, north, size) => state && new RegExp(`/${folder}/0/0_0\\.webp\\?v=`).test(state.src)
    && near(state.west, west, 0.1) && near(state.north, north, 0.1) && near(state.east - state.west, size, 0.1)
    && near(state.south - state.north, size, 0.1) && state.naturalWidth === 4096;
/** Centres the view on a world point (metres) at a zoom */
const viewAt = (x, y, zoom) => page.evaluate(([x, y, zoom]) => {
    const map = window.__App.minimap;
    const { corner0, corner1 } = map.activeMap.SDK_data.minimap;
    const lat = -(y - Math.min(corner0[1], corner1[1])) / map.mapToGameScaleY;
    const lng = (x - Math.min(corner0[0], corner1[0])) / map.mapToGameScale;
    map.setView([lat, lng], zoom, { animate: false });
}, [x, y, zoom]);

await loadLayer("Mutaha", "Mutaha_Seed_v1");
await waitOverlayLoaded();
let state = await overlay();
check("Mutaha Seed v1: own minimap above the map image, at the layer's corners",
    atCorners(state, "mutaha_minimap_seed_v1", 633.6, 581.5, 1299.97), JSON.stringify(state));
if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/layer_minimap_mutaha_seed.png` });

await page.evaluate(() => { document.querySelector("#mapLayerMenu .btn-detailed").click(); });
await page.waitForFunction(() => window.__App.minimap.layerMinimapImage === null, null, { timeout: 10000 });
check("another map layer (detailed) shows no layer minimap", (await overlay()) === null, "removed");
await page.evaluate(() => { document.querySelector("#mapLayerMenu .btn-basemap").click(); });
await waitOverlayLoaded();
check("back on the basemap the layer minimap returns", (await overlay()) !== null, "shown");

await page.evaluate(() => window.__App.minimap.layer.clear());
check("clearing the layer removes the layer minimap", (await overlay()) === null && !(await page.evaluate(() => !!document.querySelector("img[src*='_minimap_seed']"))), "removed");

await loadLayer("Mutaha", "Mutaha_RAAS_v1");
await page.waitForTimeout(1500);
check("Mutaha RAAS v1 uses the map's own texture: no layer minimap", (await overlay()) === null, "none");

// The layer API gives Black Coast Seed v1 the map's texture; the game shows the one of the layer's data asset
await loadLayer("BlackCoast", "BlackCoast_Seed_v1");
await waitOverlayLoaded();
state = await overlay();
check("Black Coast Seed v1: the layer data's own minimap, at its corners", atCorners(state, "t_blackcoast_seed_v1", 1349, 927, 1000), JSON.stringify(state));
if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/layer_minimap_blackcoast_seed.png` });

await loadLayer("Narva", "Narva_Skirmish_v1");
await waitOverlayLoaded();
state = await overlay();
check("Narva Skirmish v1: own minimap at the layer data's corners", atCorners(state, "narva_minimap_skirmish_v1", 1020, 442, 1070), JSON.stringify(state));
if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/layer_minimap_narva_skirmish.png` });

await loadLayer("Tallil", "Tallil_Seed_v1");
await waitOverlayLoaded();
state = await overlay();
check("Tallil Seed v1: own minimap", state && /tallil_outskirts_minimap_skirmish_v1\/0\/0_0\.webp/.test(state.src) && near(state.east - state.west, 1130, 0.5), JSON.stringify(state));

await page.goto(`${base}/?map=Anvil&type=basemap`, { waitUntil: "load" });
await ready();
check("a map change leaves no layer minimap behind", (await overlay()) === null, "none");

check("only the images of layers with their own texture were requested",
    requested.length > 0 && requested.every((path) => /\/(mutaha_minimap_seed_v1|t_blackcoast_seed_v1|narva_minimap_skirmish_v1|tallil_outskirts_minimap_skirmish_v1)\//.test(path)),
    requested.join(", "));

// Skorpo's basemap over the rectangle its texture shows on the world (maps.js minimap.image)
await page.goto(`${base}/?map=Skorpo&type=basemap`, { waitUntil: "load" });
await ready();
const basemap = await page.evaluate(() => {
    const map = window.__App.minimap;
    const bounds = map.activeLayer.getBounds();
    const { corner0, corner1 } = map.activeMap.SDK_data.minimap;
    const west = Math.min(corner0[0], corner1[0]);
    const north = Math.min(corner0[1], corner1[1]);
    return {
        west: west + bounds.getWest() * map.mapToGameScale, east: west + bounds.getEast() * map.mapToGameScale,
        north: north - bounds.getNorth() * map.mapToGameScaleY, south: north - bounds.getSouth() * map.mapToGameScaleY,
    };
});
check("Skorpo: the basemap lies over (-3611.1, -3291.8) - (3257.7, 3575.8) m",
    near(basemap.west, -3611.1, 0.01) && near(basemap.north, -3291.8, 0.01) && near(basemap.east, 3257.7, 0.01) && near(basemap.south, 3575.8, 0.01),
    JSON.stringify(basemap));

// In HQ the tiles are cut on the image corners and stretched onto that rectangle: the outer edges of the corner tiles
// of zoom 4 (1.67 m a pixel) lie at its corners, 11.8 px past the grid in the east
await page.evaluate(() => document.querySelector(".btn-hd").click());
await ready();
const cornerTile = async (x, y, file) => {
    await viewAt(x, y, 4);
    await page.waitForFunction((file) => [...document.querySelectorAll("img.leaflet-tile-loaded")].some((tile) => tile.src.endsWith(file)), file, { timeout: 60000 });
    return page.evaluate(([x, y, file]) => {
        const map = window.__App.minimap;
        const tile = [...document.querySelectorAll("img.leaflet-tile-loaded")].find((image) => image.src.endsWith(file)).getBoundingClientRect();
        const origin = map.getContainer().getBoundingClientRect();
        const { corner0, corner1 } = map.activeMap.SDK_data.minimap;
        const point = (wx, wy) => map.latLngToContainerPoint([-(wy - Math.min(corner0[1], corner1[1])) / map.mapToGameScaleY, (wx - Math.min(corner0[0], corner1[0])) / map.mapToGameScale]);
        const corner = point(x, y);
        const grid = map.latLngToContainerPoint(x > 0 ? [-map.pixelSize, map.pixelSize] : [0, 0]);
        const edge = x > 0 ? [tile.right - origin.left, tile.bottom - origin.top] : [tile.left - origin.left, tile.top - origin.top];
        return { edge, corner: [corner.x, corner.y], grid: [grid.x, grid.y] };
    }, [x, y, file]);
};
const northWest = await cornerTile(-3611.1, -3291.8, "/basemap_hq/4_0_0.webp");
const southEast = await cornerTile(3257.7, 3575.8, "/basemap_hq/4_15_15.webp");
if (process.env.SHOT_DIR) {
    await viewAt(3150, 1500, 5);
    await ready();
    await page.screenshot({ path: `${process.env.SHOT_DIR}/skorpo_east_edge_hq.png` });
}
const onCorner = ({ edge, corner }) => near(edge[0], corner[0], 1) && near(edge[1], corner[1], 1);
check("Skorpo HQ: the corner tiles end at the measured rectangle, within a pixel of zoom 4",
    onCorner(northWest) && onCorner(southEast) && southEast.edge[0] - southEast.grid[0] > 10, JSON.stringify({ northWest, southEast }));

check("no page error, no console error", problems.length === 0, problems.join(" | ") || "clean");
await browser.close();
process.exit(failures ? 1 : 0);
