// Checks SquadFiringSolution.getObstacle with the real SquadCalc code on synthetic terrain:
// flat ground at 0 m and an optional wall across the line of fire. Exits 1 on the first failure.
// Usage: node --import ./register.mjs obstacle_check.mjs <SquadCalc root>
import { App } from "./stub-app.mjs";
const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);

function load(name) {
    const w = WEAPONS.find((weapon) => weapon.name === name);
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    weapon.velocity = w.shells[0].velocity;
    weapon.moa = w.shells[0].moa;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    return weapon;
}

// squadMinimap.toMeters with 1 map unit = 1 m
const toMeters = (origin, ll) => ({ east: ll.lng - origin.lng, north: ll.lat - origin.lat });

// 1 map unit = 1 m along lng; a wall of `height` m covers lng [from, from + 2)
function solve(weaponName, distance, wall) {
    App.activeWeapon = load(weaponName);
    const getHeight = (ll) => (wall && ll.lng >= wall.from && ll.lng < wall.from + 2 ? wall.height : 0);
    const map = { mapToGameScale: 1, mapToGameScaleY: 1, toMeters, heightmap: { jsonPng: [[0]], getHeight } };
    return new SquadFiringSolution({ lat: 0, lng: 0 }, { lat: 0, lng: distance }, map, 0);
}

// The fastest direct-fire weapon: its low trajectory stays within a metre of the line of sight at 300 m
const direct = WEAPONS.filter((weapon) => weapon.type === "directFire")
    .reduce((best, weapon) => (weapon.shells[0].velocity > best.shells[0].velocity ? weapon : best)).name;
let failures = 0;
function expect(label, actual, check) {
    const ok = check(actual);
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${JSON.stringify(actual)}`);
    if (!ok) failures++;
}

expect(`${direct} 300 m, flat ground: low clear`, solve(direct, 300).obstacle.low, (o) => o === null);
expect(`${direct} 300 m, 10 m wall at 150 m: low blocked there`, solve(direct, 300, { from: 150, height: 10 }).obstacle.low,
    (o) => o !== null && o.distance >= 150 && o.distance < 152 && Math.abs(o.height - 10) < 1e-9);
// The muzzle is at the shoulder (1.5 m) for weapons without heightOffset: a 0.3 m hump just in front of
// the weapon is not an obstacle, as it would be for a trajectory starting on the ground
expect(`${direct} 300 m, 0.3 m hump 3-5 m in front: clear`, solve(direct, 300, { from: 3, height: 0.3 }).obstacle.low, (o) => o === null);
expect(`${direct} 300 m, wall at 1 m (weapon's own spot): ignored`, solve(direct, 300, { from: 1, height: 10 }).obstacle.low, (o) => o === null);
expect(`${direct} 300 m, wall 1 m before the target: ignored`, solve(direct, 300, { from: 298.5, height: 10 }).obstacle.low, (o) => o === null);
expect("Mortar 400 m, 20 m wall at 200 m: high lob clears it", solve("Mortar", 400, { from: 200, height: 20 }).obstacle.high, (o) => o === null);
expect("Mortar 400 m, 60 m wall 5 m in front: high lob blocked", solve("Mortar", 400, { from: 5, height: 60 }).obstacle.high,
    (o) => o !== null && o.distance >= 5 && o.distance < 7);
expect("Mortar 400 m, no heightmap loaded: no obstacle", (() => {
    App.activeWeapon = load("Mortar");
    const map = { mapToGameScale: 1, mapToGameScaleY: 1, toMeters, heightmap: { jsonPng: [], getHeight: () => 1000 } };
    return new SquadFiringSolution({ lat: 0, lng: 0 }, { lat: 0, lng: 400 }, map, 0).obstacle.high;
})(), (o) => o === null);

if (failures) {
    console.log(`${failures} failure(s)`);
    process.exit(1);
}
console.log("all obstacle checks passed");
