// Checks the Deadline SquadCalc in a real browser (Chromium through Playwright): the console stays clean,
// the heightmaps load (also when the network drops a request), the detailed map layer works, and the
// bugs fixed in 45.5.1 and in the walkthrough review (walkthrough.mjs) stay fixed.
//
//     node browser_check.mjs <site URL> [--maps] [--ballistics <weapons.json>]
//
// <site URL> is a served build with the heightmaps under /heightmaps/ (the stand, or Caddy over
// a local `npm run build`). --maps also switches through every map on the detailed layer and checks each
// loads its heightmap and its detailed tiles (tools/maptiles) without a failed request. --ballistics
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
 * @param {boolean} [loaded] - wait for the heightmap (true) or for any heightmap result, also a failure (false)
 * @throws {Error} when the page does not load, or the heightmap or the map image does not, within 120 s each: the
 *   error says which of the three and why (Playwright's reason), with the spinner's count and the requests without
 *   an answer, and the context is closed
 */
async function open(contextOptions = { viewport: { width: 1600, height: 1000 } }, prepare = async () => {}, loaded = true) {
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
    // A step of the opening that failed says what the page still waited for: the spinner's count and the requests
    // without an answer
    const stalled = (what) => async (error) => {
        const spinning = await page.evaluate(() => window.__App?.minimap?._spinning).catch(() => undefined);
        const requests = [...unanswered].map((request) => request.url());
        throw new Error(`${what}: ${error.message.split("\n")[0]} (spinner count ${spinning}, ${requests.length} request(s) without an answer${requests.length ? `: ${requests.slice(0, 5).join(", ")}` : ""})`);
    };
    try {
        await page.goto(base, { waitUntil: "load", timeout: 120000 }).catch(stalled("the page did not load"));
        await page.waitForFunction((loaded) => {
            const heightmap = window.__App?.minimap?.heightmap;
            return loaded ? heightmap?.ready : heightmap?.ready || heightmap?.failed;
        }, loaded, { timeout: 120000 }).catch(stalled("no heightmap"));
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

    // Markers placed before the heightmap arrives are solved again once it has
    const stale = await page.evaluate(async (popupSource) => {
        const popup = new Function(`return ${popupSource}`)();
        const app = window.__App;
        const map = app.minimap;
        const other = [...app.MAP_SELECTOR[0].options].find((option) => option.value !== app.MAP_SELECTOR.val());
        app.MAP_SELECTOR.val(other.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 0));
        const loadedBefore = map.heightmap.ready;
        const scale = map.mapToGameScale;
        const scaleY = map.mapToGameScaleY;
        const weapon = { lat: -map.pixelSize * 0.45, lng: map.pixelSize * 0.45 };
        map.createWeapon(weapon);
        const target = map.createTarget({ lat: weapon.lat + 400 / scaleY, lng: weapon.lng + 200 / scale }) || map.activeTargetsMarkers.getLayers()[0];
        // While the heights load the popup says it has no height data and the bridge sends no height
        const early = { heightDiff: window.squadBallistics.lastTarget()?.heightDiff, noHeightLine: popup(target).includes("height"), noHeightClass: target.calcMarker1.getContent().includes("calcNoHeight"), profile: window.squadBallistics.lastTarget()?.profile };
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.heightmap.ready) { clearInterval(timer); resolve(); } }, 50); });
        await new Promise((resolve) => setTimeout(resolve, 300));
        const shown = popup(target);
        const heightDiff = target.firingSolution1.heightDiff;
        target.updateCalc();
        const late = window.squadBallistics.lastTarget();
        return { early, late: { heightDiff: late?.heightDiff, hasProfile: Boolean(late?.profile) }, loadedBefore, map: map.activeMap.name, shown, fresh: popup(target), heightDiff, expected: map.heightmap.getHeight(target.getLatLng()) - map.heightmap.getHeight(weapon) };
    }, popupText.toString());
    check("solution after the heightmap loads", !stale.loadedBefore && stale.shown === stale.fresh && Math.abs(stale.heightDiff - stale.expected) < 0.01,
        `${stale.map}: shown "${stale.shown}", recomputed "${stale.fresh}", height difference ${stale.heightDiff.toFixed(2)} m of ${stale.expected.toFixed(2)} m`);

    check("heights unknown until the heightmap loaded", stale.early.heightDiff === null && stale.early.noHeightClass && stale.early.profile === null
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
        document.querySelector("#mapLayerMenu .btn-basemap").click();
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
                await new Promise((resolve) => { const timer = setInterval(() => { if (map.heightmap.ready) { clearInterval(timer); resolve(); } }, 20); setTimeout(() => { clearInterval(timer); resolve(); }, 120000); });
                const ms = performance.now() - start;
                const folder = map.activeMap.mapURL.split("/").filter(Boolean).pop();
                const detailed = () => map.activeLayer?._url?.startsWith(`/maptiles/${folder}/`);
                await new Promise((resolve) => { const timer = setInterval(() => { if (detailed()) { clearInterval(timer); resolve(); } }, 50); setTimeout(() => { clearInterval(timer); resolve(); }, 10000); });
                await new Promise((resolve) => setTimeout(resolve, 1500));
                observer.disconnect();
                return { name: map.activeMap.name, ready: map.heightmap.ready, detailed: detailed(), ms: Math.round(ms), longest: Math.round(Math.max(0, ...longTasks)) };
            }, value);
            const errors = problems.slice(before);
            check(`map ${result.name}`, result.ready && result.detailed && errors.length === 0,
                `heightmap in ${result.ms} ms, longest task ${result.longest} ms, detailed tiles ${result.detailed}${errors.length ? `; ${errors.join(" | ")}` : ""}`);
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
    for (const [icon, range] of [["deployable_mortars", 1237], ["deployable_hellcannon", 924]]) {
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
        const radius = await page.evaluate(() => window.__strat.constructionRange.getRadius());
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

// The circles and outlines a gameplay layer decides (SquadCalc 45.42.0 and 45.45.0; needs the layer API). The
// exclusion circle of a FOB marker is the loaded layer's, whenever the layer came: the map's 400 m on Al Basrah without
// a layer, 300 m once Al Basrah RAAS v3 has loaded, 400 m once RAAS v1 replaced it, and the map's 400 m again when the
// layer is cleared. On Goose Bay AAS v1 the protection zone of the first main, whose radius the layer data gives as
// negative, is drawn with the game's 236 m and its no-deploy circle 150 m further (386 m), the second main's with
// 150 m and 300 m. The capsule of Kohat TC v1 is drawn as its footprint and the three boxes of Fallujah Invasion v2's
// second zone each with its size and turn, none of them with a dashed outline; the point of 0.44 m of Sumari Invasion
// v1 has its no-deploy box of 50.44 m. While no layer is loaded, before the first one and after the layer was
// cleared, the settings that restyle a layer switch without an error.
await group("circles of the loaded layer", async () => {
    const { context, page, problems } = await open();
    // The layer API is asked at most once a second
    const apiPause = () => page.waitForTimeout(1100);
    /** Show the map `name` (unless it is shown) and wait until the selector offers its layer `layer` */
    const showMap = async (name, layer) => {
        await apiPause();
        await page.evaluate((name) => {
            const app = window.__App;
            if (app.minimap.activeMap.name !== name) app.MAP_SELECTOR.val(app.MAP_SELECTOR.find(`option[data-i18n="maps:${name}"]`).val()).trigger("change");
        }, name);
        await page.waitForFunction(([name, layer]) => window.__App.minimap.activeMap.name === name && [...window.__App.LAYER_SELECTOR[0].options].some((option) => option.value === layer), [name, layer], { timeout: 120000 });
    };
    /** Pick `layer` in the layer selector and wait until the map shows it */
    const loadLayer = async (layer) => {
        await apiPause();
        await page.evaluate((layer) => window.__App.LAYER_SELECTOR.val(layer).trigger("change"), layer);
        await page.waitForFunction((layer) => window.__App.minimap.layer?.layerData?.rawName === layer && !window.__App.minimap._spinning, layer, { timeout: 120000 });
    };
    /** Radius of the exclusion circle of every FOB marker on the map, in metres, in the order they were placed */
    const fobCircles = () => page.evaluate(() => {
        const map = window.__App.minimap;
        return map.activeMarkers.getLayers().filter((marker) => marker.icontype === "deployable_fob")
            .map((marker) => (map.markersGroup.hasLayer(marker.exclusionRange) ? Math.round(marker.exclusionRange.getRadius() * 10) / 10 : null));
    });
    /** Place a FOB marker `east` metres east of the map's centre, as the context menu does */
    const placeFob = (east) => page.evaluate((east) => {
        const map = window.__App.minimap;
        map.createMarker({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 + east * map.gameToMapScale }, "default", "deployables", "deployable_fob");
    }, east);
    const same = (actual, expected) => JSON.stringify(actual) === JSON.stringify(expected);
    /** Switch the settings that restyle a layer there and back, zoomed in to where its assets show; the error, if any */
    const restyle = () => page.evaluate(() => {
        const app = window.__App;
        app.minimap.setView(app.minimap.getCenter(), 5, { animate: false });
        try {
            for (const name of ["showRespawnCam", "showMapBorders", "showMainZones", "showMainAssets"]) {
                app.userSettings.set(name, !app.userSettings[name]);
                app.userSettings.set(name, !app.userSettings[name]);
            }
            return null;
        } catch (error) {
            return error.message;
        }
    });

    await showMap("AlBasrah", "AlBasrah_RAAS_v3");
    const restyledBeforeLayer = await restyle();
    await placeFob(0);
    const withoutLayer = await fobCircles();
    await loadLayer("AlBasrah_RAAS_v3");
    const layerArrived = await fobCircles();
    await placeFob(500);
    const onSmallLayer = await fobCircles();
    check("FOB circle: the map's 400 m without a layer, 300 m once Al Basrah RAAS v3 has loaded, for the marker placed before it too",
        same(withoutLayer, [400]) && same(layerArrived, [300]) && same(onSmallLayer, [300, 300]),
        `without a layer ${JSON.stringify(withoutLayer)} m, once the layer loaded ${JSON.stringify(layerArrived)} m, with a FOB placed on it ${JSON.stringify(onSmallLayer)} m`);

    await loadLayer("AlBasrah_RAAS_v1");
    const onMediumLayer = await fobCircles();
    check("FOB circles follow a change of layer: 400 m on Al Basrah RAAS v1", same(onMediumLayer, [400, 400]), `${JSON.stringify(onMediumLayer)} m`);

    await loadLayer("AlBasrah_RAAS_v3");
    const backOnSmallLayer = await fobCircles();
    await page.evaluate(() => window.__App.LAYER_SELECTOR.val("").trigger("change"));
    await placeFob(1000);
    const cleared = await page.evaluate(() => Boolean(window.__App.minimap.layer));
    const afterClear = await fobCircles();
    const restyledAfterClear = await restyle();
    check("FOB circles return to the map's 400 m when the layer is cleared, and a FOB placed then has it",
        same(backOnSmallLayer, [300, 300]) && !cleared && same(afterClear, [400, 400, 400]),
        `on RAAS v3 again ${JSON.stringify(backOnSmallLayer)} m, layer cleared (a layer still loaded: ${cleared}) ${JSON.stringify(afterClear)} m`);

    check("layer settings switch without an error while no layer is loaded", restyledBeforeLayer === null && restyledAfterClear === null,
        `before the first layer: ${restyledBeforeLayer ?? "no error"}; after the layer was cleared: ${restyledAfterClear ?? "no error"}`);

    await showMap("GooseBay", "GooseBay_AAS_v1");
    await loadLayer("GooseBay_AAS_v1");
    const zones = await page.evaluate(() => {
        const map = window.__App.minimap;
        const layer = map.layer;
        return layer.layerData.mapAssets.protectionZones.map((zone) => {
            const [lat, lng] = layer.convertToLatLng(zone.objects[0].location_x, zone.objects[0].location_y);
            const circles = layer.mainZones.rectangles.filter((shape) => shape.getRadius && map.hasLayer(shape)
                && Math.abs(shape.getLatLng().lat - lat) < 1e-6 && Math.abs(shape.getLatLng().lng - lng) < 1e-6);
            return { team: zone.teamid, dataRadius: zone.objects[0].sphereRadius / 100, drawn: circles.map((circle) => circle.getRadius()) };
        });
    });
    // The game: a sphere of 150 m scaled by -1.5759 at the first main (236.4 m), 150 m at the second; the dashed
    // circles are the zones grown by their lock distance of 150 m
    const expectedZones = [["1", [236.38, 386.38]], ["2", [150, 300]]];
    const zonesDrawn = zones.length === 2 && expectedZones.every(([team, radii], index) => zones[index].team === team && zones[index].drawn.length === 2
        && radii.every((radius, at) => Math.abs(zones[index].drawn[at] - radius) < 0.01));
    check("Goose Bay AAS v1: protection and no-deploy circles of both mains, the first main's from a negative radius in the layer data",
        zonesDrawn && zones[0].dataRadius < 0,
        zones.map((zone) => `team ${zone.team}: radius in the layer data ${zone.dataRadius.toFixed(2)} m, circles drawn ${JSON.stringify(zone.drawn.map((radius) => Number(radius.toFixed(2))))} m`).join("; "));

    /**
     * The outlines of the loaded layer's protection zones centred within 5 cm of the world point `centre` (cm): circle
     * or polygon, dashed or not, a circle's radius, and how far a polygon reaches from there along the direction
     * `degrees` (from world X towards world Y) both ways and across it both ways, in metres
     */
    const outlinesAt = (centre, degrees) => page.evaluate(([centre, degrees]) => {
        const map = window.__App.minimap;
        const layer = map.layer;
        const [lat, lng] = layer.convertToLatLng(centre[0], centre[1]);
        const toMetres = (point) => [(point.lng - lng) * map.mapToGameScale, -(point.lat - lat) * map.mapToGameScaleY];
        const turn = degrees * Math.PI / 180;
        const round = (metres) => Math.round(metres * 100) / 100;
        return layer.mainZones.rectangles.filter((shape) => map.hasLayer(shape)).flatMap((shape) => {
            const dashed = Boolean(shape.options.dashArray);
            if (shape.getRadius) {
                return Math.hypot(...toMetres(shape.getLatLng())) < 0.05 ? [{ kind: "circle", dashed, radius: round(shape.getRadius()) }] : [];
            }
            const points = shape.getLatLngs()[0].map(toMetres);
            const mean = [0, 1].map((axis) => points.reduce((sum, point) => sum + point[axis], 0) / points.length);
            if (Math.hypot(...mean) >= 0.05) return [];
            const along = points.map(([x, y]) => x * Math.cos(turn) + y * Math.sin(turn));
            const across = points.map(([x, y]) => -x * Math.sin(turn) + y * Math.cos(turn));
            return [{ kind: "polygon", dashed, reach: [Math.max(...along), -Math.min(...along), Math.max(...across), -Math.min(...across)].map(round) }];
        });
    }, [centre, degrees]);
    /** Outlines as `outlinesAt` gives them against the expected ones, sizes within 5 cm */
    const sameOutlines = (actual, expected) => actual.length === expected.length && expected.every((outline, index) => actual[index].kind === outline.kind
        && actual[index].dashed === outline.dashed && [outline.reach ?? [outline.radius]].flat().every((metres, at) => Math.abs([actual[index].reach ?? [actual[index].radius]].flat()[at] - metres) < 0.05));
    const solid = (along, across) => ({ kind: "polygon", dashed: false, reach: [along, along, across, across] });

    // Team 2's first zone (Team2ProtectionZone1) is a capsule of radius 200 m and half-height 600 m, centred at
    // (150212.58, -152349.81) cm, pitched by -87.18282 degrees, yaw -171.56177, roll -180: seen from above the segment
    // between its half-spheres' centres is 2 x 400 m x |sin(pitch)| long, along the yaw turned by 180 degrees
    await showMap("Kohat", "Kohat_TC_v1");
    await loadLayer("Kohat_TC_v1");
    const capsuleHalfLength = 400 * Math.abs(Math.sin(-87.18282 * Math.PI / 180));
    const capsule = await outlinesAt([150212.58, -152349.81], -171.56177 + 180);
    check("Kohat TC v1: the capsule zone of team 2 is its footprint on the map, 1199 m by 400 m along 8.44 degrees, without a dashed outline",
        sameOutlines(capsule, [solid(capsuleHalfLength + 200, 200)]),
        `outlines at the capsule's centre ${JSON.stringify(capsule)}; the game's reach ${(capsuleHalfLength + 200).toFixed(2)} m along, 200 m across`);

    // Team 1's second zone (Team1ProtectionZone2): boxes Box, Box1 and Box2 of half-size 3 x 35 m, 25 x 20 m and
    // 15 x 15 m at the centres (cm) and with the yaws (degrees) of the level
    await showMap("Fallujah", "Fallujah_Invasion_v2");
    await loadLayer("Fallujah_Invasion_v2");
    const fallujahBoxes = [[[-109939.67, 600.3696], -24.905027, 3, 35], [[-111755.67, -2131.6304], -33.847927, 25, 20], [[-108480.67, 3529.3696], -28.723526, 15, 15]];
    const boxes = [];
    for (const [centre, yaw] of fallujahBoxes) boxes.push(await outlinesAt(centre, yaw));
    check("Fallujah Invasion v2: the three boxes of team 1's second zone, each with the game's size and turn, without a dashed outline",
        fallujahBoxes.every(([, , x, y], index) => sameOutlines(boxes[index], [solid(x, y)])),
        boxes.map((outlines, index) => `box ${index + 1}: ${JSON.stringify(outlines)}`).join("; "));

    // Team 2's third zone (Team2ProtectionZone2): a box of 0.5 m scaled by 0.888996, centred at (-32086.55, 3599.1) cm,
    // yaw -17.40924, lock distance 50 m
    await showMap("Sumari", "Sumari_Invasion_v1");
    await loadLayer("Sumari_Invasion_v1");
    const point = 0.5 * 0.888996;
    const pointOutlines = await outlinesAt([-32086.55, 3599.1], -17.40924);
    check("Sumari Invasion v1: the point of 0.44 m of team 2 and its dashed no-deploy box of 50.44 m",
        sameOutlines(pointOutlines, [solid(point, point), { kind: "polygon", dashed: true, reach: Array(4).fill(point + 50) }]), JSON.stringify(pointOutlines));

    check("layer circles: console and requests clean", problems.length === 0, problems.length ? problems.slice(0, 10).join(" | ") : "no errors");
    await context.close();
});

// Every layer change ends its turn of the map's spinner (SquadCalc 45.39.0): a change another one supersedes in
// the same task, a tile layer another image replaces while its tiles still load (Leaflet fires no load event
// for a layer taken off the map), a map image that fails to load and a tile layer with no tile in view. Each
// time one map image is left on the map. Before 45.39.0 the spinner could be left turning at page load too (the
// first change still waited for its meta.json when the page drew the map again), and open() timed out.
await group("spinner after layer changes", async () => {
    // Tiles of /maptiles/ are held back while `holdTiles` is set (a tile layer that keeps loading); the
    // upstream basemap never loads
    let holdTiles = null;
    const { context, page, problems } = await open(undefined, async (context) => {
        await context.route(/\/maptiles\/[a-z0-9_-]+\/\d+\/\d+_\d+\.webp/, async (route) => {
            if (holdTiles) await holdTiles;
            // The page may have dropped the request by now (its layer left the map)
            await route.fallback().catch(() => {});
        });
        await context.route(/\/basemap\.webp/, (route) => route.abort("failed"));
    });
    const click = (layer) => page.evaluate((layer) => document.querySelector(`#mapLayerMenu .btn-${layer}`).click(), layer);
    // Whether the spinner is gone within 20 s, and the map images then on the map (tile layers and single images)
    const settled = async () => {
        const stopped = await page.waitForFunction(() => !window.__App.minimap._spinning, null, { timeout: 20000 }).then(() => true, () => false);
        return page.evaluate((stopped) => {
            const map = window.__App.minimap;
            let images = 0;
            map.eachLayer((layer) => { if (layer._tiles || layer._image) images++; });
            return { stopped, spinning: map._spinning, images };
        }, stopped);
    };

    await page.evaluate(() => { const map = window.__App.minimap; map.changeLayer(); map.changeLayer(); });
    const superseded = await settled();
    check("spinner stops after a layer change that superseded another", superseded.stopped && superseded.images === 1, JSON.stringify(superseded));

    const folder = await page.evaluate(() => window.__App.minimap.activeMap.mapURL.split("/").filter(Boolean).pop());
    let release;
    let replaced;
    holdTiles = new Promise((resolve) => { release = resolve; });
    try {
        await click("detailed");
        await page.waitForFunction((folder) => window.__App.minimap.activeLayer?._url?.startsWith(`/maptiles/${folder}/`), folder, { timeout: 20000 });
        await click("relief");
        replaced = await settled();
    } finally {
        holdTiles = null;
        release();
    }
    check("spinner stops after a tile layer was replaced while it loaded", replaced.stopped && replaced.images === 1, JSON.stringify(replaced));

    await click("basemap");
    const failed = await settled();
    check("spinner stops after a map image that failed to load", failed.stopped && failed.images === 1, JSON.stringify(failed));

    await page.evaluate(() => { const map = window.__App.minimap; map.setView([map.pixelSize * 4, -map.pixelSize * 4], 4, { animate: false }); });
    await click("detailed");
    const away = await settled();
    // Back over the map, the layer that had nothing to load shows its tiles
    await page.evaluate(() => { const map = window.__App.minimap; map.setView([-map.pixelSize / 2, map.pixelSize / 2], 4, { animate: false }); });
    const tiles = await page.waitForFunction((folder) => [...document.querySelectorAll("img.leaflet-tile-loaded")].some((tile) => tile.src.includes(`/maptiles/${folder}/`)), folder, { timeout: 20000 }).then(() => true, () => false);
    const back = await settled();
    check("spinner stops when no tile of the new layer is in view", away.stopped && away.images === 1 && tiles && back.stopped && back.images === 1,
        `map dragged away ${JSON.stringify(away)}, back over the map: tiles shown ${tiles}, ${JSON.stringify(back)}`);

    const unexpected = problems.filter((problem) => !/basemap\.webp|net::ERR_FAILED/.test(problem));
    check("layer changes: console and requests clean but for the basemap that was refused", unexpected.length === 0, unexpected.length ? unexpected.slice(0, 10).join(" | ") : "no other errors");
    await context.close();
});

// Layers across map changes (SquadCalc 45.47.0; needs the layer API). A Training layer of Pacific Proving Grounds,
// whose objectives the calculator does not draw, opens with its other assets and ends its turn of the spinner (it
// threw and left the spinner turning). A layer whose answer is still on its way when the map changes is not drawn on
// the new map. A list of layers that arrives after the map changed again does not fill the selector.
await group("layers across map changes", async () => {
    // The answer of Al Basrah RAAS v3 and the list of Mutaha's layers are held back while their promise is set
    let holdLayer = null;
    let holdList = null;
    const { context, page, problems } = await open(undefined, async (context) => {
        await context.route(/\/get\/layer\?name=AlBasrah_RAAS_v3$/, async (route) => {
            if (holdLayer) await holdLayer;
            // The page may have dropped the request by now (the map changed)
            await route.fallback().catch(() => {});
        });
        await context.route(/\/get\/layers\?map=Mutaha$/, async (route) => {
            if (holdList) await holdList;
            await route.fallback().catch(() => {});
        });
    });
    // The layer API is asked at most once a second
    const apiPause = () => page.waitForTimeout(1100);
    const pickMap = (name) => page.evaluate((name) => {
        const app = window.__App;
        app.MAP_SELECTOR.val(app.MAP_SELECTOR.find(`option[data-i18n="maps:${name}"]`).val()).trigger("change");
    }, name);
    /** Whether the selector offers `layer` within 60 s */
    const listed = (layer) => page.waitForFunction((layer) => [...window.__App.LAYER_SELECTOR[0].options].some((option) => option.value === layer), layer, { timeout: 60000 }).then(() => true, () => false);
    const pick = (layer) => page.evaluate((layer) => window.__App.LAYER_SELECTOR.val(layer).trigger("change"), layer);
    const state = () => page.evaluate(() => {
        const map = window.__App.minimap;
        return { map: map.activeMap.name, layer: map.layer?.layerData?.rawName ?? null, spinning: map._spinning,
            options: [...window.__App.LAYER_SELECTOR[0].options].map((option) => option.value).filter(Boolean) };
    });
    const pageErrors = () => problems.filter((problem) => problem.startsWith("pageerror"));

    await apiPause();
    await pickMap("Pacific");
    const pacific = await listed("PacificProvingGrounds_USMC-RGF");
    await apiPause();
    await pick("PacificProvingGrounds_USMC-RGF");
    const opened = await page.waitForFunction(() => window.__App.minimap.layer?.layerData?.rawName === "PacificProvingGrounds_USMC-RGF" && !window.__App.minimap._spinning,
        null, { timeout: 60000 }).then(() => true, () => false);
    const training = await state();
    check("a Training layer of Pacific Proving Grounds opens without objectives and the spinner stops", pacific && opened && pageErrors().length === 0,
        `${JSON.stringify({ ...training, options: undefined })}, page errors: ${pageErrors().join(" | ") || "none"}`);

    let releaseLayer;
    holdLayer = new Promise((resolve) => { releaseLayer = resolve; });
    await apiPause();
    await pickMap("AlBasrah");
    const alBasrah = await listed("AlBasrah_RAAS_v3");
    await apiPause();
    await pick("AlBasrah_RAAS_v3");
    await page.waitForTimeout(500);
    await apiPause();
    await pickMap("Jensen");
    const jensen = await listed("JensensRange_ADF-PLAAGF");
    releaseLayer();
    holdLayer = null;
    await page.waitForTimeout(6000);
    const moved = await state();
    check("a layer still loading when the map changes is not drawn on the new map", alBasrah && jensen && moved.map === "Jensen" && moved.layer !== "AlBasrah_RAAS_v3" && moved.spinning === 0,
        JSON.stringify({ ...moved, options: undefined }));

    let releaseList;
    holdList = new Promise((resolve) => { releaseList = resolve; });
    await apiPause();
    await pickMap("Mutaha");
    await apiPause();
    await pickMap("AlBasrah");
    const listedAgain = await listed("AlBasrah_RAAS_v3");
    releaseList();
    holdList = null;
    await page.waitForTimeout(6000);
    const late = await state();
    check("a list of layers that arrives after the map changed again does not fill the selector", listedAgain && late.map === "AlBasrah"
        && late.options.length > 0 && late.options.every((layer) => layer.startsWith("AlBasrah")) && late.spinning === 0,
        JSON.stringify(late));
    check("layers across map changes: no page error", pageErrors().length === 0, pageErrors().join(" | ") || "none");
    await context.close();
});

// The heightmap's requests: meta.json first, then the heavy file it names (heightmap.webp or
// heightmap.png, with ?v=<generated> once meta.json has it)
const heightmapRequest = /\/heightmaps\/[^/]+\/(heightmap\.(?:webp|png)|meta\.json)(?:\?.*)?$/;
/**
 * Open SquadCalc with the heightmap's requests answered by `answer`
 * @param {(route: object, file: string, attempt: number) => Promise<void>} answer - answers the
 *   `attempt`-th request (1 for the first) of `file` ("heightmap" for the heavy file, "meta.json")
 * @returns {Promise<{requests: object, result: object}>} - the number of requests per file, and the
 *   heightmap's state (map, ready, failed, the toast shown) or {error}
 */
async function openWithHeightmapRequests(answer) {
    const requests = { heightmap: 0, "meta.json": 0 };
    let result;
    try {
        const { context, page } = await open(undefined, (context) => context.route(heightmapRequest, (route) => {
            const file = route.request().url().match(heightmapRequest)[1].replace(/\.(webp|png)$/, "");
            requests[file] += 1;
            return answer(route, file, requests[file]);
        }), false);
        result = await page.evaluate(() => {
            const map = window.__App.minimap;
            return { map: map.activeMap.name, ready: map.heightmap.ready, failed: map.heightmap.failed, toast: document.querySelector("#toast h4").getAttribute("data-i18n") };
        });
        await context.close();
    } catch (error) {
        result = { error: error.message.split("\n")[0] };
    }
    return { requests, result };
}

// A heightmap request the network drops (connection lost) is tried again: the map still gets its heightmap
for (const dropped of ["heightmap", "meta.json"]) {
    const { requests, result } = await openWithHeightmapRequests((route, file, attempt) =>
        file === dropped && attempt === 1 ? route.abort("internetdisconnected") : route.fallback());
    check(`heightmap after a dropped ${dropped} request`, requests[dropped] >= 2 && result.ready === true,
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A network that keeps dropping it: four attempts, then no heights, with an error toast
    const { requests, result } = await openWithHeightmapRequests((route, file) =>
        file === "heightmap" ? route.abort("internetdisconnected") : route.fallback());
    check("failed heightmap announced when the network keeps dropping it",
        requests.heightmap === 4 && result.ready === false && result.failed === true && result.toast === "tooltips:heightmapFailed",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A deployment without the map's heightmap (meta.json 404) fails at once: one request, the heavy file is not downloaded
    const { requests, result } = await openWithHeightmapRequests((route) => route.fulfill({ status: 404, body: "" }));
    check("no heightmap (404): failed at once, no retry, no heavy download",
        requests.heightmap === 0 && requests["meta.json"] === 1 && result.ready === false && result.failed === true && result.toast === "tooltips:heightmapFailed",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // The WebP of a heightmap is unusable (a 404, or bytes the browser cannot decode): the PNG is read instead
    for (const [label, answer] of [["missing", (route) => route.fulfill({ status: 404, body: "" })], ["corrupt", (route) => route.fulfill({ status: 200, contentType: "image/webp", body: "not a webp" })]]) {
        const { requests, result } = await openWithHeightmapRequests((route, file) =>
            file === "heightmap" && /\.webp(\?|$)/.test(route.request().url()) ? answer(route) : route.fallback());
        const announcedWebp = requests.heightmap > 0 && await fetch(new URL("/heightmaps/albasrah/meta.json", base)).then((response) => response.json()).then((meta) => meta.format === "webp-rg16");
        check(`heightmap from the PNG when the WebP is ${label}`, !result.error && (!announcedWebp || (requests.heightmap === 2 && result.ready === true)),
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
