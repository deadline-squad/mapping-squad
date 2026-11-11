// Network cost of the Deadline SquadCalc as a first-time and as a returning visitor: bytes on the wire,
// requests and the time to the heightmap, per scenario, in a real Chromium.
//
//     node netcost.mjs <site URL> [--json <file>] [--cold-only]
//
// --cold-only stops after the three visits of the first scenario (no map switches, no detailed layer).
//
// Scenarios: cold first visit (empty caches, until the service worker finished precaching), warm
// revisit (same browser profile, a new page), a map switch to Yehorivka / Skorpo / Al Basrah (empty HTTP
// cache; and again with the files in it), on the detailed layer one zoom step and a half-screen pan,
// and the blank tiles seen while dragging the map at about 600 px/s.
//
// Bytes are Chromium's own count of what came over the network (Network.loadingFinished
// encodedDataLength: headers and compressed body) for every request of the page, its workers and the
// service worker; a response served by the HTTP cache or by the service worker's cache costs 0. The
// "decode" of a map switch is the time from the end of the heightmap download to the moment the
// page holds the heights (worker decode and transfer, polled every 20 ms).
//
// Environment: PLAYWRIGHT_CORE = path of the playwright-core package if it is not resolvable from here,
// CHROME = Chromium executable if Playwright's own is not installed.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2];
if (!base) {
    console.error("usage: node netcost.mjs <site URL> [--json <file>] [--cold-only]");
    process.exit(2);
}
const jsonIndex = process.argv.indexOf("--json");
const jsonFile = jsonIndex > 0 ? process.argv[jsonIndex + 1] : null;
const coldOnly = process.argv.includes("--cold-only");
const IDLE_MS = 1500;

/**
 * Raw DevTools connection to the browser: every page, worker and service worker target gets
 * Network.enable, so the requests of the workers (heightmaps) and of the service worker (precache)
 * are counted too.
 */
class Wire {
    constructor() {
        this.requests = new Map();
        this.types = new Map();
        this.finishedAt = [];
    }

    async connect(port) {
        const { webSocketDebuggerUrl } = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
        this.socket?.close();
        this.attached = new Set();
        this.socket = new WebSocket(webSocketDebuggerUrl);
        this.nextId = 1;
        this.pending = new Map();
        await new Promise((resolve) => this.socket.addEventListener("open", resolve));
        this.socket.addEventListener("message", ({ data }) => this.onMessage(JSON.parse(data)));
        this.send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
    }

    send(method, params = {}, sessionId) {
        const id = this.nextId++;
        this.socket.send(JSON.stringify({ id, method, params, sessionId }));
        return new Promise((resolve) => this.pending.set(id, resolve));
    }

    async onMessage(message) {
        if (process.env.WIRE_DEBUG && (message.error || message.method === "Target.attachedToTarget")) console.error("wire", JSON.stringify(message).slice(0, 300));
        if (message.id) return this.pending.get(message.id)?.(message.result);
        const { method, params, sessionId } = message;
        if (method === "Target.attachedToTarget") {
            const session = params.sessionId;
            // A worker is reported by the browser and by its page: one session is enough
            if (this.attached.has(params.targetInfo.targetId)) return this.send("Runtime.runIfWaitingForDebugger", {}, session);
            this.attached.add(params.targetInfo.targetId);
            this.types.set(session, params.targetInfo.type);
            // Commands of one session run in order; the target stays paused until the last one, and a
            // paused worker answers none of them
            this.send("Network.enable", {}, session);
            if (params.targetInfo.type === "page") this.send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: true, flatten: true }, session);
            this.send("Runtime.runIfWaitingForDebugger", {}, session);
        } else if (method === "Network.requestWillBeSent") {
            const key = `${sessionId}:${params.requestId}`;
            this.requests.set(key, { source: this.types.get(sessionId) ?? "page", requestId: params.requestId, url: params.request.url, type: params.type, sessionId, bytes: 0, status: 0, fromCache: false, fromServiceWorker: false, done: false, startedAt: Date.now() });
        } else if (method === "Network.responseReceived") {
            const request = this.find(sessionId, params.requestId);
            if (!request) return;
            request.status = params.response.status;
            request.fromCache = Boolean(params.response.fromDiskCache || params.response.fromPrefetchCache);
            request.fromServiceWorker = Boolean(params.response.fromServiceWorker);
        } else if (method === "Network.loadingFinished") {
            const request = this.find(sessionId, params.requestId);
            if (!request) return;
            request.done = true;
            request.bytes = params.encodedDataLength;
            request.finishedAt = Date.now();
        } else if (method === "Tracing.dataCollected") {
            this.traceEvents.push(...params.value);
        } else if (method === "Tracing.tracingComplete") {
            this.traceDone?.();
        } else if (method === "Network.loadingFailed") {
            const request = this.find(sessionId, params.requestId);
            if (request) request.done = true;
        }
    }

    /** The request of an event: by session, else by id (a worker's script is reported by its page) */
    find(sessionId, requestId) {
        return this.requests.get(`${sessionId}:${requestId}`)
            ?? [...this.requests.values()].find((request) => request.requestId === requestId && !request.done);
    }

    /** Start a Chromium trace of the frame events */
    async startTrace() {
        this.traceEvents = [];
        await this.send("Tracing.start", { categories: "disabled-by-default-devtools.timeline.frame,devtools.timeline,cc", transferMode: "ReportEvents" });
    }

    /** @returns {Promise<object[]>} the events of the trace since startTrace */
    async stopTrace() {
        const done = new Promise((resolve) => { this.traceDone = resolve; });
        this.send("Tracing.end");
        await done;
        return this.traceEvents;
    }

    /** Forget the requests so far */
    reset() {
        this.requests.clear();
    }

    /** Resolve once nothing is in flight for IDLE_MS */
    async idle(timeout = 180000) {
        const deadline = Date.now() + timeout;
        let quietSince = Date.now();
        while (Date.now() < deadline) {
            const busy = [...this.requests.values()].some((request) => !request.done);
            if (busy) quietSince = Date.now();
            else if (Date.now() - quietSince >= IDLE_MS) return;
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        const stuck = [...this.requests.values()].filter((request) => !request.done).map((request) => `${request.type} ${request.url.slice(0, 90)}`);
        throw new Error(`network never went idle: ${stuck.join(" | ")}`);
    }

    /** Bytes and requests of what came over the network since the last reset, with the largest files */
    summary() {
        const counted = [...this.requests.values()].filter((request) => request.bytes > 0 && /^https?:/.test(request.url));
        counted.sort((a, b) => b.bytes - a.bytes);
        return {
            bytes: counted.reduce((sum, request) => sum + request.bytes, 0),
            requests: counted.length,
            allRequests: this.requests.size,
            // Requests by what sent them: the page, its workers, or the service worker (precache)
            bySource: Object.fromEntries([...new Set(counted.map((request) => request.source))].map((source) => [source, round(counted.filter((request) => request.source === source).reduce((sum, request) => sum + request.bytes, 0) / 1e6, 2)])),
            largest: counted.slice(0, 4).map((request) => `${request.url.replace(base, "")} ${(request.bytes / 1e6).toFixed(2)} MB (${request.source})`),
        };
    }

    /** The finished request for the heightmap file of the map switch */
    heightmapRequest() {
        return [...this.requests.values()].filter((request) => /\/heightmaps\/[^/]+\/heightmap\.(png|webp)/.test(request.url) && request.done).pop();
    }
}

const wire = new Wire();
const profiles = [];

/**
 * Launch Chromium on a profile directory (a real on-disk HTTP cache, which a Playwright context
 * without a profile does not have: it refuses the big heightmaps) and connect the wire to it
 * @param {string} [profile] - directory of a profile to reuse; a new empty one by default
 * @returns {Promise<{context: object, profile: string}>}
 */
async function launch(profile) {
    if (!profile) {
        profile = mkdtempSync(join(tmpdir(), "netcost-"));
        profiles.push(profile);
    }
    const port = 9333 + Math.floor(Math.random() * 500);
    const context = await chromium.launchPersistentContext(profile, {
        executablePath: process.env.CHROME || undefined,
        args: [`--remote-debugging-port=${port}`],
        viewport: { width: 1600, height: 1000 },
    });
    await wire.connect(port);
    return { context, profile };
}

/**
 * Open the site in a new page and wait for the heightmap of its first map. The page is not
 * intercepted (Playwright switches the HTTP cache off for an intercepted page): Worker is wrapped in an
 * init script instead, to see when the heightmap worker answers.
 * @param {string} [query] - appended to the site URL
 * @returns {Promise<object>} the page
 */
async function openSite(context, query = "") {
    await context.addInitScript(() => {
        const NativeWorker = window.Worker;
        window.__heightmaps = [];
        window.Worker = class extends NativeWorker {
            constructor(...args) {
                super(...args);
                this.addEventListener("message", ({ data }) => {
                    if (data?.levels) window.__heightmaps.push({ at: performance.timeOrigin + performance.now(), step: data.step, url: data.url });
                });
            }
        };
    });
    const page = await context.newPage();
    // The host's network interfaces change now and then (Docker): Chromium then fails the load once
    for (let attempt = 1; ; attempt++) {
        try {
            await page.goto(base + query, { waitUntil: "load" });
            break;
        } catch (error) {
            if (attempt === 3 || !/ERR_NETWORK_CHANGED/.test(error.message)) throw error;
            log("network changed during the load, trying again");
        }
    }
    await page.waitForFunction(() => window.__heightmaps.length, null, { timeout: 120000 });
    return page;
}

/** Wait until the service worker is active (a failure after 30 s is reported, not fatal) */
async function serviceWorkerReady(page) {
    const ready = await Promise.race([page.evaluate(() => navigator.serviceWorker.ready.then(() => true)), page.waitForTimeout(30000).then(() => false)]);
    if (!ready) log("service worker not active after 30 s");
}

// Every result is printed as soon as it is known
const results = new Proxy({}, { set(target, name, value) {
    target[name] = value;
    console.error(`[${new Date().toISOString().slice(11, 19)}] ${name}: ${(value.bytes / 1e6).toFixed(2)} MB, ${value.requests} requests`);
    return true;
} });
const log = (message) => console.error(`[${new Date().toISOString().slice(11, 19)}] ${message}`);
const round = (value, digits = 0) => Number(value.toFixed(digits));

/**
 * Switch to a map and measure the download and the time to its heightmap
 * @returns {Promise<object>}
 */
async function switchMap(page, mapName) {
    wire.reset();
    const timing = await page.evaluate(async (mapName) => {
        const before = window.__heightmaps.length;
        const select = document.querySelector(".dropbtn");
        const option = [...select.options].find((candidate) => candidate.dataset.i18n === `maps:${mapName}`);
        const start = performance.timeOrigin + performance.now();
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        await new Promise((resolve) => {
            const timer = setInterval(() => { if (window.__heightmaps.length > before) { clearInterval(timer); resolve(); } }, 20);
            setTimeout(() => { clearInterval(timer); resolve(); }, 120000);
        });
        return { start, ...window.__heightmaps.at(-1) };
    }, mapName);
    const file = wire.heightmapRequest();
    await wire.idle();
    return {
        ...wire.summary(),
        step_mm: round(timing.step * 1000, 2),
        totalMs: round(timing.at - timing.start),
        decodeMs: file ? round(timing.at - file.finishedAt) : null,
        file: file ? file.url.replace(base, "") : null,
    };
}

// Cold first visit, warm revisit in a new tab, and warm revisit after restarting the browser (the
// next day): one browser profile
{
    log("cold visit");
    const { context, profile } = await launch();
    wire.reset();
    const page = await openSite(context);
    log("page open");
    // The service worker installs after load and precaches in the background
    await serviceWorkerReady(page);
    await wire.idle();
    results.coldFirstVisit = wire.summary();
    results.coldFirstVisit.cacheEntries = await page.evaluate(async () => {
        const out = {};
        for (const name of await caches.keys()) out[name] = (await (await caches.open(name)).keys()).length;
        return out;
    });
    await page.close();

    wire.reset();
    const again = await openSite(context);
    await wire.idle();
    results.warmRevisitNewTab = wire.summary();
    await again.close();
    await context.close();

    log("warm revisit after a restart");
    const restarted = await launch(profile);
    wire.reset();
    await openSite(restarted.context);
    await wire.idle();
    results.warmRevisitAfterRestart = wire.summary();
    await restarted.context.close();
}

// Map switches: with empty HTTP cache (one profile per map), then again with the files cached
if (!coldOnly) {
for (const mapName of ["Yehorivka", "Skorpo", "AlBasrah"]) {
    log(`switch ${mapName}`);
    const { context } = await launch();
    // Al Basrah is the first map: open another one first
    const page = await openSite(context, mapName === "AlBasrah" ? "?map=Yehorivka" : "");
    await serviceWorkerReady(page);
    await wire.idle();
    results[`switch${mapName}`] = await switchMap(page, mapName);
    await switchMap(page, "Anvil");
    results[`switch${mapName}Again`] = await switchMap(page, mapName);
    await context.close();
}

// Detailed layer: a zoom step, a half-screen pan, and the frames of a drag
{
    log("detailed layer");
    const { context } = await launch();
    const page = await openSite(context);
    await switchMap(page, "Yehorivka");
    await page.evaluate(() => document.querySelector("#mapLayerMenu .btn-detailed").click());
    await wire.idle();
    await page.evaluate(() => document.querySelector(".leaflet-container").focus());

    const tileZoom = () => page.evaluate(() => Math.max(0, ...[...document.querySelectorAll(".leaflet-tile-loaded")].map((tile) => Number(tile.src.match(/maptiles\/[^/]+\/(\d+)\//)?.[1] ?? 0))));
    const zoomIn = async () => {
        wire.reset();
        await page.keyboard.press("+");
        await page.waitForTimeout(500);
        await wire.idle();
        return { ...wire.summary(), tileZoom: await tileZoom() };
    };
    while (await tileZoom() < 4) await zoomIn();
    results.detailedZoomStepTo5 = await zoomIn();
    results.detailedZoomStepTo6 = await zoomIn();

    const drag = async (dx, dy, steps = 25, pauseMs = 20) => {
        await page.mouse.move(800, 500);
        await page.mouse.down();
        for (let step = 1; step <= steps; step++) {
            await page.mouse.move(800 + dx * step / steps, 500 + dy * step / steps);
            await page.waitForTimeout(pauseMs);
        }
        await page.mouse.up();
    };
    wire.reset();
    await drag(-800, 0);
    await page.waitForTimeout(500);
    await wire.idle();
    results.detailedHalfScreenPan = wire.summary();
    wire.reset();
    await drag(0, -500);
    await page.waitForTimeout(500);
    await wire.idle();
    results.detailedHalfScreenPanDown = wire.summary();

    // Dragging at about 600 px/s (12 px every 20 ms), left and back
    const dragAndBack = async () => {
        await drag(-720, 0, 60);
        await drag(720, 0, 60);
        await page.waitForTimeout(500);
    };
    // Blank screen while dragging: share of a 24 x 15 grid of points on the map that no loaded tile covers
    await page.evaluate(() => {
        window.__blank = { frames: 0, blankFrames: 0, blankShare: 0, worst: 0, running: true };
        const container = document.querySelector(".leaflet-container");
        const tick = () => {
            const state = window.__blank;
            if (!state.running) return;
            const view = container.getBoundingClientRect();
            const rects = [...document.querySelectorAll(".leaflet-tile-loaded")].map((tile) => tile.getBoundingClientRect());
            let blank = 0;
            for (let column = 0; column < 24; column++) {
                for (let row = 0; row < 15; row++) {
                    const x = view.left + (column + 0.5) * view.width / 24;
                    const y = view.top + (row + 0.5) * view.height / 15;
                    if (!rects.some((rect) => x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom)) blank++;
                }
            }
            state.frames++;
            if (blank) state.blankFrames++;
            state.blankShare += blank / 360;
            state.worst = Math.max(state.worst, blank / 360);
            requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    });
    wire.reset();
    await dragAndBack();
    const blank = await page.evaluate(() => { window.__blank.running = false; return window.__blank; });
    await wire.idle();
    results.detailedDragBlank = { ...wire.summary(), frames: blank.frames, framesWithBlank: blank.blankFrames, worstBlankShare: round(blank.worst, 3) };

    // Frame rate of the same drag (no sampling running): rAF intervals and the DroppedFrame events of a trace
    const runs = [];
    for (let run = 0; run < 3; run++) {
        await page.evaluate(() => {
            window.__frames = { intervals: [], last: 0, running: true };
            const tick = (now) => {
                const state = window.__frames;
                if (!state.running) return;
                if (state.last) state.intervals.push(now - state.last);
                state.last = now;
                requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        });
        wire.reset();
        await wire.startTrace();
        await dragAndBack();
        const events = await wire.stopTrace();
        const { intervals } = await page.evaluate(() => { window.__frames.running = false; return window.__frames; });
        await wire.idle();
        runs.push({
            ...wire.summary(),
            fps: round(1000 * intervals.length / intervals.reduce((sum, value) => sum + value, 0), 1),
            framesOver25ms: intervals.filter((value) => value > 25).length,
            droppedFrameEvents: events.filter((event) => event.name === "DroppedFrame").length,
        });
    }
    results.detailedDragFrames = {
        bytes: Math.round(runs.reduce((sum, run) => sum + run.bytes, 0) / runs.length),
        requests: Math.round(runs.reduce((sum, run) => sum + run.requests, 0) / runs.length),
        runs: runs.map(({ fps, framesOver25ms, droppedFrameEvents }) => ({ fps, framesOver25ms, droppedFrameEvents })),
    };
    await context.close();
}
}

for (const profile of profiles) rmSync(profile, { recursive: true, force: true });
const mb = (bytes) => `${(bytes / 1e6).toFixed(2)} MB`;
for (const [name, value] of Object.entries(results)) {
    const extra = Object.fromEntries(Object.entries(value).filter(([key]) => !["bytes", "requests", "largest", "allRequests"].includes(key)));
    console.log(`${name.padEnd(26)} ${mb(value.bytes).padStart(10)} ${String(value.requests).padStart(5)} req  ${JSON.stringify(extra)}`);
    if (value.largest?.length) console.log(`${"".padEnd(26)} largest: ${value.largest.join("; ")}`);
}
if (jsonFile) writeFileSync(jsonFile, JSON.stringify(results, null, 1));
process.exit(0);
