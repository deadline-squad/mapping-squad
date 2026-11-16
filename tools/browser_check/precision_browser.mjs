// Precision checks of the Deadline SquadCalc in a real browser (Chromium through Playwright), against
// oracles computed here from the raw data: the precise heightmap PNG and meta.json the site serves, a
// simulation of the game's own steps (1/49.87 s). Sections are the bug numbers of the 2026-10-29 audit
// (tools/direct_fire/precision_check.mjs holds the same checks on the modules):
//
//     node precision_browser.mjs <site URL>
//
//   B1   Skorpo (non-square): distance and bearing between two world points, map assets on the east edge
//   B2   heights of the page = the game's triangles on the served 16-bit heightmap at world points, on its own grid (the
//        landscape's vertices: origin_m, resolution_m and yaw_deg of meta.json; Skorpo's are 1.2 m apart and turned)
//   SHOT mortar and UB-32 solutions of the page land within 0.5 m in a simulation of the server's frame
//   B10  a session peer's height padding (sent as a string by older clients) is a number; ours is sent as one
//   B11  with the heightmaps blocked, an error toast says so and the target popup says "no height data"
//
// Environment: PLAYWRIGHT_CORE and CHROME as for browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
import { decodePng16 } from "../direct_fire/png16.mjs";

const [base] = process.argv.slice(2);
if (!base) {
    console.error("usage: node precision_browser.mjs <site URL>");
    process.exit(2);
}

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/**
 * Open SquadCalc with window.__App (the main bundle is rewritten in transit, the served files are not)
 * @param {function(import("playwright-core").BrowserContext): Promise<void>} [prepare] - routes, init scripts
 * @param {string} [ready] - page expression to wait for
 */
async function open(prepare = async () => {}, ready = "window.__App?.minimap?.heightmap?.ready") {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
        const response = await route.fetch();
        const body = await response.text();
        const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
        if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
        await route.fulfill({ response, body: patched });
    });
    await prepare(context);
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(ready, null, { timeout: 120000 });
    return { context, page };
}

/** Switch the page to a map by its name and wait for its precise heightmap */
const selectMap = (page, name) => page.evaluate(async (name) => {
    const app = window.__App;
    const option = [...app.MAP_SELECTOR[0].options].find((o) => app.minimap.activeMap.name !== name && o.textContent.toLowerCase().includes(name.toLowerCase()))
        || [...app.MAP_SELECTOR[0].options].find((o) => o.textContent.toLowerCase().includes(name.toLowerCase()));
    if (app.minimap.activeMap.name !== name) app.MAP_SELECTOR.val(option.value).trigger("change");
    await new Promise((resolve) => { const timer = setInterval(() => { if (app.minimap.activeMap.name === name && app.minimap.heightmap.ready) { clearInterval(timer); resolve(); } }, 50); });
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return app.minimap.activeMap.name;
}, name);

// Skorpo's precise heightmap and its grid, as served
const meta = await (await fetch(new URL("/heightmaps/skorpo/meta.json", base))).json();
const png = decodePng16(new Uint8Array(await (await fetch(new URL("/heightmaps/skorpo/heightmap.png", base))).arrayBuffer()));
const { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY } = meta.bounds_m;
/** World meters (X east, Y south) -> Leaflet LatLng of the 256-unit map, from the minimap corners alone */
const toLatLng = (x, y) => ({ lat: -(y - minY) / (maxY - minY) * 256, lng: (x - minX) / (maxX - minX) * 256 });
// Sample (col, row) lies at origin_m + col * resolution_m * (cos yaw, sin yaw) + row * resolution_m * (-sin yaw, cos yaw)
const [originX, originY] = meta.origin_m;
const yaw = meta.yaw_deg * Math.PI / 180;
/** Height of the served grid at world meters, on the game's triangles: each quad splits along the diagonal from (row, col) to (row + 1, col + 1) */
function gridHeight(x, y) {
    const dx = x - originX, dy = y - originY;
    const col = (Math.cos(yaw) * dx + Math.sin(yaw) * dy) / meta.resolution_m, row = (Math.cos(yaw) * dy - Math.sin(yaw) * dx) / meta.resolution_m;
    const c0 = Math.floor(col), r0 = Math.floor(row), fc = col - c0, fr = row - r0;
    const at = (r, c) => png.data[r * png.width + c] * meta.z_step_m;
    return fc >= fr
        ? at(r0, c0) + (at(r0, c0 + 1) - at(r0, c0)) * fc + (at(r0 + 1, c0 + 1) - at(r0, c0 + 1)) * fr
        : at(r0, c0) + (at(r0 + 1, c0) - at(r0, c0)) * fr + (at(r0 + 1, c0 + 1) - at(r0 + 1, c0)) * fc;
}

{
    const { context, page } = await open();
    const map = await selectMap(page, "Skorpo");
    check("B1 map", map === "Skorpo", map);

    // B1: weapon and target at world points; distance and bearing from the world coordinates
    const pairs = [[[0, 0], [300, 2500]], [[-2000, 1500], [-1200, -400]], [[2500, 3000], [1800, 1000]]];
    for (const [from, to] of pairs) {
        const got = await page.evaluate(([w, t]) => {
            const m = window.__App.minimap;
            m.activeWeaponsMarkers.getLayers().forEach((weapon) => weapon.delete());
            m.activeTargetsMarkers.getLayers().forEach((target) => target.delete());
            m.createWeapon(w);
            m.createTarget(t);
            const solution = m.activeTargetsMarkers.getLayers()[0].firingSolution1;
            return { distance: solution.distance, bearing: solution.bearing };
        }, [toLatLng(...from), toLatLng(...to)]);
        const dx = to[0] - from[0], dy = to[1] - from[1];
        const distance = Math.hypot(dx, dy);
        let bearing = Math.atan2(dx, -dy) * 180 / Math.PI;
        if (bearing < 0) bearing += 360;
        check(`B1 Skorpo (${from}) -> (${to}) distance`, Math.abs(got.distance - distance) < 0.01, `${got.distance.toFixed(3)} m, world ${distance.toFixed(3)} m`);
        check(`B1 Skorpo (${from}) -> (${to}) bearing`, Math.abs(got.bearing - bearing) < 0.001, `${got.bearing.toFixed(4)}°, world ${bearing.toFixed(4)}°`);
    }
    const asset = await page.evaluate(async () => {
        const app = window.__App;
        if (!app.minimap.layer) {
            const option = [...app.LAYER_SELECTOR[0].options].find((o) => o.value);
            app.LAYER_SELECTOR.val(option.value).trigger("change");
            await new Promise((resolve) => { const timer = setInterval(() => { if (app.minimap.layer?.convertToLatLng) { clearInterval(timer); resolve(); } }, 100); setTimeout(resolve, 30000); });
        }
        return app.minimap.layer?.convertToLatLng?.(300000, 100000) ?? null;
    });
    const expected = toLatLng(3000, 1000);
    check("B1 Skorpo map asset at world (3000, 1000) m", asset && Math.abs(asset[0] - expected.lat) < 1e-9 && Math.abs(asset[1] - expected.lng) < 1e-9,
        `${JSON.stringify(asset)}, expected [${expected.lat}, ${expected.lng}] (${asset ? ((asset[1] - expected.lng) * (maxX - minX) / 256).toFixed(2) : "?"} m east of it)`);

    // B2: heights at world points, interior and near the south-east corner
    const points = [[0.5, 0.25], [1234.6, -2210.3], [3230.4, 0.6], [0.3, 3569.7], [123.9, 1800.1]];
    const heights = await page.evaluate((lls) => lls.map((ll) => window.__App.minimap.heightmap.getHeight(ll)), points.map(([x, y]) => toLatLng(x, y)));
    points.forEach(([x, y], i) => {
        const expectedHeight = gridHeight(x, y);
        check(`B2 Skorpo height at world (${x}, ${y})`, Math.abs(heights[i] - expectedHeight) < 0.001,
            `${heights[i].toFixed(3)} m, served grid ${expectedHeight.toFixed(3)} m (error ${(heights[i] - expectedHeight).toFixed(3)} m)`);
    });

    // SHOT: the page's solutions, fired in a simulation with the game's gravity and launch points
    const GAME = {
        Mortar: { gravity: 9.80, v0: 110, a: 0, T: 0, pivot: 0.0245, forward: 1.569, up: 0.002, arc: "high" },
        "UB-32": { gravity: 9.80 * 2, v0: 300, a: -50, T: 2, pivot: 1.3075, forward: 1.430, up: 0.251, arc: "low" },
    };
    for (const [name, game] of Object.entries(GAME)) {
        const shots = await page.evaluate(async ({ name, targets }) => {
            const app = window.__App;
            for (const option of app.WEAPON_SELECTOR[0].options) {
                app.WEAPON_SELECTOR.val(option.value).trigger("change");
                if (app.activeWeapon.name === name) break;
            }
            await new Promise((resolve) => setTimeout(resolve, 300));
            const m = app.minimap;
            m.activeWeaponsMarkers.getLayers().forEach((weapon) => weapon.delete());
            m.activeTargetsMarkers.getLayers().forEach((target) => target.delete());
            m.createWeapon(targets[0]);
            return { weapon: app.activeWeapon.name, solutions: targets.slice(1).map((t) => {
                m.createTarget(t);
                const s = m.activeTargetsMarkers.getLayers().at(-1).firingSolution1;
                return { distance: s.distance, heightDiff: s.heightDiff, low: s.elevation.low.rad, high: s.elevation.high.rad };
            }) };
        }, { name, targets: [toLatLng(-500, 500), toLatLng(-500, -100), toLatLng(100, 300), toLatLng(-1300, 400), toLatLng(-500, 1600)] });
        let worst = 0, count = 0;
        for (const s of shots.solutions) {
            const angle = s[game.arc];
            if (!Number.isFinite(angle)) continue;
            worst = Math.max(worst, Math.abs(simulateMiss(game, angle, s.distance, s.heightDiff)));
            count++;
        }
        check(`SHOT ${shots.weapon}: ${count} solutions on Skorpo land in the game-value simulation`, count > 0 && worst < 0.5, `largest miss ${worst.toFixed(3)} m`);
    }
    await context.close();
}

/**
 * Horizontal miss of a shot in a simulation of the game's own steps, written from the server's rule and not from
 * squadBallistics.js: the dedicated server moves a projectile once per frame, 1/49.87 s (UProjectileMovementComponent
 * ::TickComponent; the median of its logged tick rate, deadline-squad/deadline-squadcalc#49), and a strict motor thrusts
 * on ceil(T / dt) - 1 steps. The projectile starts at the muzzle at the elevation, the boost acts along the launch axis,
 * the path between two steps is a straight segment; the result is the crossing of the target height closest to the
 * distance, minus the distance
 */
function simulateMiss(game, angle, distance, height) {
    const dt = 1 / 49.87, cos = Math.cos(angle), sin = Math.sin(angle);
    const boostSteps = game.a ? Math.max(0, Math.ceil(game.T / dt - 1e-9) - 1) : 0;
    let x = game.forward * cos - game.up * sin, y = game.pivot + game.forward * sin + game.up * cos;
    let vx = game.v0 * cos, vy = game.v0 * sin, best = NaN;
    for (let step = 0; step < 6000 && x < distance + 3000 && y > height - 3000; step++) {
        const boost = step < boostSteps ? game.a : 0;
        const ax = boost * cos, ay = boost * sin - game.gravity;
        const nx = x + (vx + 0.5 * ax * dt) * dt, ny = y + (vy + 0.5 * ay * dt) * dt;
        vx += ax * dt; vy += ay * dt;
        if ((y - height) * (ny - height) <= 0 && ny !== y) {
            const crossing = x + (nx - x) * (height - y) / (ny - y);
            if (isNaN(best) || Math.abs(crossing - distance) < Math.abs(best - distance)) best = crossing;
        }
        x = nx; y = ny;
    }
    return best - distance;
}

{
    // B10: a session over a stand-in WebSocket; the page's own sockets elsewhere are left alone
    const { context, page } = await open(async (ctx) => {
        await ctx.addInitScript(() => {
            const Real = window.WebSocket;
            window.__sessionSockets = [];
            window.WebSocket = class extends EventTarget {
                static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
                constructor(url, protocols) {
                    super();
                    if (!/squadcalc\.app/.test(url)) return new Real(url, protocols);
                    this.url = url; this.readyState = 1; this.sent = [];
                    window.__sessionSockets.push(this);
                    setTimeout(() => this.onopen?.({}), 0);
                }
                send(message) { this.sent.push(message); }
                close() { this.readyState = 3; }
            };
        });
    });
    const session = await page.evaluate(async () => {
        const app = window.__App;
        app.initSessionMode("PRECISION01");
        await new Promise((resolve) => setTimeout(resolve, 500));
        const socket = window.__sessionSockets[0];
        if (!socket) return { error: "no session socket" };
        const push = (data) => socket.onmessage({ data: JSON.stringify(data) });
        const m = app.minimap;
        const center = { lat: -m.pixelSize / 2, lng: m.pixelSize / 2 };
        app.userSettings.realMaxRange = true;
        push({ type: "ADDING_WEAPON", uid: "peer-weapon", lat: center.lat, lng: center.lng, heightPadding: "5" });
        const weapon = m.activeWeaponsMarkers.getLayers().find((w) => w.uid === "peer-weapon");
        const added = weapon?.heightPadding;
        push({ type: "MOVING_WEAPON", uid: "peer-weapon", lat: center.lat - 0.5, lng: center.lng, heightPadding: "7.5" });
        const moved = weapon?.heightPadding;
        weapon.updateWeaponMaxRange();
        const ring = weapon.precisionRangeMarker?.getLatLngs()?.flat(3) ?? [];
        const ringFinite = ring.length > 0 && ring.every((ll) => Number.isFinite(ll.lat) && Number.isFinite(ll.lng));
        // Our own change of the padding goes out as a number
        weapon._handleClick({ sourceTarget: weapon });
        const input = document.querySelector(".heightPadding input");
        input.value = "4";
        input.dispatchEvent(new Event("change", { bubbles: true }));
        const sent = socket.sent.map((s) => JSON.parse(s)).filter((s) => s.type === "MOVING_WEAPON").at(-1);
        return { added, moved, ringFinite, ringPoints: ring.length, sent: sent?.heightPadding };
    });
    check("B10 received height padding is a number", session.added === 5 && session.moved === 7.5, JSON.stringify(session));
    check("B10 precise range ring of the peer's weapon is finite", session.ringFinite === true, `${session.ringPoints} points`);
    check("B10 our height padding is sent as a number", session.sent === 4, JSON.stringify(session.sent));
    await context.close();
}

{
    // B11: both heightmaps blocked
    const { context, page } = await open(async (ctx) => {
        await ctx.route(/\/heightmaps\/|heightmap\.png/, (route) => route.abort());
    }, "window.__App?.minimap?.heightmap?.failed");
    await page.waitForTimeout(3000);
    const ui = await page.evaluate(() => {
        const app = window.__App;
        const m = app.minimap;
        const toast = document.querySelector("#toast");
        const toastText = toast ? `${toast.querySelector("h4")?.textContent} ${toast.querySelector("p")?.textContent}` : "";
        const toastVisible = Boolean(toast) && getComputedStyle(toast).display !== "none" && toast.classList.contains("error");
        const center = { lat: -m.pixelSize / 2, lng: m.pixelSize / 2 };
        m.createWeapon(center);
        m.createTarget({ lat: center.lat + 5, lng: center.lng });
        const popup = m.activeTargetsMarkers.getLayers()[0].calcMarker1.getContent().replace(/<[^>]+>/g, " ");
        return { failed: m.heightmap.failed, toastVisible, toastText, popup: popup.replace(/\s+/g, " ").trim() };
    });
    check("B11 heightmap marked failed", ui.failed === true, String(ui.failed));
    check("B11 error toast shown", ui.toastVisible && /No height data/.test(ui.toastText), JSON.stringify(ui.toastText));
    check("B11 target popup says no height data", /no height data/.test(ui.popup), JSON.stringify(ui.popup));
    await context.close();
}

await browser.close();
console.log(failures ? `${failures} precision browser check(s) failed` : "all precision browser checks passed");
process.exit(failures ? 1 : 0);
