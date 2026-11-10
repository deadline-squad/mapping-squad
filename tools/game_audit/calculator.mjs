// SquadCalc's data and what its solver gives at the stops of the game's mounts, as JSON for check_calculator.py.
//   node --import ../direct_fire/register.mjs calculator.mjs <SquadCalc checkout> <mount_limits.json>
// Printed: the version, per weapon of mount_limits.json its elevation limits, scale offset and, per shell, the
// minimum distance, the range on level ground at each end of the gunner's reading in the game, the longest shot
// the mount allows and the longest at any elevation; the maps' landscape, minimap and FOB radius fields; the layers
// with the small FOB radius; the radius of the range circle of the mortar and hell cannon markers.
import { readFileSync } from "node:fs";
import { levelRange } from "./level_range.mjs";

const root = process.argv[2];
const mounts = JSON.parse(readFileSync(process.argv[3], "utf8"));
const { version } = JSON.parse(readFileSync(`${root}/package.json`, "utf8"));
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { MAPS, SMALL_FOB_LAYERS } = await import(`${root}/src/data/maps.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { heightAt, maxRange } = await import(`${root}/src/js/squadBallistics.js`);

// Step of the search for the longest shot between the stops: the range changes by under 0.01 m per 0.1 degree there
const REACH_STEP = 0.1;
const GRAVITY = 9.8;

/** The shot of one shell of a weapons.js entry, as SquadCalc's own loader builds it. */
function shotOf(entry, shell) {
    const weapon = new Weapon(entry.name, entry.deceleration, entry.decelerationTime, entry.gravityScale, entry.minElevation, entry.unit, entry.logo, entry.marker, entry.type, entry.angleType, entry.elevationPrecision, entry.shells, entry.heightOffset, entry.angleOffset, entry.projectileLifespan, entry.mod, entry.elevationRate, entry.heatmap, entry.acceleration, entry.accelerationTime, entry.holdElevation, entry.ballistics, entry.image, entry.muzzle, entry.maxSpeed, entry.rotationFollowsVelocity, entry.legacyBallistics, entry.ballisticsViews);
    weapon.velocity = shell.velocity;
    return weapon.getShot(GRAVITY * entry.gravityScale);
}

/** Range on level ground of a shot at a barrel elevation in degrees. */
function rangeAt(shot, longest, degrees) {
    const angle = degrees * Math.PI / 180;
    return levelRange((distance) => heightAt(shot, angle, distance), longest * 1.001);
}

const weapons = [];
for (const [name, mount] of Object.entries(mounts)) {
    const entry = WEAPONS.find((weapon) => weapon.name === name);
    if (!entry) continue;
    const offset = entry.angleOffset || 0;
    const [low, high] = mount.reading.map((reading) => reading + offset);
    const shells = entry.shells.map((shell) => {
        const shot = shotOf(entry, shell);
        const longest = maxRange(shot);
        let reach = Math.max(rangeAt(shot, longest, low), rangeAt(shot, longest, high));
        for (let degrees = low; degrees < high; degrees += REACH_STEP) reach = Math.max(reach, rangeAt(shot, longest, degrees));
        return { name: shell.name, minDistance: shell.minDistance, atLowStop: rangeAt(shot, longest, low), atHighStop: rangeAt(shot, longest, high), reach, maxRange: longest };
    });
    weapons.push({ name, minElevation: entry.minElevation, angleOffset: offset, angleType: entry.angleType, shells });
}

const minimap = readFileSync(`${root}/src/js/squadMinimap.js`, "utf8");
const circles = {};
for (const [icon, name] of [["deployable_mortars", "Mortar"], ["deployable_hellcannon", "HellCannon"]]) {
    const entry = WEAPONS.find((weapon) => weapon.name === name);
    circles[name] = { radius: Number(minimap.match(new RegExp(`icon === "${icon}"\\) range = (\\d+);`))[1]), maxRange: maxRange(shotOf(entry, entry.shells[0])) };
}

console.log(JSON.stringify({
    version,
    weapons,
    maps: MAPS.map((map) => ({ name: map.name, radiusExclusion: map.radiusExclusion, heightmap: map.SDK_data.heightmap, minimap: map.SDK_data.minimap })),
    smallFobLayers: [...SMALL_FOB_LAYERS].sort(),
    circles,
}));
