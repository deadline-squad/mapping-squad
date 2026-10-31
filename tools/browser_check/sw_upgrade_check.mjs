// The service worker across a deploy, in a real Chromium: an old build's bundle cached in the browser, then the
// site swapped for another build on the same origin (and the reverse, a rollback), with different heightmap
// formats beside it.
//
//     node sw_upgrade_check.mjs <site URL> --old <old dist> --new <new dist> --link <symlink the server's root is>
//          [--hm-link <symlink /heightmaps/ is served from> --heightmaps <dir of the precise heightmaps>]
//
// The server is any static server whose document root (and /heightmaps/ root, with --hm-link) is a symlink this
// script re-points, e.g. Caddy over `root * /tmp/swprobe/current`. <old dist> and <new dist> are `npm run build`
// outputs of two checkouts (the old one can be an earlier tag). Environment: PLAYWRIGHT_CORE, CHROME as in
// browser_check.mjs. Checks that pass or fail exit with 1 on a failure; "known" lines are shortcomings that are
// reported with their evidence and do not fail the run.
//
// 1. Upgrade (old to new) and rollback (new to old): the precache holds exactly the new bundle once the service
//    worker has activated, the page runs the new main script, loads without a failed request, and opens offline
//    after the upgrade with the new bundle (the cached HTML is not the old one).
// 2. A tab that stays open across the deploy and loses its HTTP cache (eviction) requests a lazily loaded chunk of
//    its old bundle (the heightmap worker, at the next map switch): the precache entries are gone and the server
//    no longer has the file (known).
// 3. A precache missing entries: online the page still loads (they come from the network), the entries are not
//    put back until the next service worker version (known).
// (--hm-link points at a directory holding <map>/heightmap.png and meta.json, like the deployment's /heightmaps/)
// 4. Heightmap formats: each build with a heightmaps directory in the old format (heightmap.png, meta.json without
//    `format`) and the current one (WebP announced by meta.json): the precise heightmap loads in all four.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const base = args[0];
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : null);
const [oldDist, newDist, link, hmLink, heightmaps] = ["--old", "--new", "--link", "--hm-link", "--heightmaps"].map((name) => option(name));
if (!base || !oldDist || !newDist || !link) {
    console.error("usage: node sw_upgrade_check.mjs <site URL> --old <dist> --new <dist> --link <symlink> [--hm-link <symlink> --heightmaps <dir>]");
    process.exit(2);
}

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}
const known = (label, detail) => console.log(`known ${label}: ${detail}`);
const point = (symlink, dir) => execFileSync("ln", ["-sfn", resolve(dir), symlink]);
const mainOf = (dist) => readFileSync(join(dist, "index.html"), "utf8").match(/\/src\/js\/main\.[0-9a-f]+\.min\.js/)[0];

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const launch = () => chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "sw-upgrade-")), { executablePath: process.env.CHROME || undefined, viewport: { width: 1400, height: 900 } });
await browser.close();

/** Open the site and wait until the service worker controls it and the precache is complete */
async function visit(context, page = null) {
    page ??= await context.newPage();
    await page.goto(base, { waitUntil: "load" });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(async () => {
        const name = (await caches.keys()).find((key) => key.startsWith("workbox-precache"));
        return name && (await (await caches.open(name)).keys()).length > 400;
    }, null, { timeout: 120000 });
    return page;
}

const precache = (page) => page.evaluate(async () => {
    const name = (await caches.keys()).find((key) => key.startsWith("workbox-precache"));
    return (await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname);
});

/** Deploy `dist`: re-point the server, let the browser find the new service worker and wait until it is the active one */
async function deploy(page, dist) {
    point(link, dist);
    const wanted = mainOf(dist);
    await page.evaluate(async () => { await (await navigator.serviceWorker.getRegistration()).update(); });
    await page.waitForFunction(async (main) => {
        const registration = await navigator.serviceWorker.getRegistration();
        const name = (await caches.keys()).find((key) => key.startsWith("workbox-precache"));
        const keys = (await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname);
        return !registration.installing && !registration.waiting && keys.includes(main);
    }, wanted, { timeout: 120000 });
    await page.waitForTimeout(3000);
}

/** Console errors and failed requests of a page, collected from now on */
function watch(page) {
    const problems = [];
    page.on("console", (message) => {
        if (["error", "warning"].includes(message.type()) && !/GL Driver|GPU stall|Not connected to SquadCalc API/.test(message.text())) problems.push(`${message.type()}: ${message.text().slice(0, 100)}`);
    });
    page.on("response", (response) => { if (response.status() >= 400) problems.push(`${response.status()} ${new URL(response.url()).pathname}`); });
    page.on("requestfailed", (request) => problems.push(`failed ${new URL(request.url()).pathname} ${request.failure()?.errorText}`));
    return problems;
}

const mainRunning = (page) => page.evaluate(() => [...document.scripts].map((script) => new URL(script.src, location.href).pathname).find((path) => /\/main\./.test(path)));

// 1. Upgrade and rollback
if (hmLink && heightmaps) point(hmLink, heightmaps);
for (const [label, from, to] of [["upgrade", oldDist, newDist], ["rollback", newDist, oldDist]]) {
    point(link, from);
    const context = await launch();
    const page = await visit(context);
    await page.waitForTimeout(2000);
    const stale = await precache(page);
    await deploy(page, to);
    const problems = watch(page);
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("select.dropbtn"), null, { timeout: 60000 });
    await page.waitForTimeout(4000);
    const entries = await precache(page);
    check(`${label}: the precache holds the new bundle only`, entries.includes(mainOf(to)) && (mainOf(from) === mainOf(to) || !entries.includes(mainOf(from))), `${stale.length} entries before, ${entries.length} after; ${mainOf(from).slice(-24)} -> ${mainOf(to).slice(-24)}`);
    check(`${label}: the page runs the new main script`, (await mainRunning(page)) === mainOf(to), await mainRunning(page));
    check(`${label}: no failed request or console error`, problems.length === 0, problems.join(" | ") || "clean");
    if (to === newDist) {
        // Only the new build's service worker keeps the HTML for offline (the old one never cached it)
        await context.setOffline(true);
        await page.reload({ waitUntil: "load", timeout: 30000 }).catch(() => {});
        const offlineOpens = await page.waitForFunction(() => document.querySelector("select.dropbtn"), null, { timeout: 20000 }).then(() => true).catch(() => false);
        check(`${label}: offline after it, the page opens with the new bundle`, offlineOpens && (await mainRunning(page)) === mainOf(to), offlineOpens ? await mainRunning(page) : "page did not open");
    }
    await context.close();
}

// 2. A tab open across the deploy, HTTP cache evicted
if (mainOf(oldDist) !== mainOf(newDist)) {
    point(link, oldDist);
    const context = await launch();
    const page = await visit(context);
    await page.waitForTimeout(2000);
    await deploy(page, newDist);
    const problems = watch(page);
    const session = await context.newCDPSession(page);
    await session.send("Network.clearBrowserCache");
    await page.evaluate(() => {
        const select = document.querySelector("select.dropbtn");
        select.value = [...select.options].map((option) => option.value).find((value) => value !== select.value);
        select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(6000);
    const lost = problems.filter((problem) => /^404 \/src\/js\//.test(problem));
    if (lost.length) known("an open tab loses code it loads lazily after a deploy (HTTP cache evicted)", lost.join(", "));
    else console.log("ok   an open tab across the deploy loads its lazy chunks: no 404");
    await context.close();
}

// 3. A precache missing entries
point(link, newDist);
if (hmLink && heightmaps) point(hmLink, heightmaps);
{
    const context = await launch();
    const page = await visit(context);
    await page.waitForTimeout(2000);
    const removed = await page.evaluate(async () => {
        const cache = await caches.open((await caches.keys()).find((key) => key.startsWith("workbox-precache")));
        const gone = (await cache.keys()).filter((request) => /\/src\/js\/\d+\./.test(request.url)).slice(0, 6);
        for (const request of gone) await cache.delete(request);
        return gone.length;
    });
    const session = await context.newCDPSession(page);
    await session.send("Network.clearBrowserCache");
    const problems = watch(page);
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("select.dropbtn"), null, { timeout: 60000 });
    await page.waitForTimeout(3000);
    check("a precache missing entries: online the page still loads", problems.length === 0, `${removed} entries removed; ${problems.join(" | ") || "clean"}`);
    const back = (await precache(page)).length;
    known("missing precache entries are not put back", `${removed} removed, ${back} entries after a reload (only a new service worker version refills them)`);
    await context.close();
}

// (--hm-link points at a directory holding <map>/heightmap.png and meta.json, like the deployment's /heightmaps/)
// 4. Heightmap formats beside each build
if (hmLink && heightmaps) {
    const fixtures = mkdtempSync(join(tmpdir(), "sw-upgrade-hm-"));
    const mapName = "albasrah";
    const oldFormat = join(fixtures, "old-format", "heightmaps");
    mkdirSync(join(oldFormat, mapName), { recursive: true });
    symlinkSync(resolve(heightmaps, mapName, "heightmap.png"), join(oldFormat, mapName, "heightmap.png"));
    const meta = JSON.parse(readFileSync(join(heightmaps, mapName, "meta.json"), "utf8"));
    for (const field of ["format", "generated", "webp"]) delete meta[field];
    writeFileSync(join(oldFormat, mapName, "meta.json"), JSON.stringify(meta));
    const newFormat = resolve(heightmaps);
    const oldRoot = oldFormat;
    for (const [buildLabel, dist] of [["old build", oldDist], ["new build", newDist]]) {
        for (const [formatLabel, holder] of [["old-format heightmaps", oldRoot], ["current heightmaps", newFormat]]) {
            point(link, dist);
            point(hmLink, holder);
            const context = await launch();
            const page = await context.newPage();
            const problems = watch(page);
            const heavy = [];
            page.on("response", (response) => { if (/\/heightmaps\/albasrah\/heightmap\.(webp|png)/.test(response.url()) && response.status() === 200) heavy.push(new URL(response.url()).pathname); });
            await page.goto(base, { waitUntil: "load" });
            await page.waitForTimeout(25000);
            const toast = await page.evaluate(() => [...document.querySelectorAll("[class*=toast]")].map((e) => e.textContent).filter((t) => /height/i.test(t)));
            check(`${buildLabel} with ${formatLabel}: the precise heightmap loads`, heavy.length > 0 && toast.length === 0 && !problems.some((p) => /HEIGHTMAP|heightmap/.test(p)), `${heavy.join(", ") || "no heightmap file"}; ${problems.join(" | ") || "clean"}`);
            await context.close();
        }
    }
}

console.log(failures ? `${failures} FAILED` : "all upgrade checks passed");
process.exit(failures ? 1 : 0);
