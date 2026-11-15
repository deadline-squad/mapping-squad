// Checks SquadCalc's 3D collision layer end to end (src/js/squadVolume.js, its worker volumeWorker.js with the WebAssembly engine,
// volumeTerrain.js) and its users on synthetic scenes with known answers: the files' loading and rejection, the segment queries,
// the heights a target can have, the firing solution's obstacle check and the fire coverage.
//
//     node --import ./register.mjs volume_check.mjs <SquadCalc checkout>
//
// Needs the engine of the checkout (public/engine, `npm run build:engine`). The page's worker is run on the main thread: SquadVolume
// starts it through a stand-in for Worker, the files come from a fetch that serves the synthetic scene.
// Scene (world metres, ground at z = 0): a bridge deck x 10..30, y 0..6, z 5..6; a 0.2 m thick wall at x = 50, y 0..20,
// z 0..3; a window opening in a wall at x = 70 (x 69.9..70.1) with a 1 m wide, 1 m high gap (y 10..11, z 1..2); a hole of the
// landscape around x = 90. Voxels 0.5 m x 0.25 m, landscape vertices every 1 m. Every query is repeated in a page frame that is
// shifted from the world (the heightmap's min corner and lowest level, meta.json bounds_m and z_min_m) to check the frames.
// Exits with 1 on any failure.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { gunzipSync, gzipSync } from "node:zlib";
import { App } from "./stub-app.mjs";
import { writeTerrain, writeVolume } from "./volume_fixture.mjs";

const root = process.argv[2];

let failures = 0;
function expect(label, actual, check) {
    const ok = check(actual);
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${JSON.stringify(actual)}`);
    if (!ok) failures++;
}

// The page the layer runs on: jQuery, the window, the worker (volumeWorker.js, in this thread) and the files it fetches
const PIXEL_SIZE = 1000;
let served = null;
let worker = null;
globalThis.$ = () => ({ on: () => {}, trigger: () => {} });
globalThis.document = {};
globalThis.window = { location: { origin: "http://localhost" } };
globalThis.requestAnimationFrame = (callback) => callback();
globalThis.Worker = class {
    constructor() {
        worker = this;
    }
    postMessage(data) {
        globalThis.onmessage({ data });
    }
    terminate() {}
};
globalThis.postMessage = (message) => queueMicrotask(() => worker?.onmessage?.({ data: message }));
globalThis.fetch = async (url) => {
    const { pathname } = new URL(url);
    if (pathname.endsWith("/meta.json")) return Response.json(served.meta);
    if (pathname.endsWith("/volume.vcol")) return new Response(served.volume);
    if (pathname.endsWith("/terrain.bin")) return new Response(served.terrain);
    if (pathname.endsWith(".wasm")) return new Response(readFileSync(`${root}/public/engine/pkg/squad_engine_bg.wasm`), { headers: { "content-type": "application/wasm" } });
    return new Response(null, { status: 404 });
};
globalThis.onmessage = null;
App.userSettings = { volumeLayer: true };
await import(`${root}/src/js/volumeWorker.js`);
const { default: SquadVolume } = await import(`${root}/src/js/squadVolume.js`);
const { decodeTerrain, terrainHeight } = await import(`${root}/src/js/volumeTerrain.js`);

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const entry = (file, bytes) => ({ file, bytes: bytes.length, sha256: sha256(bytes) });

/**
 * Load a layer of the files in a page frame, like the page does
 * @param {{volume: Buffer, terrain: Buffer, dz: number, zMinVoxels: number}} files
 * @param {{origin: {x: number, y: number}, zMin: number}} frame - world position of the heightmap's min corner and
 *   world Z of its lowest level (meta.json bounds_m min_x, min_y and z_min_m)
 * @param {object} [described=files] - the files meta.json describes (size and sha256), when not the served ones
 * @returns {Promise<{map: object, layer: SquadVolume, warnings: string[]}>}
 */
async function openLayer(files, { origin, zMin }, described = files) {
    served = {
        volume: files.volume,
        terrain: files.terrain,
        meta: {
            bounds_m: { min_x: origin.x, max_x: origin.x + PIXEL_SIZE, min_y: origin.y, max_y: origin.y + PIXEL_SIZE },
            z_min_m: zMin,
            generated: "2026-11-15T00:00:00Z",
            volume: { ...entry("volume.vcol", described.volume), dz: files.dz, z_min_m: files.zMinVoxels, terrain: entry("terrain.bin", described.terrain) },
        },
    };
    const map = { heightmap: { failed: false }, activeMap: { name: "test", mapURL: "/img/maps/test/" }, pixelSize: PIXEL_SIZE, updateTargets: () => {} };
    const layer = new SquadVolume(map);
    map.volume = layer;
    const warnings = [];
    const warn = console.warn;
    console.warn = (...parts) => warnings.push(parts.join(" "));
    try {
        await layer.load();
    } finally {
        console.warn = warn;
    }
    return { map, layer, warnings };
}

const CELL = 0.5, DZ = 0.25, Z_MIN = -10, WIDTH = 240, HEIGHT = 80;
const grid = { minX: 0, minY: 0, cell: CELL, dz: DZ, zMin: Z_MIN, width: WIDTH, height: HEIGHT };

// Occupied voxels of a box (world metres) as columns -> runs; a box covers every voxel it touches
const columns = new Map();
function addBox([x0, y0, z0], [x1, y1, z1]) {
    for (let col = Math.floor(x0 / CELL); col < Math.ceil(x1 / CELL); col++) {
        for (let row = Math.floor(y0 / CELL); row < Math.ceil(y1 / CELL); row++) {
            const id = row * WIDTH + col;
            if (!columns.has(id)) columns.set(id, []);
            columns.get(id).push([Math.floor((z0 - Z_MIN) / DZ), Math.ceil((z1 - Z_MIN) / DZ)]);
        }
    }
}
addBox([10, 0, 5], [30, 6, 6]);
addBox([49.9, 0, 0.001], [50.1, 20, 3]);
// The window wall: below, beside and above the opening
addBox([69.9, 0, 0.001], [70.1, 10, 3]);
addBox([69.9, 11, 0.001], [70.1, 20, 3]);
addBox([69.9, 10, 0.001], [70.1, 11, 1]);
addBox([69.9, 10, 2], [70.1, 11, 3]);

const terrainGrid = { minX: 0, minY: 0, cell: 1, zMin: -1, step: 0.05, width: 200, height: 60 };
const holeVertex = 15 * terrainGrid.width + 90;
const sceneFiles = {
    volume: writeVolume(grid, columns),
    terrain: writeTerrain(terrainGrid, () => 0, [holeVertex]),
    dz: DZ,
    zMinVoxels: Z_MIN,
};

// The landscape file
const terrain = decodeTerrain(gunzipSync(sceneFiles.terrain));
expect("TER2: header, levels and holes", [terrain.width, terrain.step, terrain.levels[0], terrain.holes[holeVertex], terrain.holes.reduce((sum, hole) => sum + hole, 0)], ([w, s, l, h, count]) => w === 200 && Math.abs(s - 0.05) < 1e-6 && l === 21 && h === 1 && count === 1);
expect("TER2: a VCOL1 file rejected", (() => { try { decodeTerrain(gunzipSync(sceneFiles.volume)); return "accepted"; } catch (error) { return String(error); } })(), (message) => message.includes("TER2"));
// Landscape interpolation matches SquadHeightmap.getHeight (triangles split on the (row, col) -> (row + 1, col + 1) diagonal)
{
    const slope = decodeTerrain(gunzipSync(writeTerrain({ ...terrainGrid, width: 4, height: 4 }, (col, row) => (col === 1 && row === 1 ? 2 : 0))));
    // Quad (row 0, col 0) corners: (0,0)=0 (0,1)=0 (1,0)=0 (1,1)=2. Lower triangle (col >= row): 2 * row... at (col .75, row .25): z = 0 + 0 + (2 - 0) * .25 = .5
    expect("landscape: lower triangle of a quad", terrainHeight(slope, 0.75, 0.25), (z) => Math.abs(z - 0.5) < 0.03);
    // upper triangle (col < row), at (col .25, row .75): corner + (below - corner) * .75 + (diagonal - below) * .25 = .5
    expect("landscape: upper triangle of a quad", terrainHeight(slope, 0.25, 0.75), (z) => Math.abs(z - 0.5) < 0.03);
    expect("landscape: a landscape hole and the outside of the grid have no height", [terrainHeight(terrain, 90.5, 15.5), terrainHeight(terrain, 1000, 1000)], ([hole, outside]) => Number.isNaN(hole) && Number.isNaN(outside));
}

// Loading: the files are checked against meta.json and decoded by the worker; a layer that cannot load leaves the heightmap
{
    const corruptVolume = Buffer.from(sceneFiles.volume);
    corruptVolume[corruptVolume.length - 6] ^= 0xff;
    const rejected = async (label, files, pattern) => {
        const { layer, warnings } = await openLayer(files, { origin: { x: 0, y: 0 }, zMin: 0 });
        expect(`load: ${label} rejected`, [layer.state, layer.ready, warnings.join(" ")], ([state, ready, warning]) => state === "unavailable" && ready === false && pattern.test(warning));
    };
    await rejected("VCOL1: garbage", { ...sceneFiles, volume: Buffer.from("not gzip") }, /./);
    await rejected("VCOL1: a TER2 file", { ...sceneFiles, volume: sceneFiles.terrain }, /./);
    await rejected("VCOL1: truncated file", { ...sceneFiles, volume: gzipSync(gunzipSync(sceneFiles.volume).subarray(0, 60)) }, /./);
    await rejected("VCOL1: corrupt gzip", { ...sceneFiles, volume: corruptVolume }, /./);
    await rejected("TER2: a VCOL1 file", { ...sceneFiles, terrain: sceneFiles.volume }, /TER2/);
    await rejected("TER2: truncated file", { ...sceneFiles, terrain: gzipSync(gunzipSync(sceneFiles.terrain).subarray(0, 100)) }, /TER2/);
    // meta.json describes the good scene: serve other bytes than it describes
    const mismatch = await openLayer({ ...sceneFiles, volume: corruptVolume }, { origin: { x: 0, y: 0 }, zMin: 0 }, sceneFiles);
    expect("load: bytes that do not match meta.json rejected", [mismatch.layer.state, mismatch.warnings.join(" ")], ([state, warning]) => state === "unavailable" && /checksum mismatch/.test(warning));
    const good = await openLayer(sceneFiles, { origin: { x: 0, y: 0 }, zMin: 0 });
    expect("load: the scene loads", [good.layer.state, good.layer.ready, good.warnings], ([state, ready, warnings]) => state === "ready" && ready === true && warnings.length === 0);
}

// Page frames: the world itself, and a heightmap whose minimum corner is at (-7, 3) world metres and whose lowest level is the world z = -12.5
const frames = [["world frame", { x: 0, y: 0 }, 0], ["shifted frame", { x: -7, y: 3 }, -12.5]];

// Firing solution: a direct-fire weapon's low trajectory through a doorway of a 10 m high wall, and under a bridge deck
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);
const direct = WEAPONS.filter((weapon) => weapon.type === "directFire").reduce((best, weapon) => (weapon.shells[0].velocity > best.shells[0].velocity ? weapon : best)).name;
function load(name) {
    const w = WEAPONS.find((weapon) => weapon.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    weapon.velocity = w.shells[0].velocity;
    weapon.moa = w.shells[0].moa;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}
const settled = async (layer) => {
    while (layer.pending.size) await new Promise((resolve) => setTimeout(resolve, 1));
};

for (const [name, origin, zMin] of frames) {
    const { map, layer } = await openLayer(sceneFiles, { origin, zMin });
    expect(`${name}: loaded`, [layer.state, layer.ready, layer.zMin], ([state, ready, layerZMin]) => state === "ready" && ready === true && layerZMin === zMin);

    // Page position (the heightmap's frame: 1 unit = 1 m, lng = x east of the min corner, lat = -y south of it) of a world point
    const pageLatLng = (x, y) => ({ lat: -(y - origin.y), lng: x - origin.x });
    // Query in world coordinates, translated into the page frame and from it into the files' frame like the firing solution does
    const query = async (a, b) => {
        const points = [a, b].flatMap(([x, y, z]) => {
            const world = layer.toWorld(pageLatLng(x, y));
            return [world.x, world.y, z - zMin + layer.zMin];
        });
        const [hit] = await layer.trace([Float64Array.from(points)]);
        return hit;
    };
    const clear = async (label, a, b) => expect(`${name}: ${label}: clear`, await query(a, b), (hit) => hit === null);
    const blocked = async (label, a, b, check = () => true) => expect(`${name}: ${label}: blocked`, await query(a, b), (hit) => hit !== null && check(hit));

    await clear("under the bridge deck", [5, 3, 1.6], [35, 3, 1.6]);
    await blocked("through the deck", [20, 3, 1.6], [20, 3, 9], (h) => h.index === 1 && Math.abs(h.z - 5) < 0.3 && Math.abs(h.t - (5 - 1.6) / 7.4) < 0.05);
    await clear("over the deck", [5, 3, 8], [35, 3, 8]);
    await blocked("through the wall (thinner than a heightmap cell)", [40, 10.3, 1.6], [60, 10.3, 1.6], (h) => h.t > 0.45 && h.t < 0.55 && Math.abs(h.z - 1.6) < 1e-6);
    await clear("over the wall", [40, 10.3, 4], [60, 10.3, 4]);
    await clear("through the window opening", [60, 10.5, 1.5], [80, 10.5, 1.5]);
    await blocked("through the wall beside the window", [60, 12, 1.5], [80, 12, 1.5]);
    await blocked("through the wall under the window", [60, 10.5, 0.5], [80, 10.5, 0.5]);
    await blocked("into the ground", [5, 30, 1], [5, 30, -1], (h) => h.index === 1 && h.t === 1 && Math.abs(h.z) < 0.05);
    await clear("along the ground", [5, 30, 0.2], [100, 30, 0.2]);
    await clear("below the landscape inside a hole", [90.2, 15.5, -1], [90.8, 15.5, -1]);
    await blocked("below the landscape beside the hole", [90.2, 17.5, -1], [90.8, 17.5, -1]);
    await clear("outside the grid", [1000, 1000, 5], [1010, 1000, 5]);

    // The heights a target can have at a point (page heights: the world's minus the heightmap's lowest level)
    const heights = async (x, y) => layer.heightsAt(pageLatLng(x, y));
    const choice = (found, kind) => found?.choices.find((candidate) => candidate.kind === kind);
    const near = (found, kind, z) => Math.abs((choice(found, kind)?.height ?? NaN) - (z - zMin)) < 0.3;
    expect(`${name}: landscape height`, await heights(5.5, 5.5), (found) => Math.abs(found.landscape - -zMin) < 0.03 && found.choices.length === 0);
    expect(`${name}: heights under and over the bridge deck`, await heights(20, 3), (found) => near(found, "ceiling", 5) && near(found, "roof", 6));
    expect(`${name}: heights at the top of the wall`, await heights(50, 10), (found) => found.choices.length === 1 && near(found, "roof", 3));
    expect(`${name}: the opening of the window wall is a window`, await heights(70, 10.5), (found) => near(found, "window", 1.5));
    expect(`${name}: no landscape, no heights`, await heights(1000, 1000), (found) => found === null);

    // Firing solution: the page's heightmap fuses the walls with the landscape (10 m high at x = 50 and x = 70)
    const heightmap = {
        resolution: 1,
        getHeight: ({ lng }) => {
            const x = lng + origin.x;
            return -zMin + ((x > 49 && x < 51) || (x > 69 && x < 71) ? 10 : 0);
        },
    };
    map.heightmap = heightmap;
    map.mapToGameScale = 1;
    map.mapToGameScaleY = 1;
    map.toMeters = (from, to) => ({ east: to.lng - from.lng, north: to.lat - from.lat });
    // The layer answers for the heightmap that was on the map when it loaded
    layer.heightmap = heightmap;
    // The layer answers a question the second time it is asked: the first one starts the worker's trace
    async function solve(weaponName, from, to, { volumeOn = true } = {}) {
        App.activeWeapon = load(weaponName);
        map.volume = volumeOn ? layer : null;
        const solution = () => new SquadFiringSolution(pageLatLng(...from), pageLatLng(...to), map, 0);
        solution();
        await settled(layer);
        return solution();
    }
    const through = await solve(direct, [55, 10.5], [110, 10.5]);
    expect(`${name}: ${direct}: through the window opening 55 -> 110 m: clear (3D layer)`, [through.obstacle.low, layer.answers.size], ([o, answers]) => o === null && answers > 0);
    const heightmapOnly = await solve(direct, [55, 10.5], [110, 10.5], { volumeOn: false });
    expect(`${name}: ${direct}: same shot on the heightmap: blocked by the 10 m wall`, heightmapOnly.obstacle.low, (o) => o !== null && o.distance >= 14 && o.distance < 16);
    const wall = await solve(direct, [55, 15], [110, 15]);
    expect(`${name}: ${direct}: through the wall beside the window: blocked at 15 m, below the wall top (3 m)`, wall.obstacle.low, (o) => o !== null && o.distance >= 14.4 && o.distance < 15.6 && o.height > 0 && o.height < 3);
    expect(`${name}: ${direct}: thin wall found by a 1 m chord (x = 50 +- 0.1)`, (await solve(direct, [30, 10], [100, 10])).obstacle.low, (o) => o !== null && o.distance >= 19 && o.distance < 21);
    expect(`${name}: ${direct}: flat ground 60 m: clear`, (await solve(direct, [95, 40], [155, 40])).obstacle.low, (o) => o === null);
    expect(`${name}: Mortar 75 m over the 3 m wall: high lob clear`, (await solve("Mortar", [35, 5], [105, 25])).obstacle.high, (o) => o === null);
    layer.dispose();
}

// Coverage: the ray sampler with the 3D layer sees a wall that the heightmap profile would not, and not a gap
const { computeCoverageRays, COVERAGE } = await import(`${root}/src/js/squadCoverage.js`);
{
    const cols = new Map();
    for (let col = 1400; col < 1420; col++) for (let row = 0; row < 1000; row++) cols.set(row * 2000 + col, [[Math.floor((0 + 10) / DZ), Math.ceil((20 + 10) / DZ)]]);
    const bigFiles = {
        volume: writeVolume({ minX: -500, minY: -250, cell: CELL, dz: DZ, zMin: Z_MIN, width: 2000, height: 1000 }, cols),
        terrain: writeTerrain({ minX: -500, minY: -250, cell: 1, zMin: -1, step: 0.05, width: 1000, height: 500 }, () => 0),
        dz: DZ,
        zMinVoxels: Z_MIN,
    };
    const { layer } = await openLayer(bigFiles, { origin: { x: -500, y: -250 }, zMin: 0 });
    // Weapon at the world's (0, 0): the wall stands 200..210 m east of it, 20 m high
    const origin = { lat: -250, lng: 500 };
    const fromMeters = (from, east, north) => ({ lat: from.lat + north, lng: from.lng + east });
    const weapon = load(direct);
    App.activeWeapon = weapon;
    const shot = weapon.getShot(App.gravity * weapon.gravityScale, 1.5);
    const common = { ground: 0, shot, range: 500, cell: 5, rays: 36, elevationLimits: weapon.minElevation, holdElevation: weapon.holdElevation, angleOffset: weapon.angleOffset || 0, lifespan: weapon.projectileLifespan, lowOnly: true };
    // The landscape file covers x -500.5..499.5 and y -250.5..249.5 of the world (half a cell beyond its vertices), and the layer
    // marks the targets beyond it OUT; north is -y
    const inside = (e, n) => e >= -500.5 && e <= 499.5 && -n >= -250.5 && -n <= 249.5;
    const flatOnly = computeCoverageRays({ ...common, heightAt: () => 0, inside });
    const heightmapWall = computeCoverageRays({ ...common, heightAt: (e) => (e >= 200 && e <= 210 ? 20 : 0), inside });
    const withVolume = { values: await layer.coverage(common, origin, fromMeters, () => true), targets: flatOnly.targets };
    const stride = withVolume.targets + 1;
    expect("coverage: the worker returns every cell of every ray", withVolume.values?.length, (length) => length === 36 * stride);
    const cell = (result, ray, distance) => result.values[ray * stride + distance / 5];
    expect("coverage: east ray, target 150 m, 3D layer: LOW", cell(withVolume, 0, 150), (v) => v === COVERAGE.LOW || v === COVERAGE.OUT);
    expect("coverage: east ray, target 300 m behind the wall, 3D layer: the same as the heightmap wall", cell(withVolume, 0, 300), (v) => v === cell(heightmapWall, 0, 300) && v !== cell(flatOnly, 0, 300));
    // The wall is 10 m wide and the profile is sampled every few meters: cells may differ only where a target is next to it
    const far = [];
    for (let ray = 0; ray < 36; ray++) {
        for (let j = 1; j < stride; j++) {
            const distance = j * 5;
            if (withVolume.values[ray * stride + j] !== heightmapWall.values[ray * stride + j] && !(Math.cos((2 * Math.PI * ray) / 36) > 0 && distance > 190 / Math.cos((2 * Math.PI * ray) / 36) && distance < 225 / Math.cos((2 * Math.PI * ray) / 36))) far.push([ray, distance]);
        }
    }
    expect("coverage: cells that differ from the equivalent heightmap wall, away from the wall", far.length, (count) => count === 0);
    expect("coverage: west ray unaffected (no wall) equals flat ground", [cell(withVolume, 18, 300), cell(flatOnly, 18, 300)], ([a, b]) => a === b);
    layer.dispose();
}

if (failures) {
    console.log(`${failures} failure(s)`);
    process.exit(1);
}
console.log("all volume checks passed");
