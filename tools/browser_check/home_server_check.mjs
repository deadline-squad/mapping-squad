// Checks the home server of the Deadline SquadCalc in Chromium (src/js/serversSource.js; the feed /live/servers.json is
// written by deploy/live_servers.py from the game host's status):
//
//     node home_server_check.mjs <site URL>
//
// 1. With the site's own feed: /?server=<home id> opens the layer the game server plays, with its map and factions,
//    and the menu's server dropdown offers the server.
// 2. With a made-up feed (Mutaha Seed v1, then Al Basrah Seed v1 a moment later): the page follows the layer change by
//    itself (it asks again every 20 s), and the servers browser, once refreshed, lists the home server and no other.
// 3. With a feed ten minutes old: the server is not offered, and /?server=<home id> falls back to the plain page.
//
// Needs the layer API. Environment as browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node home_server_check.mjs <site URL>");
    process.exit(2);
}
const FEED = "/live/servers.json";
const LAYER_API = "https://squadcalc.app/api/get/layer?name=";
let failures = 0;
const check = (label, ok, detail) => {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
};

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

/** What the page shows: the layer, the map, the factions, the server chosen in the dropdown and the options it offers */
const shown = () => page.evaluate(() => {
    const app = window.__App;
    return {
        layer: app.minimap?.layer?.layerData?.rawName ?? null,
        map: app.minimap?.activeMap?.name ?? null,
        team1: app.FACTION1_SELECTOR.val(), team2: app.FACTION2_SELECTOR.val(),
        server: app.SERVER_SELECTOR.val(),
        offered: [...app.SERVER_SELECTOR[0].options].map(option => option.value).filter(Boolean),
        url: window.location.search,
    };
});
const waitLayer = (layer, timeout) => page.waitForFunction((name) => {
    const app = window.__App;
    return app?.minimap?.layer?.layerData?.rawName === name && app.FACTION1_SELECTOR.val() && app.FACTION2_SELECTOR.val();
}, layer, { timeout });
/** A home server on `layer`, with the first faction the layer offers each team */
const serverOn = async (layer) => {
    const data = await (await fetch(LAYER_API + layer)).json();
    return {
        id: "deadline", attributes: { name: "[RU] Deadline", players: 50, maxPlayers: 100, details: { map: layer } },
        team1: data.units.team1Units[0].factionID, team2: data.units.team2Units[0].factionID,
    };
};
/** Serves `servers` as the feed, written `ageS` seconds before the response */
let feed = null;
const serve = (servers, ageS = 5) => { feed = { servers, ageS }; };
await context.route(`**${FEED}`, async (route) => {
    if (!feed) return route.continue();
    const now = Date.now();
    await route.fulfill({
        contentType: "application/json", headers: { date: new Date(now).toUTCString() },
        body: JSON.stringify({ generated: new Date(now - feed.ageS * 1000).toISOString(), servers: feed.servers }),
    });
});

// 1. The site's own feed
const live = await (await fetch(base + FEED, { cache: "no-store" })).json();
const home = live.servers?.[0];
check("the site serves a home servers feed with the game server", Boolean(home?.id && home.attributes?.details?.map),
    JSON.stringify(live).slice(0, 300));
if (home?.team1 && home?.team2) {
    await page.goto(`${base}/?server=${home.id}`, { waitUntil: "load" });
    await waitLayer(home.attributes.details.map, 120000);
    const state = await shown();
    check("?server=<home id> opens what the game server plays",
        state.layer === home.attributes.details.map && state.team1 === home.team1 && state.team2 === home.team2
        && state.server === home.id && state.url.includes(`server=${home.id}`), JSON.stringify(state));
} else {
    console.log("skip ?server=<home id> on the site's own feed: the feed names no factions (the layer is not in the layer API)");
}

// 2. A layer change is followed, and the servers browser lists the home server alone
const first = await serverOn("Mutaha_Seed_v1");
const second = await serverOn("AlBasrah_Seed_v1");
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await waitLayer("Mutaha_Seed_v1", 120000);
let state = await shown();
check("the home server is offered in the menu and opens its layer", state.offered.includes("deadline") && state.server === "deadline"
    && state.map === "Mutaha" && state.team1 === first.team1 && state.team2 === first.team2, JSON.stringify(state));
serve([second]);
await waitLayer("AlBasrah_Seed_v1", 90000);
state = await shown();
check("the page follows the server to its next layer", state.map === "AlBasrah" && state.team1 === second.team1 && state.team2 === second.team2
    && state.url.includes("server=deadline"), JSON.stringify(state));
await page.click("#servers");
await page.waitForSelector("#serversTableBody tr[data-serverid]", { timeout: 60000 });
// The table keeps the rows of its last load; its refresh button asks for the list again
await page.click("#refreshBtn");
await page.waitForFunction(() => document.querySelector("#serversTableBody tr[data-serverid]")?.innerText.includes("AlBasrah_Seed_v1"), null, { timeout: 60000 });
const rows = await page.evaluate(() => [...document.querySelectorAll("#serversTableBody tr[data-serverid]")]
    .map(row => ({ id: row.dataset.serverid, classes: row.className.trim(), text: row.innerText.replace(/\s+/g, " ").trim().slice(0, 80) })));
check("the servers browser lists the home server, selected, and no other server", rows.length === 1 && rows[0].id === "deadline"
    && rows[0].classes === "selected" && rows[0].text.includes("AlBasrah_Seed_v1"), JSON.stringify(rows));

// 3. A feed whose writer has stopped
serve([first], 600);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !new URLSearchParams(window.location.search).has("server"),
    null, { timeout: 120000 });
state = await shown();
check("a feed ten minutes old offers no server", !state.offered.includes("deadline") && !state.server && !state.url.includes("server="), JSON.stringify(state));

check("no page errors", problems.length === 0, problems.join(" | ") || "none");
await browser.close();
process.exit(failures ? 1 : 0);
