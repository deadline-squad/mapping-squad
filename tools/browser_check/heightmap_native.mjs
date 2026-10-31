// A map with a heightmap finer than 1 m (Chora, Kokan: 0.5 m) in the page, in Chromium through Playwright:
//
//     node heightmap_native.mjs <site URL> --maps chora,kokan [--points <points.json>] [--runs 5]
//
// For each map the page loads the heightmap through its own worker and the check reports the grid it got
// (samples, resolution, step), the time from the worker's start to its result (`--runs` times: the first is
// cold, the rest read the browser cache, i.e. the decoding) and the bytes of the heavy file transferred.
// With --points (compare_native_vertices.py --points-out: {"<map>": [[x, y, z], ...]}, world metres of landscape vertices of the game) the
// page's own getHeight (height above the map's lowest point, meta.json z_min_m) is read at each point on the map and must be within half the heightmap's step of z (the
// points are vertices where the file holds the landscape to that step: no building on them). Exits with 1 on any failure.
// Environment: PLAYWRIGHT_CORE, CHROME as in browser_check.mjs.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { readFileSync } from "node:fs";

const base = process.argv[2];
const option = (name) => { const index = process.argv.indexOf(name); return index > 0 ? process.argv[index + 1] : null; };
const slugs = option("--maps")?.split(",") ?? [];
if (!base || !slugs.length) {
    console.error("usage: node heightmap_native.mjs <site URL> --maps a,b [--points <points.json>] [--runs 5]");
    process.exit(2);
}
const points = option("--points") ? JSON.parse(readFileSync(option("--points"), "utf8")) : {};
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
                resolve(data.error ? { error: data.error } : { ms, width: data.width, height: data.height, step: data.step, resolution: data.resolution, precise: data.precise, url: data.url });
            };
            worker.postMessage({ preciseBase: `${origin}/heightmaps/${slug}/`, fallbackUrl: "about:blank", fallbackScale: 1 });
        }), { slug, origin: new URL(base).origin });
        if (result.error || !result.precise) {
            check(`${slug} loads`, false, result.error ?? "not precise");
            break;
        }
        times.push(result.ms);
        grid = result;
    }
    if (!grid) continue;
    const sorted = [...times].sort((a, b) => a - b);
    const warm = sorted.slice(0, Math.max(1, times.length - 1));
    check(`${slug} grid`, grid.width === meta.width && grid.height === meta.height && grid.resolution === meta.resolution_m,
        `${grid.width} x ${grid.height} samples, resolution ${grid.resolution} m, step ${grid.step} m, ${grid.url}`);
    console.log(`     ${slug} worker time: cold ${times[0].toFixed(0)} ms, then ${times.slice(1).map((t) => t.toFixed(0)).join(", ")} ms (median warm ${warm[Math.floor(warm.length / 2)].toFixed(0)} ms)`);
}

for (const [slug, vertices] of Object.entries(points)) {
    if (!slugs.includes(slug)) continue;
    const result = await page.evaluate(async ({ slug, vertices }) => {
        const app = window.__App;
        const map = app.minimap;
        if (!map.activeMap.mapURL.includes(`/${slug}/`)) app.MAP_SELECTOR.val([...app.MAP_SELECTOR[0].options].find((o) => o.textContent.toLowerCase().includes(slug)).value).trigger("change");
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.activeMap.mapURL.includes(`/${slug}/`) && map.heightmap.precise) { clearInterval(timer); resolve(); } }, 50); setTimeout(resolve, 120000); });
        const meta = await (await fetch(`/heightmaps/${slug}/meta.json`)).json();
        const { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY } = meta.bounds_m;
        const errors = vertices.map(([x, y, z]) => map.heightmap.getHeight({ lat: -(y - minY) / (maxY - minY) * map.pixelSize, lng: (x - minX) / (maxX - minX) * map.pixelSize }) + meta.z_min_m - z);
        return { name: map.activeMap.name, resolution: map.heightmap.resolution, step: map.heightmap.step, errors, precise: map.heightmap.precise };
    }, { slug, vertices });
    const abs = result.errors.map(Math.abs).sort((a, b) => a - b);
    const rms = Math.sqrt(abs.reduce((sum, e) => sum + e * e, 0) / abs.length);
    check(`${slug} page heights at ${abs.length} landscape vertices`, result.precise && abs[abs.length - 1] <= result.step / 2 + 0.0005,
        `resolution ${result.resolution} m, rms ${(rms * 100).toFixed(3)} cm, p99 ${(abs[Math.floor(abs.length * 0.99)] * 100).toFixed(3)} cm, max ${(abs[abs.length - 1] * 100).toFixed(3)} cm (step ${(result.step * 100).toFixed(2)} cm)`);
}

check("console clean", problems.length === 0, problems.length ? problems.slice(0, 5).join(" | ") : "no errors or warnings");
await browser.close();
process.exit(failures ? 1 : 0);
