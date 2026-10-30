// Solve cases with the real SquadCalc Weapon + SquadFiringSolution; print JSON lines.
// Every shell of every weapon with a `ballistics` name is solved on the given (distance, height) cases and,
// for the weapons that fly a gravity trajectory, on a few more distances around the weapon's own maximum
// range (fractions NEAR_MAX of getMaxDistance) at NEAR_MAX_HEIGHTS.
import { App } from "./stub-app.mjs";
const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);
const cases = JSON.parse(process.argv[3]);
const NEAR_MAX = [0.5, 0.9, 0.99, 0.999, 1.001, 1.01];
const NEAR_MAX_HEIGHTS = [-40, 0, 25];
const out = [];
for (const w of WEAPONS) {
    if (!w.ballistics) continue;
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image, w.muzzle, w.maxSpeed, w.rotationFollowsVelocity);
    // 1 map unit = 1 m; the target's height is carried in its LatLng
    const map = {
        mapToGameScale: 1,
        mapToGameScaleY: 1,
        toMeters: (origin, ll) => ({ east: ll.lng - origin.lng, north: ll.lat - origin.lat }),
        heightmap: { getHeight: (ll) => ll.h },
    };
    for (const shell of w.shells) {
        weapon.velocity = shell.velocity;
        weapon.moa = shell.moa;
        weapon.minDistance = shell.minDistance;
        weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
        App.activeWeapon = weapon;
        const max = weapon.getMaxDistance();
        const all = cases.map(([distance, height]) => [distance, height, false]);
        if (w.gravityScale !== 0) {
            for (const fraction of NEAR_MAX) for (const height of NEAR_MAX_HEIGHTS) all.push([max * fraction, height, true]);
        }
        for (const [distance, height, nearMax] of all) {
            const fs = new SquadFiringSolution({ lat: 0, lng: 0, h: 0 }, { lat: 0, lng: distance, h: height }, map, 0);
            out.push({
                name: w.ballistics, shell: shell.name, type: w.type, distance, height, nearMax,
                low: fs.elevation.low.deg, sight: fs.getSightAngle(fs.elevation.low.rad), high: fs.elevation.high.deg,
                tofLow: fs.timeOfFlight.low, tofHigh: fs.timeOfFlight.high, hold: fs.holdTime.high,
                max, velocity: shell.velocity, minDistance: shell.minDistance, minElevation: w.minElevation,
            });
        }
    }
}
console.log(JSON.stringify(out));
