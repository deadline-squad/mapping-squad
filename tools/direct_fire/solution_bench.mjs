// Time SquadFiringSolution on a real precise heightmap and compare it with a reference checkout.
//
//     node --import ./register.mjs solution_bench.mjs <SquadCalc checkout> [<reference checkout>] [--map <name>]
//
// For each weapon, 40 targets between 40 m and the weapon's range from a weapon placed on the map: prints the
// microseconds per solution and, with a reference checkout, how many solutions differ in any elevation, time of
// flight, spread, hold time or obstacle (all must be identical).
import { App } from "./stub-app.mjs";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { decodePng16 } from "./png16.mjs";

const args = process.argv.slice(2);
const root = args[0];
const reference = args[1] && !args[1].startsWith("--") ? args[1] : null;
const mapName = args.includes("--map") ? args[args.indexOf("--map") + 1] : "albasrah";

const dir = `${homedir()}/apps/squadcalc/dist/heightmaps/${mapName}`;
const meta = JSON.parse(readFileSync(`${dir}/meta.json`));
const { width, height: rows, data } = decodePng16(readFileSync(`${dir}/heightmap.png`));
const grid = Array.from({ length: rows }, (_, y) => Uint16Array.from(data.subarray(y * width, (y + 1) * width)));

// The heights of the served heightmap as a stand-in for SquadHeightmap.getHeight (bilinear, row = -lat, col = lng,
// one sample per map unit): the bench times the solutions and compares two checkouts on the same heights
// (jsonPng: the heightmap's own rows, which checkouts before 45.52.0 read to know the heights loaded)
const heightmap = {
    jsonPng: grid,
    failed: false,
    getHeight(latlng) {
        let row = -latlng.lat, col = latlng.lng;
        if (!(row >= -0.5 && row <= rows - 0.5 && col >= -0.5 && col <= width - 0.5)) return 0;
        row = Math.min(Math.max(row, 0), rows - 1);
        col = Math.min(Math.max(col, 0), width - 1);
        const row0 = Math.min(Math.floor(row), rows - 2), col0 = Math.min(Math.floor(col), width - 2);
        const cw = col - col0, rw = row - row0;
        const top = grid[row0], bottom = grid[row0 + 1];
        const upper = top[col0] + (top[col0 + 1] - top[col0]) * cw;
        const lower = bottom[col0] + (bottom[col0 + 1] - bottom[col0]) * cw;
        return (upper + (lower - upper) * rw) * meta.z_step_m;
    },
};
const map = { heightmap, mapToGameScale: 1, mapToGameScaleY: 1, toMeters: (a, b) => ({ east: b.lng - a.lng, north: b.lat - a.lat }) };

async function load(checkout) {
    const { WEAPONS } = await import(`${checkout}/src/data/weapons.js`);
    const { Weapon } = await import(`${checkout}/src/js/squadWeapons.js`);
    const { default: SquadFiringSolution } = await import(`${checkout}/src/js/squadFiringSolution.js`);
    const make = (name) => {
        const w = WEAPONS.find((weapon) => weapon.name === name);
        const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
        weapon.velocity = w.shells[0].velocity;
        weapon.moa = w.shells[0].moa;
        weapon.minDistance = w.shells[0].minDistance;
        weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
        return weapon;
    };
    return { make, SquadFiringSolution };
}

const next = await load(root);
const old = reference ? await load(reference) : null;
const names = ["Mortar", "UB-32", "M1064M121", "AGS-17", "DF_M2A1_50", "DF_RPG_7_PG_7V_HEAT_OG_7V", "DF_SPG_9_HEAT", "DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2", "DF_NLAW"];
const weaponAt = { lat: -1500, lng: 1400 };

const summary = (solution) => JSON.stringify([
    solution.distance, solution.bearing, solution.heightDiff,
    solution.elevation.low.rad, solution.elevation.high.rad, solution.timeOfFlight.low, solution.timeOfFlight.high,
    solution.spreadParameters.low, solution.spreadParameters.high, solution.holdTime.low, solution.holdTime.high,
    solution.obstacle.low, solution.obstacle.high,
]);

for (const name of names) {
    const weapon = next.make(name);
    const reach = Math.min(weapon.getMaxDistance(), 3000);
    let differing = 0, microseconds = 0, microsecondsOld = 0;
    for (let i = 0; i < 40; i++) {
        const distance = 40 + (reach - 40) * ((i * 0.618) % 1);
        const angle = i * 2.399;
        const target = { lat: weaponAt.lat - Math.cos(angle) * distance, lng: weaponAt.lng + Math.sin(angle) * distance };
        App.activeWeapon = weapon;
        let start = performance.now();
        const solution = new next.SquadFiringSolution(weaponAt, target, map, 0);
        microseconds += (performance.now() - start) * 1000;
        if (!old) continue;
        App.activeWeapon = old.make(name);
        start = performance.now();
        const before = new old.SquadFiringSolution(weaponAt, target, map, 0);
        microsecondsOld += (performance.now() - start) * 1000;
        if (summary(solution) !== summary(before)) { differing++; if (process.env.DEBUG && differing === 1) console.log(summary(solution), "\n", summary(before)); }
    }
    console.log(`${name}: ${(microseconds / 40).toFixed(0)} us per solution` + (old ? ` (reference ${(microsecondsOld / 40).toFixed(0)} us), differing solutions ${differing} of 40` : ""));
}
