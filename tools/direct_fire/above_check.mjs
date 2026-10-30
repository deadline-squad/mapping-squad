// Checks that trajectory().above gives the same answer with and without the sparse range-maximum table
// (squadBallistics.RangeMax), and that a warm-started root search lands on the root of a cold one.
//
//     node --import ./register.mjs above_check.mjs <SquadCalc checkout>
//
// For every weapon, random elevations over terrain profiles that follow the trajectory to within a few meters
// (so many are grazed, never exactly: the two scans round differently within 1e-9 m), and random rows of neighbouring targets. Exits with 1 on any difference.
import { App } from "./stub-app.mjs";

const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { trajectory, RangeMax, solveElevation, ANGLE_TOLERANCE } = await import(`${root}/src/js/squadBallistics.js`);

// Deterministic pseudo-random numbers
let seed = 12345;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);

let failures = 0;
let compared = 0;
let blocked = 0;
let rootsCompared = 0;
let worstRootDifference = 0;

for (const w of WEAPONS) {
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    weapon.velocity = w.shells[0].velocity;
    App.activeWeapon = weapon;
    const gravity = App.gravity * weapon.gravityScale;
    const shot = weapon.getShot(gravity, weapon.heightOffset > 0 || weapon.muzzle ? undefined : 1.5);

    for (let trial = 0; trial < 60; trial++) {
        const angle = (random() * 1.6 - 0.1);
        const path = trajectory(shot, angle);
        const step = [1, 2, 3][trial % 3];
        const samples = 200 + Math.floor(random() * 1200);
        const profile = new Float64Array(samples);
        const slack = [1e-6, 0.001, 0.5, 3][trial % 4];
        for (let i = 0; i < samples; i++) {
            const h = path.height(i * step);
            // Where the capped coast never gets (its height is a huge negative number) the terrain is above it
            profile[i] = (h > -1e4 ? h : 0) + (random() - 0.5) * 2 * slack - (trial % 5 === 0 ? slack : 0);
        }
        const table = new RangeMax(samples).build(profile);
        const first = Math.ceil(3 / step);
        const last = samples - 1 - Math.floor(random() * 20);
        const ground = 0;
        const linear = path.above(profile, first, last, step, ground);
        const sparse = path.above(profile, first, last, step, ground, table);
        compared++;
        if (!linear) blocked++;
        if (linear !== sparse) {
            failures++;
            let violation = -1;
            for (let i = first; i <= last && violation < 0; i++) if (ground + path.height(i * step) < profile[i]) violation = i;
            if (failures <= 10) console.log(`FAIL index ${violation} of ${first}-${last}: ${w.name} angle ${angle.toFixed(4)} step ${step} slack ${slack}: linear ${linear}, sparse ${sparse}`);
        }
    }

    // Roots along a row of targets, warm-started from the previous one, against a cold search
    if (gravity > 0) {
        let roots = {};
        for (let j = 1; j <= 40; j++) {
            const distance = 20 + j * 12;
            const height = 5 * Math.sin(j / 3);
            const cold = solveElevation(shot, distance, height);
            roots = solveElevation(shot, distance, height, undefined, undefined, roots);
            for (const arc of ["low", "high"]) {
                if (Number.isNaN(cold[arc]) || Number.isNaN(roots[arc])) {
                    if (Number.isNaN(cold[arc]) !== Number.isNaN(roots[arc])) {
                        failures++;
                        console.log(`FAIL ${w.name} ${arc} at ${distance} m: cold ${cold[arc]}, warm ${roots[arc]}`);
                    }
                    continue;
                }
                rootsCompared++;
                const difference = Math.abs(cold[arc] - roots[arc]);
                worstRootDifference = Math.max(worstRootDifference, difference);
                // Both end their search within ANGLE_TOLERANCE or HEIGHT_TOLERANCE of the root
                if (difference > 1e-9) {
                    failures++;
                    console.log(`FAIL ${w.name} ${arc} at ${distance} m: cold ${cold[arc]}, warm ${roots[arc]}`);
                }
            }
        }
    }
}

console.log(`${compared} profiles compared (${blocked} blocked), ${rootsCompared} warm roots compared, largest root difference ${worstRootDifference.toExponential(2)} rad (tolerance ${ANGLE_TOLERANCE})`);
if (failures) {
    console.log(`${failures} failure(s)`);
    process.exit(1);
}
console.log("all above checks passed");
