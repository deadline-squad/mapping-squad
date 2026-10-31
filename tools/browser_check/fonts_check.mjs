// Checks that the Deadline SquadCalc takes its fonts from its own origin: no request to Google Fonts
// (fonts.googleapis.com, fonts.gstatic.com) from the page or the service worker, the self-hosted
// Montserrat and Oswald load for the language shown (the cyrillic subsets only for ru and uk), the preloaded
// latin files are downloaded once and used, the console stays clean, the service worker precaches the three
// latin files only and caches the other subsets on first use, and a subset used once still loads offline. With --measure it also prints the first-visit cost and the first contentful paint.
//
//     node fonts_check.mjs <site URL> [--measure <runs>] [--shots <dir>]
//
// --measure repeats a cold first visit (new browser context, Slow 4G network, 4x slower CPU) <runs> times in
// each language and prints FCP, the time the last font file finished loading, and the own-origin font and Google font requests of the first
// 15 s (the load event itself waits 30 s for the basemap on Slow 4G); --shots writes a screenshot of the page and of the
// settings dialog (its headings and texts) per language into <dir>, to compare two builds by eye. Environment:
// PLAYWRIGHT_CORE = path of the playwright-core package if it is not resolvable from here,
// CHROME = Chromium executable if Playwright's own is not installed. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.argv[2];
if (!base) {
    console.error("usage: node fonts_check.mjs <site URL> [--measure <runs>] [--shots <dir>]");
    process.exit(2);
}
const argValue = (flag) => (process.argv.includes(flag) ? process.argv[process.argv.indexOf(flag) + 1] : null);
const measureRuns = Number(argValue("--measure") ?? 0);
const shotsDir = argValue("--shots");
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

const GOOGLE_FONT_HOST = /(^|\.)(fonts\.googleapis\.com|fonts\.gstatic\.com)$/;
const SLOW_4G = { offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8 };
const MEASURE_WINDOW_MS = 15000;
const LANGUAGES = { en: false, fr: false, de: false, ru: true, uk: true, zh: false };

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/** Navigate; the host's network interfaces change now and then (Docker) and Chromium then fails the load once */
async function goto(page, waitUntil) {
    for (let attempt = 1; ; attempt++) {
        try {
            return await page.goto(base, { waitUntil });
        } catch (error) {
            if (attempt === 3 || !/ERR_NETWORK_CHANGED/.test(error.message)) throw error;
        }
    }
}

/**
 * Open the site as a first-time visitor in a language and wait until it is quiet
 * @param {string} language - value of the settings-language key
 * @param {boolean} throttled - Slow 4G and a 4x slower CPU
 * @returns {Promise<object>} the page, the context, the requests seen, the console problems and the FCP
 */
async function visit(language, throttled) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.addInitScript((lng) => localStorage.setItem("settings-language", lng), language);
    const requests = [];
    const problems = [];
    context.on("request", (request) => requests.push({ url: new URL(request.url()), sw: Boolean(request.serviceWorker()) }));
    const page = await context.newPage();
    page.on("console", (message) => {
        if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) problems.push(`${message.type()}: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    if (throttled) {
        const session = await context.newCDPSession(page);
        await session.send("Network.emulateNetworkConditions", SLOW_4G);
        await session.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    }
    await page.addInitScript(() => {
        window.__fcp = null;
        window.__fontsDone = null;
        document.fonts.addEventListener("loadingdone", () => { window.__fontsDone = performance.now(); });
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) if (entry.name === "first-contentful-paint") window.__fcp = entry.startTime;
        }).observe({ type: "paint", buffered: true });
    });
    if (throttled) {
        // The load event waits for the basemap image (30 s on Slow 4G): measure the first seconds only
        await goto(page, "commit");
        await page.waitForFunction(() => window.__fcp !== null, null, { timeout: 120000 });
        await page.waitForTimeout(MEASURE_WINDOW_MS);
    } else {
        await goto(page, "load");
        await page.waitForFunction(() => window.__fcp !== null, null, { timeout: 120000 });
        // The service worker precaches in the background after the load
        await page.evaluate(() => navigator.serviceWorker.ready);
        await page.waitForTimeout(4000);
    }
    await page.evaluate(() => document.fonts.ready);
    const { fcp, fontsDone } = await page.evaluate(() => ({ fcp: window.__fcp, fontsDone: window.__fontsDone }));
    return { context, page, requests, problems, fcp, fontsDone };
}

/** The font files and the Google font hosts among the requests of a visit */
const fontRequests = (requests) => requests.filter((request) => request.url.pathname.startsWith("/fonts/"));
const googleRequests = (requests) => requests.filter((request) => GOOGLE_FONT_HOST.test(request.url.hostname));

for (const [language, cyrillic] of Object.entries(LANGUAGES)) {
    const { context, page, requests, problems } = await visit(language, false);
    const fonts = fontRequests(requests);

    check(`${language}: no request to Google Fonts`, googleRequests(requests).length === 0, googleRequests(requests).map((request) => request.url.href).join(", ") || "none");
    check(`${language}: console clean`, problems.length === 0, problems.join(" | ") || "no errors or warnings");

    const faces = await page.evaluate(() => [...document.fonts].map((face) => ({ family: face.family.replace(/"/g, ""), status: face.status, })));
    const loaded = (family) => faces.filter((face) => face.family === family && face.status === "loaded").length;
    check(`${language}: font faces come from the stylesheet`, faces.length === 12, `${faces.length} @font-face rules`);
    check(`${language}: Montserrat loaded`, loaded("Montserrat") >= 1, `${loaded("Montserrat")} subset(s)`);
    check(`${language}: Oswald loaded`, loaded("Oswald") >= 1, `${loaded("Oswald")} subset(s)`);

    const pageFonts = fonts.filter((request) => !request.sw).map((request) => request.url.pathname.replace("/fonts/", ""));
    check(`${language}: latin preloads used once, not fetched twice`, ["montserrat-v31-latin.woff2", "oswald-v57-latin.woff2"].every((name) => pageFonts.filter((file) => file === name).length === 1), pageFonts.join(", "));
    check(`${language}: cyrillic subset ${cyrillic ? "requested" : "not requested"} by the page`, pageFonts.some((file) => file.includes("-cyrillic.woff2")) === cyrillic, pageFonts.join(", "));

    const precached = await page.evaluate(async () => {
        const urls = [];
        for (const name of await caches.keys()) {
            if (name === "fonts") continue;
            for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
        }
        return urls.filter((path) => path.startsWith("/fonts/")).sort();
    });
    check(`${language}: precache holds the three latin files only`, precached.length === 3 && precached.every((path) => path.endsWith("-latin.woff2")), precached.join(", ") || "none");

    if (shotsDir) {
        await page.screenshot({ path: join(shotsDir, `${language}-page.png`) });
        await page.evaluate(() => document.querySelector("#helpDialog").showModal());
        await page.waitForTimeout(1500);
        await page.screenshot({ path: join(shotsDir, `${language}-settings.png`) });
    }
    await context.close();
}

// Offline after a first visit: a subset the page used is cached by the service worker on its first use
{
    const { context, page } = await visit("ru", false);
    await page.reload({ waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(2000);
    const cached = await page.evaluate(async () => (await (await caches.open("fonts")).keys()).map((request) => new URL(request.url).pathname.replace("/fonts/", "")).sort());
    check("offline: the fonts cache holds the cyrillic subsets the page used", cached.includes("montserrat-v31-cyrillic.woff2"), cached.join(", ") || "empty");
    await context.setOffline(true);
    const probe = (file) => page.evaluate(async (path) => {
        try {
            await new FontFace("Probe", `url(/fonts/${path})`).load();
            return "loaded";
        } catch (error) {
            return error.message;
        }
    }, file);
    const latin = await probe("montserrat-v31-latin.woff2");
    const cyrillic = await probe("montserrat-v31-cyrillic.woff2");
    const unused = await probe("montserrat-v31-latin-ext.woff2");
    check("offline: the precached latin file loads", latin === "loaded", latin);
    check("offline: a cyrillic file used before loads", cyrillic === "loaded", cyrillic);
    check("offline: a subset never used is not available (the page falls back to the system font)", unused !== "loaded", unused);
    await context.close();
}

if (measureRuns > 0) {
    for (const language of ["en", "ru"]) {
        const rows = [];
        for (let run = 1; run <= measureRuns; run++) {
            const { context, requests, fcp, fontsDone } = await visit(language, true);
            const fonts = fontRequests(requests);
            rows.push({
                fcpMs: Math.round(fcp),
                lastFontLoadedMs: Math.round(fontsDone),
                requests: requests.length,
                ownFontRequests: fonts.length,
                googleRequests: googleRequests(requests).length,
            });
            await context.close();
        }
        console.log(`measure ${language} (Slow 4G, CPU x4, cold):`);
        console.table(rows);
    }
}

await browser.close();
if (failures) {
    console.error(`${failures} check(s) failed`);
    process.exit(1);
}
