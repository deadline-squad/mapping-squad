// Time SquadCalc's fire coverage (squadCoverage.js) on a real precise heightmap and snapshot its cells.
//
//     node --import ./register.mjs coverage_bench.mjs <SquadCalc checkout> [options]
//
//   --map <name>         map under ~/apps/squadcalc/dist/heightmaps (default albasrah)
//   --at <east,north>    weapon position in meters from the map center (default 120,-340)
//   --weapons <a,b,..>   weapon names (default: Mortar, UB-32, M2, tank HE, AGS-17, RPG-7, SPG-9)
//   --all                every weapon of weapons.js
//   --repeat <n>         run each weapon n times and report the fastest (default 1)
//   --save <dir>         write the cells of each weapon to <dir>/<weapon>.bin (raw Uint8Array)
//   --compare <dir>      count the cells that differ from a saved snapshot; exits 1 on any difference
//
// Runs the pipeline of SquadCoverage.compute() without the map: the same range, cell, rays and shot, in
// chunks of 24 rays. A checkout that exports computeCoveragePeaks() gets the peaks once (as compute()
// does there); an older one recomputes them in every chunk, as it did. Prints the CPU seconds per weapon (process.cpuUsage: steadier than the wall clock on a busy machine).
import { App } from "./stub-app.mjs";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { createHash } from "node:crypto";

const args = process.argv.slice(2);
const root = args[0];
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const mapName = option("--map", "albasrah");
const [startEast, startNorth] = option("--at", "120,-340").split(",").map(Number);
const repeat = Number(option("--repeat", 1));
const saveDir = option("--save", null);
const compareDir = option("--compare", null);

const { decode } = await import(`${homedir()}/agl/SquadCalc/node_modules/fast-png/lib/index.js`);
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const coverage = await import(`${root}/src/js/squadCoverage.js`);
const { computeCoverageRays, SHOULDER_HEIGHT } = coverage;

const MAX_COVERAGE_RANGE = 4000, CELLS_PER_RANGE = 320, MIN_CELL = 5, RAYS_PER_CHUNK = 24;

const dir = `${homedir()}/apps/squadcalc/dist/heightmaps/${mapName}`;
const meta = JSON.parse(readFileSync(`${dir}/meta.json`));
const png = decode(readFileSync(`${dir}/heightmap.png`));
const { width, height: rows, data } = png;
const step = meta.z_step_m;

// Bilinear height at (east, north) meters from the weapon, like SquadHeightmap.getHeight (0 outside the grid)
const originCol = (width - 1) / 2 + startEast, originRow = (rows - 1) / 2 - startNorth;
const gridHeight = (east, north) => {
    const col = originCol + east, row = originRow - north;
    if (!(row >= 0 && row <= rows - 1 && col >= 0 && col <= width - 1)) return 0;
    const row0 = Math.min(Math.floor(row), rows - 2), col0 = Math.min(Math.floor(col), width - 2);
    const rw = row - row0, cw = col - col0;
    const at = (r, c) => data[r * width + c];
    const upper = at(row0, col0) + (at(row0, col0 + 1) - at(row0, col0)) * cw;
    const lower = at(row0 + 1, col0) + (at(row0 + 1, col0 + 1) - at(row0 + 1, col0)) * cw;
    return (upper + (lower - upper) * rw) * step;
};
const inside = (east, north) => {
    const col = originCol + east, row = originRow - north;
    return row >= 0 && row <= rows - 1 && col >= 0 && col <= width - 1;
};

function makeWeapon(w) {
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    weapon.velocity = w.shells[0].velocity;
    weapon.minDistance = w.shells[0].minDistance;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}

const defaults = ["Mortar", "UB-32", "DF_M2A1_50", "DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2", "AGS-17", "DF_RPG_7_PG_7V_HEAT_OG_7V", "DF_SPG_9_HEAT"];
const names = args.includes("--all") ? WEAPONS.map((w) => w.name) : option("--weapons", defaults.join(",")).split(",");

if (saveDir) mkdirSync(saveDir, { recursive: true });
let differing = 0;

for (const name of names) {
    const definition = WEAPONS.find((w) => w.name === name);
    if (!definition) throw new Error(`no weapon ${name}`);
    const weapon = makeWeapon(definition);
    App.activeWeapon = weapon;

    const range = Math.min(weapon.getMaxDistance(), MAX_COVERAGE_RANGE);
    const cell = Math.max(MIN_CELL, range / CELLS_PER_RANGE);
    const rays = Math.max(360, Math.min(1440, Math.ceil((2 * Math.PI * range) / (2 * cell))));
    const targets = Math.floor(range / cell);
    const values = new Uint8Array(rays * (targets + 1));
    const gravity = App.gravity * weapon.gravityScale;
    const params = {
        heightAt: gridHeight, ground: gridHeight(0, 0), range, cell, rays, inside, out: values,
        shot: weapon.muzzle || weapon.heightOffset > 0 ? weapon.getShot(gravity) : weapon.getShot(gravity, SHOULDER_HEIGHT),
        elevationLimits: weapon.minElevation, holdElevation: weapon.holdElevation,
        angleOffset: weapon.angleOffset || 0, lifespan: weapon.projectileLifespan, lowOnly: weapon.type === "directFire",
    };

    let seconds = Infinity;
    let longest = 0;
    for (let run = 0; run < repeat; run++) {
        values.fill(0);
        const start = process.cpuUsage();
        let longestRun = 0;
        if (coverage.computeCoveragePeaks) params.peaks = coverage.computeCoveragePeaks(params).peaks;
        for (let first = 0; first < rays; first += RAYS_PER_CHUNK) {
            const chunkStart = performance.now();
            computeCoverageRays({ ...params, firstRay: first, lastRay: Math.min(rays, first + RAYS_PER_CHUNK) });
            longestRun = Math.max(longestRun, performance.now() - chunkStart);
        }
        const used = process.cpuUsage(start);
        const elapsed = (used.user + used.system) / 1e6;
        if (elapsed < seconds) {
            seconds = elapsed;
            longest = longestRun;
        }
    }

    let note = "";
    if (saveDir) writeFileSync(`${saveDir}/${name}.bin`, values);
    if (compareDir) {
        const file = `${compareDir}/${name}.bin`;
        if (!existsSync(file)) note = " NO SNAPSHOT";
        else {
            const before = readFileSync(file);
            let diff = before.length === values.length ? 0 : values.length;
            for (let i = 0; i < values.length && before.length === values.length; i++) if (before[i] !== values[i]) diff++;
            differing += diff;
            note = ` differing cells ${diff}`;
        }
    }
    const counts = [0, 0, 0, 0];
    for (const value of values) counts[value]++;
    const sha = createHash("sha1").update(values).digest("hex").slice(0, 10);
    console.log(`${name}: ${range.toFixed(0)} m, ${rays}x${targets} cells, ${seconds.toFixed(2)} s, longest 24-ray chunk ${longest.toFixed(0)} ms, low ${counts[1]} high ${counts[2]} blocked ${counts[3]} out ${counts[0]}, sha ${sha}${note}`);
}

process.exit(differing ? 1 : 0);
