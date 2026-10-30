// Checks the Deadline SquadCalc in a real browser (Chromium through Playwright): the console stays clean,
// the precise heightmaps load (also when the network drops a request), and the bugs fixed in 45.5.1
// and in the walkthrough review (walkthrough.mjs) stay fixed.
//
//     node browser_check.mjs <site URL> [--maps]
//
// <site URL> is a served build with the precise heightmaps under /heightmaps/ (the stand, or Caddy over
// a local `npm run build`). --maps also switches through every map and checks each loads its precise
// heightmap. Environment: PLAYWRIGHT_CORE = path of the playwright-core package if it is not
// resolvable from here, CHROME = Chromium executable if Playwright's own is not installed.
// Exits with 1 on any failure.
//
// SquadCalc keeps its App in a module; the check exposes it as window.__App by rewriting the main
// bundle in transit (the served files are not changed).
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node browser_check.mjs <site URL> [--maps]");
    process.exit(2);
}
const allMaps = process.argv.includes("--maps");

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/**
 * Open SquadCalc with window.__App and a log of console errors, page errors and failed requests
 * @param {object} [contextOptions] - Playwright browser context options (viewport, mobile emulation)
 * @param {(context: object) => Promise<void>} [prepare] - called with the context before the page loads (routes)
 * @param {boolean} [precise] - wait for the precise heightmap (true) or for any heightmap result, also
 *   the 8-bit one or a failure (false)
 * @throws {Error} when the heightmap does not load within 120 s
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
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction((precise) => {
        const heightmap = window.__App?.minimap?.heightmap;
        return precise ? heightmap?.precise : heightmap?.jsonPng.length || heightmap?.failed;
    }, precise, { timeout: 120000 });
    return { context, page, problems };
}

// Weapon at the map centre, targets `north` meters north of it (and `east`)
const place = (page, targets) => page.evaluate((targets) => {
    const map = window.__App.minimap;
    const scale = map.mapToGameScale;
    const weapon = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
    map.setView([weapon.lat + 100 / scale, weapon.lng], 5, { animate: false });
    if (!map.activeWeaponsMarkers.getLayers().length) map.createWeapon(weapon);
    for (const [east, north] of targets) map.createTarget({ lat: weapon.lat + north / scale, lng: weapon.lng + east / scale });
}, targets);
const popupText = (target) => target.calcMarker1.getContent().replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

{
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
        const weapon = { lat: -map.pixelSize * 0.45, lng: map.pixelSize * 0.45 };
        map.createWeapon(weapon);
        const target = map.createTarget({ lat: weapon.lat + 400 / scale, lng: weapon.lng + 200 / scale }) || map.activeTargetsMarkers.getLayers()[0];
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.heightmap.precise) { clearInterval(timer); resolve(); } }, 50); });
        await new Promise((resolve) => setTimeout(resolve, 300));
        const shown = popup(target);
        const heightDiff = target.firingSolution1.heightDiff;
        target.updateCalc();
        return { loadedBefore, map: map.activeMap.name, shown, fresh: popup(target), heightDiff, expected: map.heightmap.getHeight(target.getLatLng()) - map.heightmap.getHeight(weapon) };
    }, popupText.toString());
    check("solution after the heightmap loads", !stale.loadedBefore && stale.shown === stale.fresh && Math.abs(stale.heightDiff - stale.expected) < 0.01,
        `${stale.map}: shown "${stale.shown}", recomputed "${stale.fresh}", height difference ${stale.heightDiff.toFixed(2)} m of ${stale.expected.toFixed(2)} m`);

    // Back to a fresh map state for the rest
    await page.evaluate(() => { window.__App.minimap.activeWeaponsMarkers.getLayers().forEach((weapon) => weapon.delete()); });
    await place(page, [[0, 150]]);

    // The Squad Ballistics bridge stays, and the removed device link leaves nothing behind
    const bridge = await page.evaluate(async () => {
        const bridge = window.squadBallistics;
        const targets = bridge.targets();
        const names = [...window.__App.WEAPON_SELECTOR[0].options].map((option) => option.textContent);
        const selected = bridge.selectWeapon("UB-32 (S-5 rockets)");
        const weapon = bridge.weapon();
        const rejected = bridge.selectWeapon("no such weapon");
        bridge.selectWeapon("Mortar (M252 / 2B14 / L16 / Type 63)");
        return { version: bridge.version, count: targets.length, distance: targets[0]?.distance, hasProfile: Boolean(targets[0]?.profile), selected, weapon, rejected, names: names.length };
    });
    check("window.squadBallistics.targets()", bridge.count === 1 && Math.abs(bridge.distance - 150) < 1 && bridge.hasProfile, JSON.stringify(bridge));
    check("window.squadBallistics weapon sync", bridge.selected && bridge.weapon === "UB-32 (S-5 rockets)" && !bridge.rejected, JSON.stringify(bridge));
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
        const point = map.latLngToContainerPoint({ lat: target.lat + 25 / map.mapToGameScale, lng: target.lng + 25 / map.mapToGameScale });
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

    check("desktop console and requests clean", problems.length === 0, problems.length ? problems.slice(0, 10).join(" | ") : "no errors");

    if (allMaps) {
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
                await new Promise((resolve) => setTimeout(resolve, 300));
                observer.disconnect();
                return { name: map.activeMap.name, precise: map.heightmap.precise, ms: Math.round(ms), longest: Math.round(Math.max(0, ...longTasks)) };
            }, value);
            const errors = problems.slice(before);
            check(`map ${result.name}`, result.precise && errors.length === 0, `precise heightmap in ${result.ms} ms, longest task ${result.longest} ms${errors.length ? `; ${errors.join(" | ")}` : ""}`);
        }
    }
    await context.close();
}

{
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
}

// The precise heightmap's two requests, heightmap.png and meta.json, under the network's failures
const preciseRequest = /\/heightmaps\/[^/]+\/(heightmap\.png|meta\.json)$/;
/**
 * Open SquadCalc with the precise heightmap's requests answered by `answer`
 * @param {(route: object, file: string, attempt: number) => Promise<void>} answer - answers the
 *   `attempt`-th request (1 for the first) of `file` ("heightmap.png" or "meta.json")
 * @returns {Promise<{requests: object, result: object}>} - the number of requests per file, and the
 *   heightmap's state (map, precise, the toast shown) or {error}
 */
async function openWithHeightmapRequests(answer) {
    const requests = { "heightmap.png": 0, "meta.json": 0 };
    let result;
    try {
        const { context, page } = await open(undefined, (context) => context.route(preciseRequest, (route) => {
            const file = route.request().url().match(preciseRequest)[1];
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
for (const dropped of ["heightmap.png", "meta.json"]) {
    const { requests, result } = await openWithHeightmapRequests((route, file, attempt) =>
        file === dropped && attempt === 1 ? route.abort("internetdisconnected") : route.fallback());
    check(`precise heightmap after a dropped ${dropped} request`, requests[dropped] >= 2 && result.precise === true,
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A network that keeps dropping it: four attempts, then the 8-bit heightmap with a warning toast
    const { requests, result } = await openWithHeightmapRequests((route, file) =>
        file === "heightmap.png" ? route.abort("internetdisconnected") : route.fallback());
    check("coarse heightmap announced when the network keeps dropping it",
        requests["heightmap.png"] === 4 && result.precise === false && result.failed === false && result.toast === "tooltips:heightmapCoarse",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
    // A deployment without precise heightmaps (404) falls back at once: one request each, no warning
    const { requests, result } = await openWithHeightmapRequests((route) => route.fulfill({ status: 404, body: "" }));
    check("no precise heightmap (404): 8-bit one at once, no retry",
        requests["heightmap.png"] === 1 && requests["meta.json"] === 1 && result.precise === false && result.failed === false && result.toast !== "tooltips:heightmapCoarse",
        `requests ${JSON.stringify(requests)}, ${JSON.stringify(result)}`);
}

{
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
    await page.waitForTimeout(800);
    await page.touchscreen.tap(center.x, center.y - 100);
    await page.waitForTimeout(1000);
    const mobile = await page.evaluate((popupSource) => {
        const popup = new Function(`return ${popupSource}`)();
        const map = window.__App.minimap;
        const target = map.activeTargetsMarkers.getLayers()[0];
        return { weapons: map.activeWeaponsMarkers.getLayers().length, targets: map.activeTargetsMarkers.getLayers().length, popup: target && popup(target) };
    }, popupText.toString());
    check("mobile: tap places a weapon then a target", mobile.weapons === 1 && mobile.targets === 1 && /\d/.test(mobile.popup || ""), JSON.stringify(mobile));
    check("mobile console and requests clean", problems.length === 0, problems.length ? problems.slice(0, 10).join(" | ") : "no errors");
    await context.close();
}

// What the removed device link saved in a browser is dropped on the next visit
{
    const { context, page, problems } = await open(undefined, (context) => context.addInitScript(() => {
        if (sessionStorage.getItem("seeded")) return;
        sessionStorage.setItem("seeded", "1");
        localStorage.setItem("settings-overlay-link", "1");
        localStorage.setItem("overlay-session-code", "ABCDEFGH2345");
    }));
    const left = await page.evaluate(() => ["settings-overlay-link", "overlay-session-code"].filter((key) => localStorage.getItem(key) !== null));
    check("stale device link storage dropped", left.length === 0 && problems.length === 0, left.length ? `left: ${left}` : problems.length ? problems.join(" | ") : "keys removed, console clean");
    await context.close();
}

await browser.close();
console.log(failures ? `${failures} browser check(s) failed` : "all browser checks passed");
process.exit(failures ? 1 : 0);
