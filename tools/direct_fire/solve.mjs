// Solve cases with the real SquadCalc Weapon + SquadFiringSolution; print JSON lines.
import { App } from "./stub-app.mjs";
const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { default: SquadFiringSolution } = await import(`${root}/src/js/squadFiringSolution.js`);
const cases = JSON.parse(process.argv[3]);
const out = [];
for (const w of WEAPONS) {
    if (!w.ballistics) continue;
    const weapon = new Weapon(w.name, w.deceleration, w.decelerationTime, w.gravityScale, w.minElevation, w.unit, w.logo, w.marker, w.type, w.angleType, w.elevationPrecision, w.shells, w.heightOffset, w.angleOffset, w.projectileLifespan, w.mod, w.elevationRate, w.heatmap, w.acceleration, w.accelerationTime, w.holdElevation, w.ballistics, w.image);
    const shell = w.shells[0];
    weapon.velocity = shell.velocity;
    weapon.moa = shell.moa;
    weapon.minDistance = shell.minDistance;
    weapon.decelerationDistance = weapon.velocity * weapon.decelerationTime - 0.5 * weapon.deceleration * weapon.decelerationTime ** 2;
    App.activeWeapon = weapon;
    // 1 map unit = 1 m; the target's height is carried in its LatLng
    const map = { mapToGameScale: 1, heightmap: { getHeight: (ll) => ll.h } };
    for (const [distance, height] of cases) {
        const fs = new SquadFiringSolution({ lat: 0, lng: 0, h: 0 }, { lat: 0, lng: distance, h: height }, map, 0);
        out.push({ name: w.ballistics, type: w.type, distance, height, low: fs.elevation.low.deg, high: fs.elevation.high.deg, tofLow: fs.timeOfFlight.low, hold: fs.holdTime.high, max: weapon.getMaxDistance() });
    }
}
console.log(JSON.stringify(out));
