// How much sharper the upstream HQ tiles draw Skorpo's basemap than the single image, in Chromium. With the setting
// "high quality images" the page shows the map as basemap_hq tiles (8192 px across at zoom 5), without it as
// basemap.webp (4096 px). The same view, 300 m inside the east edge and 2000 m south of the north edge (the image
// corner), is captured at the page's zooms 2 to 8 both ways, without grid, markers or controls, and each 800 x 600 px
// frame is measured: the mean gradient magnitude of its luminance (Pillow's L of RGB, scipy.ndimage.sobel on both
// axes with its border rule), tiles over image, and the mean absolute difference of the two frames (a few levels:
// the same view).
//
//     node hq_sharpness.mjs <site URL> [--shots <dir>]
//
// Environment as browser_check.mjs. --shots saves the frames (skorpo_hq<0|1>_z<zoom>.png). Exits with 1 when a frame
// shows the other kind of layer (tiles without the setting, the image with it).
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const { mkdirSync } = await import("node:fs");

const base = process.argv[2];
if (!base) {
    console.error("usage: node hq_sharpness.mjs <site URL> [--shots <dir>]");
    process.exit(2);
}
const shotsAt = process.argv.indexOf("--shots");
const shots = shotsAt > 0 ? process.argv[shotsAt + 1] : null;
if (shots) mkdirSync(shots, { recursive: true });
const ZOOMS = [2, 3, 4, 5, 6, 7, 8];
const CLIP = { x: 200, y: 150, width: 800, height: 600 };
// Skorpo's image corners span 6849 m east to west
const VIEW_EAST_M = 6849 - 300;
const VIEW_SOUTH_M = 2000;

/** Mean Sobel gradient magnitude of a PNG's luminance and the frame's luminance, computed in a blank page. */
const measure = (page, png) => page.evaluate(async (url) => {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0);
    const { data, width, height } = context.getImageData(0, 0, image.width, image.height);
    const luminance = new Float64Array(width * height);
    for (let i = 0; i < width * height; i++) {
        luminance[i] = (data[4 * i] * 19595 + data[4 * i + 1] * 38470 + data[4 * i + 2] * 7471 + 0x8000) >> 16;
    }
    // scipy's "reflect" border: the row or column before the first is the first
    const at = (row, col) => luminance[Math.min(height - 1, Math.max(0, row)) * width + Math.min(width - 1, Math.max(0, col))];
    let sum = 0;
    for (let row = 0; row < height; row++) {
        for (let col = 0; col < width; col++) {
            const down = (at(row + 1, col - 1) + 2 * at(row + 1, col) + at(row + 1, col + 1))
                - (at(row - 1, col - 1) + 2 * at(row - 1, col) + at(row - 1, col + 1));
            const across = (at(row - 1, col + 1) + 2 * at(row, col + 1) + at(row + 1, col + 1))
                - (at(row - 1, col - 1) + 2 * at(row, col - 1) + at(row + 1, col - 1));
            sum += Math.hypot(down, across);
        }
    }
    return { gradient: sum / (width * height), luminance: Array.from(luminance) };
}, `data:image/png;base64,${png.toString("base64")}`);

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const blank = await browser.newPage();
const frames = {};
let failures = 0;
for (const hq of [0, 1]) {
    const context = await browser.newContext({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1 });
    await context.addInitScript((value) => {
        localStorage.setItem("settings-highquality-images", String(value));
        localStorage.setItem("settings-grid", "0");
    }, hq);
    await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
        if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
        await route.fulfill({ response, body: patched });
    });
    const page = await context.newPage();
    await page.goto(`${base}/?map=Skorpo&type=basemap`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__App?.minimap?.activeLayer && !window.__App.minimap._spinning, null, { timeout: 120000 });
    await page.addStyleTag({ content: ".leaflet-overlay-pane svg, .leaflet-overlay-pane canvas, .leaflet-marker-pane, .leaflet-tooltip-pane, #mapLayerMenu, header, nav, .leaflet-control-container, #loader { display: none !important; }" });
    for (const zoom of ZOOMS) {
        await page.evaluate(({ z, east, south }) => {
            const map = window.__App.minimap;
            map.setView([-south * map.gameToMapScaleY, east * map.gameToMapScale], z, { animate: false });
        }, { z: zoom, east: VIEW_EAST_M, south: VIEW_SOUTH_M });
        await page.waitForTimeout(800);
        await page.waitForFunction(() => {
            const layer = window.__App.minimap.activeLayer;
            if (layer._tiles) return Object.values(layer._tiles).every((tile) => tile.loaded);
            const element = layer.getElement();
            return element.complete && element.naturalWidth > 0;
        }, null, { timeout: 60000 });
        await page.waitForTimeout(1500);
        const tiles = await page.evaluate(() => Boolean(window.__App.minimap.activeLayer._tiles));
        if (tiles !== Boolean(hq)) {
            console.log(`FAIL zoom ${zoom}: ${hq ? "the setting on" : "the setting off"} shows ${tiles ? "tiles" : "the image"}`);
            failures++;
        }
        const png = await page.screenshot({ clip: CLIP, ...(shots ? { path: `${shots}/skorpo_hq${hq}_z${zoom}.png` } : {}) });
        frames[`${hq}_${zoom}`] = await measure(blank, png);
    }
    await context.close();
}
await browser.close();

console.log("zoom  gradient image  gradient tiles  tiles / image  mean |difference|");
for (const zoom of ZOOMS) {
    const image = frames[`0_${zoom}`];
    const tiles = frames[`1_${zoom}`];
    const difference = image.luminance.reduce((sum, value, i) => sum + Math.abs(value - tiles.luminance[i]), 0) / image.luminance.length;
    console.log(`${String(zoom).padStart(4)}  ${image.gradient.toFixed(3).padStart(14)}  ${tiles.gradient.toFixed(3).padStart(14)}  ` +
        `${(tiles.gradient / image.gradient).toFixed(3).padStart(13)}  ${difference.toFixed(2).padStart(17)}`);
}
process.exit(failures ? 1 : 0);
