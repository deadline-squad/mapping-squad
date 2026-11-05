// Checks the reverse-position heatmap (C5) and the damage zone with the volume layer as cover (C6) of the Deadline
// SquadCalc in a real browser (Chromium through Playwright), deadline-squad/deadline-squadcalc#22:
//   - the heatmap is off by default: the target dialog has no button without the volume layer or for a weapon that is not
//     direct fire, and nothing of it (module, precision region) is requested before the button is pressed;
//   - on Jensen, for a target in a window of a building and a grenade launcher, the button loads the module, the
//     worker traces the lines of fire with the voxels and the target's precision region (the legend says how far the
//     exact triangles reach), the image and the legend are drawn, and hiding, dragging the target and turning the volume
//     setting off remove it;
//   - the page's own run with the validation's parameters (--reference: the output of engine/tools/js/heatmap_validate.mjs
//     for this target) gives the same clear, blocked and out positions as the validation's node run and, against the exact triangle tracer, no false
//     clear and no false blocked position;
//   - the damage zone of an explosion on that target is computed by the volume layer's worker with the voxels as cover and
//     differs from the heightmap's (Cover).
// Screenshots go to --shots (default ./shots).
//
//     node heatmap_check.mjs <site URL> --reference <dir> [--shots <dir>] [--height <kind>:<index>]
//
// --height names the height of the target that the reference holds (default window:0, the only window of the building at
// (131, -199), 1.6 m over the landscape, which the exact-voxeliser file keeps; the window at (127, -205) of the sample-lattice
// file is closed in it, so a reference written for another target or height needs its own `--height`, e.g. roof:0).

// <site URL> is a served build with `npm run build:engine` done, the maps' volume files and the Jensen region
// (tools/volumetric/py/publish_regions.py) under /heightmaps/. Environment: PLAYWRIGHT_CORE, CHROME as for
// browser_check.mjs. Exits with 1 on any failure.
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const base = process.argv[2];
const argument = (name, fallback) => (process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : fallback);
const referenceDir = argument("--reference");
if (!base || !referenceDir) {
    console.error("usage: node heatmap_check.mjs <site URL> --reference <dir> [--shots <dir>] [--height <kind>:<index>]");
    process.exit(2);
}
const shots = resolve(argument("--shots", "shots"));
const HEIGHT = argument("--height", "window:0");
const [HEIGHT_KIND, HEIGHT_INDEX = "0"] = HEIGHT.split(":");
/** The dialog's text for the chosen height: the window of the validation is the one 1.6 m over the landscape */
const HEIGHT_OPTION = HEIGHT_KIND === "window" ? /^Window \+1\.6/ : new RegExp(`^${HEIGHT_KIND}`, "i");
mkdirSync(shots, { recursive: true });

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

// Jensen: the target of the validation, in a window of a building (1.6 m over the landscape), inside the precision region
// centred at (221, -229), 90 m from its centre along X: the exact triangles reach 60 m around the target
const TARGET = { x: 131, y: -199 };
const WINDOW = { x0: -404, y0: -1104, size: 1000 };
const VALIDATION_WEAPON = "DF_M2A1_50";
const SHORT_RANGE_WEAPON = "DF_M203_M320_GP_25_HK79_SL40";

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/** Open SquadCalc on the map named `mapName` with window.__App and a log of problems and requests */
async function open(mapName) {
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
        requests.push(response.url());
        if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`);
    });
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => window.__App?.minimap?.heightmap?.precise, null, { timeout: 120000 });
    await page.evaluate(async (name) => {
        const app = window.__App;
        const option = [...app.MAP_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `maps:${name}`);
        app.MAP_SELECTOR.val(option.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 0));
    }, mapName);
    await page.waitForFunction((name) => {
        const map = window.__App.minimap;
        return map.activeMap.name === name && map.heightmap?.precise && !map._spinning;
    }, mapName, { timeout: 120000 });
    return { context, page, problems, requests };
}

/** Select a weapon of weapons.js by its name */
const selectWeapon = (page, name) => page.evaluate(async (weaponName) => {
    const app = window.__App;
    const option = [...app.WEAPON_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `weapons:${weaponName}`);
    app.WEAPON_SELECTOR.val(option.value).trigger("change");
    await new Promise((resolve) => setTimeout(resolve, 300));
}, name);

/** Click the marker icon of the first target as a user: centre the map on it, then click the icon */
async function clickTarget(page) {
    await page.evaluate(() => {
        const map = window.__App.minimap;
        map.setView(map.activeTargetsMarkers.getLayers()[0].getLatLng(), map.getMaxZoom() - 1, { animate: false });
    });
    await page.waitForTimeout(400);
    const box = await page.evaluate(() => {
        const rect = window.__App.minimap.activeTargetsMarkers.getLayers()[0]._icon.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    });
    await page.mouse.click(box.x, box.y);
}

const reference = JSON.parse(readFileSync(`${referenceDir}/heatmap-jensen-${TARGET.x}_${TARGET.y}.json`)).find((entry) => entry.height === HEIGHT);
if (!reference) throw new Error(`the reference has no ${HEIGHT} run`);

const { context, page, problems, requests } = await open("Jensen");

/** Bounds of the volume files' frame (meta.json): the layer keeps them only while it is on */
const bounds = await page.evaluate(async () => {
    const mapName = window.__App.minimap.activeMap.mapURL.split("/").filter(Boolean).pop();
    return (await (await fetch(`/heightmaps/${mapName}/meta.json`)).json()).bounds_m;
});

/** Place a weapon and a target at positions of the volume files' frame */
const place = (weaponAt, targetAt) => page.evaluate(({ weaponAt, targetAt, b }) => {
    const map = window.__App.minimap;
    const latlng = (point) => ({ lng: ((point.x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((point.y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize });
    map.activeWeaponsMarkers.clearLayers();
    map.activeTargetsMarkers.clearLayers();
    map.createWeapon(latlng(weaponAt));
    map.createTarget(latlng(targetAt));
}, { weaponAt, targetAt, b: bounds });

// --- Off by default ----------------------------------------------------------------------------------------------------
await selectWeapon(page, SHORT_RANGE_WEAPON);
await place({ x: 60, y: -195 }, TARGET);
await clickTarget(page);
await page.waitForSelector("#calcInformation[open]");
await page.waitForTimeout(300);
let row = await page.evaluate(() => ({ hidden: document.getElementById("positionHeatRow").hidden, heatmap: window.__App.minimap.positionHeatmap }));
check("volume layer off: the dialog has no firing positions button and there is no heatmap", row.hidden && row.heatmap === null, JSON.stringify(row));
await page.keyboard.press("Escape");

await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
await page.waitForFunction(() => window.__App.minimap.volume.ready, null, { timeout: 120000 });
await selectWeapon(page, "Mortar");
await clickTarget(page);
await page.waitForSelector("#calcInformation[open]");
await page.waitForTimeout(300);
row = await page.evaluate(() => document.getElementById("positionHeatRow").hidden);
check("volume layer on, a weapon that is not direct fire: no button", row === true, String(row));
await page.keyboard.press("Escape");

await selectWeapon(page, SHORT_RANGE_WEAPON);
await place({ x: 60, y: -195 }, TARGET);
await clickTarget(page);
await page.waitForSelector("#calcInformation[open]");
await page.waitForFunction(() => !document.getElementById("targetHeightRow").hidden, null, { timeout: 20000 });
const visible = await page.evaluate(() => ({ hidden: document.getElementById("positionHeatRow").hidden, label: document.getElementById("positionHeatButton").textContent, heatmap: window.__App.minimap.positionHeatmap }));
check("volume layer on, a direct-fire weapon: the button is offered and nothing of the heatmap is loaded", !visible.hidden && visible.label === "Show on the map" && visible.heatmap === null
    && !requests.some((url) => /region_|positionHeat/.test(url)), JSON.stringify(visible));
await page.screenshot({ path: `${shots}/heatmap-dialog-button.png` });

// --- The heatmap of the window ------------------------------------------------------------------------------------
const options = await page.$$eval("#targetHeightSelect option", (list) => list.map((option) => option.textContent));
const windowOption = options.findIndex((text) => HEIGHT_OPTION.test(text));
check(`the dialog offers the height ${HEIGHT} of the building`, windowOption > 0, JSON.stringify(options));
await page.selectOption("#targetHeightSelect", { index: windowOption });
await page.waitForTimeout(500);

const scriptsBefore = requests.filter((url) => /\.js(\?|$)/.test(url));
await page.click("#positionHeatButton");
await page.waitForFunction(() => window.__App.minimap.positionHeatmap?.result, null, { timeout: 240000 });
await page.waitForFunction(() => document.querySelector(".positionHeatOverlay"), null, { timeout: 30000 });
const shown = await page.evaluate(() => {
    const heat = window.__App.minimap.positionHeatmap;
    const { values, exact, margin, loadMs, computeMs, wallMs, range, cell, rays } = heat.result;
    let clear = 0;
    let blocked = 0;
    for (const value of values) {
        if (value === 1) blocked++;
        else if (value >= 2) clear++;
    }
    return {
        range, cell, rays, exact, margin, loadMs: Math.round(loadMs), computeMs: Math.round(computeMs), wallMs: Math.round(wallMs), clear, blocked,
        legend: getComputedStyle(document.getElementById("positionHeatLegend")).display, status: document.getElementById("positionHeatStatus").textContent,
        dialogOpen: document.getElementById("calcInformation").open, button: document.getElementById("positionHeatButton").textContent,
    };
});
const scriptsAfter = requests.filter((url) => /\.js(\?|$)/.test(url));
check("pressing the button loads the module on demand", scriptsAfter.length > scriptsBefore.length, JSON.stringify(scriptsAfter.filter((url) => !scriptsBefore.includes(url)).map((url) => url.split("/").pop())));
check("the target's precision region was fetched and used", requests.some((url) => /regions\/region_221_-229\.rtri/.test(url)) && shown.exact === true && shown.margin === 60, `exact ${shown.exact}, margin ${shown.margin} m, region load ${shown.loadMs} ms`);
check("the legend says how far the exact triangles reach", shown.legend === "block" && /Exact triangles within 60 m of the target/.test(shown.status), JSON.stringify(shown.status));
const live = await page.evaluate(() => { const status = document.getElementById("positionHeatStatus"); return { role: status.getAttribute("role"), live: status.getAttribute("aria-live") }; });
check("the legend's status line is a live region for screen readers", live.role === "status" && live.live === "polite", JSON.stringify(live));
check("the dialog closed to show the map, and the button now hides", shown.dialogOpen === false, JSON.stringify(shown));
check("positions are clear and blocked around the building", shown.clear > 0 && shown.blocked > 0, `${shown.clear} clear, ${shown.blocked} blocked of ${shown.rays * Math.floor(shown.range / shown.cell)} (range ${shown.range} m, cell ${shown.cell} m), computed in ${shown.computeMs} ms (wall ${shown.wallMs} ms)`);
await page.evaluate(() => {
    const map = window.__App.minimap;
    map.setView(map.activeTargetsMarkers.getLayers()[0].getLatLng(), map.getMaxZoom() - 2, { animate: false });
});
await page.waitForTimeout(1200);
await page.screenshot({ path: `${shots}/heatmap-window.png` });

// A target on open ground beside the building (no object over it): the shadows of the buildings
await place({ x: 60, y: -195 }, { x: 140, y: -205 });
const openGround = await page.evaluate(async () => {
    const map = window.__App.minimap;
    const heat = map.positionHeatmap;
    const target = map.activeTargetsMarkers.getLayers()[0];
    heat.toggle(target);
    for (let i = 0; i < 1200 && !(heat.result && document.querySelector(".positionHeatOverlay")); i++) await new Promise((resolve) => setTimeout(resolve, 100));
    let clear = 0;
    let blocked = 0;
    for (const value of heat.result.values) {
        if (value === 1) blocked++;
        else if (value >= 2) clear++;
    }
    map.setView(target.getLatLng(), map.getMaxZoom() - 2, { animate: false });
    return { clear, blocked, exact: heat.result.exact, status: document.getElementById("positionHeatStatus").textContent };
});
await page.waitForTimeout(1500);
await page.screenshot({ path: `${shots}/heatmap-open-ground.png` });
check("a target on open ground has a large clear area with the shadows of the buildings in it", openGround.clear > openGround.blocked / 4 && openGround.blocked > 0, JSON.stringify(openGround));
await page.evaluate(() => window.__App.minimap.positionHeatmap.hide());
await place({ x: 60, y: -195 }, TARGET);

// Voxels only: the same target without its region (a map entry removed in the page)
await page.evaluate(() => window.__App.minimap.positionHeatmap.hide());
const voxelOnly = await page.evaluate(async () => {
    const map = window.__App.minimap;
    const regions = map.volume.regions;
    map.volume.regions = [];
    const heat = map.positionHeatmap;
    heat.toggle(map.activeTargetsMarkers.getLayers()[0]);
    for (let i = 0; i < 600 && !heat.result; i++) await new Promise((resolve) => setTimeout(resolve, 100));
    await new Promise((resolve) => setTimeout(resolve, 500));
    const answer = { exact: heat.result.exact, status: document.getElementById("positionHeatStatus").textContent, computeMs: Math.round(heat.result.computeMs) };
    heat.hide();
    map.volume.regions = regions;
    return answer;
});
check("a target without a region says it is voxels only", voxelOnly.exact === false && /Voxels only/.test(voxelOnly.status), JSON.stringify(voxelOnly));

// Hiding, dragging, deleting and turning the layer off
const hide = async (how) => {
    await page.evaluate(() => {
        const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
        // The drag below is started and never dropped
        target.isDragging = false;
        window.__App.minimap.positionHeatmap.toggle(target);
    });
    await page.waitForFunction(() => document.querySelector(".positionHeatOverlay"), null, { timeout: 240000 });
    await page.evaluate(how);
    await page.waitForTimeout(300);
    return page.evaluate(() => ({ overlay: Boolean(document.querySelector(".positionHeatOverlay")), legend: getComputedStyle(document.getElementById("positionHeatLegend")).display, target: window.__App.minimap.positionHeatmap.target }));
};
let state = await hide(() => window.__App.minimap.positionHeatmap.toggle(window.__App.minimap.activeTargetsMarkers.getLayers()[0]));
check("the button hides the heatmap", !state.overlay && state.legend === "none" && state.target === null, JSON.stringify(state));
state = await hide(() => window.__App.minimap.activeTargetsMarkers.getLayers()[0]._handleDragStart());
check("dragging the target removes it", !state.overlay && state.legend === "none" && state.target === null, JSON.stringify(state));
state = await hide(() => window.__App.minimap.activeTargetsMarkers.getLayers()[0].delete());
check("deleting the target removes it", !state.overlay && state.legend === "none" && state.target === null, JSON.stringify(state));
await place({ x: 60, y: -195 }, TARGET);
state = await hide(() => window.__App.userSettings.set("volumeLayer", false));
check("turning the volume layer off removes it", !state.overlay && state.legend === "none" && state.target === null, JSON.stringify(state));
await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
await page.waitForFunction(() => window.__App.minimap.volume.ready, null, { timeout: 120000 });

// --- The page's run against the validation's --------------------------------------------------------------------------
const bins = (name) => new Uint8Array(readFileSync(`${referenceDir}/heatmap-jensen-${TARGET.x}_${TARGET.y}-${HEIGHT_KIND}${HEIGHT_INDEX}-${name}.bin`));
const pageRun = await page.evaluate(async ({ reference, weaponName }) => {
    const app = window.__App;
    const map = app.minimap;
    const option = [...app.WEAPON_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `weapons:${weaponName}`);
    app.WEAPON_SELECTOR.val(option.value).trigger("change");
    await new Promise((resolve) => setTimeout(resolve, 300));
    const weapon = app.activeWeapon;
    const b = map.volume.bounds;
    const latlng = { lng: ((reference.target.x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((reference.target.y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize };
    const params = {
        targetZ: reference.target.z - map.volume.zMin, elevated: true, shot: weapon.getShot(app.gravity * weapon.gravityScale, 1.5),
        range: reference.range, cell: reference.cell, rays: reference.rays, elevationLimits: weapon.minElevation, angleOffset: weapon.angleOffset || 0,
        lifespan: weapon.projectileLifespan, moa: weapon.moa,
    };
    const answer = await map.volume.positionHeatmap(params, latlng, (from, east, north) => map.fromMeters(from, east, north), () => true);
    return { values: Array.from(answer.values), exact: answer.exact, margin: answer.margin, loadMs: answer.loadMs, computeMs: answer.computeMs };
}, { reference, weaponName: VALIDATION_WEAPON });
const precision = bins("precision");
const exactValues = bins("exact");
// The page and node run the same classifier and engine, but the target's height goes through a subtraction and an addition of the
// map's lowest level and Chromium's and node's Math functions may differ in the last bit: a line that touches a voxel face to the
// last bit flips now and then (the share allowed is 0.05 %), and a score moves by one step
const kindOf = (value) => (value === 0 ? "out" : value === 1 ? "blocked" : "clear");
let differing = 0;
let kindsDiffering = 0;
let largest = 0;
pageRun.values.forEach((value, i) => {
    if (value === precision[i]) return;
    differing++;
    largest = Math.max(largest, Math.abs(value - precision[i]));
    if (kindOf(value) !== kindOf(precision[i])) kindsDiffering++;
});
check("the page's run gives the validation's precision run: the same clear, blocked and out positions", kindsDiffering <= precision.length / 2000 && differing <= precision.length / 1000 && pageRun.values.length === precision.length && pageRun.exact,
    `${kindsDiffering} positions differ in kind, ${differing} of ${precision.length} in value (by at most ${largest}), exact ${pageRun.exact}, region load ${Math.round(pageRun.loadMs)} ms, trace ${Math.round(pageRun.computeMs)} ms`);

const stride = Math.floor(reference.range / reference.cell) + 1;
let cells = 0;
let falseClear = 0;
let falseBlocked = 0;
let exactClear = 0;
for (let ray = 0; ray < reference.rays; ray++) {
    const heading = (2 * Math.PI * ray) / reference.rays;
    for (let j = 1; j < stride; j++) {
        const x = TARGET.x + Math.cos(heading) * j * reference.cell;
        const y = TARGET.y - Math.sin(heading) * j * reference.cell;
        if (x < WINDOW.x0 || x > WINDOW.x0 + WINDOW.size || y < WINDOW.y0 || y > WINDOW.y0 + WINDOW.size) continue;
        const mine = pageRun.values[ray * stride + j];
        const truth = exactValues[ray * stride + j];
        if (mine === 0 || truth === 0) continue;
        cells++;
        if (truth >= 2) exactClear++;
        if (mine >= 2 && truth === 1) falseClear++;
        if (mine === 1 && truth >= 2) falseBlocked++;
    }
}
// The validation's own precision run is the bound: 0 and 0 for the window of the sample-lattice file, a handful of false blocked
// positions beyond the region's reach (the voxels decide there) for the roof of the exact-voxeliser file
const allowed = reference.precision;
check("against the exact triangles the page's precision run is no worse than the validation's (none for a target the region covers)", falseClear <= allowed.falseClear && falseBlocked <= allowed.falseBlocked && exactClear > 0,
    `${cells} positions in the window with a shooter, ${exactClear} clear by the exact tracer, false clear ${falseClear} (validation ${allowed.falseClear}), false blocked ${falseBlocked} (validation ${allowed.falseBlocked})`);

// --- Cover: the damage zone with the voxels ----------------------------------------------------------------------------
await selectWeapon(page, SHORT_RANGE_WEAPON);
await place({ x: 60, y: -195 }, TARGET);
const zone = await page.evaluate(async ({ kind, above }) => {
    const map = window.__App.minimap;
    const target = map.activeTargetsMarkers.getLayers()[0];
    const settle = async (test) => {
        for (let i = 0; i < 300 && !test(); i++) await new Promise((resolve) => setTimeout(resolve, 100));
    };
    const pixels = async (target) => {
        const image = new Image();
        image.src = target.coverOverlay._url;
        await image.decode();
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d");
        context.drawImage(image, 0, 0);
        const data = context.getImageData(0, 0, image.width, image.height).data;
        const counts = { kill: 0, wound: 0, covered: 0 };
        for (let i = 0; i < data.length; i += 4) {
            if (data[i + 3] === 0) continue;
            // The canvas hands the colours back with the rounding of a premultiplied alpha: classify by hue
            if (data[i + 2] > 140 && data[i] < 100) counts.covered++;
            else if (data[i + 1] < 110) counts.kill++;
            else counts.wound++;
        }
        return counts;
    };
    // The window for the volume run
    const found = await map.volume.heightsAt(target.getLatLng());
    const floor = found.choices.find((choice) => choice.kind === kind && (above === null || Math.abs(choice.above - above) < 0.2));
    window.__App.userSettings.set("volumeLayer", false);
    target.heightChoice = null;
    target.updateCoverZone();
    await settle(() => target.coverOverlay);
    const heightmap = { signature: target.coverSignature, ...await pixels(target) };
    window.__App.userSettings.set("volumeLayer", true);
    await settle(() => map.volume.ready);
    target.heightChoice = floor;
    target.updateCoverZone();
    await settle(() => target.coverOverlay && target.coverSignature.includes("volume:"));
    const volume = { signature: target.coverSignature, ...await pixels(target) };
    return { heightmap, volume };
}, { kind: HEIGHT_KIND, above: HEIGHT_KIND === "window" ? 1.6 : null });
check("with the volume layer the damage zone is computed with the voxels as cover", /heightmap$/.test(zone.heightmap.signature) && /volume:/.test(zone.volume.signature)
    && zone.volume.covered > 0 && zone.volume.kill + zone.volume.wound > 0 && (zone.volume.covered !== zone.heightmap.covered || zone.volume.kill !== zone.heightmap.kill), JSON.stringify(zone));
await page.evaluate(() => {
    const map = window.__App.minimap;
    map.setView(map.activeTargetsMarkers.getLayers()[0].getLatLng(), map.getMaxZoom() - 1, { animate: false });
});
await page.waitForTimeout(1200);
await page.screenshot({ path: `${shots}/damage-zone-voxel-cover.png` });

check("console and requests are clean", problems.length === 0, problems.join(" | ") || "no errors, warnings or failed requests");
await context.close();
await browser.close();
if (failures) {
    console.error(`${failures} failed`);
    process.exit(1);
}
console.log("all ok");
