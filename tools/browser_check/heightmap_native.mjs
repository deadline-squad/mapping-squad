// The heightmap of a map on the game's landscape vertices in the page, in Chromium through Playwright:
//
//     node heightmap_native.mjs <site URL> --maps skorpo,anvil,chora [--points <points.json>] [--detail <points.json>] [--runs 5]
//
// For each map the page loads the heightmap through its own worker and the check reports the grid it got
// (samples, the lattice of meta.json: origin, resolution, yaw; step), the time from the worker's start to its result (`--runs`
// times: the first is cold, the rest read the browser cache, i.e. the decoding) and the bytes of the heavy file transferred,
// and the quads of its detail where objects stand (the count in the header of the `HMD1` bytes the worker hands the engine), which must be meta.json's `detail.quads` (none without the entry).
// With --points (compare_native_vertices.py --points-out: {"<map>": [[x, y, z], ...]}, world metres and the game's
// collision: landscape vertices and points inside quads, where the file holds the bare landscape) the page's own getHeight (read
// by the engine's core)
// (height above the map's lowest point, meta.json z_min_m) is read at each point on the map and must be within half the
// heightmap's step of z, plus 0.5 mm. With --detail (heightmap_detail.py of tools/heightmaps: points in quads with detail,
// z the height its reader gives from the served files) the page must read z within 0.1 mm. Exits with 1 on any failure.
// Environment: PLAYWRIGHT_CORE, CHROME as in browser_check.mjs.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { readFileSync } from "node:fs";

const base = process.argv[2];
const option = (name) => { const index = process.argv.indexOf(name); return index > 0 ? process.argv[index + 1] : null; };
const slugs = option("--maps")?.split(",") ?? [];
if (!base || !slugs.length) {
    console.error("usage: node heightmap_native.mjs <site URL> --maps a,b [--points <points.json>] [--detail <points.json>] [--runs 5]");
    process.exit(2);
}
const points = option("--points") ? JSON.parse(readFileSync(option("--points"), "utf8")) : {};
const detailPoints = option("--detail") ? JSON.parse(readFileSync(option("--detail"), "utf8")) : {};
const runs = Number(option("--runs") ?? 5);

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
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
// SquadCalc keeps its App in a module; expose it as window.__App by rewriting the main bundle (as browser_check.mjs does)
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
    if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
    await route.fulfill({ response, body: patched });
});
const page = await context.newPage();
const problems = [];
page.on("console", (message) => { if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) problems.push(message.text()); });
page.on("pageerror", (error) => problems.push(String(error)));
let heavyBytes = 0;
page.on("response", async (response) => {
    if (/\/heightmaps\/[^/]+\/heightmap\.(webp|png)/.test(response.url())) heavyBytes = Number(response.headers()["content-length"] ?? 0);
});
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__workerUrl && window.__App?.minimap?.heightmap, null, { timeout: 60000 });

for (const slug of slugs) {
    const meta = await (await fetch(new URL(`/heightmaps/${slug}/meta.json`, base))).json();
    const times = [];
    let grid = null;
    for (let run = 0; run < runs; run++) {
        heavyBytes = 0;
        const result = await page.evaluate(async ({ slug, origin }) => new Promise((resolve) => {
            const start = performance.now();
            const worker = new Worker(window.__workerUrl);
            worker.onmessage = ({ data }) => {
                const ms = performance.now() - start;
                worker.terminate();
                resolve(data.error ? { error: data.error } : { ms, width: data.width, height: data.height, step: data.step, lattice: data.lattice, url: data.url,
                    detailQuads: data.detail ? new DataView(data.detail.buffer, data.detail.byteOffset).getUint32(20, true) : null, detailError: data.detailError });
            };
            worker.postMessage({ base: `${origin}/heightmaps/${slug}/` });
        }), { slug, origin: new URL(base).origin });
        if (result.error) {
            check(`${slug} loads`, false, result.error);
            break;
        }
        times.push(result.ms);
        grid = result;
    }
    if (!grid) continue;
    const sorted = [...times].sort((a, b) => a - b);
    const warm = sorted.slice(0, Math.max(1, times.length - 1));
    const { originX, originY, resolution, yawDeg } = grid.lattice;
    check(`${slug} grid`, grid.width === meta.width && grid.height === meta.height && resolution === meta.resolution_m
        && originX === meta.origin_m[0] && originY === meta.origin_m[1] && yawDeg === meta.yaw_deg,
        `${grid.width} x ${grid.height} samples from (${originX}, ${originY}), resolution ${resolution} m, yaw ${yawDeg} deg, step ${grid.step} m, ${grid.url}`);
    check(`${slug} detail`, grid.detailQuads === (meta.detail?.quads ?? null) && !grid.detailError,
        meta.detail ? `${grid.detailQuads} quads with detail (meta.json ${meta.detail.quads}, threshold ${meta.detail.threshold_m} m, ${meta.detail.bytes} bytes)${grid.detailError ? `, ${grid.detailError}` : ""}`
            : `none announced, ${grid.detailQuads ?? "none"} read`);
    console.log(`     ${slug} worker time: cold ${times[0].toFixed(0)} ms, then ${times.slice(1).map((t) => t.toFixed(0)).join(", ")} ms (median warm ${warm[Math.floor(warm.length / 2)].toFixed(0)} ms)`);
}

/**
 * The page's getHeight plus meta.json z_min_m minus z at world points [[x, y, z], ...] of a map, the map selected first
 * @param {string} slug
 * @param {number[][]} vertices
 * @returns {Promise<{name: string, resolution: number, step: number, errors: number[], ready: boolean}>}
 */
async function pageErrors(slug, vertices) {
    return page.evaluate(async ({ slug, vertices }) => {
        const app = window.__App;
        const map = app.minimap;
        if (!map.activeMap.mapURL.includes(`/${slug}/`)) app.MAP_SELECTOR.val([...app.MAP_SELECTOR[0].options].find((o) => o.dataset.i18n.toLowerCase() === `maps:${slug}`).value).trigger("change");
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.activeMap.mapURL.includes(`/${slug}/`) && map.heightmap.ready) { clearInterval(timer); resolve(); } }, 50); setTimeout(resolve, 120000); });
        const meta = await (await fetch(`/heightmaps/${slug}/meta.json`)).json();
        const { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY } = meta.bounds_m;
        const errors = vertices.map(([x, y, z]) => map.heightmap.getHeight({ lat: -(y - minY) / (maxY - minY) * map.pixelSize, lng: (x - minX) / (maxX - minX) * map.pixelSize }) + meta.z_min_m - z);
        // The step of z the worker took for the page: the WebP's when meta.json announces one, else the PNG's
        const step = meta.webp?.file ? meta.webp.z_step_m : meta.z_step_m;
        return { name: map.activeMap.name, resolution: map.heightmap.resolution, step, errors, ready: map.heightmap.ready };
    }, { slug, vertices });
}

/**
 * Check the page's errors at a map's points against a tolerance in metres
 * @param {string} label
 * @param {{resolution: number, step: number, errors: number[], ready: boolean}} result
 * @param {number} tolerance
 */
function checkErrors(label, result, tolerance) {
    const abs = result.errors.map(Math.abs).sort((a, b) => a - b);
    const rms = Math.sqrt(abs.reduce((sum, e) => sum + e * e, 0) / abs.length);
    check(label, result.ready && abs.length > 0 && abs[abs.length - 1] <= tolerance,
        `resolution ${result.resolution} m, rms ${(rms * 100).toFixed(3)} cm, p99 ${(abs[Math.floor(abs.length * 0.99)] * 100).toFixed(3)} cm, max ${(abs[abs.length - 1] * 100).toFixed(3)} cm (step ${(result.step * 100).toFixed(2)} cm)`);
}

for (const [slug, vertices] of Object.entries(points)) {
    if (!slugs.includes(slug)) continue;
    const result = await pageErrors(slug, vertices);
    checkErrors(`${slug} page heights at ${vertices.length} points of the game's landscape`, result, result.step / 2 + 0.0005);
}
for (const [slug, vertices] of Object.entries(detailPoints)) {
    if (!slugs.includes(slug) || !vertices.length) continue;
    checkErrors(`${slug} page heights at ${vertices.length} points in quads with detail`, await pageErrors(slug, vertices), 0.0001);
}

check("console clean", problems.length === 0, problems.length ? problems.slice(0, 5).join(" | ") : "no errors or warnings");
await browser.close();
process.exit(failures ? 1 : 0);
