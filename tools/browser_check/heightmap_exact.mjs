// Proves the browser decodes heightmap.webp exactly: for each map the worker of the site loads the
// heightmap twice, once through the WebP (meta.json announcing it) and once through the PNG (meta.json
// without `format`), and the two are compared pixel by pixel in the page: the WebP holds the PNG's levels and step
// (tools/heightmaps/py/heightmap_webp.py), so every pixel must match. With
// --fast-png the PNG the worker decoded (native inflate and our own scanline filters) is also compared
// with the one fast-png (the decoder the worker used before 45.10) reads from --dist, by checksum.
//
//     node heightmap_exact.mjs <site URL> [--maps a,b,...] [--dist <dir with <map>/heightmap.png>]
//         [--fast-png <fast-png package dir>] [--webp-meta <dir with <map>/meta.json announcing the WebP>]
//
// --webp-meta tests WebP files that are deployed but not announced yet: the page is given that meta.json
// instead of the served one. Environment: PLAYWRIGHT_CORE, CHROME as in browser_check.mjs.
// Exits with 1 on any difference.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { readFileSync } from "node:fs";

const base = process.argv[2];
const option = (name) => { const index = process.argv.indexOf(name); return index > 0 ? process.argv[index + 1] : null; };
if (!base) {
    console.error("usage: node heightmap_exact.mjs <site URL> [--maps a,b] [--dist <dir>] [--fast-png <dir>] [--webp-meta <dir>]");
    process.exit(2);
}
const distDir = option("--dist");
const webpMetaDir = option("--webp-meta");
const fastPng = option("--fast-png") ? await import(`${option("--fast-png")}/lib/index.js`) : null;

/** FNV-1a over the 16-bit levels */
function checksum(levels) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < levels.length; i++) hash = Math.imul(hash ^ levels[i], 16777619) >>> 0;
    return hash;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext();
await context.addInitScript(() => {
    const NativeWorker = window.Worker;
    window.Worker = class extends NativeWorker {
        constructor(url, ...rest) {
            super(url, ...rest);
            window.__workerUrl = String(url);
        }
    };
});
let mode = "webp";
await context.route(/\/heightmaps\/[^/]+\/meta\.json$/, async (route) => {
    const slug = route.request().url().match(/heightmaps\/([^/]+)\//)[1];
    if (mode === "webp" && webpMetaDir) return route.fulfill({ body: readFileSync(`${webpMetaDir}/${slug}/meta.json`), contentType: "application/json" });
    const response = await route.fetch();
    const meta = await response.json();
    if (mode === "png") delete meta.format;
    return route.fulfill({ response, json: meta });
});
const page = await context.newPage();
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__workerUrl, null, { timeout: 60000 });

const slugs = option("--maps")?.split(",") ?? [];
if (!slugs.length) {
    console.error("give --maps <slug,slug,...> (folder names under /heightmaps/)");
    process.exit(2);
}

let failures = 0;
for (const slug of slugs) {
    const result = {};
    for (const wanted of ["webp", "png"]) {
        mode = wanted;
        result[wanted] = await page.evaluate(async ({ slug, origin }) => new Promise((resolve) => {
            const worker = new Worker(window.__workerUrl);
            worker.onmessage = ({ data }) => {
                worker.terminate();
                if (data.error) return resolve({ error: data.error });
                window[`__levels_${slug}`] = window[`__levels_${slug}`] || {};
                window[`__levels_${slug}`][data.url.split("?")[0].split(".").pop()] = data.levels;
                resolve({ url: data.url, step: data.step, width: data.width, height: data.height });
            };
            worker.postMessage({ base: `${origin}/heightmaps/${slug}/` });
        }), { slug, origin: new URL(base).origin });
    }
    const label = `map ${slug}`;
    if (result.webp.error || result.png.error || !result.webp.url.includes(".webp") || !result.png.url.includes(".png")) {
        console.log(`FAIL ${label}: ${JSON.stringify(result)}`);
        failures++;
        continue;
    }
    const compared = await page.evaluate((slug) => {
        const { webp, png } = window[`__levels_${slug}`];
        let mismatches = 0;
        for (let i = 0; i < webp.length; i++) if (webp[i] !== png[i]) mismatches++;
        let hash = 0x811c9dc5;
        for (let i = 0; i < png.length; i++) hash = Math.imul(hash ^ png[i], 16777619) >>> 0;
        delete window[`__levels_${slug}`];
        return { sizeMatches: webp.length === png.length, mismatches, pngChecksum: hash };
    }, slug);
    let ok = compared.sizeMatches && result.webp.width === result.png.width && result.webp.step === result.png.step && compared.mismatches === 0;
    let reference = "";
    if (fastPng && distDir) {
        const old = fastPng.decode(readFileSync(`${distDir}/${slug}/heightmap.png`));
        const referenceMatches = checksum(old.data) === compared.pngChecksum;
        ok &&= referenceMatches;
        reference = `, native PNG decode ${referenceMatches ? "identical to" : "DIFFERENT from"} fast-png`;
    }
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: webp step ${(result.webp.step * 1000).toFixed(3)} mm, png step ${(result.png.step * 1000).toFixed(3)} mm, `
        + `${compared.mismatches} mismatched pixels${reference}`);
    if (!ok) failures++;
}
await browser.close();
console.log(failures ? `${failures} map(s) differ` : "all maps match");
process.exit(failures ? 1 : 0);
