// Checks the in-game-style grid of the Deadline SquadCalc in Chromium: the grid starts at the game's minimap corner
// (MapTextureCorner0/1 of the layer's SQWorldSettings) and not at the map image's corner.
//
//     node grid_check.mjs <site URL>
//
// Skorpo without a layer: the grid starts 9.5 m east of its image (SDK_data.minimap.game). Chora with the layer
// Chora_Skirmish_v1 (needs the layer API): it starts 1007 m east and 1222 m south, and returns to the map's
// corner when the layer is cleared. Environment as browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node grid_check.mjs <site URL>");
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

/** The grid's origin offset (m) and the longitude of its first keypad line in metres east of the image corner */
const gridState = () => page.evaluate(() => {
    const map = window.__App.minimap;
    const vertical = map.grid.kpLines.map((line) => line.getLatLngs()).filter(([a, b]) => a.lng === b.lng).map(([a]) => a.lng);
    const horizontal = map.grid.kpLines.map((line) => line.getLatLngs()).filter(([a, b]) => a.lat === b.lat).map(([a]) => a.lat);
    return {
        offset: map.grid.originOffset,
        firstEast: Math.min(...vertical) * map.mapToGameScale,
        firstSouth: -Math.max(...horizontal) * map.mapToGameScaleY,
        map: map.activeMap.name,
    };
});
const ready = () => page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !window.__App.minimap._spinning, null, { timeout: 120000 });
const near = (a, b) => Math.abs(a - b) < 0.05;

await page.goto(`${base}/?map=Skorpo`, { waitUntil: "load" });
await ready();
let state = await gridState();
check("Skorpo: grid starts 9.5 m east of the image", state.map === "Skorpo" && near(state.offset[0], 9.5) && near(state.firstEast, 9.5) && near(state.firstSouth, 0), JSON.stringify(state));

await page.goto(`${base}/?map=Chora`, { waitUntil: "load" });
await ready();
await page.evaluate(() => window.__App.LAYER_SELECTOR.val("Chora_Skirmish_v1").trigger("change"));
await page.waitForFunction(() => window.__App?.minimap?.layer?.layerData?.rawName === "Chora_Skirmish_v1", null, { timeout: 120000 });
await ready();
state = await gridState();
check("Chora Skirmish v1: grid starts at the layer's corner", state.map === "Chora" && near(state.offset[0], 1007.16) && near(state.offset[1], 1221.99) && near(state.firstEast, 1007.16) && near(state.firstSouth, 1221.99), JSON.stringify(state));

await page.evaluate(() => window.__App.minimap.layer.clear());
state = await gridState();
check("clearing the layer returns the grid to the map's corner", near(state.offset[0], 0) && near(state.offset[1], 0) && near(state.firstEast, 0), JSON.stringify(state));

check("no page error", problems.length === 0, problems.join(" | ") || "clean");
await browser.close();
process.exit(failures ? 1 : 0);
