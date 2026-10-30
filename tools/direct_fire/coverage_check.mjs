// Check SquadCalc's fire coverage (squadCoverage.js) against an analytic oracle on synthetic terrain.
//
//     node --import ./register.mjs coverage_check.mjs <SquadCalc checkout>
//
// Terrain: flat ground at 0 m with a wall WALL_HEIGHT high between WALL_EAST and WALL_EAST + WALL_WIDTH
// meters east of the weapon, across the whole map. The oracle classifies every cell from the trajectory
// of squadBallistics.js (elevations, heights and time at single points) and the exact wall crossing: the
// path y(x) bends down everywhere (gravity; a motor along the path or the barrel only speeds it up), so it
// clears the wall iff it clears both wall edges; no profile sampling. The coverage must agree on every
// cell except where the wall is within one cell of the target (the tolerance zone). Exits with 1 otherwise.
import { App } from "./stub-app.mjs";

const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { computeCoverageRays, rasterizeCoverage, COVERAGE } = await import(`${root}/src/js/squadCoverage.js`);
const { heightAt: projectileHeight, pathAt, solveElevation } = await import(`${root}/src/js/squadBallistics.js`);

const WALL_EAST = 200, WALL_WIDTH = 10, WALL_HEIGHT = 20, MUZZLE_CLEARANCE = 3;
const heightAt = (east) => (east >= WALL_EAST && east <= WALL_EAST + WALL_WIDTH ? WALL_HEIGHT : 0);

function makeWeapon(name) {
    const w = WEAPONS.find((weapon) => weapon.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    const shell = w.shells[0];
    weapon.velocity = shell.velocity;
    weapon.minDistance = shell.minDistance;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}

let failures = 0;

// A lob, boosted rockets (along the path, clamped by the cap), shells slowed to their cap at launch,
// a straight flight, an elevation weapon
for (const name of ["AGS-17", "DF_RPG_29", "DF_M3_MAAWS_HEAT_Smoke", "DF_Tank_AP_M256_Rh120", "DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2", "DF_NLAW", "Mortar"]) {
    const weapon = makeWeapon(name);
    App.activeWeapon = weapon;
    const range = Math.min(weapon.getMaxDistance(), 1500);
    const cell = 5;
    const rays = 72;
    const muzzleHeight = weapon.heightOffset > 0 ? weapon.heightOffset : 1.5;
    const gravity = App.gravity * weapon.gravityScale;
    const shot = weapon.getShot(gravity, muzzleHeight);
    const lowOnly = weapon.type === "directFire";
    const { values, targets } = computeCoverageRays({
        heightAt, ground: 0, shot, range, cell, rays,
        elevationLimits: weapon.minElevation, holdElevation: weapon.holdElevation,
        angleOffset: weapon.angleOffset || 0, lifespan: weapon.projectileLifespan, lowOnly,
    });

    const counts = { [COVERAGE.OUT]: 0, [COVERAGE.LOW]: 0, [COVERAGE.HIGH]: 0, [COVERAGE.BLOCKED]: 0 };
    let mismatches = 0, skipped = 0;

    for (let ray = 0; ray < rays; ray++) {
        const heading = (2 * Math.PI * ray) / rays;
        const cos = Math.cos(heading);
        // Along this ray the wall spans [x0, x1] meters, if the ray goes east
        const x0 = cos > 1e-9 ? WALL_EAST / cos : Infinity;
        const x1 = cos > 1e-9 ? (WALL_EAST + WALL_WIDTH) / cos : Infinity;

        for (let j = 1; j <= targets; j++) {
            const d = j * cell;
            const got = values[ray * (targets + 1) + j];
            counts[got]++;
            const targetHeight = heightAt(cos * d);

            const arcs = [];
            if (gravity === 0) arcs.push(["low", Math.atan2(targetHeight - muzzleHeight, d)]);
            else {
                const { low, high } = solveElevation(shot, d, targetHeight);
                if (!Number.isNaN(low)) arcs.push(["low", low]);
                if (!Number.isNaN(high) && !lowOnly) arcs.push(["high", high]);
            }
            const fireable = ([kind, a]) => {
                const deg = (a * 180) / Math.PI - (weapon.angleOffset || 0);
                if (deg < weapon.minElevation[0] || deg > weapon.minElevation[1]) return false;
                if (kind === "high" && weapon.holdElevation && (deg < weapon.holdElevation[0] || deg > weapon.holdElevation[1])) return false;
                return pathAt(shot, a, d).time <= weapon.projectileLifespan;
            };
            // Exact: the downward-bending path clears the wall iff both wall edges are cleared (within the checked span)
            const end = d - Math.max(cell, 3);
            const y = (a, x) => projectileHeight(shot, a, x);
            const clears = ([, a]) => {
                const lo = Math.max(x0, MUZZLE_CLEARANCE), hi = Math.min(x1, end);
                if (lo > hi) return true;
                return y(a, lo) >= WALL_HEIGHT && y(a, hi) >= WALL_HEIGHT;
            };
            const ok = arcs.filter(fireable);
            let expected;
            const low = ok.find(([k]) => k === "low");
            const high = ok.find(([k]) => k === "high");
            if (low && clears(low)) expected = COVERAGE.LOW;
            else if (high && clears(high)) expected = COVERAGE.HIGH;
            else if (ok.length) expected = COVERAGE.BLOCKED;
            else expected = COVERAGE.OUT;

            // Within a sample step or a cell of the wall edges or the tolerance zone the sampling may differ,
            // and so may a trajectory grazing an edge by less than it climbs or drops over one 2 m sample
            const slope = (a, x) => (y(a, x + 0.01) - y(a, x - 0.01)) / 0.02;
            const grazes = ok.some(([, a]) => [x0, x1].some((x) => x >= MUZZLE_CLEARANCE && x <= end
                && Math.abs(y(a, x) - WALL_HEIGHT) <= Math.abs(slope(a, x)) * 2 + 0.01));
            const nearEdge = grazes || [x0, x1].some((x) => Math.abs(end - x) < 2.5 || Math.abs(d - x) < cell);
            if (got !== expected) {
                if (nearEdge) skipped++;
                else {
                    mismatches++;
                    if (mismatches <= 5) console.log("MISMATCH", name, "ray", ray, "d", d, "got", got, "expected", expected);
                }
            }
        }
    }
    const raster = rasterizeCoverage(values, rays, targets, cell, range);
    console.log(`${name}: range ${range.toFixed(0)} m, cells ${rays * targets}, low ${counts[1]}, high ${counts[2]}, blocked ${counts[3]}, out ${counts[0]}, mismatches ${mismatches}, edge differences ${skipped}, image ${raster.size}px`);
    if (mismatches) failures++;
}

// Timing on a realistic setup, sized like squadCoverage.js: the AGS-17 and the longest range (tank, 4 km)
for (const name of ["AGS-17", "DF_Tank_AP_M256_Rh120", "DF_M3_MAAWS_HEAT_Smoke"]) {
    const weapon = makeWeapon(name);
    App.activeWeapon = weapon;
    const range = Math.min(weapon.getMaxDistance(), 4000);
    const cell = Math.max(5, range / 320);
    const rays = Math.max(360, Math.min(1440, Math.ceil((2 * Math.PI * range) / (2 * cell))));
    const start = performance.now();
    computeCoverageRays({
        heightAt: (e, n) => 10 * Math.sin(e / 37) * Math.cos(n / 53), ground: 1, range, cell, rays,
        shot: weapon.getShot(App.gravity * weapon.gravityScale, 1),
        elevationLimits: weapon.minElevation, holdElevation: weapon.holdElevation,
        angleOffset: 0, lifespan: weapon.projectileLifespan, lowOnly: weapon.type === "directFire",
    });
    console.log(`timing: ${name} ${range.toFixed(0)} m, ${rays} rays x ${Math.floor(range / cell)} cells: ${(performance.now() - start).toFixed(0)} ms`);
}

process.exit(failures ? 1 : 0);
