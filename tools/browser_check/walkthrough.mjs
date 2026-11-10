// Records a click-through of every user-facing feature of the Deadline SquadCalc as a video a human can
// follow: a visible cursor, a ring on every click, the pressed keys and a caption per step.
//
//     node walkthrough.mjs <site URL> [--out <dir>] [--only desktop|mobile]
//
// Writes to <dir> (default ~/videos/squadcalc): desktop.webm (1920x1080), mobile.webm (720x1280,
// a 360x640 phone at 2x), a screenshot per step in frames/, and walkthrough-log.json with the steps
// and every console error or warning, page error and failed request tagged with the step it happened
// in. Exits with 1 when any such problem was seen. Environment: PLAYWRIGHT_CORE and CHROME as for
// browser_check.mjs.
//
// Not clicked: the collaborative session (it creates a session on the upstream squadcalc.app server)
// and the external links. The squadcalc.app statistics endpoints (/post/*) are answered locally so
// the walkthrough's markers do not end up in the upstream statistics.
import { mkdirSync, rmSync, renameSync, writeFileSync, readdirSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const argv = process.argv.slice(2);
const option = (name, fallback) => (argv.includes(name) ? argv[argv.indexOf(name) + 1] : fallback);
const base = argv[0];
if (!base || base.startsWith("--")) {
    console.error("usage: node walkthrough.mjs <site URL> [--out <dir>] [--only desktop|mobile]");
    process.exit(2);
}
const outDir = option("--out", join(homedir(), "videos", "squadcalc"));
const only = option("--only", null);
const framesDir = join(outDir, "frames");
mkdirSync(framesDir, { recursive: true });

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const log = { base, started: new Date().toISOString(), runs: {} };
const openRuns = new Map();

/**
 * Cursor, click rings, key badges and the caption, drawn in a top-layer popover so they stay above
 * modal dialogs (re-raised whenever a dialog opens). Runs in the page before its own scripts.
 */
function installOverlay() {
    const install = () => {
        if (document.getElementById("__wt")) return;
        const style = document.createElement("style");
        style.textContent = `
            #__wt{position:fixed;inset:0;width:100vw;height:100vh;margin:0;padding:0;border:0;background:transparent;overflow:visible;pointer-events:none}
            #__wt *{pointer-events:none}
            #__wtCursor{position:fixed;left:0;top:0;width:28px;height:28px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.8))}
            .__wtRing{position:fixed;width:48px;height:48px;margin:-24px 0 0 -24px;border-radius:50%;border:3px solid #ffd400;background:rgba(255,212,0,.3);animation:__wtRing .7s ease-out forwards}
            @keyframes __wtRing{from{transform:scale(.3);opacity:1}to{transform:scale(1.7);opacity:0}}
            #__wtCaption{position:fixed;left:50%;top:84px;transform:translateX(-50%);padding:8px 20px;border-radius:8px;background:rgba(10,10,10,.82);color:#fff;font:600 20px/1.35 system-ui,sans-serif;max-width:80vw;text-align:center;border-left:4px solid #ffd400}
            #__wtCaption:empty{display:none}
            #__wtKeys{position:fixed;right:24px;bottom:24px;display:flex;gap:6px}
            .__wtKey{padding:6px 12px;border-radius:6px;background:#fff;color:#111;font:700 20px/1 system-ui,sans-serif;box-shadow:0 2px 6px rgba(0,0,0,.6);animation:__wtKey 1.6s ease-in forwards}
            @keyframes __wtKey{0%,70%{opacity:1}100%{opacity:0}}
            @media (max-width:600px){#__wtCaption{top:auto;bottom:12px;font-size:14px;max-width:92vw}}
            @media (hover:none){#__wtCursor{display:none}}`;
        document.head.appendChild(style);
        const layer = document.createElement("div");
        layer.id = "__wt";
        layer.setAttribute("popover", "manual");
        layer.innerHTML = `<svg id="__wtCursor" viewBox="0 0 24 24"><path d="M3 2l17 10.5-7.6 1.4 4.6 7.6-3 1.7-4.5-7.7L4 21z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg><div id="__wtCaption"></div><div id="__wtKeys"></div>`;
        document.body.appendChild(layer);
        const raise = () => { try { layer.hidePopover(); } catch { /* not shown yet */ } layer.showPopover(); };
        raise();
        const cursor = layer.querySelector("#__wtCursor");
        const keys = layer.querySelector("#__wtKeys");
        const move = (x, y) => { cursor.style.transform = `translate(${x - 4}px, ${y - 3}px)`; };
        move(innerWidth / 2, innerHeight / 2);
        document.addEventListener("pointermove", (event) => move(event.clientX, event.clientY), true);
        const ringAt = (x, y) => {
            const ring = document.createElement("div");
            ring.className = "__wtRing";
            ring.style.left = `${x}px`;
            ring.style.top = `${y}px`;
            layer.appendChild(ring);
            setTimeout(() => ring.remove(), 800);
        };
        document.addEventListener("pointerdown", (event) => { move(event.clientX, event.clientY); ringAt(event.clientX, event.clientY); }, true);
        document.addEventListener("keydown", (event) => {
            if (["Control", "Shift", "Alt", "Meta"].includes(event.key)) return;
            const parts = [event.ctrlKey && "Ctrl", event.altKey && "Alt", event.shiftKey && "Shift", event.key === " " ? "Space" : event.key.length === 1 ? event.key.toUpperCase() : event.key].filter(Boolean);
            const badge = document.createElement("div");
            badge.className = "__wtKey";
            badge.textContent = parts.join(" + ");
            keys.appendChild(badge);
            setTimeout(() => badge.remove(), 1700);
        }, true);
        new MutationObserver(raise).observe(document.documentElement, { subtree: true, attributeFilter: ["open"] });
        window.__wtCaption = (text) => { layer.querySelector("#__wtCaption").textContent = text; };
        window.__wtRing = ringAt;
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
    else install();
}

/**
 * A browser context recording a video, with window.__App exposed, the overlay, the statistics
 * endpoints answered locally and every problem logged with the current step
 * @param {string} name - run name: video file name and key in the log
 * @param {object} contextOptions - Playwright context options (viewport, touch)
 * @param {{width: number, height: number}} videoSize - recorded video size
 */
async function startRun(name, contextOptions, videoSize) {
    const videoTmp = join(tmpdir(), `walkthrough-${name}-${process.pid}`);
    rmSync(videoTmp, { recursive: true, force: true });
    const context = await browser.newContext({ ...contextOptions, acceptDownloads: true, recordVideo: { dir: videoTmp, size: videoSize } });
    // Every request is made by Playwright (Node) and handed to the page: Chromium aborts its own
    // requests in flight with ERR_NETWORK_CHANGED whenever a network interface comes or goes, which
    // on a Docker host happens every few seconds. Routes registered later take precedence.
    await context.route(/^https?:/, async (route) => {
        for (let attempt = 1; ; attempt++) {
            try {
                return await route.fulfill({ response: await route.fetch({ timeout: 60000 }) });
            } catch (error) {
                if (attempt >= 3 || /closed|disposed/i.test(error.message)) return route.abort().catch(() => {});
            }
        }
    });
    await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
        if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
        await route.fulfill({ response, body: patched });
    });
    await context.route(/squadcalc\.app\/(api\/)?post\//, (route) => route.fulfill({ status: 204, body: "" }));
    await context.addInitScript(installOverlay);
    const page = await context.newPage();
    const run = { steps: [], problems: [] };
    log.runs[name] = run;
    let step = "load";
    page.on("console", (message) => {
        // Headless Chromium's software GL reports its own stalls
        if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) run.problems.push({ step, kind: message.type(), text: message.text() });
    });
    page.on("pageerror", (error) => run.problems.push({ step, kind: "pageerror", text: error.message }));
    page.on("response", (response) => { if (response.status() >= 400) run.problems.push({ step, kind: `HTTP ${response.status()}`, text: response.url() }); });
    page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText || "";
        // Requests cancelled by the page itself (a map change aborts the previous layer fetch)
        if (/ERR_ABORTED/.test(failure)) return;
        run.problems.push({ step, kind: "requestfailed", text: `${failure} ${request.url()}` });
    });

    let shotIndex = 0;
    const startedAt = Date.now();
    const api = {
        page,
        context,
        cursor: { x: (contextOptions.viewport.width / 2), y: (contextOptions.viewport.height / 2) },
        /** Start a step: caption on screen, entry in the log */
        async caption(text) {
            step = text;
            run.steps.push({ at: Date.now(), text });
            console.log(`[${name}] +${((Date.now() - startedAt) / 1000).toFixed(1)}s ${text}`);
            await page.evaluate((caption) => window.__wtCaption?.(caption), text).catch(() => {});
        },
        pause: (ms = 900) => page.waitForTimeout(ms),
        /** Glide the cursor to a point */
        async moveTo(x, y, steps = 10) {
            await page.mouse.move(x, y, { steps });
            api.cursor = { x, y };
        },
        /** Move to a point and click it (button, modifiers, double click) */
        async clickAt(x, y, { button = "left", clickCount = 1, modifiers = [] } = {}) {
            await api.moveTo(x, y);
            await page.waitForTimeout(250);
            for (const key of modifiers) await page.keyboard.down(key);
            await page.mouse.click(x, y, { button, clickCount, delay: 60 });
            for (const key of modifiers) await page.keyboard.up(key);
            await page.waitForTimeout(350);
        },
        /** Centre of an element on screen, scrolling it into view first */
        async centerOf(locator) {
            await locator.scrollIntoViewIfNeeded().catch(() => {});
            const box = await locator.boundingBox();
            if (!box) throw new Error(`not visible: ${locator}`);
            return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
        },
        /** Move to an element and click it */
        async click(target, options) {
            const locator = typeof target === "string" ? page.locator(target).first() : target;
            await locator.waitFor({ state: "visible", timeout: 8000 });
            const { x, y } = await api.centerOf(locator);
            await api.clickAt(x, y, options);
        },
        async hover(target) {
            const locator = typeof target === "string" ? page.locator(target).first() : target;
            const { x, y } = await api.centerOf(locator);
            await api.moveTo(x, y);
        },
        /** Drag with the mouse from one point to another */
        async drag(from, to) {
            await api.moveTo(from.x, from.y);
            await page.waitForTimeout(200);
            await page.mouse.down();
            await page.mouse.move(to.x, to.y, { steps: 30 });
            api.cursor = to;
            await page.waitForTimeout(150);
            await page.mouse.up();
            await page.waitForTimeout(500);
        },
        async press(key) {
            await page.keyboard.press(key);
            await page.waitForTimeout(700);
        },
        /** Pick an entry of a select2 dropdown by its visible text */
        async pickSelect2(container, text) {
            await api.click(`${container} .select2-selection`);
            const choice = page.locator(".select2-container--open .select2-results__option").filter({ hasText: new RegExp(`^\\s*${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`) }).first();
            await choice.waitFor({ state: "visible", timeout: 15000 });
            await page.waitForTimeout(400);
            await api.click(choice);
        },
        /** A walkthrough step that did not go as scripted: logged as a problem */
        note(text) {
            console.log(`[${name}] NOTE ${text}`);
            run.problems.push({ step, kind: "walkthrough", text });
        },
        async shot(label) {
            shotIndex += 1;
            const file = join(framesDir, `${name}-${String(shotIndex).padStart(2, "0")}-${label}.png`);
            await page.screenshot({ path: file });
        },
        /** Wait until the heightmap of the current map is loaded; a coarse one instead of the precise one is a problem */
        async waitHeightmap() {
            await page.waitForFunction(() => window.__App?.minimap?.heightmap?.jsonPng?.length, null, { timeout: 120000 });
            const { precise, map } = await page.evaluate(() => ({ precise: window.__App.minimap.heightmap.precise, map: window.__App.minimap.activeMap.name }));
            if (!precise) run.problems.push({ step, kind: "heightmap", text: `${map}: the coarse 8-bit heightmap was loaded instead of the precise one` });
        },
        /** Screen point of a position `east`/`north` meters from the map centre */
        async pointAt(east, north) {
            return page.evaluate(([east, north]) => {
                const map = window.__App.minimap;
                const scale = map.mapToGameScale;
                const latlng = { lat: -map.pixelSize / 2 + north / scale, lng: map.pixelSize / 2 + east / scale };
                const point = map.latLngToContainerPoint(latlng);
                const box = map.getContainer().getBoundingClientRect();
                return { x: box.left + point.x, y: box.top + point.y };
            }, [east, north]);
        },
        /** Screen point of a marker icon */
        async markerPoint(kind, index = 0) {
            return page.evaluate(([kind, index]) => {
                const map = window.__App.minimap;
                const group = kind === "weapon" ? map.activeWeaponsMarkers : map.activeTargetsMarkers;
                const box = group.getLayers()[index]._icon.getBoundingClientRect();
                return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
            }, [kind, index]);
        },
        /** Close the open modal dialog with its close button */
        async closeDialog() {
            const close = page.locator("dialog[open] .closeModal").first();
            if (await close.isVisible().catch(() => false)) await api.click(close);
            else await api.press("Escape");
            await page.waitForTimeout(500);
        },
        /** Text of the option of `select` whose attribute `attribute` is `value` */
        optionText: (select, attribute, value) => page.evaluate(([select, attribute, value]) => [...document.querySelectorAll(`${select} option`)].find((option) => option.getAttribute(attribute) === value)?.textContent.trim(), [select, attribute, value]),
        async finish() {
            await page.waitForTimeout(1500);
            const video = page.video();
            await context.close();
            const target = join(outDir, `${name}.webm`);
            renameSync(await video.path(), target);
            rmSync(videoTmp, { recursive: true, force: true });
            run.video = target;
            return target;
        },
    };
    openRuns.set(name, api);
    return api;
}

/** Map settings dialog: toggle a checkbox through its label, as a user would */
async function toggleSetting(run, id) {
    const label = run.page.locator(`tr:has(#${id}) .toggleCheckbox, tr:has(#${id}) label.mcui-checkbox`).first();
    await run.click(label);
    await run.pause(450);
}

async function desktop() {
    const run = await startRun("desktop", { viewport: { width: 1920, height: 1080 } }, { width: 1920, height: 1080 });
    const { page } = run;

    await page.goto(base, { waitUntil: "load" });
    await run.caption("Deadline SquadCalc: loading the map and its precise heightmap");
    await run.waitHeightmap();
    await run.pause(2500);
    await run.shot("start");

    // Maps, including a large one
    for (const name of ["Yehorivka", "Skorpo", "AlBasrah", "Gorodok"]) {
        const text = await run.optionText("select.dropbtn", "data-i18n", `maps:${name}`);
        await run.caption(`Map selector: ${text}`);
        await run.pickSelect2("#mapSelector", text);
        await run.waitHeightmap();
        await run.pause(1800);
        if (name === "Yehorivka") await run.shot("map-large");
    }

    // Game layer
    await run.caption("Layer selector: a game layer with flags, mains and spawns");
    await page.waitForFunction(() => document.querySelectorAll("select.dropbtn5 option").length > 2, null, { timeout: 30000 });
    const layer = await page.evaluate(() => [...document.querySelectorAll("select.dropbtn5 option")].map((o) => o.textContent.trim()).find((t) => /RAAS/i.test(t)) || [...document.querySelectorAll("select.dropbtn5 option")][2].textContent.trim());
    await run.pickSelect2("#layerSelector", layer);
    await run.pause(3000);
    await run.shot("layer");

    // Zoom with the wheel
    await run.caption("Mouse wheel zoom");
    await run.moveTo(960, 560);
    for (let i = 0; i < 3; i++) { await page.mouse.wheel(0, -240); await run.pause(500); }
    await run.pause(800);
    for (let i = 0; i < 3; i++) { await page.mouse.wheel(0, 240); await run.pause(500); }
    await page.evaluate(() => {
        const map = window.__App.minimap;
        const scale = map.mapToGameScale;
        const center = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
        map.fitBounds([[center.lat - 700 / scale, center.lng - 900 / scale], [center.lat + 1000 / scale, center.lng + 900 / scale]], { animate: false });
    });
    await run.pause(1200);

    // Map styles
    await run.caption("Map styles: detailed, relief, satellite, HD images");
    await run.hover("#mapBtnLayers #btn-map-choices");
    await run.pause(600);
    for (const style of [".btn-detailed", ".btn-relief", ".btn-basemap"]) {
        await run.click(`#mapLayerMenu ${style}`);
        await run.pause(1500);
        if (style === ".btn-relief") await run.shot("relief");
    }
    await run.click("#mapLayerMenu .btn-hd");
    await run.pause(2000);
    await run.click("#mapLayerMenu .btn-hd");
    await run.pause(1000);

    // Weapon and targets
    await run.caption("Double-click: the first one places the weapon, and the weapon selector appears");
    const weaponPoint = await run.pointAt(0, -350);
    await run.clickAt(weaponPoint.x, weaponPoint.y, { clickCount: 2 });
    await run.pause(1500);

    await run.caption("Weapon selector: deployables, vehicles and direct-fire weapons");
    await run.click("#weaponSelector .select2-selection");
    await run.pause(900);
    for (const group of await page.locator(".select2-container--open .select2-results__group").all()) {
        await run.hover(group);
        await run.pause(700);
    }
    await run.shot("weapon-groups");
    await run.press("Escape");
    const weaponText = (name) => run.optionText("select.dropbtn2", "data-i18n", `weapons:${name}`);
    await run.caption("Mortar");
    await run.pickSelect2("#weaponSelector", await weaponText("Mortar"));
    await run.pause(800);

    await run.caption("Double-click again: targets with elevation, bearing, spread and damage zone");
    for (const [east, north] of [[-250, 450], [150, 650], [380, 350]]) {
        const point = await run.pointAt(east, north);
        await run.clickAt(point.x, point.y, { clickCount: 2 });
        await run.pause(1200);
    }
    await run.pause(1500);
    await run.shot("targets");

    await run.caption("Hover a target: the others fade out");
    await run.moveTo(...Object.values(await run.markerPoint("target", 1)));
    await run.pause(2000);
    await run.moveTo(1500, 900);
    await run.pause(800);

    await run.caption("Drag a target and the weapon: the solutions follow");
    let from = await run.markerPoint("target", 0);
    await run.drag(from, { x: from.x + 120, y: from.y - 60 });
    from = await run.markerPoint("weapon", 0);
    await run.drag(from, { x: from.x - 80, y: from.y + 40 });
    await run.pause(1200);

    await run.caption("Click a target: trajectory and obstacle view");
    let target = await run.markerPoint("target", 1);
    await run.clickAt(target.x, target.y);
    await run.pause(3500);
    await run.shot("trajectory");
    await run.closeDialog();

    await run.caption("Click the weapon: weapon card, extra height, move to a keypad");
    let weapon = await run.markerPoint("weapon", 0);
    await run.clickAt(weapon.x, weapon.y);
    await run.pause(1500);
    const heightInput = page.locator("#weaponInformation .heightPadding input").first();
    if (await heightInput.isVisible().catch(() => false)) {
        await run.click(heightInput, { clickCount: 3 });
        await page.keyboard.type("15", { delay: 120 });
        await page.keyboard.press("Tab");
        await run.pause(1000);
    }
    await run.shot("weapon-card");
    await run.closeDialog();

    // Every weapon group with markers placed
    for (const [name, label] of [["HellCannon", "Hell Cannon (high angle)"], ["UB-32", "UB-32 rockets"], ["BM-21Grad", "BM-21 Grad (vehicle)"], ["M1064M121", "M1064 (two shells)"], ["AGS-17", "AGS-17: hold time instead of an angle"], ["DF_RPG_7_PG_7V_HEAT_OG_7V", "Direct fire (Squad Ballistics): RPG-7"]]) {
        const text = await weaponText(name);
        await run.caption(`Weapon: ${label}`);
        await run.pickSelect2("#weaponSelector", text);
        await run.pause(1800);
        if (name === "M1064M121") {
            const shell = await page.evaluate(() => [...document.querySelectorAll("select.dropbtn3 option")].at(-1).textContent.trim());
            await run.caption(`Ammunition selector: ${shell}`);
            await run.pickSelect2("#ammoSelector", shell);
            await run.pause(1500);
        }
        if (name === "AGS-17") await run.shot("ags17");
        if (name.startsWith("DF_")) await run.shot("direct-fire");
    }
    await run.caption("Back to the mortar");
    await run.pickSelect2("#weaponSelector", await weaponText("Mortar"));
    await run.pause(1000);

    // Fire correction
    await run.caption("Fire correction: Ctrl + double-click where a round burst");
    target = await run.markerPoint("target", 1);
    await run.clickAt(target.x + 35, target.y - 25, { clickCount: 2, modifiers: ["Control"] });
    await run.pause(2500);
    await run.shot("fire-correction");
    await run.caption("Right-click the burst removes it");
    await run.clickAt(target.x + 35, target.y - 25, { button: "right" });
    await run.pause(1500);

    // Context menu and drawing
    await run.caption("Right-click the map: context menu with map markers");
    let point = await run.pointAt(-500, 100);
    await run.clickAt(point.x, point.y, { button: "right" });
    await run.pause(1200);
    await run.shot("context-menu");
    await run.click(".contextmenu .ctxButton:nth-child(2)");
    await run.pause(1000);
    await run.press("Escape");
    point = await run.pointAt(-500, 100);
    await run.clickAt(point.x, point.y, { button: "right" });
    await run.pause(800);
    const vehicle = page.locator(".contextmenu .ctxButton").nth(2);
    if (await vehicle.isVisible().catch(() => false)) {
        await run.click(vehicle);
        await run.pause(800);
        const icon = page.locator(".tippy-box .contextmenuVert .ctxButton, .tippy-box .ctxButton").nth(1);
        if (await icon.isVisible().catch(() => false)) await run.click(icon);
    }
    await run.pause(1200);
    await run.press("Escape");

    // Map buttons
    await run.caption("Fire coverage of the weapon");
    await run.click("#mapLayerMenu .btn-coverage");
    await run.pause(4000);
    await run.shot("coverage");
    await run.click("#mapLayerMenu .btn-coverage");
    await run.pause(1000);

    await run.caption("Undo removes the last marker");
    await run.click("#mapLayerMenu .btn-undo");
    await run.pause(1200);

    await run.caption("More tools: heatmap, focus mode, download, upload, share, legacy UI");
    await run.hover("#mapBtnTools #btn-map-choices");
    await run.pause(1200);
    const tool = async (selector, wait = 1500) => {
        await run.hover("#mapBtnTools #btn-map-choices");
        // The tool buttons slide in from the right: aim once they stopped
        await run.pause(1200);
        const button = page.locator(`#mapLayerMenu ${selector}`).first();
        if (!(await button.isVisible().catch(() => false))) {
            run.note(`tool button ${selector} not visible in the tools menu`);
            return false;
        }
        await run.click(button);
        await run.pause(wait);
        return true;
    };
    await run.caption("Heatmap of where players aim this weapon");
    await tool(".btn-helpmap", 3000);
    await run.shot("heatmap");
    await tool(".btn-helpmap", 800);
    if (await page.locator(".btn-helpmap.active").count()) run.note("the heatmap stayed on after its button was clicked again");
    await run.caption("Focus mode");
    await tool(".btn-focus", 2000);
    await run.press("Enter");
    await run.pause(800);
    await run.caption("Download the map state to a file");
    const downloadPromise = page.waitForEvent("download", { timeout: 10000 }).catch(() => null);
    await tool(".btn-download", 800);
    const download = await downloadPromise;
    const savedFile = download ? join(tmpdir(), `walkthrough-map-${process.pid}.json`) : null;
    if (download) await download.saveAs(savedFile);
    else run.note("no file downloaded by the download button");
    await run.caption("Share the loadout");
    await tool(".btn-share", 1500);
    await run.closeDialog().catch(() => {});

    // Keyboard shortcuts
    await run.caption("Shortcut M: next map style");
    await run.moveTo(1500, 700);
    for (let i = 0; i < 3; i++) { await run.press("m"); await run.pause(900); }
    await run.caption("Shortcut Enter: focus mode on and off");
    await run.press("Enter");
    await run.pause(1500);
    await run.shot("focus-mode");
    await run.press("Enter");
    await run.caption("Shortcut Ctrl + Z: delete the last target");
    await run.press("Control+z");
    await run.pause(1000);
    await run.caption("Shortcut Ctrl + M: legacy UI and back");
    await run.press("Control+m");
    await run.pause(2500);
    await run.shot("legacy-ui");
    await run.press("Control+m");
    await run.pause(1500);
    await run.caption("Shortcut Delete: clear every marker");
    await run.press("Delete");
    await run.pause(1200);

    if (savedFile) {
        await run.caption("Upload the saved map state back");
        const chooserPromise = page.waitForEvent("filechooser", { timeout: 10000 }).catch(() => null);
        await tool(".btn-upload", 300);
        const chooser = await chooserPromise;
        if (chooser) await chooser.setFiles(savedFile);
        else run.note("the upload button opened no file chooser");
        await run.pause(2500);
    }
    const placed = await page.evaluate(() => ({ weapons: window.__App.minimap.activeWeaponsMarkers.getLayers().length, targets: window.__App.minimap.activeTargetsMarkers.getLayers().length }));
    if (savedFile && !placed.targets) run.note("the uploaded map state restored no target");
    if (!placed.targets) {
        await run.caption("Place a weapon and targets again");
        if (!placed.weapons) {
            const p = await run.pointAt(0, -350);
            await run.clickAt(p.x, p.y, { clickCount: 2 });
        }
        for (const [east, north] of [[-250, 450], [150, 650], [380, 350]]) {
            const q = await run.pointAt(east, north);
            await run.clickAt(q.x, q.y, { clickCount: 2 });
        }
    }
    await run.pause(1000);

    // Factions and servers
    await run.caption("Faction bar: pick factions and units of the layer");
    if (await page.locator("#factionsButton .btn-faction").isVisible().catch(() => false)) {
        await run.click("#factionsButton .btn-faction");
        await run.pause(2500);
        await run.shot("factions");
        await run.closeDialog();
    }
    await run.caption("Server browser");
    if (await page.locator("#mapLayerMenu #servers").isVisible().catch(() => false)) {
        await run.click("#mapLayerMenu #servers");
        await run.pause(3500);
        await run.shot("servers");
        await run.closeDialog();
    }

    // Settings
    await run.caption("Settings: map options");
    await run.click("#mapLayerMenu .btn-settings");
    await run.pause(1200);
    await run.shot("settings-map");
    for (const id of ["keypadUnderCursorSetting", "cursorChoiceSettings", "mapAnimationSettings", "contextMenuSettings"]) {
        await toggleSetting(run, id);
        await toggleSetting(run, id);
    }
    await run.caption("Settings: map buttons shown in the bar");
    await run.click("#mapBtnToggles .mapBtnToggle[data-key='settings-btn-helpmap']");
    await run.pause(800);
    await run.click("#mapBtnToggles .mapBtnToggle[data-key='settings-btn-helpmap']");
    await run.pause(600);
    await run.caption("Settings: sliders (grid, zoom, font, markers, brightness, contrast)");
    for (const id of ["gridSlider", "zoomSlider", "fontSlider", "markerSlider", "brightnessSlider", "contrastSlider"]) {
        const slider = page.locator(`#${id}`);
        await slider.scrollIntoViewIfNeeded();
        const box = await slider.boundingBox();
        const original = await slider.inputValue();
        await run.clickAt(box.x + box.width * 0.85, box.y + box.height / 2);
        await run.pause(500);
        await slider.evaluate((element, value) => { element.value = value; element.dispatchEvent(new Event("input")); }, original);
    }
    await run.pause(600);

    await run.caption("Settings: weapons and targets");
    await run.click("#settingsControls button[value='panel2']");
    await run.pause(800);
    await run.shot("settings-weapons");
    for (const id of ["weaponDragSetting", "realMaxRangeSettings", "targetAnimationSettings", "targetDragSetting", "targetCopySetting"]) {
        await toggleSetting(run, id);
        await toggleSetting(run, id);
    }
    await run.caption("Settings: modded weapons and their mod filters");
    await toggleSetting(run, "experimentalSetting");
    await run.pause(1200);
    await toggleSetting(run, "experimentalSetting");

    await run.caption("Settings: what the target popups show");
    const display = ["lowAndHighSetting", "lastDigitsSetting", "targetGridSetting", "lineToTargetSetting", "distanceSetting", "timeOfFlightSetting", "heightSetting"];
    for (const id of display) await toggleSetting(run, id);
    for (const id of ["spreadRadiusSetting", "damageRadiusSetting", "bearingSetting"]) await toggleSetting(run, id);
    await run.closeDialog();
    await run.caption("Target popups with low and high angle, last digits, distance, time of flight, height, grid and line; no spread, damage or bearing");
    await run.pause(3500);
    await run.shot("display-settings");
    await run.click("#mapLayerMenu .btn-settings");
    await run.click("#settingsControls button[value='panel2']");
    for (const id of [...display, "spreadRadiusSetting", "damageRadiusSetting", "bearingSetting"]) await toggleSetting(run, id);
    await run.closeDialog();
    await run.caption("Popups back to the defaults");
    await run.pause(2000);

    await run.caption("Settings: layer and faction options");
    await run.click("#settingsControls button[value='panel3']");
    await run.pause(800);
    await run.shot("settings-layer");
    for (const id of ["showMainZonesSettings", "showMainAssetsSettings", "showMapBordersSettings", "respawnCamSettings", "circlesFlagsSettings", "showFlagsDistanceSettings", "showNextFlagPercentageSettings", "capZoneOnHoverSettings", "revealLayerOnHoverSettings", "enableFactionsSettings", "defaultFactionsSettings", "hideLowRespawnSettings", "disableSoundsSettings", "minimizeFactionBarSettings"]) {
        await toggleSetting(run, id);
        await toggleSetting(run, id);
    }

    await run.caption("Settings: keyboard shortcuts, rebinding one");
    await run.click("#settingsControls button[value='panel4']");
    await run.pause(1000);
    await run.shot("settings-shortcuts");
    await run.click("#panel4 .shortcut-row");
    await run.pause(800);
    await page.keyboard.press("k");
    await run.pause(1200);
    await run.click("#captureCancel");
    await run.pause(800);

    await run.caption("Language: Russian, French, then English");
    await run.click("#settingsControls button[value='panel1']");
    for (const language of ["ru", "fr", "en"]) {
        await run.pickSelect2("#lngSelector", await run.optionText("#lngDropbtn", "value", language));
        await run.pause(2000);
        if (language === "ru") await run.shot("language-ru");
    }

    await run.caption("Changelog");
    await run.click("#openChangelog");
    await run.pause(2500);
    await run.closeDialog();
    await run.closeDialog().catch(() => {});

    await run.caption("Delete button clears the map");
    if (await page.locator("#mapLayerMenu .btn-delete").isVisible().catch(() => false)) await run.click("#mapLayerMenu .btn-delete");
    await run.pause(1500);
    await run.caption("End of the desktop walkthrough");
    await run.pause(1500);
    return run.finish();
}

async function mobile() {
    const run = await startRun("mobile", {
        viewport: { width: 360, height: 640 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
        userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    }, { width: 720, height: 1280 });
    const { page } = run;
    const tap = async (x, y) => {
        await page.evaluate(([x, y]) => window.__wtRing?.(x, y), [x, y]);
        await page.touchscreen.tap(x, y);
        await run.pause(900);
    };
    const tapOn = async (selector) => {
        const locator = typeof selector === "string" ? page.locator(selector).first() : selector;
        await locator.waitFor({ state: "visible", timeout: 15000 });
        const { x, y } = await run.centerOf(locator);
        await tap(x, y);
    };

    await page.goto(base, { waitUntil: "load" });
    await run.caption("Phone: loading");
    await run.waitHeightmap();
    await run.pause(2000);
    await run.shot("start");
    await page.evaluate(() => { const map = window.__App.minimap; map.setView([-map.pixelSize / 2, map.pixelSize / 2], 3, { animate: false }); });
    await run.pause(800);

    // Screen points clear of the selectors at the top and the buttons on the right
    await run.caption("Tap: weapon, then targets");
    for (const [x, y] of [[170, 540], [90, 330], [250, 380]]) await tap(x, y);
    await run.pause(1500);
    await run.shot("targets");

    await run.caption("Tap a target: trajectory");
    const target = await run.markerPoint("target", 0);
    await tap(target.x, target.y);
    await run.pause(3000);
    await run.shot("trajectory");
    await tapOn("dialog[open] .closeModal");

    await run.caption("Weapon selector: UB-32");
    await tapOn("#weaponSelector .select2-selection");
    await run.pause(800);
    const ub32 = await run.optionText("select.dropbtn2", "data-i18n", "weapons:UB-32");
    await tapOn(page.locator(".select2-container--open .select2-results__option").filter({ hasText: new RegExp(`^\\s*${ub32}\\s*$`) }));
    await run.pause(1500);

    await run.caption("Map selector: Yehorivka");
    await tapOn("#mapSelector .select2-selection");
    await run.pause(800);
    const yeho = await run.optionText("select.dropbtn", "data-i18n", "maps:Yehorivka");
    await tapOn(page.locator(".select2-container--open .select2-results__option").filter({ hasText: new RegExp(`^\\s*${yeho}\\s*$`) }));
    await run.waitHeightmap();
    await run.pause(2000);

    await run.caption("Settings on a phone");
    const settings = page.locator("#mapLayerMenu .btn-settings");
    if (!(await settings.isVisible().catch(() => false))) await tapOn("#mapBtnTools #btn-map-choices");
    await tapOn(settings);
    await run.pause(1200);
    await run.shot("settings");
    await tapOn("#settingsControls button[value='panel2']");
    await run.pause(1200);
    await page.locator("#helpDialog").evaluate((dialog) => dialog.scrollBy({ top: 400, behavior: "smooth" }));
    await run.pause(1500);
    await run.shot("settings-weapons");
    await tapOn("dialog[open] .closeModal");
    await run.caption("End of the phone walkthrough");
    await run.pause(1500);
    return run.finish();
}

let exitCode = 0;
for (const [name, record] of [["desktop", desktop], ["mobile", mobile]]) {
    if (only && only !== name) continue;
    try {
        await record();
    } catch (error) {
        console.error(`[${name}] walkthrough failed: ${error.stack}`);
        log.runs[name] = { ...log.runs[name], failure: error.message };
        exitCode = 1;
        // Keep the video up to the failure
        await openRuns.get(name)?.finish().catch(() => {});
    }
    const problems = log.runs[name]?.problems || [];
    console.log(`[${name}] ${problems.length} problem(s)`);
    for (const problem of problems.slice(0, 40)) console.log(`  [${problem.step}] ${problem.kind}: ${problem.text.slice(0, 300)}`);
    if (problems.length) exitCode = 1;
}
await browser.close();
log.finished = new Date().toISOString();
writeFileSync(join(outDir, "walkthrough-log.json"), JSON.stringify(log, null, 2));
console.log(`frames: ${readdirSync(framesDir).length} in ${framesDir}`);
process.exit(exitCode);
