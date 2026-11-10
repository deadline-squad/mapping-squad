// Checks the Deadline SquadCalc in a real browser (Chromium through Playwright): the console stays clean,
// the precise heightmaps load (also when the network drops a request), the detailed map layer works, and the
// bugs fixed in 45.5.1 and in the walkthrough review (walkthrough.mjs) stay fixed.
//
//     node browser_check.mjs <site URL> [--maps] [--ballistics <weapons.json>]
//
// <site URL> is a served build with the precise heightmaps under /heightmaps/ (the stand, or Caddy over
// a local `npm run build`). --maps also switches through every map on the detailed layer and checks each
// loads its precise heightmap and its detailed tiles (tools/maptiles) without a failed request. --ballistics
// also selects every weapon of Squad Ballistics' weapons.json aimed with the overlay through
// window.squadBallistics, by its name. Environment: PLAYWRIGHT_CORE = path of the playwright-core package
// if it is not
// resolvable from here, CHROME = Chromium executable if Playwright's own is not installed.
// The checks run in groups, each on a page of its own (`group`): a page that does not open is one FAIL and the
// other groups still run. The last line gives the totals. Exits with 1 on any failure.
//
// SquadCalc keeps its App in a module; the check exposes it as window.__App by rewriting the main
// bundle in transit (the served files are not changed).
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node browser_check.mjs <site URL> [--maps] [--ballistics <weapons.json>]");
    process.exit(2);
}
const allMaps = process.argv.includes("--maps");
const ballisticsIndex = process.argv.indexOf("--ballistics");
const ballisticsFile = ballisticsIndex > 0 ? process.argv[ballisticsIndex + 1] : null;

let checks = 0;
let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    checks++;
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

// Requests Chromium dropped because the network of the host changed under it (an interface came or went, as
// when Docker starts or stops a container): it fails every request in flight then, whatever the site does
const NETWORK_CHANGED = "net::ERR_NETWORK_CHANGED";
let networkChanges = 0;

/**
 * Run a group of checks that share a page. A page that does not open, or a step that throws, is one FAIL under
 * the group's name: the checks left in the group are not reached, the groups after it still run.
 * @param {string} label - name of the group in the FAIL line
 * @param {() => Promise<void>} body - the checks of the group
 */
async function group(label, body) {
    try {
        await body();
    } catch (error) {
        check(label, false, `stopped by ${error.message.split("\n")[0]}`);
        // The page the group left open
        await Promise.all(browser.contexts().map((context) => context.close()));
    }
}

/**
 * Open SquadCalc with window.__App and a log of console errors, page errors and failed requests
 * @param {object} [contextOptions] - Playwright browser context options (viewport, mobile emulation)
 * @param {(context: object) => Promise<void>} [prepare] - called with the context before the page loads (routes)
 * @param {boolean} [precise] - wait for the precise heightmap (true) or for any heightmap result, also
 *   the 8-bit one or a failure (false)
 * @throws {Error} when the page does not load, or the heightmap or the map image does not, within 120 s each: the
 *   error names the spinner's count and the requests without an answer, and the context is closed
 */
async function open(contextOptions = { viewport: { width: 1600, height: 1000 } }, prepare = async () => {}, precise = true) {
    const context = await browser.newContext(contextOptions);
    await prepare(context);
    await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
        if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
        await route.fulfill({ response, body: patched });
    });
    const page = await context.newPage();
    const problems = [];
    page.on("console", (message) => {
        // Headless Chromium's software GL reports its own stalls
        if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) problems.push(`${message.type()}: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    page.on("response", (response) => { if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`); });
    const unanswered = new Set();
    page.on("request", (request) => unanswered.add(request));
    page.on("requestfinished", (request) => unanswered.delete(request));
    page.on("requestfailed", (request) => {
        unanswered.delete(request);
        if (request.failure()?.errorText === NETWORK_CHANGED) networkChanges++;
    });
    // A wait that ran out says what the page still waited for: the spinner's count and the requests without an answer
    const stalled = (what) => async () => {
        const spinning = await page.evaluate(() => window.__App?.minimap?._spinning).catch(() => undefined);
        const requests = [...unanswered].map((request) => request.url());
        throw new Error(`${what} after 120 s (spinner count ${spinning}, ${requests.length} request(s) without an answer${requests.length ? `: ${requests.slice(0, 5).join(", ")}` : ""})`);
    };
    try {
        await page.goto(base, { waitUntil: "load", timeout: 120000 });
        await page.waitForFunction((precise) => {
            const heightmap = window.__App?.minimap?.heightmap;
            return precise ? heightmap?.precise : heightmap?.jsonPng.length || heightmap?.failed;
        }, precise, { timeout: 120000 }).catch(stalled("no heightmap"));
        // The map image still fades in after the heights (the WebP heightmap is usually there first): clicks
        // before the spinner is gone are lost
        await page.waitForFunction(() => !window.__App.minimap._spinning, null, { timeout: 120000 }).catch(stalled("the map's spinner still turns"));
    } catch (error) {
        await context.close();
        throw error;
    }
    return { context, page, problems };
}

// Weapon at the map centre, targets `north` meters north of it (and `east`); non-square maps scale
// north and east apart (mapToGameScaleY)
const place = (page, targets) => page.evaluate((targets) => {
    const map = window.__App.minimap;
    const scale = map.mapToGameScale;
    const scaleY = map.mapToGameScaleY;
    const weapon = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
    map.setView([weapon.lat + 100 / scaleY, weapon.lng], 5, { animate: false });
    if (!map.activeWeaponsMarkers.getLayers().length) map.createWeapon(weapon);
    for (const [east, north] of targets) map.createTarget({ lat: weapon.lat + north / scaleY, lng: weapon.lng + east / scale });
}, targets);
const popupText = (target) => target.calcMarker1.getContent().replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

await group("desktop checks", async () => {
    const { context, page, problems } = await open();

    // Markers placed before the precise heightmap arrives are solved again once it has
    const stale = await page.evaluate(async (popupSource) => {
        const popup = new Function(`return ${popupSource}`)();
        const app = window.__App;
        const map = app.minimap;
        const other = [...app.MAP_SELECTOR[0].options].find((option) => option.value !== app.MAP_SELECTOR.val());
        app.MAP_SELECTOR.val(other.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 0));
        const loadedBefore = map.heightmap.precise;
        const scale = map.mapToGameScale;
        const scaleY = map.mapToGameScaleY;
        const weapon = { lat: -map.pixelSize * 0.45, lng: map.pixelSize * 0.45 };
        map.createWeapon(weapon);
        const target = map.createTarget({ lat: weapon.lat + 400 / scaleY, lng: weapon.lng + 200 / scale }) || map.activeTargetsMarkers.getLayers()[0];
        // While the heights load the popup says it has no height data and the bridge sends no height
        const early = { heightDiff: window.squadBallistics.lastTarget()?.heightDiff, noHeightLine: popup(target).includes("height"), noHeightClass: target.calcMarker1.getContent().includes("calcNoHeight"), profile: window.squadBallistics.lastTarget()?.profile };
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.heightmap.precise) { clearInterval(timer); resolve(); } }, 50); });
        await new Promise((resolve) => setTimeout(resolve, 300));
        const shown = popup(target);
        const heightDiff = target.firingSolution1.heightDiff;
        target.updateCalc();
        const late = window.squadBallistics.lastTarget();
        return { early, late: { heightDiff: late?.heightDiff, hasProfile: Boolean(late?.profile) }, loadedBefore, map: map.activeMap.name, shown, fresh: popup(target), heightDiff, expected: map.heightmap.getHeight(target.getLatLng()) - map.heightmap.getHeight(weapon) };
    }, popupText.toString());
    check("solution after the heightmap loads", !stale.loadedBefore && stale.shown === stale.fresh && Math.abs(stale.heightDiff - stale.expected) < 0.01,
        `${stale.map}: shown "${stale.shown}", recomputed "${stale.fresh}", height difference ${stale.heightDiff.toFixed(2)} m of ${stale.expected.toFixed(2)} m`);

    check("heights unknown until the precise heightmap loaded", stale.early.heightDiff === null && stale.early.noHeightClass && stale.early.profile === null
        && Number.isFinite(stale.late.heightDiff) && stale.late.hasProfile, JSON.stringify({ early: { ...stale.early, profile: stale.early.profile }, late: stale.late }));

    // Back to a fresh map state for the rest
    await page.evaluate(() => { window.__App.minimap.activeWeaponsMarkers.getLayers().forEach((weapon) => weapon.delete()); });
    await place(page, [[0, 150]]);

    // The Squad Ballistics bridge stays, and the removed device link leaves nothing behind
    const bridge = await page.evaluate(async () => {
        const bridge = window.squadBallistics;
        const targets = bridge.targets();
        const first = bridge.revision();
        const sameAgain = bridge.revision();
        const last = bridge.lastTarget();
        const cached = bridge.targets()[0].profile === targets[0].profile;
        const map = window.__App.minimap;
        map.createTarget({ lat: map.activeTargetsMarkers.getLayers()[0].getLatLng().lat + 60 / map.mapToGameScaleY, lng: map.activeTargetsMarkers.getLayers()[0].getLatLng().lng });
        const afterTarget = bridge.revision();
        const two = bridge.targets();
        const newest = bridge.lastTarget();
        const lastIsNewest = JSON.stringify(newest) === JSON.stringify(two[two.length - 1]) && two.length === 2;
        map.activeTargetsMarkers.getLayers()[1].delete();
        const afterDelete = bridge.revision();
        const revisions = { first, sameAgain, afterTarget, afterDelete, lastIsNewest, cached, lastMatches: JSON.stringify(last) === JSON.stringify(targets[0]), type: typeof first };
        const names = [...window.__App.WEAPON_SELECTOR[0].options].map((option) => option.textContent);
        const selected = bridge.selectWeapon("UB-32 (S-5 rockets)");
        const weapon = bridge.weapon();
        const rejected = bridge.selectWeapon("no such weapon");
        bridge.selectWeapon("Mortar (M252 / 2B14 / L16 / Type 63)");
        return { revisions, version: bridge.version, count: targets.length, distance: targets[0]?.distance, hasProfile: Boolean(targets[0]?.profile), selected, weapon, rejected, names: names.length };
    });
    check("window.squadBallistics.targets()", bridge.count === 1 && Math.abs(bridge.distance - 150) < 1 && bridge.hasProfile, JSON.stringify(bridge));
    const r = bridge.revisions;
    check("window.squadBallistics lastTarget() and revision()", bridge.version >= 5 && r.type === "number" && r.first === r.sameAgain && r.afterTarget > r.sameAgain && r.afterDelete > r.afterTarget && r.lastIsNewest && r.cached && r.lastMatches, JSON.stringify(r));
    check("window.squadBallistics weapon sync", bridge.selected && bridge.weapon === "UB-32 (S-5 rockets)" && !bridge.rejected, JSON.stringify(bridge));

    if (ballisticsFile) {
        // Every weapon Squad Ballistics aims with the overlay (its `aim` rule, mods excluded) is selected by
        // its name and reported back under it; those laid by holding a key (`hold_rate`) show the hold time
        // of the lob on a target 600 m away, as the AGS-17
        const { readFileSync } = await import("node:fs");
        const weapons = JSON.parse(readFileSync(ballisticsFile, "utf8"));
        delete weapons._comment;
        const overlay = Object.entries(weapons).filter(([, w]) => !w.mod && (w.aim ?? ((w.arc ?? "low") === "high" ? "elevation" : "overlay")) === "overlay");
        const selection = await page.evaluate(({ names, holdLaid, popupSource }) => {
            const popup = new Function(`return ${popupSource}`)();
            const app = window.__App;
            const map = app.minimap;
            const bridge = window.squadBallistics;
            const weapon = map.activeWeaponsMarkers.getLayers()[0].getLatLng();
            const failed = [];
            const holds = {};
            for (const name of names) {
                const selected = bridge.selectWeapon(name);
                const reported = bridge.weapon();
                if (!selected || reported !== name) failed.push(`${name}: selectWeapon ${selected}, weapon() ${reported}`);
                if (!holdLaid.includes(name)) continue;
                const before = new Set(map.activeTargetsMarkers.getLayers());
                map.createTarget({ lat: weapon.lat + 600 / map.mapToGameScaleY, lng: weapon.lng });
                const target = map.activeTargetsMarkers.getLayers().find((layer) => !before.has(layer));
                const hold = target.firingSolution1.holdTime.high;
                holds[name] = { hold, popup: popup(target) };
                if (!(hold > 0) || !holds[name].popup.includes(hold.toFixed(app.activeWeapon.elevationPrecision))) failed.push(`${name}: no hold time (${holds[name].popup})`);
                target.delete();
            }
            bridge.selectWeapon("Mortar (M252 / 2B14 / L16 / Type 63)");
            return { failed, holds };
        }, { names: overlay.map(([name]) => name), holdLaid: overlay.filter(([, w]) => w.hold_rate).map(([name]) => name), popupSource: popupText.toString() });
        check(`every Squad Ballistics overlay weapon selectable (${overlay.length})`, selection.failed.length === 0,
            selection.failed.length ? selection.failed.join(" | ") : `all selected and reported back; hold times at 600 m: ${JSON.stringify(selection.holds)}`);
    }
    const removedLink = await page.evaluate(() => ({
        controls: document.querySelectorAll("#overlayLinkSetting, #overlayCode, #overlayCodeNew, #overlayStatus").length,
        storage: ["settings-overlay-link", "overlay-session-code"].filter((key) => localStorage.getItem(key) !== null),
        relayRequests: performance.getEntriesByType("resource").filter((entry) => entry.name.includes("/relay/")).length,
    }));
    check("device link removed", removedLink.controls === 0 && removedLink.storage.length === 0 && removedLink.relayRequests === 0, JSON.stringify(removedLink));

    // The rounds line follows the damage radius setting
    const rounds = await page.evaluate(() => {
        const settings = window.__App.userSettings;
        const target = window.__App.minimap.activeTargetsMarkers.getLayers()[0];
        const shown = () => /calcRounds/.test(target.calcMarker1.getContent());
        settings.set("damageRadius", false);
        const off = shown();
        settings.set("damageRadius", true);
        return { off, on: shown() };
    });
    check("rounds line follows the damage radius setting", !rounds.off && rounds.on, `off: ${rounds.off}, on: ${rounds.on}`);

    // Fire correction: Ctrl + double-click marks a burst; another weapon drops it
    const burstPoint = await page.evaluate(() => {
        const map = window.__App.minimap;
        const target = map.activeTargetsMarkers.getLayers()[0].getLatLng();
        const point = map.latLngToContainerPoint({ lat: target.lat + 25 / map.mapToGameScaleY, lng: target.lng + 25 / map.mapToGameScale });
        const box = map.getContainer().getBoundingClientRect();
        return { x: box.left + point.x, y: box.top + point.y };
    });
    await page.keyboard.down("Control");
    await page.mouse.dblclick(burstPoint.x, burstPoint.y);
    await page.keyboard.up("Control");
    const correction = await page.evaluate(() => {
        const app = window.__App;
        const target = app.minimap.activeTargetsMarkers.getLayers()[0];
        const marked = target.impacts.length;
        const withBurst = /calcCorrection/.test(target.calcMarker1.getContent());
        const other = [...app.WEAPON_SELECTOR[0].options].find((option) => option.value !== app.WEAPON_SELECTOR.val() && option.textContent.includes("UB-32"));
        const previous = app.WEAPON_SELECTOR.val();
        app.WEAPON_SELECTOR.val(other.value).trigger("change");
        const afterChange = target.impacts.length;
        const lineAfter = /calcCorrection/.test(target.calcMarker1.getContent());
        const layersAfter = target.impacts.length === 0 && !app.minimap.markersGroup.getLayers().some((layer) => layer.options?.color === "#f39c12");
        app.WEAPON_SELECTOR.val(previous).trigger("change");
        return { marked, withBurst, afterChange, lineAfter, layersAfter };
    });
    check("burst marked with Ctrl + double-click", correction.marked === 1 && correction.withBurst, JSON.stringify(correction));
    check("bursts dropped when the weapon changes", correction.afterChange === 0 && !correction.lineAfter && correction.layersAfter, JSON.stringify(correction));

    // Hover-out does not recompute the damage zones of every target
    await page.evaluate(() => window.__App.minimap.activeTargetsMarkers.getLayers().forEach((target) => target.delete()));
    await place(page, Array.from({ length: 10 }, (_, i) => [40 * Math.floor(i / 5) - 20, 200 + 40 * (i % 5)]));
    await page.waitForTimeout(500);
    const icon = await page.evaluate(() => { const box = window.__App.minimap.activeTargetsMarkers.getLayers()[0]._icon.getBoundingClientRect(); return { x: box.left + box.width / 2, y: box.top + box.height / 2 }; });
    await page.mouse.move(icon.x, icon.y);
    await page.waitForTimeout(800);
    const hover = await page.evaluate(async () => {
        const targets = window.__App.minimap.activeTargetsMarkers.getLayers();
        const overlays = targets.map((target) => target.coverOverlay);
        window.__hoverOut = performance.now();
        return { overlays: overlays.filter(Boolean).length };
    });
    await page.mouse.move(icon.x + 300, icon.y + 300);
    await page.waitForTimeout(500);
    const after = await page.evaluate(() => {
        const targets = window.__App.minimap.activeTargetsMarkers.getLayers();
        return { visible: targets.filter((target) => target.coverOverlay && target.coverOverlay.options.opacity === 1).length };
    });
    check("damage zones kept through hover", hover.overlays === 10 && after.visible === 10, `zones while hovering ${hover.overlays}/10, visible after ${after.visible}/10`);

    // The damage zone stays above the map image after a layer change (standard images)
    const stacking = await page.evaluate(async () => {
        if (window.__App.userSettings.highQualityImages) document.querySelector(".btn-hd").click();
        await new Promise((resolve) => setTimeout(resolve, 1500));
        document.querySelector("#mapLayerMenu .btn-terrainmap").click();
        await new Promise((resolve) => setTimeout(resolve, 2500));
        const z = (element) => Number(getComputedStyle(element).zIndex) || 0;
        const pane = [...document.querySelector(".leaflet-overlay-pane").children];
        const zone = pane.find((element) => element.classList.contains("coverZoneOverlay"));
        const maps = pane.filter((element) => element.tagName === "IMG" && !element.className.includes("Overlay"));
        // Same z-index: the later one in the pane is on top
        const above = (a, b) => z(a) > z(b) || (z(a) === z(b) && pane.indexOf(a) > pane.indexOf(b));
        return { zone: Boolean(zone), mapImages: maps.length, above: Boolean(zone) && maps.every((image) => above(zone, image)) };
    });
    check("damage zone above the map image after a layer change", stacking.zone && stacking.mapImages > 0 && stacking.above, JSON.stringify(stacking));

    // Detailed layer (tools/maptiles): this deployment's tiles down to the finest zoom, two zoom levels deeper
    // than those, and the upstream layers back at their zoom limit
    const detailed = await page.evaluate(async () => {
        const map = window.__App.minimap;
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const name = map.activeMap.mapURL.split("/").filter(Boolean).pop();
        const meta = await (await fetch(`/maptiles/${name}/meta.json`)).json();
        document.querySelector("#mapLayerMenu .btn-detailed").click();
        await wait(2000);
        const maxZoom = map.getMaxZoom();
        map.setView([-map.pixelSize / 2, map.pixelSize / 2], meta.maxNativeZoom, { animate: false });
        await wait(3000);
        const finest = [...document.querySelectorAll("img.leaflet-tile-loaded")].filter((tile) => tile.src.includes(`/maptiles/${name}/${meta.maxNativeZoom}/`)).length;
        map.setZoom(maxZoom, { animate: false });
        await wait(1000);
        const deepest = map.getZoom();
        document.querySelector("#mapLayerMenu .btn-basemap").click();
        await wait(1500);
        return { map: name, maxNativeZoom: meta.maxNativeZoom, maxZoom, finest, deepest, zoomAfter: map.getZoom(), maxZoomAfter: map.getMaxZoom() };
    });
    check("detailed layer", detailed.finest > 0 && detailed.maxZoom === Math.max(8, detailed.maxNativeZoom + 2) && detailed.deepest === detailed.maxZoom
        && detailed.maxZoomAfter === 8 && detailed.zoomAfter <= 8, JSON.stringify(detailed));

    check("desktop console and requests clean", problems.length === 0, problems.length ? problems.slice(0, 10).join(" | ") : "no errors");

    if (allMaps) {
        // Every map on the detailed layer: a missing tile or meta.json shows up as a failed request or a warning
        await page.evaluate(() => document.querySelector("#mapLayerMenu .btn-detailed").click());
        const maps = await page.evaluate(() => [...window.__App.MAP_SELECTOR[0].options].map((option) => option.value));
        for (const value of maps) {
            const before = problems.length;
            const result = await page.evaluate(async (value) => {
                const app = window.__App;
                const map = app.minimap;
                const longTasks = [];
                const observer = new PerformanceObserver((list) => list.getEntries().forEach((entry) => longTasks.push(entry.duration)));
                observer.observe({ type: "longtask" });
                const start = performance.now();
                app.MAP_SELECTOR.val(value).trigger("change");
                await new Promise((resolve) => { const timer = setInterval(() => { if (map.heightmap.precise) { clearInterval(timer); resolve(); } }, 20); setTimeout(() => { clearInterval(timer); resolve(); }, 120000); });
                const ms = performance.now() - start;
                const folder = map.activeMap.mapURL.split("/").filter(Boolean).pop();
                const detailed = () => map.activeLayer?._url?.startsWith(`/maptiles/${folder}/`);
                await new Promise((resolve) => { const timer = setInterval(() => { if (detailed()) { clearInterval(timer); resolve(); } }, 50); setTimeout(() => { clearInterval(timer); resolve(); }, 10000); });
                await new Promise((resolve) => setTimeout(resolve, 1500));
                observer.disconnect();
                return { name: map.activeMap.name, precise: map.heightmap.precise, detailed: detailed(), ms: Math.round(ms), longest: Math.round(Math.max(0, ...longTasks)) };
            }, value);
            const errors = problems.slice(before);
            check(`map ${result.name}`, result.precise && result.detailed && errors.length === 0,
                `precise heightmap in ${result.ms} ms, longest task ${result.longest} ms, detailed tiles ${result.detailed}${errors.length ? `; ${errors.join(" | ")}` : ""}`);
        }
    }
    await context.close();
});

await group("settings dialog", async () => {
    // Every row of every settings panel stays above the footer of the dialog (on a 1920 x 1080 screen
    // the Mortars panel spilled past the bottom of the fixed-height dialog)
    const { context, page } = await open({ viewport: { width: 1920, height: 1080 } });
    // Real clicks: the dialog closes on a click outside it, and a scripted click has no position
    await page.click(".btn-settings");
    await page.waitForTimeout(1500);
    const settingsRows = [];
    for (const panel of ["panel1", "panel2", "panel3", "panel4"]) {
        await page.click(`#settingsControls button[value='${panel}']`);
        await page.waitForTimeout(300);
        settingsRows.push(...await page.evaluate((panel) => {
            const footer = document.querySelector("#settingsVersion").getBoundingClientRect().top;
            if (!footer) return [`${panel}: dialog not shown`];
            return [...document.querySelectorAll("#helpDialog .panel.active tr")]
                .filter((row) => row.getBoundingClientRect().bottom > footer + 1)
                .map((row) => `${panel}: ${row.textContent.trim().replace(/\s+/g, " ").slice(0, 30)}`);
        }, panel));
    }
    check("settings rows above the dialog footer", settingsRows.length === 0, settingsRows.length ? settingsRows.join(" | ") : "every panel fits");

    await context.close();
});

// Placed mortar and Hell Cannon strat markers show their range circle while hovered (Leaflet 2 fires
// pointerover/pointerout, not mouseover/mouseout), and dragging one pauses the keypad popup under the cursor
// through the pointermove listener it was bound with
await group("strat markers", async () => {
    const { context, page } = await open();
    // The start-up splash still covers the map for a moment after the heights are there: pointer events need it gone
    await page.waitForFunction(() => document.elementFromPoint(800, 500)?.closest("#map"), null, { timeout: 30000 });
    await page.evaluate(() => { window.__App.userSettings.set("keypadUnderCursor", true); });
    for (const [icon, range] of [["deployable_mortars", 1237], ["deployable_hellcannon", 923]]) {
        const marker = await page.evaluate((icon) => {
            const map = window.__App.minimap;
            map.setView([-map.pixelSize / 2, map.pixelSize / 2], 4, { animate: false });
            map.createMarker({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }, "ally", "deployables", icon);
            const marker = window.__strat = map.activeMarkers.getLayers().at(-1);
            return { point: map.latLngToContainerPoint(marker.getLatLng()), rect: map.getContainer().getBoundingClientRect().toJSON() };
        }, icon);
        const shown = () => page.evaluate(() => window.__App.minimap.markersGroup.hasLayer(window.__strat.constructionRange));
        const before = await shown();
        await page.mouse.move(marker.rect.left + marker.point.x + 150, marker.rect.top + marker.point.y + 150);
        await page.mouse.move(marker.rect.left + marker.point.x, marker.rect.top + marker.point.y, { steps: 5 });
        const over = await shown();
        const radius = await page.evaluate(() => window.__strat.constructionRange.getRadius() / window.__App.minimap.gameToMapScale);
        await page.mouse.move(marker.rect.left + marker.point.x + 150, marker.rect.top + marker.point.y + 150, { steps: 5 });
        const after = await shown();
        check(`${icon} marker shows its range circle on hover`, !before && over && !after && Math.abs(radius - range) < 1,
            `before hover ${before}, hovered ${over}, pointer away ${after}, radius ${radius.toFixed(0)} m of ${range} m`);
        await page.evaluate(() => window.__strat.delete());
    }
    const drag = await page.evaluate(() => {
        const map = window.__App.minimap;
        const listening = () => map.listens("pointermove", map._handleMouseMove);
        map.createMarker({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }, "ally", "deployables", "deployable_mortars");
        const marker = map.activeMarkers.getLayers().at(-1);
        const idle = listening();
        marker.fire("dragstart");
        const dragging = listening();
        marker.fire("dragend");
        const dropped = listening();
        marker.delete();
        return { idle, dragging, dropped };
    });
    check("strat marker drag pauses the pointer popup and restores it", drag.idle && !drag.dragging && drag.dropped, JSON.stringify(drag));
    await context.close();
});

// The precise heightmap's requests: meta.json first, then the heavy file it names (heightmap.webp or
// heightmap.png, with ?v=<generated> once meta.json has it)
const preciseRequest = /\/heightmaps\/[^/]+\/(heightmap\.(?:webp|png)|meta\.json)(?:\?.*)?$/;
/**
 * Open SquadCalc with the precise heightmap's requests answered by `answer`
 * @param {(route: object, file: string, attempt: number) => Promise<void>} answer - answers the
 *   `attempt`-th request (1 for the first) of `file` ("heightmap" for the heavy file, "meta.json")
 * @returns {Promise<{requests: object, result: object}>} - the number of requests per file, and the
 *   heightmap's state (map, precise, the toast shown) or {error}
 */
async function openWithHeightmapRequests(answer) {
    const requests = { heightmap: 0, "meta.json": 0 };
    let result;
    try {
        const { context, page } = await open(undefined, (context) => context.route(preciseRequest, (route) => {
            const file = route.request().url().match(preciseRequest)[1].replace(/\.(webp|png)$/, "");
            requests[file] += 1;
            return answer(route, file, requests[file]);
        }), false);
        result = await page.evaluate(() => {
            const map = window.__App.minimap;
            return { map: map.activeMap.name, precise: map.heightmap.precise, failed: map.heightmap.failed, toast: document.querySelector("#toast h4").getAttribute("data-i18n") };
        });
        await context.close();
    } catch (error) {
        result = { error: error.message.split("\n")[0] };
    }
    return { requests, result };
}

// A heightmap request the network drops (connection lost) is tried again: the map still gets its
// precise heightmap instead of silently keeping the coarse 8-bit one
for (const dropped of ["heightmap", "meta.json"]) {
    const { requests, result } = await openWithHeightmapRequests((route, file, attempt) =>
        file === dropped && attempt === 1 ? route.abort("internetdisconnected") : route.fallback());
    check(`precise heightmap after a dropped ${dropped} request`, requests[dropped] >= 2 && result.precise === true,
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A network that keeps dropping it: four attempts, then the 8-bit heightmap with a warning toast
    const { requests, result } = await openWithHeightmapRequests((route, file) =>
        file === "heightmap" ? route.abort("internetdisconnected") : route.fallback());
    check("coarse heightmap announced when the network keeps dropping it",
        requests.heightmap === 4 && result.precise === false && result.failed === false && result.toast === "tooltips:heightmapCoarse",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A deployment without precise heightmaps (meta.json 404) falls back at once: one request, the heavy file is not downloaded, no warning
    const { requests, result } = await openWithHeightmapRequests((route) => route.fulfill({ status: 404, body: "" }));
    check("no precise heightmap (404): 8-bit one at once, no retry, no heavy download",
        requests.heightmap === 0 && requests["meta.json"] === 1 && result.precise === false && result.failed === false && result.toast !== "tooltips:heightmapCoarse",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // The WebP of a heightmap is unusable (a 404, or bytes the browser cannot decode): the PNG is read instead
    for (const [label, answer] of [["missing", (route) => route.fulfill({ status: 404, body: "" })], ["corrupt", (route) => route.fulfill({ status: 200, contentType: "image/webp", body: "not a webp" })]]) {
        const { requests, result } = await openWithHeightmapRequests((route, file) =>
            file === "heightmap" && /\.webp(\?|$)/.test(route.request().url()) ? answer(route) : route.fallback());
        const announcedWebp = requests.heightmap > 0 && await fetch(new URL("/heightmaps/albasrah/meta.json", base)).then((response) => response.json()).then((meta) => meta.format === "webp-rg16");
        check(`precise heightmap from the PNG when the WebP is ${label}`, !result.error && (!announcedWebp || (requests.heightmap === 2 && result.precise === true)),
            `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
    }
}

await group("mobile", async () => {
    // Mobile: a tap places the weapon, the next one a target
    const { context, page, problems } = await open({
        viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3,
        userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    });
    // The map fades in after the heightmap; taps before that are lost
    await page.waitForTimeout(1000);
    await page.evaluate(() => { const map = window.__App.minimap; map.setView([-map.pixelSize / 2, map.pixelSize / 2], 4, { animate: false }); });
    const center = await page.evaluate(() => { const box = window.__App.minimap.getContainer().getBoundingClientRect(); return { x: box.left + box.width / 2, y: box.top + box.height / 2 }; });
    await page.touchscreen.tap(center.x, center.y + 120);
    await page.waitForFunction(() => window.__App.minimap.activeWeaponsMarkers.getLayers().length === 1, null, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(2000);
    await page.touchscreen.tap(center.x, center.y - 100);
    await page.waitForFunction(() => window.__App.minimap.activeTargetsMarkers.getLayers().length === 1, null, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(500);
    const mobile = await page.evaluate((popupSource) => {
        const popup = new Function(`return ${popupSource}`)();
        const map = window.__App.minimap;
        const target = map.activeTargetsMarkers.getLayers()[0];
        return { weapons: map.activeWeaponsMarkers.getLayers().length, targets: map.activeTargetsMarkers.getLayers().length, popup: target && popup(target) };
    }, popupText.toString());
    check("mobile: tap places a weapon then a target", mobile.weapons === 1 && mobile.targets === 1 && /\d/.test(mobile.popup || ""), JSON.stringify(mobile));
    check("mobile console and requests clean", problems.length === 0, problems.length ? problems.slice(0, 10).join(" | ") : "no errors");
    await context.close();
});

// What the removed device link saved in a browser is dropped on the next visit
await group("stale device link storage", async () => {
    const { context, page, problems } = await open(undefined, (context) => context.addInitScript(() => {
        if (sessionStorage.getItem("seeded")) return;
        sessionStorage.setItem("seeded", "1");
        localStorage.setItem("settings-overlay-link", "1");
        localStorage.setItem("overlay-session-code", "ABCDEFGH2345");
    }));
    const left = await page.evaluate(() => ["settings-overlay-link", "overlay-session-code"].filter((key) => localStorage.getItem(key) !== null));
    check("stale device link storage dropped", left.length === 0 && problems.length === 0, left.length ? `left: ${left}` : problems.length ? problems.join(" | ") : "keys removed, console clean");
    await context.close();
});

await browser.close();
if (networkChanges) console.log(`${networkChanges} request(s) were dropped by a change of the host's network (${NETWORK_CHANGED}): a check that lists that error or lost a request to it says nothing about the site, run it again`);
console.log(failures ? `${failures} of ${checks} browser checks failed` : `all ${checks} browser checks passed`);
process.exit(failures ? 1 : 0);
