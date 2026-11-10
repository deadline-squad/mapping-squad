// Checks the in-game-style grid of the Deadline SquadCalc in Chromium against the game's (Squad dedicated server build
// 26005357: MapTextureCorner0/1 of the layer's SQWorldSettings, MapLocationToGridCoordinateString,
// W_SQMapHorizontalBar/VerticalBar): where the grid starts and ends, its letters and numbers, the keypad text of the map
// and where the game's own keypad text lands when it is typed.
//
//     node grid_check.mjs <site URL>
//
// Skorpo without a layer: the grid starts 9.5 m east of its image (SDK_data.minimap.game). Chora with the layer
// Chora_Skirmish_v1 (needs the layer API): it starts 1007 m east and 1222 m south and ends at the layer's far edges,
// and returns to the map's corner when the layer is cleared. Al Basrah without a layer: a grid at the image's corner.
// On each: the keypad text 1 m inside the corners and at the middle is the game's (the calculator pads the row,
// C03-3-7 for the game's C3 - 3 - 7) and the box under the cursor shows it, none outside the grid; the game's text,
// typed with its spaces, without them and padded, lands in the 33.3 m square it names; the letters and numbers are the game's,
// the last one at the middle of the strip left after the last whole keypad, along the grid's north and west edges;
// no line or label lies outside the grid. Environment as browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node grid_check.mjs <site URL>");
    process.exit(2);
}
let failures = 0;
const check = (label, ok, detail) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
};

// The game's grid of each case: its corners (world metres, +X east, +Y south), letters, number of rows, the middle of
// the last column and row, its text at points 1 m inside the corners and at the middle (the middle is points[4]) and
// points where it gives no keypad
const CASES = [
    {
        name: "Skorpo",
        min: [-3601.5, -3293], max: [3248.5, 3576.08], columns: "ABCDEFGHIJKLMNOPQRSTUVW", rows: 23, last: [3123.5, 3441.54],
        points: [[[-3600.5, -3292], "A1 - 7 - 7"], [[3247.5, -3292], "W1 - 9 - 8"], [[-3600.5, 3575.08], "A23 - 1 - 1"], [[3247.5, 3575.08], "W23 - 3 - 2"], [[-176, 142.04], "L12 - 5 - 4"], [[-3306.5, -3183], "A1 - 6 - 9"]],
        outside: [[-3605, 0]],
    },
    {
        name: "Chora_Skirmish_v1",
        min: [-1456.8422, -1442.0139], max: [163.15789, 177.98627], columns: "ABCDEF", rows: 6, last: [103.1578, 117.9862],
        points: [[[-1455.8422, -1441.0139], "A1 - 7 - 7"], [[162.1579, -1441.0139], "F1 - 8 - 7"], [[-1455.8422, 176.9863], "A6 - 4 - 7"], [[162.1579, 176.9863], "F6 - 5 - 7"], [[-646.34, -631.51], "C3 - 3 - 7"]],
        outside: [[-2000, -2000], [500, 500], [-1460, -600], [-600, 180]],
    },
    {
        name: "AlBasrah",
        min: [-2000, -2000], max: [2000, 2000], columns: "ABCDEFGHIJKLMN", rows: 14, last: [1950, 1950],
        points: [[[-1999, -1999], "A1 - 7 - 7"], [[1999, -1999], "N1 - 7 - 9"], [[-1999, 1999], "A14 - 7 - 1"], [[1999, 1999], "N14 - 7 - 3"], [[0.5, 0.5], "G7 - 3 - 7"]],
        outside: [],
    },
];

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    const patched = body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={");
    if (patched === body) throw new Error("window.squadBallistics not found in the main bundle");
    await route.fulfill({ response, body: patched });
});
const page = await context.newPage();
const problems = [];
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

/** The grid's origin offset (m) and the longitude of its first keypad line in metres east of the image corner */
const gridState = () => page.evaluate(() => {
    const map = window.__App.minimap;
    const vertical = map.grid.kpLines.map((line) => line.getLatLngs()).filter(([a, b]) => a.lng === b.lng).map(([a]) => a.lng);
    const horizontal = map.grid.kpLines.map((line) => line.getLatLngs()).filter(([a, b]) => a.lat === b.lat).map(([a]) => a.lat);
    return {
        offset: map.grid.originOffset,
        firstEast: Math.min(...vertical) * map.mapToGameScale,
        firstSouth: -Math.max(...horizontal) * map.mapToGameScaleY,
        map: map.activeMap.name,
    };
});

/** The calculator's form of a game text: no spaces, the row with two digits */
const padded = (text) => text.replace(/\s/g, "").replace(/^([A-Z])(\d+)/, (_, letter, row) => `${letter}${row.padStart(2, "0")}`);
/** The forms of a game text a player types: as the game prints it, without its spaces, padded as the calculator prints it */
const typedForms = (text) => [text, text.replace(/\s/g, ""), padded(text)];

/** What the page shows of a case's grid, in world metres: keypad texts, the cursor box, entries, labels, lines */
const inspect = (c) => page.evaluate(({ c, typed }) => {
    const App = window.__App, map = App.minimap, minimap = map.activeMap.SDK_data.minimap;
    const imageMin = [Math.min(minimap.corner0[0], minimap.corner1[0]), Math.min(minimap.corner0[1], minimap.corner1[1])];
    const toMap = ([x, y]) => ({ lat: -(y - imageMin[1]) * map.gameToMapScaleY, lng: (x - imageMin[0]) * map.gameToMapScale });
    const toWorld = ({ lat, lng }) => [imageMin[0] + lng * map.mapToGameScale, imageMin[1] - lat * map.mapToGameScaleY];
    const textAt = (at) => { const point = toMap(at); return map.getKP(-point.lat, point.lng, 4); };
    // the box shows as many sub-keypads as the zoom allows: two, as many as the game prints, at zoom 4
    const cursorBoxAt = (at) => {
        map.setView(toMap(at), 4, { animate: false });
        map.updateMouseLocationPopup(toMap(at));
        const text = map.mouseLocationPopup.isOpen() ? map.mouseLocationPopup.getElement().textContent.trim() : null;
        map.mouseLocationPopup.close();
        return text;
    };
    // getPos gives metres east (lat) and south (lng) of the image's corner
    const entry = (text) => { const pos = App.getPos(text); return [imageMin[0] + pos.lat, imageMin[1] + pos.lng]; };
    const labels = map.grid.labels.map((label) => ({ text: String(label.options.icon.options.html), at: toWorld(label.getLatLng()) }));
    const lines = [...map.grid.kpLines, ...map.grid.s1Lines, ...map.grid.s2Lines].flatMap((line) => line.getLatLngs().map(toWorld));
    return {
        layer: map.layer?.layerData?.rawName ?? null,
        texts: c.points.map(([at]) => textAt(at)),
        cursorBox: cursorBoxAt(c.points[4][0]),
        outsideTexts: c.outside.map(textAt),
        outsideBoxes: c.outside.map(cursorBoxAt),
        entries: typed.map((forms) => forms.map(entry)),
        columns: labels.filter((label) => /^[A-Z]$/.test(label.text)),
        rows: labels.filter((label) => /^\d+$/.test(label.text)),
        lineBox: [0, 1].map((i) => [Math.min(...lines.map((point) => point[i])), Math.max(...lines.map((point) => point[i]))]),
        dom: [...document.querySelectorAll(".gridText")].map((element) => element.textContent.trim()),
    };
}, { c, typed: c.points.map(([, text]) => typedForms(text)) });

const ready = () => page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !window.__App.minimap._spinning, null, { timeout: 120000 });
const near = (a, b) => Math.abs(a - b) < 0.05;
const square = (point, min) => point.map((value, i) => Math.floor((value - min[i]) / (300 / 9))).join(",");

/** Every check of one case on the page as it is; returns what inspect saw */
async function checkCase(c) {
    const seen = await inspect(c);
    const expectedTexts = c.points.map(([, text]) => padded(text));
    check(`${c.name}: keypad text at the corners and the middle is the game's`, seen.texts.every((text, i) => text === expectedTexts[i]), seen.texts.map((text, i) => `${text}${text === expectedTexts[i] ? "" : ` (game ${c.points[i][1]})`}`).join(", "));
    check(`${c.name}: the box under the cursor shows the game's keypad`, seen.cursorBox === expectedTexts[4], `${seen.cursorBox} (game ${c.points[4][1]})`);
    if (c.outside.length) {
        check(`${c.name}: no keypad and no box outside the grid, as in the game`, seen.outsideTexts.every((text) => text === "") && seen.outsideBoxes.every((box) => box === null), `texts ${JSON.stringify(seen.outsideTexts)}, boxes ${JSON.stringify(seen.outsideBoxes)} at ${JSON.stringify(c.outside)}`);
    }
    const entries = c.points.flatMap(([at, text], i) => typedForms(text).map((typed, form) => [typed, seen.entries[i][form], at]));
    const misses = entries.filter(([, landed, at]) => square(landed, c.min) !== square(at, c.min));
    check(`${c.name}: the game's text, typed as printed, without spaces or padded, lands in the square it names`, misses.length === 0, misses.length ? misses.map(([text, landed, at]) => `"${text}" at ${landed.map((v) => v.toFixed(1))}, the game's ${at}`).join("; ") : `${entries.length} entries`);
    const letters = seen.columns.map((label) => label.text).join("");
    const numbers = seen.rows.map((label) => label.text);
    const lastColumnAt = seen.columns.at(-1)?.at[0] ?? NaN, lastRowAt = seen.rows.at(-1)?.at[1] ?? NaN;
    check(`${c.name}: the letters and numbers are the game's, the last one at the middle of the last strip`,
        letters === c.columns && numbers.join() === Array.from({ length: c.rows }, (_, i) => i + 1).join() && near(lastColumnAt, c.last[0]) && near(lastRowAt, c.last[1]),
        `${letters} x 1-${numbers.at(-1)}, last at ${lastColumnAt.toFixed(2)} / ${lastRowAt.toFixed(2)} (game ${c.columns} x 1-${c.rows}, last at ${c.last})`);
    check(`${c.name}: the letters run along the grid's north edge and the numbers along its west edge`,
        seen.columns.every((label) => near(label.at[1], c.min[1])) && seen.rows.every((label) => near(label.at[0], c.min[0])),
        `letters at y ${[...new Set(seen.columns.map((label) => label.at[1].toFixed(2)))]}, numbers at x ${[...new Set(seen.rows.map((label) => label.at[0].toFixed(2)))]} (game ${c.min})`);
    const inside = (point) => [0, 1].every((i) => point[i] >= c.min[i] - 0.05 && point[i] <= c.max[i] + 0.05);
    check(`${c.name}: no line or label outside the grid`,
        seen.lineBox.every(([low, high], i) => low >= c.min[i] - 0.05 && high <= c.max[i] + 0.05) && [...seen.columns, ...seen.rows].every((label) => inside(label.at)),
        `lines over x ${seen.lineBox[0].map((v) => v.toFixed(2))}, y ${seen.lineBox[1].map((v) => v.toFixed(2))} (game ${c.min} / ${c.max})`);
    const expectedDom = [...c.columns, ...Array.from({ length: c.rows }, (_, i) => String(i + 1))].sort().join();
    check(`${c.name}: the page shows those labels`, [...seen.dom].sort().join() === expectedDom, `${seen.dom.length} labels`);
    return seen;
}

await page.goto(`${base}/?map=Skorpo`, { waitUntil: "load" });
await ready();
let state = await gridState();
check("Skorpo: grid starts 9.5 m east of the image", state.map === "Skorpo" && near(state.offset[0], 9.5) && near(state.firstEast, 9.5) && near(state.firstSouth, 0), JSON.stringify(state));
await checkCase(CASES[0]);

await page.goto(`${base}/?map=Chora`, { waitUntil: "load" });
await ready();
await page.evaluate(() => window.__App.LAYER_SELECTOR.val("Chora_Skirmish_v1").trigger("change"));
await page.waitForFunction(() => window.__App?.minimap?.layer?.layerData?.rawName === "Chora_Skirmish_v1", null, { timeout: 120000 });
await ready();
state = await gridState();
check("Chora Skirmish v1: grid starts at the layer's corner", state.map === "Chora" && near(state.offset[0], 1007.16) && near(state.offset[1], 1221.99) && near(state.firstEast, 1007.16) && near(state.firstSouth, 1221.99), JSON.stringify(state));
const chora = await checkCase(CASES[1]);
const centres = chora.entries[4].map(([x, y]) => Math.hypot(x + 640.2, y + 625.3));
check("Chora Skirmish v1: C3 - 3 - 7, C3-3-7 and C03-3-7 land within 1 m of the game's C3-3-7 centre (-640.2, -625.3)", centres.every((distance) => distance < 1), chora.entries[4].map(([x, y]) => `${x.toFixed(1)}, ${y.toFixed(1)}`).join("; "));

await page.evaluate(() => window.__App.minimap.layer.clear());
state = await gridState();
check("clearing the layer returns the grid to the map's corner", near(state.offset[0], 0) && near(state.offset[1], 0) && near(state.firstEast, 0), JSON.stringify(state));
const labels = await page.evaluate(() => window.__App.minimap.grid.labels.map((label) => String(label.options.icon.options.html)));
const clearedLetters = labels.filter((text) => /^[A-Z]$/.test(text)).join("");
const clearedRows = labels.filter((text) => /^\d+$/.test(text)).length;
check("clearing the layer returns the map's letters and numbers (Chora: A-N x 1-14, as the game)", clearedLetters === "ABCDEFGHIJKLMN" && clearedRows === 14, `${clearedLetters} x 1-${clearedRows}`);

await page.goto(`${base}/?map=AlBasrah`, { waitUntil: "load" });
await ready();
await checkCase(CASES[2]);

check("no page error", problems.length === 0, problems.join(" | ") || "clean");
await browser.close();
process.exit(failures ? 1 : 0);
