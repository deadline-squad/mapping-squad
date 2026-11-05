// Print SquadCalc's WEAPONS array (src/data/weapons.js) as JSON, for tools/game_ballistics/provenance.py.
//   node --import ./register.mjs weapons_json.mjs <SquadCalc checkout>
import "./stub-app.mjs";
const { WEAPONS } = await import(`${process.argv[2]}/src/data/weapons.js`);
console.log(JSON.stringify(WEAPONS));
