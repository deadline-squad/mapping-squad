// Checks in Chromium that the Deadline SquadCalc shows the bearing as the game's HUD compass shows it and draws its circles
// in metres on a map whose corners are not square (Skorpo, 6849 m by 6869 m).
//
//     node coords_check.mjs <site URL> [--shots <dir>]
//
// The compass (native USQCompassMK2 of the Squad dedicated server build 26005357) cuts the bearing to a whole degree and
// pads it to three digits, in (0, 360]: the calculator shows those digits, then the tenth within that degree. A target
// 800 m from the weapon at 45.96 degrees reads 045.9 in its popup, its summary and the target dialog (the plain compass
// shows 046 only from 46.0, and %.1f would round it to 46.0), one due north reads 360.0, and the keypad panel shows
// 026.6 from B03-5-5 to C01-5-5 (300 m east, 600 m north). The help of the bearing (panel, target dialog) says that the
// compass cuts off the tenth, and the help of the distance in the target dialog that the game's marker distance is slant
// and cut to 50 m steps.
// Circles: the weapon's range ring (Mortar 1236.9 m, UB-32 2184.3 m), the FOB marker's construction (150 m) and
// exclusion (400 m) circles and a target's damage radii are their radius east to west and north to south within 1 cm,
// measured on the shape's geometry (bounds, drawn radii) and on its SVG path (whole pixels, within half a pixel at zoom 6).
// Screenshots go to --shots (default ./shots). Environment as browser_check.mjs. Exits with 1 on any failure.
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node coords_check.mjs <site URL> [--shots <dir>]");
    process.exit(2);
}
const shotsIndex = process.argv.indexOf("--shots");
const shots = resolve(shotsIndex > 0 ? process.argv[shotsIndex + 1] : "shots");
mkdirSync(shots, { recursive: true });

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

await page.goto(`${base}/?map=Skorpo`, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.activeMap?.name === "Skorpo" && window.__App.minimap.heightmap?.precise && !window.__App.minimap._spinning, null, { timeout: 120000 });
console.log(`site ${base}, SquadCalc ${await page.evaluate(() => window.__App.version)}`);

/** Select a weapon of weapons.js by its name */
const selectWeapon = (name) => page.evaluate(async (weaponName) => {
    const app = window.__App;
    const option = [...app.WEAPON_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `weapons:${weaponName}`);
    app.WEAPON_SELECTOR.val(option.value).trigger("change");
    await new Promise((done) => setTimeout(done, 300));
}, name);

/** The text of the tooltips shown after hovering an element */
async function tooltipOf(selector) {
    if (!(await page.$(selector))) return `no ${selector} on the page`;
    await page.mouse.move(0, 0);
    await page.waitForTimeout(300);
    await page.hover(selector);
    await page.waitForSelector(".tippy-box", { timeout: 5000 }).catch(() => null);
    await page.waitForTimeout(700);
    return page.evaluate(() => [...document.querySelectorAll(".tippy-box")].map((box) => box.textContent.trim()).join(" | "));
}

// The middle of the map, the weapon there and the target 800 m away at 45.96 degrees
const CENTRE = { lat: -128, lng: 128 };
const BEARING = 45.96;

await selectWeapon("Mortar");
await page.evaluate(({ centre, bearing }) => {
    const map = window.__App.minimap;
    const turn = bearing * Math.PI / 180;
    map.setView(centre, 6, { animate: false });
    map.createWeapon(centre);
    map.createTarget(map.fromMeters(centre, 800 * Math.sin(turn), 800 * Math.cos(turn)));
}, { centre: CENTRE, bearing: BEARING });
await page.waitForTimeout(500);

// --- The bearing as the game's compass shows it ------------------------------------------------------------------
const popup = await page.evaluate(() => {
    const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
    const content = target.calcMarker1.getContent();
    const box = document.createElement("div");
    box.innerHTML = content;
    return {
        bearing: target.firingSolution1.bearing,
        line: box.querySelector(".bearingUiCalc")?.textContent ?? null,
        tenth: box.querySelector(".bearingUiCalc .compassTenth")?.textContent ?? null,
        summary: target.getContent(target.firingSolution1, window.__App.minimap.activeWeaponsMarkers.getLayers()[0].angleType)[1],
    };
});
check("the page's bearing to the target is 45.96 degrees", Math.abs(popup.bearing - BEARING) < 1e-9, `${popup.bearing}`);
check("the popup shows 045.9°, the tenth smaller after the compass's three digits", popup.line === "045.9°" && popup.tenth === ".9", `${JSON.stringify(popup.line)}, tenth ${JSON.stringify(popup.tenth)}`);
check("the popup's summary gives the bearing as 045.9°", / - Bearing: 045\.9°$/.test(popup.summary), popup.summary);
const popupBox = await page.evaluate(() => {
    const map = window.__App.minimap;
    const target = map.activeTargetsMarkers.getLayers()[0];
    map.setView(target.getLatLng(), 6, { animate: false });
    const rect = target._icon.getBoundingClientRect();
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
});
await page.waitForTimeout(400);
await page.screenshot({ path: `${shots}/coords-popup-skorpo.png`, clip: { x: popupBox.x - 200, y: popupBox.y - 120, width: 400, height: 240 } });

await page.evaluate(() => {
    const map = window.__App.minimap;
    const target = map.activeTargetsMarkers.getLayers()[0];
    map.setView(target.getLatLng(), map.getMaxZoom() - 1, { animate: false });
});
await page.waitForTimeout(400);
const targetBox = await page.evaluate(() => {
    const rect = window.__App.minimap.activeTargetsMarkers.getLayers()[0]._icon.getBoundingClientRect();
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
});
await page.mouse.click(targetBox.x, targetBox.y);
await page.waitForSelector("#calcInformation[open]");
await page.waitForTimeout(400);
const dialog = await page.evaluate(() => document.querySelector("#sim1 .infBearing").textContent);
check("the target dialog shows 045.9°", dialog === "045.9°", JSON.stringify(dialog));
const bearingHelp = await tooltipOf("#sim1 .infBearingTooltip");
check("the target dialog's help of the bearing says the compass cuts off the tenth", /cuts off the tenth: it shows 045 from 45\.0° to 45\.9°/.test(bearingHelp), bearingHelp);
await page.screenshot({ path: `${shots}/coords-dialog-bearing-help.png` });
const distanceHelp = await tooltipOf("#sim1 .infDistanceTooltip");
check("the target dialog's help of the distance says the game's marker distance is slant and cut to 50 m", /slant/.test(distanceHelp) && /50 m/.test(distanceHelp), distanceHelp);
await page.screenshot({ path: `${shots}/coords-dialog-distance-help.png` });
await page.keyboard.press("Escape");

const north = await page.evaluate(({ centre }) => {
    const map = window.__App.minimap;
    map.activeTargetsMarkers.clearLayers();
    const target = map.createTarget(map.fromMeters(centre, 0, 500)) || map.activeTargetsMarkers.getLayers()[0];
    const box = document.createElement("div");
    box.innerHTML = target.calcMarker1.getContent();
    return { bearing: target.firingSolution1.bearing, line: box.querySelector(".bearingUiCalc")?.textContent ?? null };
}, { centre: CENTRE });
check("a target due north reads 360.0°, as the game's compass gives north", north.bearing === 0 && north.line === "360.0°", JSON.stringify(north));

await page.evaluate(() => {
    const app = window.__App;
    if (app.ui !== 0) app.switchUI();
    document.getElementById("mortar-location").value = "B03-5-5";
    document.getElementById("target-location").value = "C01-5-5";
    app.shoot();
});
await page.waitForTimeout(900);
const panel = await page.evaluate(() => ({ text: document.getElementById("bearingNum").textContent, tenth: document.querySelector("#bearingNum .compassTenth")?.textContent ?? null }));
check("the keypad panel shows 026.6 from B03-5-5 to C01-5-5 (26.565 degrees)", panel.text === "026.6" && panel.tenth === ".6", JSON.stringify(panel));
const panelHelp = await tooltipOf("#bearingNum");
check("the panel's help of the bearing says the compass cuts off the tenth", /cuts off the tenth/.test(panelHelp), panelHelp);
await page.screenshot({ path: `${shots}/coords-panel-bearing-help.png` });
await page.mouse.move(0, 0);
await page.evaluate(() => window.__App.switchUI());

// --- Circles in metres -----------------------------------------------------------------------------------------
/**
 * The radii of a drawn shape in metres: east to west and north to south from its geometry (Leaflet bounds of a circle,
 * the drawn radii and tilt of an ellipse), and from the arc radii of its SVG path (whole pixels) at the map's zoom
 */
const MEASURE = `(shape) => {
    const map = window.__App.minimap;
    const zoom = 2 ** map.getZoom();
    const pxEast = zoom * map.gameToMapScale, pxNorth = zoom * map.gameToMapScaleY;
    const d = shape._path.getAttribute("d");
    if (shape._radiusX !== undefined) {
        const tilt = shape._tilt;
        const halfWidth = Math.hypot(shape._radiusX * Math.cos(tilt), shape._radiusY * Math.sin(tilt));
        const halfHeight = Math.hypot(shape._radiusX * Math.sin(tilt), shape._radiusY * Math.cos(tilt));
        return { ew: halfWidth / pxEast, ns: halfHeight / pxNorth, d: d.slice(0, 80) };
    }
    const bounds = shape.getBounds();
    const arc = d.match(/a(-?[0-9.]+),(-?[0-9.]+)/);
    return {
        ew: (bounds.getEast() - bounds.getWest()) / 2 * map.mapToGameScale,
        ns: (bounds.getNorth() - bounds.getSouth()) / 2 * map.mapToGameScaleY,
        svg: arc ? { ew: Number(arc[1]) / pxEast, ns: Number(arc[2]) / pxNorth, halfPixel: 0.5 / pxNorth } : null,
    };
}`;

const radiusCheck = (label, radius, seen) => {
    const error = Math.max(Math.abs(seen.ew - radius), Math.abs(seen.ns - radius));
    const svg = seen.svg ? `; SVG arcs ${seen.svg.ew.toFixed(3)} m east-west, ${seen.svg.ns.toFixed(3)} m north-south (half a pixel ${seen.svg.halfPixel.toFixed(3)} m)` : "";
    const svgOk = !seen.svg || (Math.abs(seen.svg.ew - radius) <= seen.svg.halfPixel * 1.01 && Math.abs(seen.svg.ns - radius) <= seen.svg.halfPixel * 1.01);
    check(`${label}: ${radius} m east to west and north to south within 1 cm`, error <= 0.01 && svgOk,
        `${seen.ew.toFixed(4)} m east-west, ${seen.ns.toFixed(4)} m north-south (off by ${(seen.ew - radius).toPrecision(2)} m and ${(seen.ns - radius).toPrecision(2)} m)${svg}`);
};

await page.evaluate(({ centre }) => window.__App.minimap.setView(centre, 6, { animate: false }), { centre: CENTRE });
await page.waitForTimeout(400);
for (const name of ["Mortar", "UB-32"]) {
    await selectWeapon(name);
    const ring = await page.evaluate(`(() => { const weapon = window.__App.minimap.activeWeaponsMarkers.getLayers()[0]; return { radius: window.__App.activeWeapon.getMaxDistance(), seen: (${MEASURE})(weapon.rangeMarker) }; })()`);
    radiusCheck(`Skorpo, the ${name}'s range ring`, ring.radius, ring.seen);
}
await page.evaluate(() => {
    const map = window.__App.minimap;
    map.activeWeaponsMarkers.getLayers()[0].fire("pointerover");
});
await page.waitForTimeout(300);
await page.screenshot({ path: `${shots}/coords-ub32-ring-skorpo.png` });
await selectWeapon("Mortar");

const fob = await page.evaluate(`(() => {
    const map = window.__App.minimap;
    map.createMarker(map.fromMeters(${JSON.stringify(CENTRE)}, -1500, -1500), "default", "deployables", "deployable_fob");
    const marker = map.activeMarkers.getLayers().at(-1);
    return { construction: (${MEASURE})(marker.constructionRange), exclusion: (${MEASURE})(marker.exclusionRange) };
})()`);
radiusCheck("Skorpo, a FOB marker's construction circle", 150, fob.construction);
radiusCheck("Skorpo, a FOB marker's exclusion circle", 400, fob.exclusion);

const damage = await page.evaluate(`(() => {
    const app = window.__App, map = app.minimap;
    app.userSettings.set("spreadRadius", false);
    app.userSettings.set("damageRadius", true);
    const target = map.activeTargetsMarkers.getLayers()[0];
    target.updateDamageRadius();
    return {
        radii: [app.activeWeapon.hundredDamageRadius, app.activeWeapon.twentyFiveDamageRadius],
        hundred: (${MEASURE})(target.hundredDamageRadius),
        twentyFive: (${MEASURE})(target.twentyFiveDamageRadius),
    };
})()`);
radiusCheck("Skorpo, a target's kill radius", damage.radii[0], damage.hundred);
radiusCheck("Skorpo, a target's 25-damage radius", damage.radii[1], damage.twentyFive);

check("no page error", problems.length === 0, problems.join(" | ") || "clean");
await browser.close();
console.log(failures ? `${failures} FAIL` : "all coords checks passed");
process.exit(failures ? 1 : 0);
