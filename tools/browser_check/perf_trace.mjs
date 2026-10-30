// Main-thread cost of SquadCalc in a real browser: a Chromium trace of the fire coverage of seven weapons,
// of the damage zones of ten targets and of a scripted drag of a target.
//
//     node perf_trace.mjs <site URL> [--map <option value>] [--label <text>] [--scenarios coverage,zones,drag]
//         [--weapons <SquadCalc checkout>/src/data/weapons.js]
//
// <site URL> serves a build with the precise heightmaps under /heightmaps/ (see README.md). Environment as
// browser_check.mjs: PLAYWRIGHT_CORE, CHROME. For each scenario prints the wall time and the main-thread tasks
// of the trace (ThreadControllerImpl::RunTask on CrRendererMain): the longest one, how many are over 16 ms, and the busy total.
// The page is the one of any build: it needs `window.__App`, which the script exposes by rewriting the main
// bundle in transit, as browser_check.mjs does.
import { homedir } from "node:os";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const args = process.argv.slice(2);
const base = args[0];
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const label = option("--label", base);
const scenarios = option("--scenarios", "coverage,zones,drag").split(",");
const weaponsFile = option("--weapons", `${homedir()}/agl/SquadCalc/src/data/weapons.js`);
const { WEAPONS } = await import(weaponsFile);
const names = ["Mortar", "UB-32", "DF_M2A1_50", "DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2", "AGS-17", "DF_RPG_7_PG_7V_HEAT_OG_7V", "DF_SPG_9_HEAT"];
const indices = Object.fromEntries(names.map((name) => [name, WEAPONS.findIndex((weapon) => weapon.name === name)]));

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--enable-precise-memory-info"] });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
    if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
    await route.fulfill({ response, body: patched });
});
const page = await context.newPage();
page.on("pageerror", (error) => console.log(`pageerror: ${error.message}`));
await page.goto(base, { waitUntil: "load" });
const mapValue = option("--map", null);
if (mapValue) {
    await page.evaluate((value) => window.__App.MAP_SELECTOR.val(value).trigger("change"), mapValue);
}
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.precise, null, { timeout: 120000 });
await page.waitForTimeout(1500);

/**
 * Run `action` under a trace and summarize the renderer's main-thread tasks
 * @param {string} name
 * @param {() => Promise<*>} action
 * @returns {Promise<*>} the action's result, printed with the summary
 */
async function traced(name, action) {
    await browser.startTracing(page, { categories: ["toplevel", "devtools.timeline"] });
    const start = Date.now();
    const result = await action();
    const seconds = (Date.now() - start) / 1000;
    const trace = JSON.parse((await browser.stopTracing()).toString());
    const events = trace.traceEvents;
    const mainThreads = events.filter((event) => event.name === "thread_name" && event.args?.name === "CrRendererMain");
    const tasks = events.filter((event) => event.name === "ThreadControllerImpl::RunTask" && event.ph === "X"
        && mainThreads.some((thread) => thread.pid === event.pid && thread.tid === event.tid)).map((event) => event.dur / 1000);
    if (process.env.TOP_EVENTS) {
        const totals = new Map();
        const threadNames = new Map(events.filter((event) => event.name === "thread_name").map((event) => [`${event.pid}:${event.tid}`, event.args.name]));
        for (const event of events) {
            if (event.ph !== "X" || event.name === "ThreadControllerImpl::RunTask" || event.name.startsWith("Receive mojo") || event.name === "EpollEvent") continue;
            const key = `${threadNames.get(`${event.pid}:${event.tid}`)}/${event.name}`;
            totals.set(key, (totals.get(key) ?? 0) + event.dur / 1000);
        }
        console.log([...totals].sort((a, b) => b[1] - a[1]).slice(0, 22).map(([n, ms]) => `${n} ${ms.toFixed(0)}ms`).join("\n  "));
    }
    if (process.env.LONG_TASKS) {
        const main = events.filter((event) => event.ph === "X" && mainThreads.some((thread) => thread.pid === event.pid && thread.tid === event.tid));
        for (const task of main.filter((event) => event.name === "ThreadControllerImpl::RunTask" && event.dur > 16000)) {
            const inside = main.filter((event) => event !== task && event.ts >= task.ts && event.ts + event.dur <= task.ts + task.dur && event.dur > 2500);
            console.log(`  long task ${(task.dur / 1000).toFixed(0)} ms: ${inside.map((event) => `${event.name} ${(event.dur / 1000).toFixed(0)}`).join(", ")}`);
        }
    }
    tasks.sort((a, b) => b - a);
    const busy = tasks.reduce((sum, ms) => sum + ms, 0);
    console.log(`${label} | ${name}: ${seconds.toFixed(2)} s, longest task ${(tasks[0] ?? 0).toFixed(1)} ms, tasks over 16 ms: ${tasks.filter((ms) => ms > 16).length}, over 50 ms: ${tasks.filter((ms) => ms > 50).length}, main-thread busy ${(busy / 1000).toFixed(2)} s`);
    return result;
}

// 0. Map switches: the map image (a 4096 px webp upstream) decoded and shown
if (scenarios.includes("mapswitch")) {
    for (let i = 0; i < 4; i++) {
        await traced(`map switch ${i + 1}`, async () => {
            await page.evaluate(() => {
                const app = window.__App;
                const options = [...app.MAP_SELECTOR[0].options].filter((option) => option.value);
                const current = options.findIndex((option) => option.value === app.MAP_SELECTOR.val());
                app.MAP_SELECTOR.val(options[(current + 1) % options.length].value).trigger("change");
            });
            await page.waitForFunction(() => window.__App.minimap.heightmap?.precise, null, { timeout: 120000, polling: 50 });
            await page.waitForTimeout(2500);
        });
    }
    await browser.close();
    process.exit(0);
}

// A weapon at the map centre
await page.evaluate(() => {
    const map = window.__App.minimap;
    const weapon = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
    map.setView([weapon.lat, weapon.lng], 5, { animate: false });
    if (!map.activeWeaponsMarkers.getLayers().length) map.createWeapon(weapon);
});

// 1. Fire coverage: from the switch on to the image on the map
for (const name of scenarios.includes("coverage") ? names : []) {
    await page.evaluate((index) => {
        const app = window.__App;
        app.minimap.coverage.setEnabled(false);
        app.WEAPON_SELECTOR.val(index).trigger("change");
    }, indices[name]);
    await page.waitForTimeout(700);
    await traced(`coverage ${name}`, async () => {
        await page.evaluate(() => window.__App.minimap.coverage.setEnabled(true));
        await page.waitForFunction(() => window.__App.minimap.coverage.overlay, null, { timeout: 120000, polling: 20 });
        await page.waitForTimeout(300);
    });
}
await page.evaluate(() => window.__App.minimap.coverage.setEnabled(false));

if (!scenarios.includes("zones") && !scenarios.includes("drag")) {
    await browser.close();
    process.exit(0);
}

// 2. Damage zones: ten targets placed, then all redrawn by a shell change
await page.evaluate((index) => {
    const app = window.__App;
    const map = app.minimap;
    app.WEAPON_SELECTOR.val(index).trigger("change");
    app.userSettings.damageRadius = true;
    const scale = map.mapToGameScale;
    const weapon = map.activeWeaponsMarkers.getLayers()[0].getLatLng();
    for (let i = 0; i < 10; i++) {
        const angle = i * 0.6;
        map.createTarget({ lat: weapon.lat + (400 + 60 * i) * Math.cos(angle) / scale, lng: weapon.lng + (400 + 60 * i) * Math.sin(angle) / scale });
    }
}, indices.Mortar);
await page.waitForTimeout(3000);
const zones = () => page.evaluate(() => [...window.__App.minimap.activeTargetsMarkers.getLayers()].filter((target) => target.coverOverlay).length);
console.log(`${label} | damage zones after placing ten targets: ${await zones()} of 10`);
await traced("damage zones of ten targets redrawn (position moved by 1 m)", async () => {
    await page.evaluate(() => {
        const map = window.__App.minimap;
        for (const target of map.activeTargetsMarkers.getLayers()) {
            const ll = target.getLatLng();
            target.setLatLng({ lat: ll.lat + 1 / map.mapToGameScale, lng: ll.lng });
        }
        map.updateTargets();
    });
    await page.waitForFunction(() => [...window.__App.minimap.activeTargetsMarkers.getLayers()].every((target) => target.coverOverlay), null, { timeout: 60000, polling: 20 });
});

if (!scenarios.includes("drag")) {
    await browser.close();
    process.exit(0);
}

// 3. Drag a target across the map with the mouse: 120 moves, 8 ms apart
const where = await page.evaluate(() => {
    const map = window.__App.minimap;
    const target = map.activeTargetsMarkers.getLayers()[0];
    const point = map.latLngToContainerPoint(target.getLatLng());
    const box = map.getContainer().getBoundingClientRect();
    return { x: box.left + point.x, y: box.top + point.y };
});
await page.evaluate((experiment) => {
    window.__experiment = experiment;
    window.__frames = [];
    window.__frameTimes = [];
    let last = performance.now();
    const nativeFrame = window.requestAnimationFrame.bind(window);
    window.__nativeFrame = nativeFrame;
    const loop = (now) => {
        window.__frames.push(now - last);
        window.__frameTimes.push(now);
        last = now;
        nativeFrame(loop);
    };
    nativeFrame(loop);
    if (window.__experiment === "sync") window.requestAnimationFrame = (callback) => { callback(performance.now()); return 0; };
}, process.env.EXPERIMENT ?? "");
if (process.env.EXPERIMENT === "nozones") await page.evaluate(() => window.__App.minimap.activeTargetsMarkers.getLayers().forEach((target) => target.removeCoverZone()));
if (process.env.EXPERIMENT === "noimage") await page.evaluate(() => document.querySelectorAll(".leaflet-image-layer").forEach((image) => { image.style.display = "none"; }));
if (process.env.EXPERIMENT === "info") console.log(JSON.stringify(await page.evaluate(() => [...document.querySelectorAll("img.leaflet-image-layer")].map((image) => [image.className, image.style.cssText.slice(0, 80), image.naturalWidth, image.decoding]))));
if (process.env.EXPERIMENT === "nodamage") await page.evaluate(() => { window.__App.userSettings.damageRadius = false; window.__App.minimap.updateTargets(); });
await page.waitForTimeout(500);
await page.evaluate(() => { window.__frames.length = 0; window.__frameTimes.length = 0; });
await traced("drag of a target (120 moves)", async () => {
    await page.mouse.move(where.x, where.y);
    await page.mouse.down();
    for (let i = 1; i <= 120; i++) {
        await page.mouse.move(where.x + i * 2, where.y + Math.sin(i / 8) * 30);
        await page.waitForTimeout(8);
    }
    await page.evaluate(() => { window.__upAt = performance.now(); });
    await page.mouse.up();
});
if (process.env.FRAME_LOG) {
    const log = await page.evaluate(() => window.__frames.map((ms, i) => [i, Math.round(ms), Math.round(window.__frameTimes[i])]).filter(([, ms]) => ms > 33).concat([["up", Math.round(window.__upAt)]]));
    console.log(JSON.stringify(log));
}
const frames = await page.evaluate(() => window.__frames);
frames.sort((a, b) => b - a);
console.log(`${label} | drag frames: ${frames.length}, longest frame ${frames[0]?.toFixed(0)} ms, frames over 33 ms: ${frames.filter((ms) => ms > 33).length}, median ${frames[Math.floor(frames.length / 2)]?.toFixed(1)} ms`);

await browser.close();
