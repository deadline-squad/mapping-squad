// CPU profile (V8 sampling profiler through CDP) of the fire coverage of one weapon in a real browser.
//
//     node cpu_profile.mjs <site URL> <weapon name in weapons.js> [--weapons <weapons.js>]
//
// Prints the functions with the most self time between the switch on of the coverage and its image. Environment
// as browser_check.mjs (PLAYWRIGHT_CORE, CHROME).
import { homedir } from "node:os";
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const [base, name] = process.argv.slice(2);
const weaponsFile = process.argv.includes("--weapons") ? process.argv[process.argv.indexOf("--weapons") + 1] : `${homedir()}/agl/SquadCalc/src/data/weapons.js`;
const { WEAPONS } = await import(weaponsFile);
const index = WEAPONS.findIndex((weapon) => weapon.name === name);

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    await route.fulfill({ response, body: body.replace(/window\.squadBallistics\s*=\s*\{/, "window.__App=this,window.squadBallistics={") });
});
const page = await context.newPage();
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.ready, null, { timeout: 120000 });
await page.waitForTimeout(1500);
await page.evaluate((index) => {
    const app = window.__App;
    const map = app.minimap;
    const weapon = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
    map.setView([weapon.lat, weapon.lng], 5, { animate: false });
    map.createWeapon(weapon);
    app.WEAPON_SELECTOR.val(index).trigger("change");
}, index);
await page.waitForTimeout(700);
const session = await context.newCDPSession(page);
await session.send("Profiler.enable");
await session.send("Profiler.setSamplingInterval", { interval: 200 });
await session.send("Profiler.start");
await page.evaluate(() => window.__App.minimap.coverage.setEnabled(true));
await page.waitForFunction(() => window.__App.minimap.coverage.overlay, null, { timeout: 120000, polling: 20 });
const { profile } = await session.send("Profiler.stop");
const byId = new Map(profile.nodes.map((node) => [node.id, node]));
const self = new Map();
let total = 0;
profile.samples.forEach((id, i) => {
    const frame = byId.get(id).callFrame;
    const key = `${frame.functionName || "(anonymous)"} ${frame.url.split("/").pop()}:${frame.lineNumber}`;
    self.set(key, (self.get(key) ?? 0) + profile.timeDeltas[i]);
    total += profile.timeDeltas[i];
});
const parents = new Map();
for (const node of profile.nodes) for (const child of node.children ?? []) parents.set(child, node.id);
const inclusive = new Map();
profile.samples.forEach((id, i) => {
    const seen = new Set();
    for (let current = id; current !== undefined; current = parents.get(current)) {
        const frame = byId.get(current).callFrame;
        const key = `${frame.functionName || "(anonymous)"} ${frame.url.split("/").pop()}:${frame.lineNumber}`;
        if (seen.has(key)) continue;
        seen.add(key);
        inclusive.set(key, (inclusive.get(key) ?? 0) + profile.timeDeltas[i]);
    }
});
console.log("inclusive:");
for (const [key, microseconds] of [...inclusive].sort((a, b) => b[1] - a[1]).slice(0, 18)) console.log(`${(microseconds / 1000).toFixed(0).padStart(6)} ms ${key}`);
console.log(`${name}: ${(total / 1e6).toFixed(2)} s sampled; self time:`);
for (const [key, microseconds] of [...self].sort((a, b) => b[1] - a[1]).slice(0, 14)) console.log(`${(microseconds / 1000).toFixed(0).padStart(6)} ms ${key}`);
await browser.close();
