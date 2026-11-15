// Checks SquadCalc's 3D collision layer (src/js/squadVolume.js) and its users on synthetic scenes with known answers:
// the decoders of the VCOL1 / TER1 files, the segment queries, the firing solution's obstacle check and the fire coverage.
//
//     node --import ./register.mjs volume_check.mjs <SquadCalc checkout>
//
// Scene (world metres, ground at z = 0): a bridge deck x 10..30, y 0..6, z 5..6; a 0.2 m thick wall at x = 50, y 0..20,
// z 0..3; a window opening in a wall at x = 70 (x 69.9..70.1) with a 1 m wide, 1 m high gap (y 10..11, z 1..2); a hole of the
// landscape around x = 90. Voxels 0.5 m x 0.25 m, landscape vertices every 1 m. Every query is repeated in a page frame that is
// shifted from the world (origin and z offset of the heightmap) to check the frames. Exits with 1 on any failure.
import { App } from "./stub-app.mjs";
import { writeTerrain, writeVolume } from "./volume_fixture.mjs";

const root = process.argv[2];
const { decodeTerrain, decodeVolume, SquadVolume } = await import(`${root}/src/js/squadVolume.js`);

let failures = 0;
function expect(label, actual, check) {
    const ok = check(actual);
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${JSON.stringify(actual)}`);
    if (!ok) failures++;
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

const terrainGrid = { minX: 0, minY: 0, cell: 1, zMin: -1, step: 0.05, width: 120, height: 40 };
const holeVertex = 15 * terrainGrid.width + 90;
const volumeFile = writeVolume(grid, columns);
const terrainFile = writeTerrain(terrainGrid, () => 0, [holeVertex]);

const volume = await decodeVolume(volumeFile);
const terrain = await decodeTerrain(terrainFile);
expect("VCOL1: header", volume.header, (h) => h.cell === 0.5 && h.dz === 0.25 && h.zMin === -10 && h.width === WIDTH && h.height === HEIGHT);
expect("VCOL1: columns and runs", [volume.ids.length, volume.runs.length / 2], ([c, r]) => c === columns.size && r >= c);
expect("TER1: header, levels and holes", [terrain.header.width, terrain.header.step, terrain.levels[0], terrain.holes[0]], ([w, s, l, h]) => w === 120 && Math.abs(s - 0.05) < 1e-6 && l === 21 && h === holeVertex);
await decodeVolume(Buffer.from("not gzip")).then(() => expect("VCOL1: garbage rejected", "accepted", () => false), () => expect("VCOL1: garbage rejected", "rejected", () => true));
await decodeVolume(terrainFile).then(() => expect("VCOL1: a TER1 file rejected", "accepted", () => false), (e) => expect("VCOL1: a TER1 file rejected", String(e), (m) => m.includes("VCOL1")));
await decodeTerrain(volumeFile).then(() => expect("TER1: a VCOL1 file rejected", "accepted", () => false), (e) => expect("TER1: a VCOL1 file rejected", String(e), (m) => m.includes("TER1")));
const { gunzipSync, gzipSync } = await import("node:zlib");
await decodeVolume(gzipSync(gunzipSync(volumeFile).subarray(0, 60))).then(() => expect("VCOL1: truncated file rejected", "accepted", () => false), () => expect("VCOL1: truncated file rejected", "rejected", () => true));
const corrupt = Buffer.from(volumeFile);
corrupt[corrupt.length - 6] ^= 0xff;
await decodeVolume(corrupt).then(() => expect("VCOL1: corrupt gzip rejected", "accepted", () => false), () => expect("VCOL1: corrupt gzip rejected", "rejected", () => true));

// Page frames: the world itself, and a heightmap whose minimum corner is at (-7, 3) world metres and whose 0 is the world z = -12.5
for (const [name, origin, zOffset] of [["world frame", { x: 0, y: 0 }, 0], ["shifted frame", { x: -7, y: 3 }, -12.5]]) {
    const layer = new SquadVolume({ volume, terrain, origin, zOffset });
    // Query in world coordinates, translated into the page frame
    const query = (a, b) => {
        const hit = layer.firstBlocker(a[0] - origin.x, a[1] - origin.y, a[2] - zOffset, b[0] - origin.x, b[1] - origin.y, b[2] - zOffset);
        return hit && { t: hit.t, top: hit.top + zOffset };
    };
    const clear = (label, a, b) => expect(`${name}: ${label}: clear`, query(a, b), (hit) => hit === null);
    const blocked = (label, a, b, check = () => true) => expect(`${name}: ${label}: blocked`, query(a, b), (hit) => hit !== null && check(hit));

    clear("under the bridge deck", [5, 3, 1.6], [35, 3, 1.6]);
    blocked("through the deck", [20, 3, 1.6], [20, 3, 9], (h) => Math.abs(h.top - 6) < 0.3 && Math.abs(h.t - (5 - 1.6) / 7.4) < 0.05);
    clear("over the deck", [5, 3, 8], [35, 3, 8]);
    blocked("through the wall (thinner than a heightmap cell)", [40, 10.3, 1.6], [60, 10.3, 1.6], (h) => h.t > 0.45 && h.t < 0.55 && Math.abs(h.top - 3) < 0.3);
    clear("over the wall", [40, 10.3, 4], [60, 10.3, 4]);
    clear("through the window opening", [60, 10.5, 1.5], [80, 10.5, 1.5]);
    blocked("through the wall beside the window", [60, 12, 1.5], [80, 12, 1.5]);
    blocked("through the wall under the window", [60, 10.5, 0.5], [80, 10.5, 0.5]);
    blocked("into the ground", [5, 30, 1], [5, 30, -1], (h) => h.top === 0 || Math.abs(h.top) < 0.05);
    clear("along the ground", [5, 30, 0.2], [100, 30, 0.2]);
    clear("below the landscape inside a hole", [89.7, 15, -1], [90.3, 15, -1]);
    blocked("below the landscape beside the hole", [89.7, 17, -1], [90.3, 17, -1]);
    clear("outside the grid", [1000, 1000, 5], [1010, 1000, 5]);
    expect(`${name}: blocked() agrees with firstBlocker()`, [layer.blocked(20 - origin.x, 3 - origin.y, 1.6 - zOffset, 20 - origin.x, 3 - origin.y, 9 - zOffset), layer.blocked(5 - origin.x, 3 - origin.y, 1.6 - zOffset, 35 - origin.x, 3 - origin.y, 1.6 - zOffset)], (r) => r[0] === true && r[1] === false);
    expect(`${name}: landscape height`, [layer.groundAt(5.5 - origin.x, 5.5 - origin.y), layer.groundAt(-100, -100)], ([ground, outside]) => Math.abs(ground - -zOffset) < 0.03 && outside === -Infinity);
    expect(`${name}: solid intervals of a column`, (() => { const out = []; layer.solidsAt(20 - origin.x, 3 - origin.y, out); return out; })(), (out) => out.length === 2 && Math.abs(out[0] - (5 - zOffset)) < 0.3 && Math.abs(out[1] - (6 - zOffset)) < 0.3);
    expect(`${name}: hull along a stretch`, (() => { const found = layer.hullAlong(48 - origin.x, 10 - origin.y, 52 - origin.x, 10 - origin.y); return [found, layer.hullLow + zOffset, layer.hullHigh + zOffset]; })(), ([found, low, high]) => found && low < 0.3 && Math.abs(high - 3) < 0.3);
    expect(`${name}: hull of empty ground`, layer.hullAlong(100 - origin.x, 50 - origin.y, 104 - origin.x, 50 - origin.y), (found) => found === false);
}

// Landscape interpolation matches SquadHeightmap.getHeight (triangles split on the (row, col) -> (row + 1, col + 1) diagonal)
{
    const slope = writeTerrain({ ...terrainGrid, width: 4, height: 4 }, (col, row) => (col === 1 && row === 1 ? 2 : 0));
    const layer = new SquadVolume({ volume, terrain: await decodeTerrain(slope), origin: { x: 0, y: 0 }, zOffset: 0 });
    // Quad (row 0, col 0) corners: (0,0)=0 (0,1)=0 (1,0)=0 (1,1)=2. Lower triangle (col >= row): 2 * row... at (col .75, row .25): z = 0 + 0 + (2 - 0) * .25 = .5
    expect("landscape: lower triangle of a quad", layer.groundAt(0.75, 0.25), (z) => Math.abs(z - 0.5) < 0.03);
    // upper triangle (col < row), at (col .25, row .75): corner + (below - corner) * .75 + (diagonal - below) * .25 = .5
    expect("landscape: upper triangle of a quad", layer.groundAt(0.25, 0.75), (z) => Math.abs(z - 0.5) < 0.03);
}

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
const toMeters = (origin, ll) => ({ east: ll.lng - origin.lng, north: ll.lat - origin.lat });
const layer = new SquadVolume({ volume, terrain, origin: { x: 0, y: 0 }, zOffset: 0 });
// Page map units: 1 unit = 1 m; lng = x, lat = -y (the row of the heightmap grows southwards)
function solve(weaponName, from, to, { volumeOn = true, heightmapTop = 0 } = {}) {
    App.activeWeapon = load(weaponName);
    const heightmap = {
        resolution: 1, getHeight: ({ lng }) => (lng > 49 && lng < 51 ? 10 : lng > 69 && lng < 71 ? 10 : heightmapTop),
        activeVolume: volumeOn ? layer : null, gridMeters: ({ lat, lng }) => ({ x: lng, y: -lat }),
    };
    const map = { mapToGameScale: 1, mapToGameScaleY: 1, toMeters, heightmap };
    return new SquadFiringSolution({ lat: -from[1], lng: from[0] }, { lat: -to[1], lng: to[0] }, map, 0);
}
const through = solve(direct, [55, 10.5], [110, 10.5]);
expect(`${direct}: usesVolume`, through.usesVolume, (v) => v === true);
expect(`${direct}: through the window opening 55 -> 110 m: clear (3D layer)`, through.obstacle.low, (o) => o === null);
const heightmapOnly = solve(direct, [55, 10.5], [110, 10.5], { volumeOn: false });
expect(`${direct}: same shot on the heightmap: blocked by the 10 m wall`, [heightmapOnly.usesVolume, heightmapOnly.obstacle.low], ([used, o]) => used === false && o !== null && o.distance >= 14 && o.distance < 16);
const wall = solve(direct, [55, 15], [110, 15]);
expect(`${direct}: through the wall beside the window: blocked at 15 m, wall top 3 m`, wall.obstacle.low, (o) => o !== null && o.distance >= 14.4 && o.distance < 15.6 && Math.abs(o.height - (3 - wall.weaponHeight)) < 0.3);
expect(`${direct}: thin wall found by a 1 m chord (x = 50 +- 0.1)`, solve(direct, [30, 10], [100, 10]).obstacle.low, (o) => o !== null && o.distance >= 19 && o.distance < 21);
expect(`${direct}: flat ground 60 m: clear`, solve(direct, [95, 40], [155, 40]).obstacle.low, (o) => o === null);
const mortar = solve("Mortar", [35, 5], [105, 25]);
expect("Mortar 75 m over the 3 m wall: high lob clear", mortar.obstacle.high, (o) => o === null);

// Coverage: the ray sampler with the 3D layer sees a wall that the page frame's heightmap profile would not, and not a gap
const { computeCoverageRays, COVERAGE } = await import(`${root}/src/js/squadCoverage.js`);
{
    const wide = 400;
    const cols = new Map();
    for (let col = 1400; col < 1420; col++) for (let row = 0; row < 1000; row++) cols.set(row * 2000 + col, [[Math.floor((0 + 10) / DZ), Math.ceil((20 + 10) / DZ)]]);
    const big = await decodeVolume(writeVolume({ minX: -500, minY: -250, cell: CELL, dz: DZ, zMin: Z_MIN, width: 2000, height: 1000 }, cols));
    const flat = await decodeTerrain(writeTerrain({ minX: -500, minY: -250, cell: 1, zMin: -1, step: 0.05, width: 1000, height: 500 }, () => 0));
    const bigLayer = new SquadVolume({ volume: big, terrain: flat, origin: { x: -500, y: -250 }, zOffset: 0 });
    // Weapon at the grid point (500, 250): the wall stands 200..210 m east of it, 20 m high
    const weapon = load(direct);
    App.activeWeapon = weapon;
    const shot = weapon.getShot(App.gravity * weapon.gravityScale, 1.5);
    const common = { ground: 0, shot, range: 500, cell: 5, rays: 36, elevationLimits: weapon.minElevation, holdElevation: weapon.holdElevation, angleOffset: weapon.angleOffset || 0, lifespan: weapon.projectileLifespan, lowOnly: true };
    const flatOnly = computeCoverageRays({ ...common, heightAt: () => 0 });
    const withVolume = computeCoverageRays({
        ...common, heightAt: () => 0,
        groundAt: (e, n) => bigLayer.groundAt(500 + e, 250 + n),
        hullAlong: (e0, n0, e1, n1) => (bigLayer.hullAlong(500 + e0, 250 + n0, 500 + e1, 250 + n1) ? { low: bigLayer.hullLow, high: bigLayer.hullHigh } : null),
    });
    const heightmapWall = computeCoverageRays({ ...common, heightAt: (e) => (e >= 200 && e <= 210 ? 20 : 0) });
    const stride = withVolume.targets + 1;
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
}

if (failures) {
    console.log(`${failures} failure(s)`);
    process.exit(1);
}
console.log("all volume checks passed");
