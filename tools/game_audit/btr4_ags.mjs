// BTR-4 AGS, the open difference O1 of docs/game-data-audit.md in numbers: where a shot lands on level ground for a
// reading of the gunner's display, with SquadCalc's hand-kept entry "BTR4-AGS" (launch height and barrel offset of
// its upstream) and with the launch point and barrel offset of the game files, which Squad Ballistics' entry
// "AGS-30 / BTR-4 AGS" carries (launch_height, muzzle_forward, muzzle_up, bore). Both with SquadCalc's solver.
//   node --import ../direct_fire/register.mjs btr4_ags.mjs <SquadCalc checkout> <Squad-Ballistics checkout>
import { readFileSync } from "node:fs";
import { levelRange } from "./level_range.mjs";

const [calculatorRoot, ballisticsRoot] = process.argv.slice(2);
const { WEAPONS } = await import(`${calculatorRoot}/src/data/weapons.js`);
const { heightAt, maxRange } = await import(`${calculatorRoot}/src/js/squadBallistics.js`);
const READINGS = [0, 2, 5, 10, 20];
const GRAVITY = 9.8;

const kept = WEAPONS.find((weapon) => weapon.name === "BTR4-AGS");
const files = JSON.parse(readFileSync(`${ballisticsRoot}/weapons.json`, "utf8"))["AGS-30 / BTR-4 AGS"];
const flight = { velocity: kept.shells[0].velocity, gravity: GRAVITY * kept.gravityScale, acceleration: 0, boostTime: 0, maxSpeed: 0, rotationFollowsVelocity: true };
const models = {
    "SquadCalc entry": { shot: { ...flight, pivotHeight: kept.heightOffset, muzzleForward: 0, muzzleUp: 0 }, barrelAboveReading: kept.angleOffset },
    "game files": { shot: { ...flight, pivotHeight: files.launch_height, muzzleForward: files.muzzle_forward, muzzleUp: files.muzzle_up }, barrelAboveReading: files.bore },
};

for (const [label, { shot, barrelAboveReading }] of Object.entries(models)) {
    const far = maxRange(shot) * 1.001;
    const ranges = READINGS.map((reading) => {
        const angle = (reading + barrelAboveReading) * Math.PI / 180;
        return `${reading} deg: ${levelRange((distance) => heightAt(shot, angle, distance), far).toFixed(0)} m`;
    });
    console.log(`${label} (launch ${shot.pivotHeight} m, barrel ${barrelAboveReading.toFixed(4)} deg above the reading): ${ranges.join(", ")}`);
}
