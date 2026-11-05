// Checks the target heights of the volume layer and the structure damage of the Deadline SquadCalc in a real browser
// (Chromium through Playwright), deadline-squad/deadline-squadcalc#22 C3, C4, C7b:
//   - the setting is off by default and the target dialog has no height control while it is off or the map has no
//     volume file; nothing of the layer is requested;
//   - with the setting on, the target dialog of a target inside a Jensen building lists the heights found by the
//     vertical ray (floor, ceiling, roof, window, doorway), the chosen one changes the firing solution (target height,
//     height difference) and the line-of-fire answer, shows in the popup, and goes back to the ground;
//   - a deployable marker (FOB radio, HAB) opens a popup with the shells that destroy it for the selected ammunition,
//     the target dialog shows the same for a target on the marker, AP/machine-gun ammunition says "no structure damage",
//     the tooltip says which part is read from the server and which is inferred, and the Russian locale has the strings.
// Screenshots go to the directory given by --shots (default ./shots).
//
//     node targets_check.mjs <site URL> [--shots <dir>]
//
// <site URL> is a served build with `npm run build:engine` done and the maps' volume files under /heightmaps/.
// Environment: PLAYWRIGHT_CORE, CHROME as for browser_check.mjs. Exits with 1 on any failure.
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const base = process.argv[2];
if (!base) {
    console.error("usage: node targets_check.mjs <site URL> [--shots <dir>]");
    process.exit(2);
}
const shotsIndex = process.argv.indexOf("--shots");
const shots = resolve(shotsIndex > 0 ? process.argv[shotsIndex + 1] : "shots");
mkdirSync(shots, { recursive: true });

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

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

/** LatLng of a position in the frame of the volume files (Unreal metres), a function to run in the page */
const LATLNG_AT = `(x, y) => { const map = window.__App.minimap; const b = map.volume.bounds; return { lng: ((x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize }; }`;

/** Click the marker icon of a target (or deployable marker) as a user: centre the map on it, then click the icon */
async function clickMarker(page, how) {
    await page.evaluate(({ how }) => {
        const map = window.__App.minimap;
        const marker = how === "target" ? map.activeTargetsMarkers.getLayers()[0] : map.activeMarkers.getLayers().at(-1);
        map.setView(marker.getLatLng(), map.getMaxZoom() - 1, { animate: false });
    }, { how });
    await page.waitForTimeout(400);
    const box = await page.evaluate(({ how }) => {
        const map = window.__App.minimap;
        const marker = how === "target" ? map.activeTargetsMarkers.getLayers()[0] : map.activeMarkers.getLayers().at(-1);
        const rect = marker._icon.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    }, { how });
    await page.mouse.click(box.x, box.y);
}

// ---------------------------------------------------------------------------------------------------------------
// Jensen: a building with several storeys, a window and a doorway (found with the vertical ray, see the cases below)
const BUILDING = { x: 94.517, y: -173.986 };
const WINDOW_POINT = { x: 82.81, y: -164.666 };
const WEAPON_FROM = { x: 40, y: -200 };

{
    const { context, page, problems, requests } = await open("Jensen");
    const volumeRequests = () => requests.filter((url) => /volume\.vcol|terrain\.bin|\/engine\//.test(url)).length;

    const setting = await page.evaluate(() => ({ fresh: window.__App.userSettings.volumeLayer, stored: localStorage.getItem("settings-volume-layer") }));
    check("the volume setting is off by default", setting.fresh === false && setting.stored !== "1", JSON.stringify(setting));

    // Setting off: a target dialog has no height control
    await selectWeapon(page, "Mortar");
    // The frame conversion needs meta.json's bounds, which the layer reads when it is on: read them once here
    const bounds = await page.evaluate(async () => {
        const mapName = window.__App.minimap.activeMap.mapURL.split("/").filter(Boolean).pop();
        return (await (await fetch(`/heightmaps/${mapName}/meta.json`)).json()).bounds_m;
    });
    const toLatLng = (point) => page.evaluate(({ point, b }) => {
        const map = window.__App.minimap;
        return { lng: ((point.x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((point.y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize };
    }, { point, b: bounds });
    const place = async (weaponAt, targetAt) => page.evaluate(({ weaponAt, targetAt }) => {
        const map = window.__App.minimap;
        map.activeWeaponsMarkers.clearLayers();
        map.activeTargetsMarkers.clearLayers();
        map.createWeapon(weaponAt);
        map.createTarget(targetAt);
    }, { weaponAt: await toLatLng(WEAPON_FROM), targetAt: await toLatLng(targetAt) });
    await place(WEAPON_FROM, BUILDING);

    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForTimeout(300);
    const off = await page.evaluate(() => ({ hidden: document.getElementById("targetHeightRow").hidden, volume: window.__App.minimap.volume.state }));
    check("setting off: the target dialog has no height control and the layer is not loaded", off.hidden && off.volume === "idle" && volumeRequests() === 0, JSON.stringify({ ...off, requests: volumeRequests() }));
    await page.keyboard.press("Escape");

    // Setting on
    await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
    await page.waitForFunction(() => window.__App.minimap.volume.ready, null, { timeout: 120000 });
    await place(WEAPON_FROM, BUILDING);
    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForFunction(() => !document.getElementById("targetHeightRow").hidden, null, { timeout: 10000 });
    const options = await page.$$eval("#targetHeightSelect option", (list) => list.map((option) => option.textContent));
    check("setting on: the dialog lists the ground, the heights of the vertical ray and the landscape under the building", options[0].startsWith("Ground") && options.at(-1).startsWith("Landscape") && ["Roof", "Ceiling", "Floor", "Window"].every((kind) => options.some((text) => text.startsWith(kind))), JSON.stringify(options));
    await page.screenshot({ path: `${shots}/target-dialog-heights.png` });

    const ground = await page.evaluate(() => {
        const solution = window.__App.minimap.activeTargetsMarkers.getLayers()[0].firingSolution1;
        return { targetHeight: solution.targetHeight, heightDiff: solution.heightDiff, elevated: solution.elevatedTarget };
    });
    check("ground (default): the firing solution is the one of the heightmap", ground.elevated === false, JSON.stringify(ground));

    // Choose the floor of the second storey (the option after the ceiling that follows the roof)
    const chosen = options.findIndex((text) => text.startsWith("Floor"));
    await page.selectOption("#targetHeightSelect", { index: chosen });
    await page.waitForTimeout(600);
    const floor = await page.evaluate(() => {
        const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
        return {
            targetHeight: target.firingSolution1.targetHeight, heightDiff: target.firingSolution1.heightDiff, elevated: target.firingSolution1.elevatedTarget,
            choice: target.heightChoice, dialogHeight: document.querySelector("#sim1 .infTHeight").textContent,
            popup: target.calcMarker1.getElement().querySelector(".calcTargetHeight")?.textContent ?? null,
        };
    });
    check("floor chosen: the target height, the height difference, the dialog table and the popup follow", floor.elevated && Math.abs(floor.targetHeight - floor.choice.height) < 1e-9 && floor.targetHeight !== ground.targetHeight && floor.dialogHeight === `${floor.targetHeight.toFixed(1)}m` && /Floor \+/.test(floor.popup ?? ""),
        JSON.stringify(floor));
    await page.screenshot({ path: `${shots}/target-dialog-floor-chosen.png` });

    // The line of fire: a direct-fire weapon firing at the ground floor of the building and at its roof
    await page.keyboard.press("Escape");
    await selectWeapon(page, "DF_NLAW");
    const line = await page.evaluate(async ({ weaponAt, targetAt }) => {
        const map = window.__App.minimap;
        map.activeWeaponsMarkers.clearLayers();
        map.activeTargetsMarkers.clearLayers();
        map.createWeapon(weaponAt);
        map.createTarget(targetAt);
        const target = map.activeTargetsMarkers.getLayers()[0];
        const { choices } = await map.volume.heightsAt(targetAt);
        const settle = () => new Promise((resolve) => setTimeout(resolve, 500));
        const answerFor = async (choice) => {
            target.heightChoice = choice;
            target.updateCalc();
            await settle();
            target.updateCalc();
            const solution = target.firingSolution1;
            return { kind: choice?.kind ?? "ground", targetHeight: solution.targetHeight, blocked: Boolean(solution.obstacle.low), obstacle: solution.obstacle.low };
        };
        const results = [await answerFor(null)];
        for (const choice of choices) results.push(await answerFor(choice));
        target.heightChoice = null;
        return results;
    }, { weaponAt: await toLatLng({ x: 94.5, y: -150 }), targetAt: await toLatLng(BUILDING) });
    const blockedKinds = line.filter((entry) => entry.blocked).map((entry) => entry.kind);
    const clearKinds = line.filter((entry) => !entry.blocked).map((entry) => entry.kind);
    check("the line of fire uses the chosen height: some heights at the same point are blocked, some are clear", blockedKinds.length > 0 && clearKinds.length > 0, JSON.stringify(line.map(({ kind, targetHeight, blocked }) => ({ kind, h: +targetHeight.toFixed(1), blocked }))));

    // Dragging the target puts it back on the ground; turning the setting off does too
    const afterDrag = await page.evaluate(() => {
        const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
        target.heightChoice = { kind: "roof", height: 10, above: 9 };
        target._handleDragStart();
        return target.heightChoice;
    });
    check("dragging a target puts it back on the ground", afterDrag === null, JSON.stringify(afterDrag));
    const afterOff = await page.evaluate(() => {
        const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
        target.heightChoice = { kind: "roof", height: 10, above: 9 };
        window.__App.userSettings.set("volumeLayer", false);
        const height = target.getTargetHeight();
        window.__App.userSettings.set("volumeLayer", true);
        return height;
    });
    check("turning the setting off makes every target a ground target again", afterOff === null, JSON.stringify(afterOff));
    await page.waitForFunction(() => window.__App.minimap.volume.ready, null, { timeout: 60000 });

    // Window and doorway of the real data
    const openings = await page.evaluate(async ({ points, b }) => {
        const map = window.__App.minimap;
        const result = {};
        for (const [name, point] of Object.entries(points)) {
            const latlng = { lng: ((point.x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((point.y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize };
            result[name] = (await map.volume.heightsAt(latlng)).choices.map((choice) => choice.kind);
        }
        return result;
    }, { points: { window: WINDOW_POINT, building: BUILDING, doorway: { x: 91.875, y: -187.75 } }, b: bounds });
    check("the vertical ray finds a window, a doorway, floors and ceilings in the buildings of Jensen", openings.window.includes("window") && openings.doorway.includes("doorway") && openings.building.includes("floor") && openings.building.includes("ceiling"), JSON.stringify(openings));

    check("console and requests are clean", problems.length === 0, problems.join(" | ") || "no errors, warnings or failed requests");
    await context.close();
}

// ---------------------------------------------------------------------------------------------------------------
// Structures: markers and the target dialog (the setting is not needed)
{
    const { context, page, problems } = await open("Jensen");
    await selectWeapon(page, "Mortar");

    const center = await page.evaluate(() => {
        const map = window.__App.minimap;
        return { lng: 0.5 * map.pixelSize, lat: -0.5 * map.pixelSize };
    });
    const markerPopup = async (icon, dx) => {
        await page.evaluate(({ center, icon, dx }) => {
            const map = window.__App.minimap;
            map.createMarker(map.fromMeters(center, dx, 0), "default", "deployables", icon);
        }, { center, icon, dx });
        await clickMarker(page, "marker");
        await page.waitForSelector(".structurePopup", { timeout: 5000 });
        return page.$eval(".structurePopup .leaflet-popup-content", (element) => element.innerText.replace(/\s+/g, " ").trim());
    };
    const fob = await markerPopup("deployable_fob", 0);
    check("a FOB marker opens a popup with the shells that destroy the radio (mortar round)", /Shells to destroy/.test(fob) && !/inferred/.test(fob) && /FOB radio: 2$/.test(fob), fob);
    await page.screenshot({ path: `${shots}/structure-popup-fob.png` });
    // The open popup follows the weapon and the shell (review finding 9)
    const popupText = () => page.$eval(".structurePopup .leaflet-popup-content", (element) => element.innerText.replace(/\s+/g, " ").trim());
    await selectWeapon(page, "DF_Tank_AP_M256_Rh120");
    const apPopup = await popupText();
    check("the open structure popup is refreshed when the weapon changes", /FOB radio: no structure damage$/.test(apPopup), apPopup);
    await selectWeapon(page, "Mortar");
    const backPopup = await popupText();
    check("and again when it changes back", backPopup === fob, backPopup);
    await page.keyboard.press("Escape");
    await page.evaluate(() => document.querySelectorAll(".structurePopup .leaflet-popup-close-button").forEach((button) => button.click()));
    const hab = await markerPopup("deployable_hab", 40);
    check("a HAB marker opens its popup", /HAB: 18$/.test(hab), hab);

    const helipad = await page.evaluate(({ center }) => {
        const map = window.__App.minimap;
        const before = document.querySelectorAll(".structurePopup").length;
        map.createMarker(map.fromMeters(center, 80, 0), "default", "deployables", "deployable_helipad");
        map.activeMarkers.getLayers().at(-1)._handleClick();
        return { before, after: document.querySelectorAll(".structurePopup").length };
    }, { center });
    check("a marker the game data has no structure for opens no popup", helipad.before === helipad.after, JSON.stringify(helipad));

    // A target on the FOB marker: the dialog row
    await page.evaluate(() => document.querySelectorAll(".structurePopup .leaflet-popup-close-button").forEach((button) => button.click()));
    await page.evaluate(({ center }) => {
        const map = window.__App.minimap;
        map.createWeapon(map.fromMeters(center, 0, -300));
        map.createTarget(map.fromMeters(center, 0.5, 0));
    }, { center });
    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForTimeout(300);
    const row = await page.evaluate(() => ({ hidden: document.getElementById("structureRow").hidden, text: document.querySelector("#structureRow .infStructure").textContent, label: document.querySelector("#structureRow td").textContent }));
    check("a target on the FOB marker shows the shells in the dialog", !row.hidden && row.text === "FOB radio: 2" && row.label === "Shells to destroy", JSON.stringify(row));
    await page.hover("#structureRow td.infStructureTooltip");
    await page.waitForSelector(".tippy-box", { timeout: 5000 });
    const tooltip = await page.$eval(".tippy-box", (element) => element.innerText);
    check("the tooltip says the rules are read from the server and only the impact and secondary explosion are inferred", /read from the server/.test(tooltip) && /impact.*inferred/.test(tooltip) && !/not verified in game/.test(tooltip), tooltip.slice(0, 160));
    await page.screenshot({ path: `${shots}/target-dialog-structure.png` });
    await page.keyboard.press("Escape");

    // AP and machine-gun ammunition
    await selectWeapon(page, "DF_Tank_AP_M256_Rh120");
    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForTimeout(300);
    const ap = await page.evaluate(() => document.querySelector("#structureRow .infStructure").textContent);
    check("armour-piercing ammunition: no structure damage", ap === "FOB radio: no structure damage", ap);
    await page.screenshot({ path: `${shots}/target-dialog-structure-ap.png` });
    await page.keyboard.press("Escape");

    // A target away from every marker: no row
    await selectWeapon(page, "Mortar");
    await page.evaluate(({ center }) => {
        const map = window.__App.minimap;
        map.activeTargetsMarkers.clearLayers();
        map.createTarget(map.fromMeters(center, 0, 60));
    }, { center });
    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForTimeout(300);
    const none = await page.evaluate(() => document.getElementById("structureRow").hidden);
    check("a target away from the markers has no structure row", none === true, String(none));
    await page.keyboard.press("Escape");

    // Russian: the popup of a marker and the dialog row are translated
    await page.evaluate(() => {
        const select = document.querySelector(".dropbtn4");
        select.value = "ru";
        select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(800);
    await selectWeapon(page, "Mortar");
    await page.evaluate(({ center }) => {
        const map = window.__App.minimap;
        map.activeTargetsMarkers.clearLayers();
        map.createTarget(map.fromMeters(center, 0.5, 0));
    }, { center });
    await clickMarker(page, "target");
    await page.waitForSelector("#calcInformation[open]");
    await page.waitForTimeout(300);
    const russian = await page.evaluate(() => ({ label: document.querySelector("#structureRow td").textContent, text: document.querySelector("#structureRow .infStructure").textContent }));
    check("Russian: the structure row is translated", russian.label === "Снарядов для уничтожения" && russian.text === "Радиостанция FOB: 2", JSON.stringify(russian));
    await page.screenshot({ path: `${shots}/target-dialog-structure-ru.png` });
    await page.keyboard.press("Escape");
    check("console and requests are clean", problems.length === 0, problems.join(" | ") || "no errors, warnings or failed requests");
    await context.close();
}

await browser.close();
console.log(failures ? `${failures} FAIL` : "all targets checks passed");
process.exit(failures ? 1 : 0);
