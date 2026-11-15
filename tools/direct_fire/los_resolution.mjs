// Line of sight and fire obstacles at different heightmap steps, with the real SquadCalc code.
//
//     node --import ./register.mjs los_resolution.mjs <SquadCalc checkout> <grid dir> [pairs] [seed]
//
// <grid dir> is written by tools/heightmaps/py/compare_resolution.py: grid_<step>.u16/.json for 1, 0.5 and
// 0.25 m of one window (terrain + static meshes). Each grid is loaded into a SquadHeightmap (read by the checkout's
// engine core: `npm run build:engine` first), weapons and
// targets are drawn at random on the window's open ground 80-400 m apart, and SquadFiringSolution.getObstacle
// (the first point where the trajectory passes under the heightmap) decides for the fastest direct-fire weapon
// (low trajectory) and the mortar (high lob). The 0.25 m grid is the reference; for each coarser grid the
// script prints how often "blocked or clear" differs, how far the first obstacle moves, and how often
// the elevation to the target differs by more than 1 mil (the target's own height).
import { readFileSync } from "node:fs";
import { App } from "./stub-app.mjs";
import { blankHeightmap } from "./stub-heightmap.mjs";

const [root, dir, pairsArg = "4000", seedArg = "1"] = process.argv.slice(2);
if (!root || !dir) {
    console.error("usage: node --import ./register.mjs los_resolution.mjs <SquadCalc checkout> <grid dir> [pairs] [seed]");
    process.exit(2);
}
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);
const { default: SquadHeightmap } = await import(`${root}/src/js/squadHeightmaps.js`);
globalThis.document ??= {};
globalThis.$ ??= () => ({ trigger() {}, show() {}, hide() {}, text() {}, html() {}, attr() {} });
console.debug = () => {};

function load(name) {
    const w = WEAPONS.find((weapon) => weapon.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    weapon.velocity = w.shells[0].velocity;
    weapon.moa = w.shells[0].moa;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}

const fastest = WEAPONS.filter((weapon) => weapon.type === "directFire")
    .reduce((best, weapon) => (weapon.shells[0].velocity > best.shells[0].velocity ? weapon : best)).name;
const cases = [[fastest, true], ["Mortar", false]];

/** A SquadHeightmap over grid_<step>, in a map of 1 unit = 1 m (lat = -south, lng = east from the window's corner) */
async function heightmapOf(step) {
    const meta = JSON.parse(readFileSync(`${dir}/grid_${step}.json`));
    const bytes = readFileSync(`${dir}/grid_${step}.u16`);
    const levels = new Uint16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2).slice();
    const size = (meta.width - 1) * meta.step;
    const heightmap = blankHeightmap(SquadHeightmap, { pixelSize: size });
    await heightmap.receive({ levels, width: meta.width, height: meta.height, step: meta.z_step, url: "synthetic",
        lattice: { originX: 0, originY: 0, resolution: Number(step), yawDeg: 0 }, bounds: { min_x: 0, max_x: size, min_y: 0, max_y: size } });
    // receive() ignores z_min: all grids share it, so it cancels in every height difference
    return { heightmap, size, step };
}

const grids = Object.fromEntries(await Promise.all(["1.0", "0.5", "0.25"].map(async (step) => [step, await heightmapOf(step)])));
const size = grids["0.25"].size;
const toMeters = (origin, ll) => ({ east: ll.lng - origin.lng, north: ll.lat - origin.lat });

let seed = Number(seedArg);
const random = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);

function solve(heightmap, name, from, to) {
    App.activeWeapon = load(name);
    const map = { mapToGameScale: 1, mapToGameScaleY: 1, toMeters, heightmap };
    return new SquadFiringSolution(from, to, map, 0);
}

const reference = grids["0.25"].heightmap;
const pairs = [];
while (pairs.length < Number(pairsArg)) {
    const from = { lat: -(30 + random() * (size - 60)), lng: 30 + random() * (size - 60) };
    const bearing = random() * 2 * Math.PI;
    const distance = 80 + random() * 320;
    const to = { lat: from.lat - Math.cos(bearing) * distance, lng: from.lng + Math.sin(bearing) * distance };
    if (to.lat > -10 || to.lat < -(size - 10) || to.lng < 10 || to.lng > size - 10) continue;
    // Open ground at both ends: where the 0.25 m grid has no object within 2 m, so the endpoint's own cover is not the difference
    const flat = (p) => [[0, 0], [2, 0], [-2, 0], [0, 2], [0, -2]].every(([a, b]) => Math.abs(reference.getHeight({ lat: p.lat + a, lng: p.lng + b }) - reference.getHeight(p)) < 0.3);
    if (flat(from) && flat(to)) pairs.push([from, to]);
}

for (const [name, low] of cases) {
    const truth = pairs.map(([from, to]) => solve(reference, name, from, to).getObstacle(low));
    console.log(`${name} (${low ? "low" : "high"} trajectory), ${pairs.length} pairs 80-400 m on open ground; ${truth.filter(Boolean).length} blocked at 0.25 m`);
    for (const step of ["1.0", "0.5"]) {
        let flipped = 0, blockedMore = 0, moved = 0, movedSum = 0, elevation = 0;
        pairs.forEach(([from, to], i) => {
            const solution = solve(grids[step].heightmap, name, from, to);
            const obstacle = solution.getObstacle(low);
            const t = truth[i];
            if (Boolean(obstacle) !== Boolean(t)) {
                flipped++;
                if (obstacle) blockedMore++;
            } else if (obstacle && Math.abs(obstacle.distance - t.distance) > 1) {
                moved++;
                movedSum += Math.abs(obstacle.distance - t.distance);
            }
            const ref = solve(reference, name, from, to);
            const key = low ? "low" : "high";
            if (Math.abs(solution.elevation[key].mil - ref.elevation[key].mil) > 1) elevation++;
        });
        console.log(`  step ${step} m: blocked-or-clear differs in ${flipped} pairs (${(100 * flipped / pairs.length).toFixed(2)} %, ${blockedMore} falsely blocked, ${flipped - blockedMore} falsely clear); `
            + `first obstacle moves > 1 m in ${moved} more (mean ${(moved ? movedSum / moved : 0).toFixed(1)} m); elevation differs > 1 mil in ${elevation}`);
    }
}
