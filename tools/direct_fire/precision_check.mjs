// Precision checks of the Deadline SquadCalc against independent oracles, one section per defect of the
// 2026-10-29 precision audit (the section names are the audit's bug numbers):
//
//     node --import ./register.mjs precision_check.mjs <SquadCalc checkout> [SECTION ...]
//
//   B1  non-square maps: distance and bearing use the scale of each map axis (Skorpo 6849 x 6869 m)
//   B2  heightmap grid of width+1 samples and interpolation (synthetic plane heightmap), and the game's triangles:
//       each quad splits along the diagonal from (row, col) to (row + 1, col + 1), not bilinear (synthetic saddles)
//   B6  UB-32 equivalent velocity below the end of its deceleration (Squad Ballistics' time_to model)
//   B7  rockets: the elevation lands on the target, to 0.5 m, in a simulation of the game's 20 ms substeps
//       with the game's values (GAME_ROCKETS): the S-5's boost along the launch axis, the other rockets'
//       along the velocity (bRotationFollowsVelocity), speed capped at MaxSpeed
//   MUZZLE  gravity 9.80 and the launch point moving with the elevation (mortar, Hell Cannon, UB-32): the
//       solutions land on the target in the same simulation run with the game's values
//   B9  AGS-17 spread from the game's MOA curve (15 to 50 MOA)
//   B11 a failed heightmap load is announced and marks the solutions
//
// Without SECTION every section runs. Prints one line per check; exits with 1 on any failure.
import { App } from "./stub-app.mjs";

const root = process.argv[2];
const only = process.argv.slice(3);
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

/** SquadCalc's Weapon for a weapons.js entry, with its first shell loaded like Weapon.changeShell */
function makeWeapon(name) {
    const w = WEAPONS.find((weapon) => weapon.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    const shell = w.shells[0];
    weapon.velocity = shell.velocity;
    weapon.moa = shell.moa;
    weapon.minDistance = shell.minDistance;
    // Read by the code before the deceleration was folded into the boost model
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}

/**
 * A squadMinimap stand-in with its own scale on each axis, like squadMinimap.draw: the map image is
 * 256 x 256 units spanning `sizeX` x `sizeY` meters. The oracle converts with the same per-axis rule.
 */
function axisMap(sizeX, sizeY, getHeight = () => 0) {
    const scaleX = sizeX / 256, scaleY = sizeY / 256;
    return {
        pixelSize: 256,
        mapToGameScale: scaleX,
        mapToGameScaleY: scaleY,
        heightmap: { jsonPng: [[0]], getHeight },
        toMeters: (origin, latlng) => ({ east: (latlng.lng - origin.lng) * scaleX, north: (latlng.lat - origin.lat) * scaleY }),
        fromMeters: (origin, east, north) => ({ lat: origin.lat + north / scaleY, lng: origin.lng + east / scaleX }),
    };
}

const sections = {};

sections.B1 = () => {
    // Skorpo's minimap corners: 6849 m along X (lng), 6869 m along Y (lat)
    const map = axisMap(6849, 6869);
    App.activeWeapon = makeWeapon("Mortar");
    const weapon = { lat: -128, lng: 128 };
    for (const [east, north] of [[0, 1000], [0, -1200], [800, 600], [-500, -900]]) {
        const target = { lat: weapon.lat + north / (6869 / 256), lng: weapon.lng + east / (6849 / 256) };
        const solution = new SquadFiringSolution(weapon, target, map, 0);
        const distance = Math.hypot(east, north);
        let bearing = Math.atan2(east, north) * 180 / Math.PI;
        if (bearing < 0) bearing += 360;
        check(`Skorpo ${east} m east, ${north} m north: distance`, Math.abs(solution.distance - distance) < 1e-6,
            `${solution.distance.toFixed(3)} m, expected ${distance.toFixed(3)} m (error ${(solution.distance - distance).toFixed(3)} m)`);
        check(`Skorpo ${east} m east, ${north} m north: bearing`, Math.abs(solution.bearing - bearing) < 1e-6,
            `${solution.bearing.toFixed(4)}°, expected ${bearing.toFixed(4)}°`);
    }
};

sections.B2 = async () => {
    const { default: SquadHeightmap } = await import(`${root}/src/js/squadHeightmaps.js`);
    globalThis.document ??= {};
    globalThis.$ ??= () => ({ trigger() {}, show() {}, hide() {}, text() {}, html() {}, attr() {} });
    // A plane on a 100 x 120 m map: one sample per meter, corners included (101 x 121 samples), level =
    // 3 per meter east + 7 per meter south, 1 cm per level. Both bilinear and triangle interpolation are exact on a plane.
    const width = 101, height = 121, step = 0.01;
    const levels = new Uint16Array(width * height);
    for (let row = 0; row < height; row++) for (let col = 0; col < width; col++) levels[row * width + col] = 3 * col + 7 * row;
    const heightmap = Object.create(SquadHeightmap.prototype);
    heightmap.jsonPng = [];
    heightmap.worker = null;
    heightmap.map = { pixelSize: 256, heightmap, activeMap: { size: 100, sizeY: 120 } };
    heightmap.receive({ levels, width, height, step, precise: true, url: "synthetic" });
    for (const [east, south] of [[0, 0], [37.3, 88.6], [99.5, 0.25], [100, 120], [12.75, 119.9], [50, 60]]) {
        const got = heightmap.getHeight({ lat: -south / 120 * 256, lng: east / 100 * 256 });
        const expected = (3 * east + 7 * south) * step;
        check(`plane heightmap at ${east} m east, ${south} m south`, Math.abs(got - expected) < 1e-9,
            `${got.toFixed(4)} m, expected ${expected.toFixed(4)} m (error ${(got - expected).toFixed(4)} m)`);
    }

    // A peak of 1 m (level 100 at 1 cm) at the centre sample of a 3 x 3 grid, one meter per sample, 0 elsewhere. The
    // game splits a quad along the diagonal from its (row, col) corner to its (row + 1, col + 1) corner. Quad
    // (0, 0) has the peak at that far corner, so its surface is min(east, south); quad (0, 1) has it at its
    // (row + 1, col) corner, off the diagonal: 0 where east - 1 >= south and south - (east - 1) above it.
    // Bilinear interpolation gives east * south and (1 - fx) * fy there.
    const peak = Object.create(SquadHeightmap.prototype);
    peak.jsonPng = [];
    peak.worker = null;
    peak.map = { pixelSize: 256, heightmap: peak, activeMap: { size: 2, sizeY: 2 } };
    peak.receive({ levels: Uint16Array.from([0, 0, 0, 0, 100, 0, 0, 0, 0]), width: 3, height: 3, step: 0.01, precise: true, url: "synthetic" });
    const triangles = [
        [0.5, 0.5, 0.5], [0.75, 0.25, 0.25], [0.25, 0.75, 0.25], [0.5, 0.25, 0.25], [0.25, 0.5, 0.25], [1, 1, 1],
        [1.5, 0.5, 0], [1.75, 0.25, 0], [1.25, 0.75, 0.5],
    ];
    for (const [east, south, expected] of triangles) {
        const got = peak.getHeight({ lat: -south / 2 * 256, lng: east / 2 * 256 });
        check(`peak heightmap at ${east} m east, ${south} m south follows the game's triangles`, Math.abs(got - expected) < 1e-9,
            `${got.toFixed(4)} m, expected ${expected.toFixed(4)} m`);
    }
};

/** App.minimap stand-in for the bridge in smcConnector: one weapon marker and these targets (their firingSolution1) */
function bridgeMinimap(solutions, angleType = "low") {
    const layers = (items) => ({ getLayers: () => items, eachLayer: (callback) => items.forEach(callback) });
    return {
        activeWeaponsMarkers: layers([{ angleType }]),
        activeTargetsMarkers: layers(solutions.map((solution) => ({ firingSolution1: solution }))),
    };
}

sections.B11 = async () => {
    const { default: SquadHeightmap } = await import(`${root}/src/js/squadHeightmaps.js`);
    const { getTargetData } = await import(`${root}/src/js/smcConnector.js`);
    globalThis.document ??= {};
    globalThis.$ ??= () => ({ trigger() {}, show() {}, hide() {}, text() {}, html() {}, attr() {} });
    const toasts = [];
    App.openToast = (type, title, text) => toasts.push([type, title, text]);
    const originalError = console.error;
    console.error = () => {};
    const heightmap = Object.create(SquadHeightmap.prototype);
    heightmap.jsonPng = [];
    heightmap.worker = null;
    heightmap.map = { pixelSize: 256, heightmap };
    heightmap.receive({ error: "TypeError: Failed to fetch", url: "heightmap.png" });
    console.error = originalError;
    check("failed load: error toast", toasts.length === 1 && toasts[0][0] === "error" && toasts[0][1] === "heightmapFailed",
        JSON.stringify(toasts));
    check("failed load: heightmap marked failed", heightmap.failed === true, String(heightmap.failed));

    App.activeWeapon = makeWeapon("Mortar");
    const map = { ...axisMap(4000, 4000), heightmap };
    const solution = new SquadFiringSolution({ lat: -128, lng: 128 }, { lat: -128, lng: 128 + 700 / (4000 / 256) }, map, 0);
    check("failed load: solution has no height data", solution.hasHeightData === false, String(solution.hasHeightData));
    App.minimap = bridgeMinimap([solution], "high");
    const [data] = getTargetData();
    check("failed load: bridge height unknown (null)", data.heightDiff === null, JSON.stringify(data.heightDiff));
};

// Slope (rise over run) under which the miss is read on the height axis instead of the distance axis
const GRAZING = 0.02;

/**
 * Independent simulation of a shot in the game's own steps: the dedicated server moves a projectile in
 * substeps of 20 ms (UProjectileMovementComponent::TickComponent, 50 Hz tick; deadline-squad/squad-ballistics#4),
 * written here from that description and not from squadBallistics.js. Per substep, with v the velocity,
 * R the projectile's rotation and V(R) = (v + (A(R) + g) dt) capped at `maxSpeed`:
 * move p += v dt + (V(R) - v) dt / 2, then R = direction of v when `steered`, then v = V(R). A(R) is the
 * motor: `acceleration` along R in every substep that starts before `boostTime` (R is the launch axis at
 * `angle` until the first turn). The path between two substeps is a straight segment.
 * The projectile starts at the muzzle (`launch`, meters from the pivot's foot, the weapon's ground).
 * @returns {number} - miss in meters: the crossing of the target height closest to `distance` minus
 *   `distance` (NaN if the trajectory never crosses that height); where the path at the target is flatter
 *   than GRAZING (a target at the apex: the crossing moves meters for a micrometer of height), the
 *   height of the path at `distance` minus `height`
 */
function simulateMiss({ velocity, gravity, acceleration, boostTime, steered = false, maxSpeed = 0, launch }, angle, distance, height) {
    const dt = 0.02;
    const boostSteps = acceleration ? Math.ceil(boostTime / dt - 1e-9) : 0;
    const capped = (vx, vy) => {
        const speed = Math.hypot(vx, vy);
        return maxSpeed > 0 && speed > maxSpeed ? [vx * maxSpeed / speed, vy * maxSpeed / speed] : [vx, vy];
    };
    let x = launch.x, y = launch.y, vx = velocity * Math.cos(angle), vy = velocity * Math.sin(angle);
    let rx = Math.cos(angle), ry = Math.sin(angle);
    let best = NaN, flat = NaN;
    for (let step = 0; step < 6000 && x < distance + 3000 && y > height - 3000; step++) {
        const motor = step < boostSteps ? acceleration : 0;
        const [mx, my] = capped(vx + motor * rx * dt, vy + (motor * ry - gravity) * dt);
        const nx = x + vx * dt + (mx - vx) * dt / 2, ny = y + vy * dt + (my - vy) * dt / 2;
        if (steered) {
            const speed = Math.hypot(vx, vy);
            rx = vx / speed;
            ry = vy / speed;
        }
        [vx, vy] = capped(vx + motor * rx * dt, vy + (motor * ry - gravity) * dt);
        if ((y - height) * (ny - height) <= 0 && ny !== y) {
            const crossing = x + (nx - x) * (height - y) / (ny - y);
            if (isNaN(best) || Math.abs(crossing - distance) < Math.abs(best - distance)) best = crossing;
        }
        if (x <= distance && distance < nx && Math.abs(ny - y) < GRAZING * (nx - x)) flat = y + (ny - y) * (distance - x) / (nx - x) - height;
        x = nx;
        y = ny;
    }
    return isNaN(flat) ? best - distance : flat;
}

/**
 * Launch description for simulateMiss: the weapon's velocity and boost, and `launch` (pivotHeight,
 * forward, up; default the weapon's own muzzle model, or heightOffset)
 */
function simulatedShot(weapon, gravity, launch = weapon.muzzle) {
    const muzzle = launch;
    return {
        velocity: weapon.velocity, gravity,
        acceleration: weapon.hasBoost?.() ? weapon.acceleration : (weapon.deceleration ? -weapon.deceleration : 0),
        boostTime: weapon.hasBoost?.() ? weapon.accelerationTime : (weapon.deceleration ? weapon.decelerationTime : 0),
        launchAt: (angle) => (muzzle
            ? { x: muzzle.forward * Math.cos(angle) - muzzle.up * Math.sin(angle), y: muzzle.pivotHeight + muzzle.forward * Math.sin(angle) + muzzle.up * Math.cos(angle) }
            : { x: 0, y: weapon.heightOffset || 0 }),
    };
}

/**
 * Fire every solution of `names` at the cases in the simulation; checks the miss is under `tolerance`
 * @returns {number} - largest miss, meters
 */
function simulateSolutions(label, names, cases, tolerance, game = null, flights = {}) {
    let worst = 0;
    const rows = [];
    for (const name of names) {
        const weapon = makeWeapon(name);
        App.activeWeapon = weapon;
        // The game's gravity and launch point when given, else the weapon's own model
        const gravity = (game ? game.gravity : App.gravity) * weapon.gravityScale;
        // The game's flight when given (GAME_ROCKETS), else the weapon's own
        const shot = { ...simulatedShot(weapon, gravity, game ? game.launch[name] : weapon.muzzle), ...flights[name] };
        const map = axisMap(4000, 4000, (ll) => ll.h ?? 0);
        for (const [distance, height] of cases) {
            const solution = new SquadFiringSolution({ lat: -128, lng: 64, h: 0 }, { lat: -128, lng: 64 + distance / (4000 / 256), h: height }, map, 0);
            for (const arc of ["low", "high"]) {
                const elevation = solution.elevation[arc].rad;
                if (isNaN(elevation)) continue;
                const angle = elevation + (weapon.angleOffset || 0) * Math.PI / 180;
                const miss = simulateMiss({ ...shot, launch: shot.launchAt(angle) }, angle, distance, height);
                rows.push(`${name} ${arc} ${distance} m ${height >= 0 ? "+" : ""}${height} m: ${miss.toFixed(3)}`);
                if (!(Math.abs(miss) <= worst)) worst = Math.abs(miss);
                if (!(Math.abs(miss) < tolerance)) check(`${label}: ${name} ${arc} ${distance} m, height ${height} m`, false, `misses by ${miss.toFixed(3)} m`);
            }
        }
    }
    check(`${label}: ${rows.length} solutions land within ${tolerance} m in the simulation`, worst < tolerance, `largest miss ${worst.toFixed(3)} m`);
    if (process.env.VERBOSE) console.log(rows.join("\n"));
    return worst;
}

// Rockets in the game files (Squad build 26005357), independent of weapons.js: WeaponConfig.MuzzleVelocity,
// the projectile's ConstantAcceleration for ConstantAccelerationTimeout and MaxSpeed (cm -> m), and
// bRotationFollowsVelocity: BP_S5_Proj2 sets it false; the RPG-7 and M3 MAAWS rockets keep the native
// default of SQMortarProjectile, true (S-5 and BP_Proj_Generictank_HE, children of the same class, store
// false, and a cooked asset stores only the values that differ from its parent's)
const RPG_7 = { velocity: 117, acceleration: 150, boostTime: 0.8, maxSpeed: 250, steered: true };
const SPG_9_HEAT = { velocity: 435, acceleration: 100, boostTime: 1.1, maxSpeed: 330, steered: true };
const SPG_9_FRAG = { velocity: 315, acceleration: 100, boostTime: 1.1, maxSpeed: 250, steered: true };
const GROM_FRAG = { velocity: 290, acceleration: 100, boostTime: 1.1, maxSpeed: 250, steered: true };
const GAME_ROCKETS = {
    "UB-32": { velocity: 300, acceleration: -50, boostTime: 2, maxSpeed: 300, steered: false },
    "Tech.UB-32": { velocity: 300, acceleration: -50, boostTime: 2, maxSpeed: 300, steered: false },
    DF_RPG_7_PG_7V_HEAT_OG_7V: RPG_7,
    DF_RPG_7V1_HEAT: RPG_7,
    DF_RPG_7_PG_7VR_Tandem: { velocity: 63, acceleration: 45, boostTime: 0.6, maxSpeed: 160, steered: true },
    DF_RPG_7_TBG_7V_Thermobaric: { velocity: 63, acceleration: 150, boostTime: 0.6, maxSpeed: 160, steered: true },
    DF_M3_MAAWS_HEAT_Smoke: { velocity: 63, acceleration: 230, boostTime: 1.5, maxSpeed: 230, steered: true },
    DF_M3_MAAWS_Tandem: { velocity: 63, acceleration: 230, boostTime: 1.5, maxSpeed: 230, steered: true },
    DF_MK153_SMAW: { velocity: 220, acceleration: 150, boostTime: 0.8, maxSpeed: 220, steered: true },
    DF_PF98_Tandem: { velocity: 310, acceleration: 230, boostTime: 1.5, maxSpeed: 310, steered: true },
    DF_PF98_HE_I: { velocity: 220, acceleration: 180, boostTime: 1.5, maxSpeed: 220, steered: true },
    DF_RPG_29: { velocity: 280, acceleration: 80, boostTime: 1.1, maxSpeed: 280, steered: true },
    DF_Carl_Gustav_M2_FFV551_HEAT: { velocity: 310, acceleration: 150, boostTime: 0.8, maxSpeed: 310, steered: true },
    DF_Carl_Gustav_M2_FFV751_Tandem: { velocity: 255, acceleration: 230, boostTime: 1.5, maxSpeed: 230, steered: true },
    DF_SPG_9_HEAT: SPG_9_HEAT,
    DF_SPG_9_HEAT_scope: SPG_9_HEAT,
    DF_SPG_9_HEAT_scope_no_optic: SPG_9_HEAT,
    DF_SPG_9_FRAG: SPG_9_FRAG,
    DF_SPG_9_FRAG_scope: SPG_9_FRAG,
    DF_SPG_9_FRAG_scope_no_optic: SPG_9_FRAG,
    DF_2A28_Grom_BMP_1_BMD_1_HEAT: SPG_9_HEAT,
    DF_2A28_Grom_BMD_1M_HEAT: SPG_9_HEAT,
    DF_2A28_Grom_BMP_1_BMD_1_FRAG: GROM_FRAG,
    DF_2A28_Grom_BMD_1M_FRAG: GROM_FRAG,
};

sections.B7 = async () => {
    // Rockets under gravity (NLAW flies the straight line of sight, without this model)
    const rockets = WEAPONS.filter((w) => (w.acceleration || w.deceleration) && w.gravityScale > 0).map((w) => w.name);
    const missing = rockets.filter((name) => !GAME_ROCKETS[name]);
    check("boost model: every rocket has its game values", missing.length === 0, missing.join(", ") || `${rockets.length} rockets`);
    const cases = [100, 300, 500, 800, 1200, 1600, 2000].flatMap((d) => [-40, 0, 25].map((h) => [d, h]));
    simulateSolutions("boost model", rockets, cases, 0.5, null, GAME_ROCKETS);

    // The search finds every root: on a 0.05° grid the error changes sign only between low and high
    const { pathAt, solveElevation } = await import(`${root}/src/js/squadBallistics.js`);
    let extra = 0;
    for (const name of rockets) {
        const weapon = makeWeapon(name);
        App.activeWeapon = weapon;
        const shot = weapon.getShot(App.gravity * weapon.gravityScale);
        for (const [distance, height] of cases) {
            const { low, high } = solveElevation(shot, distance, height);
            let signs = 0, previous = null;
            for (let degrees = -89.9; degrees < 89.9; degrees += 0.05) {
                const sign = Math.sign(pathAt(shot, degrees * Math.PI / 180, distance).height - height);
                if (previous !== null && sign !== previous) signs++;
                previous = sign;
            }
            if (signs !== (isNaN(low) ? 0 : 2)) extra++;
        }
    }
    check("boost model: exactly the two roots found (dense scan)", extra === 0, `${extra} case(s) with other sign changes`);
};

// Game data (Squad build 26005357), independent of weapons.js and app.js: DefaultGravityZ = -980 cm/s²
// (no layer overrides it) and where each weapon's BarrelSocketName (Attach_Muzzle) sits: pivot height
// above the ground, then along and above the barrel axis, in meters (tube, swivel and tripod skeletons)
const GAME = {
    gravity: 9.80,
    launch: {
        Mortar: { pivotHeight: 0.0245, forward: 1.569, up: 0.002 },
        HellCannon: { pivotHeight: 0.155, forward: 2.373, up: 0.002 },
        "UB-32": { pivotHeight: 1.3075, forward: 1.430, up: 0.251 },
    },
};

sections.MUZZLE = () => {
    check("world gravity is the game's", App.gravity === GAME.gravity, `${App.gravity} m/s², game ${GAME.gravity} m/s²`);
    const cases = [60, 150, 300, 500, 800, 1000, 1200, 1500, 2000].flatMap((d) => [-40, 0, 25].map((h) => [d, h]));
    simulateSolutions("game launch point", Object.keys(GAME.launch), cases, 0.5, GAME);
};

sections.B9 = () => {
    // FC_MOACurve_GenericGMG of BP_AGS-17_Weapon (Squad build 26005357): 15 MOA at rest, 50 MOA in a
    // sustained burst. SquadCalc draws the sustained envelope: full cone angle of 50 MOA.
    const weapon = makeWeapon("AGS-17");
    App.activeWeapon = weapon;
    const map = axisMap(4000, 4000);
    const solution = new SquadFiringSolution({ lat: -128, lng: 64 }, { lat: -128, lng: 64 + 1000 / (4000 / 256) }, map, 0);
    const cone = (50 / 60) * Math.PI / 180;
    const expected = Math.sin(cone) * solution.velocity * solution.timeOfFlight.high;
    const got = solution.spreadParameters.high.semiMajorAxis;
    check("AGS-17 spread from the game's MOA curve (50 MOA envelope)", Math.abs(got - expected) < 1e-6,
        `lateral spread at 1000 m ${got.toFixed(2)} m, expected ${expected.toFixed(2)} m (moa ${weapon.moa})`);
};

sections.B6 = async () => {
    // Squad Ballistics' Weapon.time_to: 300 m/s, -50 m/s² for 2 s (the boost covers 500 m)
    const timeTo = (d) => {
        const v0 = 300, a = -50, boostTime = 2;
        const boostDistance = v0 * boostTime + 0.5 * a * boostTime ** 2;
        if (d <= boostDistance) return (Math.sqrt(v0 ** 2 + 2 * a * d) - v0) / a;
        return boostTime + (d - boostDistance) / (v0 + a * boostTime);
    };
    for (const name of ["UB-32", "Tech.UB-32"]) {
        const weapon = makeWeapon(name);
        for (const d of [50, 200, 400, 500, 650, 1200]) {
            const expected = d / timeTo(d);
            const got = weapon.getVelocity(d);
            check(`${name} equivalent velocity at ${d} m`, Math.abs(got - expected) < 1e-9, `${got.toFixed(4)} m/s, expected ${expected.toFixed(4)} m/s`);
        }
    }
    const sb = process.env.SQUAD_BALLISTICS;
    if (!sb) return;
    const { execFileSync } = await import("node:child_process");
    const distances = [50, 200, 400, 500, 650, 1200];
    const sbVelocities = JSON.parse(execFileSync(`${sb}/.venv/bin/python`, ["-I", "-c", [
        "import json, sys", `sys.path.insert(0, ${JSON.stringify(sb)})`, "from ballistics import load_weapons",
        `w = load_weapons(${JSON.stringify(sb + "/weapons.json")})["UB-32 (S-5 rockets)"]`,
        `print(json.dumps([w.velocity_at(d) for d in ${JSON.stringify(distances)}]))`,
    ].join("\n")], { encoding: "utf8" }));
    const weapon = makeWeapon("UB-32");
    const worst = Math.max(...distances.map((d, i) => Math.abs(weapon.getVelocity(d) - sbVelocities[i])));
    check("UB-32 velocity equals Squad Ballistics' velocity_at", worst < 1e-9, `largest difference ${worst.toExponential(2)} m/s`);
};

const selected = only.length ? only : Object.keys(sections);
for (const name of selected) {
    console.log(`== ${name}`);
    try {
        await sections[name]();
    } catch (error) {
        check(name, false, `threw ${error.stack.split("\n").slice(0, 2).join(" ")}`);
    }
}
console.log(failures ? `${failures} failure(s)` : "all checks passed");
process.exit(failures ? 1 : 0);
