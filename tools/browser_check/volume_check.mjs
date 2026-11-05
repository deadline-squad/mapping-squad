// Checks the volume layer of the Deadline SquadCalc in a real browser (Chromium through Playwright):
// nothing of it is downloaded until the setting is turned on, then the voxel file, the landscape file and the
// WebAssembly engine load, a known wall blocks and a known opening passes (segments of the voxel parity data of
// Jensen and Kokan, engine/README.md "Voxel columns", picked in volume_cases.json), the firing solution and the fire
// coverage use the layer, a map without volume file keeps the heightmap, and the console stays clean.
//
//     node volume_check.mjs <site URL>
//
// <site URL> is a served build with `npm run build:engine` done and the maps' volume files under /heightmaps/.
// Environment: PLAYWRIGHT_CORE, CHROME as for browser_check.mjs. Exits with 1 on any failure.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const base = process.argv[2];
if (!base) {
    console.error("usage: node volume_check.mjs <site URL>");
    process.exit(2);
}
const cases = JSON.parse(readFileSync(new URL("./volume_cases.json", import.meta.url), "utf8"));

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/** Open SquadCalc on the map whose name is `mapName` with window.__App and a log of problems and requests */
async function open(mapName) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
        if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
        await route.fulfill({ response, body: patched });
    });
    const page = await context.newPage();
    const problems = [];
    const requests = [];
    page.on("console", (message) => {
        if (["error", "warning"].includes(message.type()) && !/GL Driver Message|GPU stall/.test(message.text())) problems.push(`${message.type()}: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
    page.on("response", (response) => {
        requests.push({ url: response.url(), status: response.status(), headers: response.headers() });
        if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`);
    });
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => window.__App?.minimap?.heightmap?.precise, null, { timeout: 120000 });
    await page.evaluate(async (name) => {
        const app = window.__App;
        const option = [...app.MAP_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `maps:${name}`);
        app.MAP_SELECTOR.val(option.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 0));
    }, mapName);
    await page.waitForFunction((name) => {
        const map = window.__App.minimap;
        return map.activeMap.name === name && map.heightmap?.precise && !map._spinning;
    }, mapName, { timeout: 120000 });
    return { context, page, problems, requests };
}

/** Resident memory in MB of this process's descendants (the browser, its renderers and its workers, shared pages counted once per process) */
function browserRssMb() {
    const rows = execFileSync("ps", ["-eo", "pid=,ppid=,rss="], { encoding: "utf8" }).trim().split("\n").map((line) => line.trim().split(/\s+/).map(Number));
    const family = new Set([process.pid]);
    for (let grew = true; grew;) {
        grew = false;
        for (const [pid, parent] of rows) if (family.has(parent) && !family.has(pid)) { family.add(pid); grew = true; }
    }
    return rows.filter(([pid]) => family.has(pid) && pid !== process.pid).reduce((sum, row) => sum + row[2], 0) / 1024;
}

const volumeRequests = (requests) => requests.filter((request) => /volume\.vcol|terrain\.bin|\/engine\//.test(request.url));

for (const [slug, mapName] of [["jensen", "Jensen"], ["kokan", "Kokan"]]) {
    const { context, page, problems, requests } = await open(mapName);
    const before = volumeRequests(requests).length;
    check(`${slug}: nothing of the layer is requested while the setting is off`, before === 0, `${before} requests`);

    const started = Date.now();
    await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
    await page.waitForFunction(() => window.__App.minimap.volume.state !== "loading" && window.__App.minimap.volume.state !== "idle", null, { timeout: 120000 });
    const state = await page.evaluate(() => ({ state: window.__App.minimap.volume.state, ready: window.__App.minimap.volume.ready }));
    const loaded = volumeRequests(requests);
    const sizes = loaded.map((request) => `${request.url.replace(/^.*\/(heightmaps\/|engine\/)/, "$1").replace(/\?.*/, "")} ${request.headers["content-length"] ?? "?"} B`).join(", ");
    check(`${slug}: the layer loads after the setting is turned on`, state.ready && loaded.some((request) => /volume\.vcol/.test(request.url)) && loaded.some((request) => /terrain\.bin/.test(request.url)) && loaded.some((request) => /\.wasm/.test(request.url)), `${state.state} in ${Date.now() - started} ms; ${sizes}`);
    const vcol = loaded.find((request) => /volume\.vcol/.test(request.url));
    check(`${slug}: the voxel file is served with its cache key`, /\?v=/.test(vcol?.url ?? "") && vcol.status === 200, `${vcol?.url} cache-control "${vcol?.headers["cache-control"]}"`);

    // Segments of the parity data: walls block, openings pass
    const traced = await page.evaluate(async ({ walls, openings }) => {
        const volume = window.__App.minimap.volume;
        const paths = [...walls, ...openings].map((segment) => Float64Array.from(segment));
        const hits = await volume.trace(paths);
        return { walls: hits.slice(0, walls.length), openings: hits.slice(walls.length) };
    }, { walls: cases[slug].walls, openings: cases[slug].openings });
    check(`${slug}: ${traced.walls.length} known walls block`, traced.walls.every((hit) => hit && hit.index === 1 && hit.t >= 0 && hit.t < 1), JSON.stringify(traced.walls.map((hit) => hit && +hit.t.toFixed(3))));
    check(`${slug}: ${traced.openings.length} known openings pass`, traced.openings.every((hit) => hit === null), JSON.stringify(traced.openings.map((hit) => hit && +hit.t.toFixed(3))));

    // The world frame of the page: the map's own point at a world position comes back to it
    const frame = await page.evaluate(() => {
        const volume = window.__App.minimap.volume;
        const map = window.__App.minimap;
        const there = volume.toWorld({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 });
        const b = volume.bounds;
        return { there, expected: { x: (b.min_x + b.max_x) / 2, y: (b.min_y + b.max_y) / 2 } };
    });
    check(`${slug}: the page's frame is the files' frame`, Math.abs(frame.there.x - frame.expected.x) < 1e-6 && Math.abs(frame.there.y - frame.expected.y) < 1e-6, JSON.stringify(frame.there));

    // Landscape of the layer against the heightmap: the heightmap fuses the buildings with the ground and counts from its
    // lowest level, so on a grid of points around the centre the downward trace meets the ground at the heightmap's
    // height plus meta.json z_min_m wherever nothing stands, and the median of the differences is zero
    const ground = await page.evaluate(async () => {
        const map = window.__App.minimap;
        const volume = map.volume;
        const paths = [];
        const heights = [];
        for (let north = -600; north <= 600; north += 40) {
            for (let east = -600; east <= 600; east += 40) {
                const latlng = map.fromMeters({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }, east, north);
                const height = map.heightmap.getHeight(latlng) + volume.zMin;
                const world = volume.toWorld(latlng);
                paths.push(Float64Array.from([world.x, world.y, height + 3, world.x, world.y, height - 3]));
                heights.push(height);
            }
        }
        const hits = await volume.trace(paths);
        const differences = hits.map((hit, i) => hit && hit.z - heights[i]).filter((difference) => difference !== null).sort((a, b) => a - b);
        return { points: paths.length, hits: differences.length, median: differences[Math.floor(differences.length / 2)], zMin: volume.zMin };
    });
    check(`${slug}: the landscape is at the heightmap's height on open ground`, ground.hits > ground.points / 4 && Math.abs(ground.median) < 0.1, JSON.stringify(ground));

    // The line of fire of a direct-fire weapon, with and without the layer, from the same weapon to the same target
    const fire = await page.evaluate(async ({ segments, weaponName }) => {
        const app = window.__App;
        const map = app.minimap;
        const volume = map.volume;
        const b = volume.bounds;
        const latlng = (x, y) => ({ lng: ((x - b.min_x) / (b.max_x - b.min_x)) * map.pixelSize, lat: -((y - b.min_y) / (b.max_y - b.min_y)) * map.pixelSize });
        const weaponOption = [...app.WEAPON_SELECTOR[0].options].find((candidate) => candidate.dataset.i18n === `weapons:${weaponName}`);
        app.WEAPON_SELECTOR.val(weaponOption.value).trigger("change");
        await new Promise((resolve) => setTimeout(resolve, 300));
        const results = [];
        for (const segment of segments) {
            const start = latlng(segment[0], segment[1]);
            const end = latlng(segment[3], segment[4]);
            map.activeWeaponsMarkers.clearLayers();
            map.activeTargetsMarkers.clearLayers();
            map.createWeapon(start);
            map.activeWeaponsMarkers.getLayers()[0].heightPadding = Math.max(0, segment[2] - volume.zMin - map.heightmap.getHeight(start));
            map.createTarget(end);
            const target = map.activeTargetsMarkers.getLayers()[0];
            await new Promise((resolve) => setTimeout(resolve, 150));
            target.updateCalc();
            await new Promise((resolve) => setTimeout(resolve, 150));
            results.push({ segment, volume: target.firingSolution1.obstacle.low, ready: volume.ready, answers: volume.answers.size });
        }
        app.userSettings.set("volumeLayer", false);
        await new Promise((resolve) => setTimeout(resolve, 200));
        for (const result of results) {
            const start = latlng(result.segment[0], result.segment[1]);
            const end = latlng(result.segment[3], result.segment[4]);
            map.activeWeaponsMarkers.clearLayers();
            map.activeTargetsMarkers.clearLayers();
            map.createWeapon(start);
            map.activeWeaponsMarkers.getLayers()[0].heightPadding = Math.max(0, result.segment[2] - volume.zMin - map.heightmap.getHeight(start));
            map.createTarget(end);
            result.heightmap = map.activeTargetsMarkers.getLayers()[0].firingSolution1.obstacle.low;
            result.readyAfterOff = volume.ready;
        }
        app.userSettings.set("volumeLayer", true);
        return results;
    }, { segments: [...cases[slug].walls, ...cases[slug].openings], weaponName: "DF_NLAW" });
    const differing = fire.filter((result) => Boolean(result.volume) !== Boolean(result.heightmap));
    check(`${slug}: the line of fire uses the layer (turned off, the heightmap answers)`, fire.every((result) => result.ready && !result.readyAfterOff) && fire.some((result) => result.answers > 0),
        `${fire.length} shots, ${fire.filter((result) => result.volume).length} blocked with the layer, ${fire.filter((result) => result.heightmap).length} with the heightmap, ${differing.length} differ`);

    // Fire coverage with and without the layer
    const coverage = await page.evaluate(async () => {
        const app = window.__App;
        const map = app.minimap;
        const centre = { lng: 0.5 * map.pixelSize, lat: -0.5 * map.pixelSize };
        map.activeWeaponsMarkers.clearLayers();
        map.activeTargetsMarkers.clearLayers();
        map.createWeapon(centre);
        const run = async (volume) => {
            app.userSettings.set("volumeLayer", volume);
            if (volume) await new Promise((resolve) => { const timer = setInterval(() => { if (map.volume.ready) { clearInterval(timer); resolve(); } }, 50); });
            const started = performance.now();
            map.coverage.setEnabled(false);
            map.coverage.setEnabled(true);
            await new Promise((resolve) => { const timer = setInterval(() => { if (map.coverage.overlay) { clearInterval(timer); resolve(); } }, 50); });
            const canvas = document.createElement("canvas");
            const image = new Image();
            image.src = map.coverage.overlayUrl;
            await image.decode();
            canvas.width = image.width;
            canvas.height = image.height;
            const context = canvas.getContext("2d");
            context.drawImage(image, 0, 0);
            const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
            const tally = { green: 0, yellow: 0, red: 0 };
            for (let i = 0; i < pixels.length; i += 4) {
                if (!pixels[i + 3]) continue;
                if (pixels[i + 1] > 180 && pixels[i] < 100) tally.green++;
                else if (pixels[i] > 200 && pixels[i + 1] > 150) tally.yellow++;
                else tally.red++;
            }
            map.coverage.overlay.remove();
            map.coverage.overlay = null;
            return { ms: Math.round(performance.now() - started), size: image.width, tally };
        };
        const withHeightmap = await run(false);
        const withVolume = await run(true);
        return { withHeightmap, withVolume, jobs: map.volume.coverageJobs };
    });
    check(`${slug}: the fire coverage is drawn with the layer`, coverage.jobs >= 1 && coverage.withVolume.tally.green + coverage.withVolume.tally.yellow + coverage.withVolume.tally.red > 1000,
        `${coverage.jobs} jobs of the layer; heightmap ${JSON.stringify(coverage.withHeightmap)}; layer ${JSON.stringify(coverage.withVolume)}`);

    check(`${slug}: console and requests are clean`, problems.length === 0, problems.length ? problems.join(" | ") : "no errors, warnings or failed requests");
    await context.close();
}

// The largest files (every map has volume files now; the six biggest are 25 to 49 MB gzip): the layer loads, the landscape
// agrees with the heightmap and the coverage finishes. Reported: load = from the setting being turned on to the worker's
// "ready" (download, sha256, engine start, decompression of both files), and the resident memory of the browser's process
// tree (peak sampled every 50 ms during the load, and after the coverage) against its size before the setting was turned on
for (const mapName of ["Fallujah", "GooseBay", "Kamdesh", "Skorpo", "BlackCoast", "Chora", "Gorodok", "Harju", "Yehorivka"]) {
    const { context, page, problems, requests } = await open(mapName);
    const baselineMb = browserRssMb();
    let peakMb = baselineMb;
    const sampler = setInterval(() => { peakMb = Math.max(peakMb, browserRssMb()); }, 50);
    const started = Date.now();
    await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
    await page.waitForFunction(() => ["ready", "unavailable"].includes(window.__App.minimap.volume.state), null, { timeout: 300000 });
    const loadMs = Date.now() - started;
    const loadedMb = browserRssMb();
    const result = await page.evaluate(async () => {
        const map = window.__App.minimap;
        const volume = map.volume;
        if (!volume.ready) return { ready: false };
        const paths = [];
        const heights = [];
        for (let north = -600; north <= 600; north += 40) {
            for (let east = -600; east <= 600; east += 40) {
                const latlng = map.fromMeters({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }, east, north);
                const height = map.heightmap.getHeight(latlng) + volume.zMin;
                const world = volume.toWorld(latlng);
                paths.push(Float64Array.from([world.x, world.y, height + 3, world.x, world.y, height - 3]));
                heights.push(height);
            }
        }
        const hits = await volume.trace(paths);
        const differences = hits.map((hit, i) => hit && hit.z - heights[i]).filter((difference) => difference !== null).sort((a, b) => a - b);
        map.activeWeaponsMarkers.clearLayers();
        map.createWeapon({ lng: 0.5 * map.pixelSize, lat: -0.5 * map.pixelSize });
        const started = performance.now();
        map.coverage.setEnabled(true);
        await new Promise((resolve) => { const timer = setInterval(() => { if (map.coverage.overlay) { clearInterval(timer); resolve(); } }, 50); });
        return { ready: true, hits: differences.length, points: paths.length, median: differences[Math.floor(differences.length / 2)], coverageMs: Math.round(performance.now() - started), jobs: volume.coverageJobs };
    });
    clearInterval(sampler);
    const finalMb = browserRssMb();
    peakMb = Math.max(peakMb, finalMb);
    const files = volumeRequests(requests).map((request) => Number(request.headers["content-length"] ?? 0));
    const memory = `browser RSS ${baselineMb.toFixed(0)} MB before, peak ${peakMb.toFixed(0)} MB, ${loadedMb.toFixed(0)} MB when ready, ${finalMb.toFixed(0)} MB after the coverage`;
    check(`${mapName}: loads, the landscape agrees with the heightmap, the coverage finishes`, result.ready && result.hits > result.points / 4 && Math.abs(result.median) < 0.1 && result.jobs >= 1,
        `${JSON.stringify(result)}; load ${loadMs} ms, ${(files.reduce((sum, size) => sum + size, 0) / 1e6).toFixed(1)} MB downloaded; ${memory}`);
    check(`${mapName}: console and requests are clean`, problems.length === 0, problems.join(" | ") || "clean");
    await context.close();
}

{
    // A map whose volume file cannot be fetched (every map has one now: the request is answered with 404) keeps the heightmap
    // and says so once in the console
    const { context, page, problems, requests } = await open("AlBasrah");
    await context.route(/\/heightmaps\/albasrah\/volume\.vcol/, (route) => route.fulfill({ status: 404, body: "" }));
    await page.evaluate(() => window.__App.userSettings.set("volumeLayer", true));
    await page.waitForFunction(() => window.__App.minimap.volume.state === "unavailable", null, { timeout: 60000 });
    const state = await page.evaluate(() => ({ ready: window.__App.minimap.volume.ready, heightmap: Boolean(window.__App.minimap.heightmap?.precise) }));
    check("a map whose volume file is missing keeps the heightmap", !state.ready && state.heightmap, JSON.stringify(state));
    const unexpected = problems.filter((problem) => !/HTTP 404: .*volume\.vcol|Failed to load resource|\[VOLUME\]/.test(problem));
    check("a map whose volume file is missing: only the 404 and the layer's own warning in the console", unexpected.length === 0 && problems.some((problem) => /\[VOLUME\]/.test(problem)), problems.join(" | "));
    await context.close();
}

await browser.close();
process.exit(failures ? 1 : 0);
