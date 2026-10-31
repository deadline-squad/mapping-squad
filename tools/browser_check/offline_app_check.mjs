// The app offline, in a real Chromium with a profile that survives a restart: after one visit with the
// network, a reload with the network gone opens the page (the HTML comes from the service worker's "pages"
// cache, the scripts from the precache), the translations are the saved ones (text, not keys), the precise
// heightmap of the map seen is served from the cache (meta.json and the ?v= file), the Google Fonts are saved,
// and with the network back a changed translation shows at once (network first, no stale copy).
//
//     node offline_app_check.mjs <site URL> [--no-fonts]
//
// Environment: PLAYWRIGHT_CORE, CHROME as in browser_check.mjs. --no-fonts skips the font check on a machine
// that cannot reach fonts.googleapis.com; the Google caches are skipped by themselves when the page does not request them. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2];
if (!base) {
    console.error("usage: node offline_app_check.mjs <site URL> [--no-fonts]");
    process.exit(2);
}
const fontsWanted = !process.argv.includes("--no-fonts");
let fonts = fontsWanted;

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const profile = mkdtempSync(join(tmpdir(), "offline-app-"));
const launch = () => chromium.launchPersistentContext(profile, { executablePath: process.env.CHROME || undefined, viewport: { width: 1400, height: 900 } });
const cacheNames = (page) => page.evaluate(() => caches.keys());

let context = await launch();
let page = await context.newPage();
const problems = [];
page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()) && !/GL Driver|GPU stall|ERR_INTERNET_DISCONNECTED|Failed to load resource|Not connected to SquadCalc API/.test(message.text())) problems.push(`${message.type()}: ${message.text().slice(0, 120)}`);
});
await page.goto(base, { waitUntil: "load" });
await page.evaluate(() => navigator.serviceWorker.ready);
await page.waitForFunction(async () => {
    const precache = (await caches.keys()).find((name) => name.startsWith("workbox-precache"));
    return precache && (await (await caches.open(precache)).keys()).length > 400;
}, null, { timeout: 120000 });
// The visit that fills the runtime caches goes through the now controlling service worker
await page.reload({ waitUntil: "load" });
await page.waitForFunction(() => document.body.style.visibility !== "hidden" && document.querySelector("[data-i18n]")?.textContent.trim(), null, { timeout: 60000 });
await page.waitForTimeout(8000);
const online = await page.evaluate(() => ({ text: document.body.innerText.replace(/\s+/g, " ").slice(0, 200), fonts: [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family) }));
// A build with self-hosted fonts never asks Google: its fonts are in the precache and the Google caches stay unused
const asksGoogle = await page.evaluate(() => performance.getEntriesByType("resource").some((entry) => entry.name.startsWith("https://fonts.googleapis.com/")));
if (fonts && !asksGoogle) {
    console.log("skip Google Fonts caches: the page does not request fonts.googleapis.com (self-hosted fonts); the offline font check below still runs");
    fonts = false;
}
const names = await cacheNames(page);
for (const name of ["pages", "locales", "heightmap-meta", "precise-heightmaps", ...(fonts ? ["google-fonts-stylesheets", "google-fonts-files"] : [])]) {
    check(`the "${name}" cache exists after a visit`, names.includes(name), names.join(", "));
}

await context.setOffline(true);
await page.reload({ waitUntil: "load", timeout: 30000 }).catch((error) => check("offline reload", false, error.message.split("\n")[0]));
const ready = await page.waitForFunction(() => document.querySelector("select.dropbtn") && window.getComputedStyle(document.body).visibility !== "hidden", null, { timeout: 30000 }).then(() => true).catch(() => false);
check("offline reload opens the page", ready, ready ? "page visible" : "page stays hidden");
const offline = await page.evaluate(() => ({ text: document.body.innerText.replace(/\s+/g, " ").slice(0, 200), keys: [...document.body.innerText.matchAll(/\b(?:common|tooltips|settings|maps|weapons):[\w.]+/g)].length }));
check("translations offline are text, not keys", offline.keys === 0 && offline.text.length > 20, `${offline.keys} untranslated keys; "${offline.text.slice(0, 80)}"`);
check("the page text offline is that of the online page", offline.text.slice(0, 60) === online.text.slice(0, 60), `"${offline.text.slice(0, 60)}"`);

if (!ready) {
    console.log(`${failures} FAILED (the page did not open, the remaining checks need it)`);
    process.exit(1);
}
const heights = await page.evaluate(async () => {
    const stats = {};
    for (const request of await (await caches.open("precise-heightmaps")).keys()) stats[new URL(request.url).pathname] = true;
    const names = Object.keys(stats);
    if (!names.length) return { cached: 0 };
    const meta = await fetch(names[0].replace(/heightmap\.(webp|png)$/, "meta.json"));
    return { cached: names.length, metaOffline: meta.ok };
});
check("the precise heightmap seen is available offline", heights.cached > 0 && heights.metaOffline === true, JSON.stringify(heights));
const failedHeights = await page.evaluate(() => [...document.querySelectorAll(".toast, [class*=toast]")].map((e) => e.textContent).filter((t) => /height/i.test(t)));
check("no heightmap error offline", failedHeights.length === 0, JSON.stringify(failedHeights));
if (fontsWanted) {
    const offlineFonts = await page.evaluate(async () => { await document.fonts.ready; return [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family); });
    check("web fonts offline", offlineFonts.length >= online.fonts.length && online.fonts.length > 0, `online ${online.fonts.join(",")} offline ${offlineFonts.join(",")}`);
}

// After a restart, still offline
await context.close();
context = await launch();
await context.setOffline(true);
page = await context.newPage();
await page.goto(base, { waitUntil: "load", timeout: 30000 }).catch((error) => check("offline start after a restart", false, error.message.split("\n")[0]));
const restarted = await page.waitForFunction(() => document.querySelector("select.dropbtn") && window.getComputedStyle(document.body).visibility !== "hidden", null, { timeout: 30000 }).then(() => true).catch(() => false);
check("offline start after a restart opens the page", restarted, restarted ? "page visible" : "page stays hidden");

// Network back: a changed translation shows at once
await context.setOffline(false);
await context.route(/\/locales\/en\/common\.json/, async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    const key = Object.keys(json)[0];
    json[key] = "EDITED-TRANSLATION";
    await route.fulfill({ response, json });
});
await page.goto(base, { waitUntil: "load" });
await page.waitForTimeout(3000);
const stale = await page.evaluate(async () => {
    const cached = await (await caches.open("locales")).match("/locales/en/common.json");
    return cached ? JSON.stringify(await cached.json()).includes("EDITED-TRANSLATION") : null;
});
check("online, the translation comes from the network first (the cache is refreshed)", stale === true || stale === null, `cache holds the edited copy: ${stale}`);

// A regenerated heightmap (meta.json names a new `generated`): the new ?v= URL is not in the cache, so the heavy
// file is fetched and saved under it, the stale copy is not served
await context.route(/\/heightmaps\/[a-z0-9_-]+\/meta\.json/, async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.generated = "regenerated-test";
    await route.fulfill({ response, json });
});
await page.goto(base, { waitUntil: "load" });
await page.waitForTimeout(8000);
const versions = await page.evaluate(async () => (await (await caches.open("precise-heightmaps")).keys()).map((request) => new URL(request.url).search));
check("a regenerated heightmap is fetched under its new ?v= URL", versions.includes("?v=regenerated-test"), versions.join(" "));

check("console clean", problems.length === 0, problems.join(" | ") || "clean");
await context.close();
console.log(failures ? `${failures} FAILED` : "all offline-app checks passed");
process.exit(failures ? 1 : 0);
