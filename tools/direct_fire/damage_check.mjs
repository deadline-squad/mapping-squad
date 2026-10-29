// Check SquadCalc's explosion damage with cover and hit probability (squadDamage.js) on synthetic terrain.
//
//     node --import ./register.mjs damage_check.mjs <SquadCalc checkout>
//
// Oracles: on flat ground the kill and wound zones are the circles SquadCalc already draws
// (Weapon.calculateDistanceForDamage); a wall or a roof hides the soldiers behind it; with a circular
// spread on flat ground the kill probability is the area ratio (kill radius / spread radius)^2.
// Exits with 1 on any failure.
import "./stub-app.mjs";

const root = process.argv[2];
const { WEAPONS } = await import(`${root}/src/data/weapons.js`);
const { Weapon } = await import(`${root}/src/js/squadWeapons.js`);
const { damageField, impactDamage, hitProbability, roundsNeeded, KILL_DAMAGE, WOUND_DAMAGE } = await import(`${root}/src/js/squadDamage.js`);

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const explosionOf = (shell) => ({
    damage: shell.explosionDamage,
    inner: shell.explosionRadius[0],
    outer: shell.explosionRadius[1],
    falloff: shell.damageFallOff,
    distanceFromImpact: shell.explosionDistanceFromImpact,
});
const circles = (shell, damage) => Weapon.prototype.calculateDistanceForDamage(
    shell.explosionDamage, shell.explosionRadius[0], shell.explosionRadius[1], shell.damageFallOff, shell.explosionDistanceFromImpact, damage);
const flat = () => 0;

// 1. Flat ground: the zones match SquadCalc's circles (to one cell)
const CELL = 0.5;
for (const [name, shellIndex] of [["Mortar", 0], ["M1064M121", 0], ["M1064M121", 1], ["HellCannon", 0], ["AGS-17", 0], ["BM-21Grad", 0]]) {
    const shell = WEAPONS.find((w) => w.name === name).shells[shellIndex];
    const field = damageField(flat, explosionOf(shell), CELL);
    const half = (field.size - 1) / 2;
    // Radius along the east axis where the damage last reaches a threshold
    const reach = (threshold) => {
        let last = -1;
        for (let col = half; col < field.size; col++) if (field.damage[half * field.size + col] >= threshold) last = col - half;
        return last * CELL;
    };
    for (const [threshold, label] of [[KILL_DAMAGE, "kill"], [WOUND_DAMAGE, "wound"]]) {
        const expected = circles(shell, threshold);
        const got = reach(threshold);
        const ok = Number.isNaN(expected) ? got < 0 : Math.abs(got - expected) <= CELL;
        check(`${name}/${shell.name} flat ${label} radius`, ok, `${got} m vs circle ${Number.isNaN(expected) ? "none" : expected.toFixed(2)} m`);
    }
    check(`${name}/${shell.name} flat: nothing covered`, field.damage.every((d, i) => d === field.exposed[i]), "no cover on flat ground");
}

// 2. A 3 m wall from 10 to 12 m east of the impact hides the soldiers behind it, not the others
const mortar = explosionOf(WEAPONS.find((w) => w.name === "Mortar").shells[0]);
const wall = (east) => (east >= 10 && east <= 12 ? 3 : 0);
const behind = impactDamage(wall, mortar, { east: 0, north: 0 }, { east: 16, north: 0 });
const front = impactDamage(wall, mortar, { east: 0, north: 0 }, { east: -16, north: 0 });
const beside = impactDamage(wall, mortar, { east: 0, north: 0 }, { east: 0, north: 16 });
check("wall: soldier 16 m behind it", behind.covered && behind.damage === 0, JSON.stringify(behind));
check("wall: soldier 16 m on the open side", !front.covered && front.damage > 0, JSON.stringify(front));
check("wall: soldier 16 m beside the impact, along the wall", !beside.covered && beside.damage > 0, JSON.stringify(beside));
check("wall: open side and side take the same damage", Math.abs(front.damage - beside.damage) < 1e-6, `${front.damage} / ${beside.damage}`);

// 3. Low cover: a 0.5 m kerb does not hide a standing soldier (the trace goes to his body centre)
const kerb = (east) => (east >= 10 && east <= 11 ? 0.5 : 0);
const overKerb = impactDamage(kerb, mortar, { east: 0, north: 0 }, { east: 16, north: 0 });
check("0.5 m kerb: standing soldier behind it is hit", !overKerb.covered && overKerb.damage > 0, JSON.stringify(overKerb));

// A wall 2 m from the impact already shields: only the impact's own meter is skipped
const nearWall = (east) => (east >= 2 && east <= 3 ? 3 : 0);
const nearShield = impactDamage(nearWall, mortar, { east: 0, north: 0 }, { east: 8, north: 0 });
check("3 m wall 2 m from the impact", nearShield.covered && nearShield.damage === 0, JSON.stringify(nearShield));

// The explosion has to see the body centre: a 1.2 m wall right in front of a standing soldier hides it
const chestWall = (east) => (east >= 14 && east <= 15 ? 1.2 : 0);
const atWall = impactDamage(chestWall, mortar, { east: 0, north: 0 }, { east: 16, north: 0 });
check("1.2 m wall just in front of the soldier", atWall.covered && atWall.damage === 0, JSON.stringify(atWall));

// 4. A round on a 6 m roof (10 x 10 m building) does not reach the street behind the building
const building = (east, north) => (Math.abs(east) <= 5 && Math.abs(north) <= 5 ? 6 : 0);
const street = impactDamage(building, mortar, { east: 0, north: 0 }, { east: 9, north: 0 });
check("roof impact: soldier in the street 4 m from the wall", street.covered && street.damage === 0, JSON.stringify(street));

// 5. Circular spread on flat ground: kill probability = (kill radius / spread radius)^2
for (const spread of [30, 50]) {
    const shell = WEAPONS.find((w) => w.name === "Mortar").shells[0];
    const killRadius = circles(shell, KILL_DAMAGE);
    const expected = Math.min(1, (killRadius / spread) ** 2);
    const { kill } = hitProbability(flat, explosionOf(shell), spread, spread, 37);
    check(`Mortar spread radius ${spread} m: kill probability`, Math.abs(kill - expected) <= 0.02, `${kill.toFixed(3)} vs ${expected.toFixed(3)}`);
}
const noSpread = hitProbability(flat, mortar, 0, 0, 0);
check("no spread: a direct hit kills", noSpread.kill === 1 && noSpread.wound === 1, JSON.stringify(noSpread));

// 6. Elliptic spread: rotating the line of fire on flat ground does not change the probability
const p0 = hitProbability(flat, mortar, 40, 15, 0).kill;
const p90 = hitProbability(flat, mortar, 40, 15, 90).kill;
check("elliptic spread: same probability whatever the bearing", Math.abs(p0 - p90) < 1e-9, `${p0} / ${p90}`);

// 7. Rounds for 90 %
check("rounds: p = 0.5 -> 4", roundsNeeded(0.5) === 4, roundsNeeded(0.5));
check("rounds: p = 0.9 -> 1", roundsNeeded(0.9) === 1, roundsNeeded(0.9));
check("rounds: p = 0.1 -> 22", roundsNeeded(0.1) === 22, roundsNeeded(0.1));
check("rounds: p = 0 -> never", roundsNeeded(0) === Infinity, roundsNeeded(0));

console.log(failures ? `${failures} damage checks failed` : "all damage checks passed");
process.exit(failures ? 1 : 0);
