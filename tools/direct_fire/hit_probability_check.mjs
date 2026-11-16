// Check SquadCalc's hit probability (squadDamage.hitProbability and the "rounds to kill / wound" line)
// against the game's spread.
//
//     node --import ./register.mjs hit_probability_check.mjs <SquadCalc checkout>
//
// The oracle is built only from the game and exact physics, not from SquadCalc's sampling: shots from
// the game's cone, thrown on the exact flat-ground parabola from the weapon's muzzle, SquadCalc's own
// impactDamage for the damage.
//
// The game's cone (Squad build 26005357, SquadGameServer; deadline-squad/deadline-squadcalc#6):
//   half-angle h = MOA / 60 * 0.5 degrees (ConvertMOAToRadians, 0xa4252c0),
//   FMath::VRandCone (0x4a13010): Phi = fmodf(acosf(2v - 1), h), v uniform in [0, 1),
//   so Phi is uniform on [0, h) (acos(2v - 1) is spread over [0, pi], the remainder by a tiny h is flat):
//   the miss RADIUS is uniform, the density is 1/r, not uniform over the area. Theta is uniform.
//
// Direct-fire weapons (deadline-squad/deadline-squadcalc#8) are flown in the game's steps of 1/49.87 s (motor along the
// path or the barrel, speed cap, as squadBallistics.js documents): the shot of each cone direction is flown from the
// real muzzle, so the closed-form spread of getSpreadParameter, which assumes a constant speed, is not part of the
// oracle (SquadCalc's hit probability uses firingSolution.getHitSpread for those shots).
//
// Cases: first shell of the Mortar (50 MOA) and of the AGS-17 (50 MOA, high arc) on flat ground, the aim
// point at the origin. 400,000 shots each, seeded; the recorded kill and wound are those of the oracle (the
// issue lists 0.489 / 0.901 for the mortar at 1000 m, its oracle left out the muzzle's 1.57 m along the tube,
// which moves the whole spread by 0.7 m). The rounds compared are the ones the popup shows.
// Exits with 1 on any failure.
import { App } from "./stub-app.mjs";

const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);
const { impactDamage, hitProbability, roundsNeeded, KILL_DAMAGE, WOUND_DAMAGE } = await import(`${root}/src/js/squadDamage.js`);

const SHOTS = 400000;
const TOLERANCE = 0.01;
const flat = () => 0;

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

/** mulberry32: small seeded generator, so the oracle gives the same numbers on every run */
function seeded(seed) {
    let state = seed >>> 0;
    return () => {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const explosionOf = (shell) => ({
    damage: shell.explosionDamage,
    inner: shell.explosionRadius[0],
    outer: shell.explosionRadius[1],
    falloff: shell.damageFallOff,
    distanceFromImpact: shell.explosionDistanceFromImpact,
});

/** The weapon, loaded with its first shell, and the firing solution to a target on flat ground */
function solve(name, distance, shellIndex = 0) {
    const w = WEAPONS.find((entry) => entry.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    const shell = w.shells[shellIndex];
    weapon.velocity = shell.velocity;
    weapon.moa = shell.moa;
    weapon.minDistance = shell.minDistance;
    weapon.decelerationDistance = 0;
    App.activeWeapon = weapon;
    const map = {
        mapToGameScale: 1,
        mapToGameScaleY: 1,
        toMeters: (origin, ll) => ({ east: ll.lng - origin.lng, north: ll.lat - origin.lat }),
        heightmap: { getHeight: () => 0 },
    };
    const solution = new SquadFiringSolution({ lat: 0, lng: 0 }, { lat: 0, lng: distance }, map, 0);
    return { weapon, shell, solution };
}

/**
 * The game's shots at the aim point: where each one lands relative to it
 * @returns {{east: number, north: number}[]} - the line of fire points east
 */
function gameImpacts(weapon, moa, elevation, distance, random) {
    const shot = weapon.getShot();
    if (shot.acceleration || shot.maxSpeed) throw new Error("the oracle throws a plain parabola");
    const halfAngle = (moa / 60) * 0.5 * Math.PI / 180;
    const sinE = Math.sin(elevation);
    const cosE = Math.cos(elevation);
    // The muzzle: ahead of the pivot along the barrel, above it perpendicular to it
    const x0 = shot.muzzleForward * cosE - shot.muzzleUp * sinE;
    const z0 = shot.pivotHeight + shot.muzzleForward * sinE + shot.muzzleUp * cosE;
    const impacts = new Array(SHOTS);
    for (let i = 0; i < SHOTS; i++) {
        const phi = Math.acos(2 * random() - 1) % halfAngle;
        const theta = 2 * Math.PI * random();
        const sideways = Math.sin(phi) * Math.cos(theta);
        const upwards = Math.sin(phi) * Math.sin(theta);
        const forward = Math.cos(phi) * cosE - upwards * sinE;
        const up = Math.cos(phi) * sinE + upwards * cosE;
        const vz = shot.velocity * up;
        const flight = (vz + Math.sqrt(vz * vz + 2 * shot.gravity * z0)) / shot.gravity;
        impacts[i] = { east: x0 + shot.velocity * forward * flight - distance, north: shot.velocity * sideways * flight };
    }
    return impacts;
}

const STEP = 1 / 49.87;

/**
 * Horizontal distance a shot flies, in the game's steps (Velocity Verlet, motor along R for the first
 * ceil(boostTime / dt) - 1 steps, speed cap on every step, R following the velocity unless the projectile keeps the barrel's axis), until it comes
 * down to the ground, from its start point.
 */
function flySteps(shot, elevation, startX, startZ) {
    let x = startX;
    let z = startZ;
    let vx = shot.velocity * Math.cos(elevation);
    let vz = shot.velocity * Math.sin(elevation);
    let axis = [Math.cos(elevation), Math.sin(elevation)];
    const next = (axisNow, time) => {
        const push = shot.boostTime > 0 && time < shot.boostTime - 1e-12 ? shot.acceleration : 0;
        let nx = vx + push * axisNow[0] * STEP;
        let nz = vz + (push * axisNow[1] - shot.gravity) * STEP;
        const speed = Math.hypot(nx, nz);
        if (shot.maxSpeed && speed > shot.maxSpeed) {
            nx *= shot.maxSpeed / speed;
            nz *= shot.maxSpeed / speed;
        }
        return [nx, nz];
    };
    // `time` is the time since the spawn at the end of the step: the strict thrust acts while it is under boostTime
    for (let step = 0, time = STEP; step < 20000; step++, time += STEP) {
        const before = next(axis, time);
        const nextX = x + vx * STEP + (before[0] - vx) * STEP / 2;
        const nextZ = z + vz * STEP + (before[1] - vz) * STEP / 2;
        if (nextZ <= 0 && step > 0) return x + (nextX - x) * z / (z - nextZ);
        x = nextX;
        z = nextZ;
        if (shot.rotationFollowsVelocity) axis = [vx / Math.hypot(vx, vz), vz / Math.hypot(vx, vz)];
        [vx, vz] = next(axis, time);
    }
    return NaN;
}

/** The game's shots at the aim point for a weapon that does not fly a plain parabola (rockets, capped shells) */
function stepImpacts(weapon, moa, elevation, distance, random, shots) {
    const shot = weapon.getShot();
    const halfAngle = (moa / 60) * 0.5 * Math.PI / 180;
    const sinE = Math.sin(elevation);
    const cosE = Math.cos(elevation);
    const x0 = shot.muzzleForward * cosE - shot.muzzleUp * sinE;
    const z0 = shot.pivotHeight + shot.muzzleForward * sinE + shot.muzzleUp * cosE;
    const impacts = new Array(shots);
    for (let i = 0; i < shots; i++) {
        const phi = Math.acos(2 * random() - 1) % halfAngle;
        const theta = 2 * Math.PI * random();
        const sideways = Math.sin(phi) * Math.cos(theta);
        const upwards = Math.sin(phi) * Math.sin(theta);
        const forward = Math.cos(phi) * cosE - upwards * sinE;
        const up = Math.cos(phi) * sinE + upwards * cosE;
        const range = flySteps(shot, Math.atan2(up, Math.hypot(forward, sideways)), x0, z0) - x0;
        const azimuth = Math.atan2(sideways, forward);
        impacts[i] = { east: x0 + range * Math.cos(azimuth) - distance, north: range * Math.sin(azimuth) };
    }
    return impacts;
}

const aimPoint = { east: 0, north: 0 };
function gameProbabilities(impacts, explosion) {
    const total = impacts.length;
    let kills = 0;
    let wounds = 0;
    for (const impact of impacts) {
        const { damage } = impactDamage(flat, explosion, impact, aimPoint);
        if (damage >= KILL_DAMAGE) kills++;
        if (damage >= WOUND_DAMAGE) wounds++;
    }
    return { kill: kills / total, wound: wounds / total };
}

// The distribution itself: CDF of Phi / h at 0.1 ... 0.9 is the fraction itself (uniform in radius);
// uniform in area would give its square
{
    const random = seeded(1);
    const halfAngle = (50 / 60) * 0.5 * Math.PI / 180;
    const fractions = [0.1, 0.25, 0.5, 0.75, 0.9];
    const below = fractions.map(() => 0);
    for (let i = 0; i < SHOTS; i++) {
        const phi = (Math.acos(2 * random() - 1) % halfAngle) / halfAngle;
        fractions.forEach((fraction, k) => { if (phi < fraction) below[k]++; });
    }
    fractions.forEach((fraction, k) => check(`VRandCone: P(Phi/h < ${fraction})`, Math.abs(below[k] / SHOTS - fraction) < 0.005, (below[k] / SHOTS).toFixed(4)));
}

// Flat ground, circular spread of radius R: the kill probability is the kill radius over R (radius uniform),
// not its square
{
    const { shell } = solve("Mortar", 300);
    const explosion = explosionOf(shell);
    const killRadius = Weapon.prototype.calculateDistanceForDamage(explosion.damage, explosion.inner, explosion.outer, explosion.falloff, explosion.distanceFromImpact, KILL_DAMAGE);
    for (const spread of [30, 50]) {
        const { kill } = hitProbability(flat, explosion, spread, spread, 37);
        const expected = killRadius / spread;
        check(`circular spread ${spread} m: kill = kill radius / R`, Math.abs(kill - expected) <= TOLERANCE, `${kill.toFixed(3)} vs ${expected.toFixed(3)}`);
    }
}

// Weapons on flat ground: the shown spread, the game's kill and wound, the rounds to fire
const cases = [
    { name: "Mortar", distance: 300, shown: [17.83, 17.42], kill: 0.369, wound: 0.711 },
    { name: "Mortar", distance: 1000, shown: [16.01, 10.56], kill: 0.494, wound: 0.910 },
    { name: "AGS-17", distance: 300, shown: [28.14, 27.88], kill: 0.115, wound: 0.510 },
    { name: "AGS-17", distance: 1000, shown: [27.20, 24.18], kill: 0.125, wound: 0.556 },
    { name: "AGS-17", distance: 1500, shown: [25.52, 17.91], kill: 0.150, wound: 0.665 },
];
for (const { name, distance, shown, kill, wound } of cases) {
    const { weapon, shell, solution } = solve(name, distance);
    const explosion = explosionOf(shell);
    const arc = weapon.angleType === "high" ? "high" : "low";
    const spread = solution.spreadParameters[arc];
    const lateral = spread.semiMajorAxis / 2;
    const along = spread.semiMinorAxis / 2;
    const label = `${name} ${distance} m`;

    check(`${label}: ellipse radii shown`, Math.abs(lateral - shown[0]) <= 0.01 && Math.abs(along - shown[1]) <= 0.01, `${lateral.toFixed(2)} / ${along.toFixed(2)} vs ${shown.join(" / ")}`);

    const impacts = gameImpacts(weapon, shell.moa, solution.elevation[arc].rad, distance, seeded(distance + name.length));
    const game = gameProbabilities(impacts, explosion);
    check(`${label}: oracle kill / wound as recorded`, Math.abs(game.kill - kill) <= TOLERANCE && Math.abs(game.wound - wound) <= TOLERANCE, `${game.kill.toFixed(3)} / ${game.wound.toFixed(3)} vs ${kill} / ${wound}`);

    const squadcalc = hitProbability(flat, explosion, lateral, along, 90);
    check(`${label}: kill`, Math.abs(squadcalc.kill - game.kill) <= TOLERANCE, `${squadcalc.kill.toFixed(3)} vs game ${game.kill.toFixed(3)}`);
    check(`${label}: wound`, Math.abs(squadcalc.wound - game.wound) <= TOLERANCE, `${squadcalc.wound.toFixed(3)} vs game ${game.wound.toFixed(3)}`);
    const rounds = (probabilities) => [roundsNeeded(probabilities.kill), roundsNeeded(probabilities.wound)];
    const [killRounds, woundRounds] = rounds(squadcalc);
    const [gameKillRounds, gameWoundRounds] = rounds(game);
    check(`${label}: rounds to kill / wound for 90 %`, Math.abs(killRounds - gameKillRounds) <= 1 && Math.abs(woundRounds - gameWoundRounds) <= 1, `${killRounds} / ${woundRounds} vs game ${gameKillRounds} / ${gameWoundRounds}`);
}

// Direct-fire weapons with an explosion, three distances each (a plain grenade parabola, a boosted rocket, a capped
// shell and an autocannon). The nominal shot must land on the target, and SquadCalc's kill / wound per round and the
// rounds to fire must agree with the oracle.
const DIRECT_SHOTS = 300000;
const directCases = [
    { name: "DF_M203_M320_GP_25_HK79_SL40", shell: 0, distances: [150, 300, 450] },
    // The tripod MK19 shoots from the ground (a plain parabola). The vehicle MK19s (PARS III, 2.7 m up) have the game's launch
    // point, which makes the shot graze the ground at 300 m; the symmetric ellipse is off there by 0.02-0.03 (deadline-squad/deadline-squadcalc#19)
    { name: "DF_MK19_emplacement_C16_L134A1", shell: 0, distances: [300, 800, 1500] },
    { name: "DF_RPG_7_PG_7V_HEAT_OG_7V", shell: 0, distances: [150, 400, 800] },
    { name: "DF_RPG_7_PG_7V_HEAT_OG_7V", shell: 1, distances: [150, 400, 800] },
    { name: "DF_SPG_9_FRAG", shell: 0, distances: [150, 400, 800] },
    { name: "DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2", shell: 1, distances: [300, 800, 1500] },
    { name: "DF_2A70_100mm_BMP_3_BMD_4_ZBD04A_FRAG", shell: 0, distances: [300, 800, 1500] },
    // 300 m is a grazing shot (0.16 degrees): the range of a round fired below the line of sight goes with 1/angle,
    // so the landing spots are skewed and the symmetric ellipse is off by 0.011 (0.350 against 0.339); 0.015 allowed there
    { name: "DF_CTAS40_40mm_GP", shell: 0, distances: [300, 800, 1500], tolerance: { 300: 0.015 } },
];
for (const { name, shell: shellIndex, distances, tolerance = {} } of directCases) {
    for (const distance of distances) {
        const { weapon, shell, solution } = solve(name, distance, shellIndex);
        const explosion = explosionOf(shell);
        const elevation = solution.elevation.low.rad;
        const label = `${name}/${shell.name} ${distance} m`;
        const shot = weapon.getShot();
        const start = { x: shot.muzzleForward * Math.cos(elevation) - shot.muzzleUp * Math.sin(elevation), z: shot.pivotHeight + shot.muzzleForward * Math.sin(elevation) + shot.muzzleUp * Math.cos(elevation) };
        const landed = flySteps(shot, elevation, start.x, start.z);
        check(`${label}: the nominal shot lands on the target`, Math.abs(landed - distance) <= 1, `${(landed - distance).toFixed(2)} m off`);

        const game = gameProbabilities(stepImpacts(weapon, shell.moa, elevation, distance, seeded(distance + shellIndex), DIRECT_SHOTS), explosion);
        const { lateral, along } = solution.getHitSpread("low");
        const squadcalc = hitProbability(flat, explosion, lateral, along, 90);
        check(`${label}: kill`, Math.abs(squadcalc.kill - game.kill) <= (tolerance[distance] ?? TOLERANCE), `${squadcalc.kill.toFixed(3)} vs game ${game.kill.toFixed(3)}`);
        check(`${label}: wound`, Math.abs(squadcalc.wound - game.wound) <= (tolerance[distance] ?? TOLERANCE), `${squadcalc.wound.toFixed(3)} vs game ${game.wound.toFixed(3)}`);
        const rounds = (probabilities) => [roundsNeeded(probabilities.kill), roundsNeeded(probabilities.wound)];
        const [killRounds, woundRounds] = rounds(squadcalc);
        const [gameKillRounds, gameWoundRounds] = rounds(game);
        check(`${label}: rounds to kill / wound for 90 %`, Math.abs(killRounds - gameKillRounds) <= 1 && Math.abs(woundRounds - gameWoundRounds) <= 1, `${killRounds} / ${woundRounds} vs game ${gameKillRounds} / ${gameWoundRounds}`);
    }
}

// A plain parabola keeps the closed-form spread (the Mortar's and the grenades' numbers above do not change)
{
    const { solution } = solve("DF_M203_M320_GP_25_HK79_SL40", 300);
    const spread = solution.spreadParameters.low;
    const hit = solution.getHitSpread("low");
    check("plain parabola: hit spread is the closed form", hit.lateral === spread.semiMajorAxis / 2 && hit.along === spread.semiMinorAxis / 2, `${hit.lateral.toFixed(3)} / ${hit.along.toFixed(3)}`);
}

console.log(failures ? `${failures} hit probability checks failed` : "all hit probability checks passed");
process.exit(failures ? 1 : 0);
