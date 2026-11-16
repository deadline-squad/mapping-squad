// The service worker's caching of SquadCalc, in a real Chromium with a profile that survives a restart:
// the precache holds no vehicle image (except the placeholder) and no README screenshot, a vehicle image
// shown once is served from the service worker's cache afterwards (also with the network gone, also after
// the browser was restarted), and one never shown falls back to the placeholder without the network.
//
//     node offline_check.mjs <site URL> --vehicles <dir of the vehicle images>
//
// Environment: PLAYWRIGHT_CORE, CHROME as in browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2];
const vehiclesDir = process.argv[process.argv.indexOf("--vehicles") + 1];
if (!base || process.argv.indexOf("--vehicles") < 0) {
    console.error("usage: node offline_check.mjs <site URL> --vehicles <dir>");
    process.exit(2);
}
const names = readdirSync(vehiclesDir).filter((name) => name.endsWith(".webp") && name !== "placeholder.webp");
const shown = names.slice(0, 3);
const neverShown = names.at(-1);

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const profile = mkdtempSync(join(tmpdir(), "offline-check-"));
const launch = () => chromium.launchPersistentContext(profile, { executablePath: process.env.CHROME || undefined });

/** Open the site and wait for the service worker to control it */
async function open(context) {
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "load" });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(async () => {
        const names = await caches.keys();
        const precache = names.find((name) => name.startsWith("workbox-precache"));
        return precache && (await (await caches.open(precache)).keys()).length > 400;
    }, null, { timeout: 120000 });
    return page;
}

/** Load /img/vehicles/<name> as an <img>: true when it displayed */
const loads = (page, name) => page.evaluate((name) => new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(true);
    image.onerror = () => resolve(false);
    image.src = `/img/vehicles/${encodeURIComponent(name)}`;
}), name);

let context = await launch();
let page = await open(context);
const precached = await page.evaluate(async () => {
    const precache = (await caches.keys()).find((name) => name.startsWith("workbox-precache"));
    return (await (await caches.open(precache)).keys()).map((request) => new URL(request.url).pathname);
});
const vehicleEntries = precached.filter((path) => path.startsWith("/img/vehicles/"));
check("precache has no vehicle image but the placeholder, no README screenshot",
    vehicleEntries.length === 1 && vehicleEntries[0] === "/img/vehicles/placeholder.webp" && !precached.some((path) => path.startsWith("/img/github/")),
    `${precached.length} entries, vehicles ${JSON.stringify(vehicleEntries)}`);

for (const name of shown) await loads(page, name);
/** The names in the service worker's vehicle-images cache */
const cachedNames = () => page.evaluate(async () => (await (await caches.open("vehicle-images")).keys()).map((request) => decodeURIComponent(new URL(request.url).pathname.split("/").pop())));
// The service worker writes a response after the image's onload, so wait (bounded) for the names instead of reading once
const deadline = Date.now() + 5000;
let cached = await cachedNames();
while (!shown.every((name) => cached.includes(name)) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    cached = await cachedNames();
}
check("vehicle images shown once are cached by the service worker", shown.every((name) => cached.includes(name)), `${cached.length} cached: ${cached.join(", ")}`);

await context.setOffline(true);
const offline = [];
for (const name of shown) offline.push(await loads(page, name));
check("cached vehicle images show without the network", offline.every(Boolean), JSON.stringify(offline));
const missing = await loads(page, neverShown);
check("a vehicle image never shown fails offline (the page then shows the placeholder)", missing === false, `loaded: ${missing}`);
check("the precached placeholder shows offline", await loads(page, "placeholder.webp"), "loaded");
await context.setOffline(false);
await context.close();

// Warm start: a restarted browser, the same profile; the service worker answers from its cache
context = await launch();
page = await open(context);
await context.setOffline(true);
const warm = [];
for (const name of shown) warm.push(await loads(page, name));
check("after a restart the vehicle images are still served from the cache", warm.every(Boolean), JSON.stringify(warm));
await context.setOffline(false);
await context.close();
rmSync(profile, { recursive: true, force: true });
console.log(failures ? `${failures} offline check(s) failed` : "all offline checks passed");
process.exit(failures ? 1 : 0);
