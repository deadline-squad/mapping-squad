// Squad Ballistics' own page scripts (maplink.py bridge_script and WATCH_SCRIPT, exported as JSON) run against a
// SquadCalc page: does the bridge answer, does the watcher announce a change, and how long is the click to the
// solution, measured as SB's host does (a `sb:changed` message, then one poll).
//
//     python3 -c "import json, maplink; json.dump({'bridge': maplink.bridge_script(None), 'watch': maplink.WATCH_SCRIPT}, open('/tmp/sb_scripts.json', 'w'))"   # in a Squad Ballistics checkout
//     node sb_bridge_probe.mjs <site URL> [/tmp/sb_scripts.json] [--clicks 12]
//
// Environment as browser_check.mjs. The delay of one click is from the double-click on the map to the poll
// that returns the new target; the page's own console.info("sb:changed") and the watcher's both count.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const { readFileSync } = await import("node:fs");

const args = process.argv.slice(2);
const base = args[0];
const scripts = JSON.parse(readFileSync(args[1] && !args[1].startsWith("--") ? args[1] : "/tmp/sb_scripts.json", "utf8"));
const clicks = args.includes("--clicks") ? Number(args[args.indexOf("--clicks") + 1]) : 12;

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext({ viewport: { width: 1200, height: 800 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    await route.fulfill({ response, body: body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={") });
});
const page = await context.newPage();
const announcements = [];
page.on("console", (message) => { if (message.text() === "sb:changed") announcements.push(Date.now()); });
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.ready, null, { timeout: 120000 });
await page.waitForTimeout(1500);

// The poll script with the revision the host already has (bridge_script(known_revision))
const poll = (known) => scripts.bridge.replace(/, null\)$/, `, ${known})`);
const first = await page.evaluate((script) => JSON.parse(window.eval(script)), poll(null));
console.log("SB poll script, first answer:", JSON.stringify(first).slice(0, 200));

// The watcher runs in the page like SB injects it
await page.evaluate((script) => { window.eval(script); }, scripts.watch);
await page.evaluate(() => {
    const map = window.__App.minimap;
    map.setView([-map.pixelSize / 2, map.pixelSize / 2], 5, { animate: false });
    map.createWeapon({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 });
});
await page.waitForTimeout(500);

const box = await page.evaluate(() => { const b = window.__App.minimap.getContainer().getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
const delays = [];
let known = first.revision;
for (let i = 0; i < clicks; i++) {
    const announced = announcements.length;
    const clickedAt = Date.now();
    await page.mouse.dblclick(box.x + ((i * 53) % 400) - 200, box.y - 80 - ((i * 37) % 200));
    // SB's host: the announcement asks for one poll at once; without one it polls on its timer
    let answer = null;
    while (Date.now() - clickedAt < 3000) {
        if (announcements.length > announced) {
            answer = await page.evaluate((script) => JSON.parse(window.eval(script)), poll(known));
            if (answer.targets?.length) break;
        }
        await page.waitForTimeout(5);
    }
    delays.push(answer?.targets?.length ? Date.now() - clickedAt : null);
    if (answer) known = answer.revision;
}
const done = delays.filter((ms) => ms !== null).sort((a, b) => a - b);
console.log(`click to solution (${done.length} of ${clicks} announced and read): median ${done[Math.floor(done.length / 2)]} ms, p90 ${done[Math.floor(done.length * 0.9)]} ms, worst ${done[done.length - 1]} ms; announcements ${announcements.length}`);
await browser.close();
