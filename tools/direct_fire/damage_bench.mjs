// Time SquadCalc's damage zone with cover (squadDamage.js) on a real precise heightmap and compare it with a
// reference checkout.
//
//     node --import ./register.mjs damage_bench.mjs <SquadCalc checkout> [<reference checkout>] [--map <name>]
//
// For each explosion (inner, outer radius in meters) and 12 impact points of the map, computes the damage field
// the way SquadTargetMarker.updateCoverZone does (cell 0.5 m, 1 m above 30 m of radius) and prints the
// milliseconds per field; with a reference checkout, also the cells whose class (kills / wounds / covered by
// cover / none) differs from the reference's, and the same for hitProbability (kill and wound probability).
import "./stub-app.mjs";
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
const step = meta.z_step_m;

// The heights as SquadHeightmap stores them (one Uint16Array view per row), read bilinearly as a stand-in for its
// getHeight(fromMeters(...)): the bench times the damage field, the same heights for every run
const levels = Uint16Array.from(data);
const grid = Array.from({ length: rows }, (_, y) => levels.subarray(y * width, (y + 1) * width));
const getHeight = (latlng) => {
    let row = latlng.lat * -1, col = latlng.lng * 1;
    if (!(row >= -0.5 && row <= rows - 0.5 && col >= -0.5 && col <= width - 0.5)) return 0;
    row = Math.min(Math.max(row, 0), rows - 1);
    col = Math.min(Math.max(col, 0), width - 1);
    const row0 = Math.min(Math.floor(row), rows - 2), col0 = Math.min(Math.floor(col), width - 2);
    const colWeight = col - col0, rowWeight = row - row0;
    const top = grid[row0], bottom = grid[row0 + 1];
    const upper = top[col0] + (top[col0 + 1] - top[col0]) * colWeight;
    const lower = bottom[col0] + (bottom[col0 + 1] - bottom[col0]) * colWeight;
    return (upper + (lower - upper) * rowWeight) * step;
};
const fromMeters = (origin, east, north) => ({ lat: origin.lat + north, lng: origin.lng + east });
const around = (centerCol, centerRow) => {
    const center = { lat: -centerRow, lng: centerCol };
    return (east, north) => getHeight(fromMeters(center, east, north));
};

const modules = async (checkout) => import(`${checkout}/src/js/squadDamage.js`);
const next = await modules(root);
const old = reference ? await modules(reference) : null;

const explosions = [
    { damage: 350, inner: 0, outer: 40, falloff: 7, distanceFromImpact: 1 },
    { damage: 115, inner: 5, outer: 18, falloff: 1, distanceFromImpact: 0.2 },
    { damage: 300, inner: 2, outer: 60, falloff: 2, distanceFromImpact: 1 },
    { damage: 800, inner: 40, outer: 75, falloff: 2, distanceFromImpact: 1 },
    { damage: 90, inner: 1, outer: 15, falloff: 1, distanceFromImpact: 0.5 },
];
const points = Array.from({ length: 12 }, (_, i) => [300 + ((i * 977) % 3300), 300 + ((i * 1543) % 3300)]);
const classOf = (field, i) => (field.damage[i] >= 100 ? 3 : field.damage[i] >= 25 ? 2 : field.exposed[i] >= 25 ? 1 : 0);

for (const explosion of explosions) {
    const cell = explosion.outer > 30 ? 1 : 0.5;
    let msNext = 0, msOld = 0, differing = 0, cells = 0, maxProbability = 0, probabilityMs = 0, probabilityOldMs = 0;
    for (const [col, row] of points) {
        const heightAt = around(col, row);
        let start = performance.now();
        const field = next.damageField(heightAt, explosion, cell);
        msNext += performance.now() - start;
        start = performance.now();
        const probability = next.hitProbability(heightAt, explosion, 25, 12, 70);
        probabilityMs += performance.now() - start;
        if (!old) continue;
        start = performance.now();
        const before = old.damageField(heightAt, explosion, cell);
        msOld += performance.now() - start;
        start = performance.now();
        const probabilityOld = old.hitProbability(heightAt, explosion, 25, 12, 70);
        probabilityOldMs += performance.now() - start;
        for (let i = 0; i < field.damage.length; i++) {
            cells++;
            if (classOf(field, i) !== classOf(before, i)) differing++;
        }
        maxProbability = Math.max(maxProbability, Math.abs(probability.kill - probabilityOld.kill), Math.abs(probability.wound - probabilityOld.wound));
    }
    const per = (ms) => (ms / points.length).toFixed(1);
    console.log(`explosion [${explosion.inner}, ${explosion.outer}] cell ${cell}: ${per(msNext)} ms per field` +
        (old ? ` (reference ${per(msOld)} ms), differing cells ${differing} of ${cells}, hitProbability ${(probabilityMs / points.length).toFixed(1)} ms (reference ${(probabilityOldMs / points.length).toFixed(1)}), largest probability difference ${maxProbability.toFixed(4)}` : `, hitProbability ${(probabilityMs / points.length).toFixed(1)} ms`));
}
