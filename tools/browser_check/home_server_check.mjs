// Checks the home server of the Deadline SquadCalc in Chromium (src/js/serversSource.js; the feed /live/servers.json is
// written by deploy/live_servers.py from the game host's status):
//
//     node home_server_check.mjs <site URL>
//
// 1. With the site's own feed: /?server=<home id> opens the layer the game server plays, with its map and factions,
//    and the menu's server dropdown offers the server.
// 2. With a made-up feed (Mutaha Seed v1, then Al Basrah Seed v1 a moment later): the page follows the layer change by
//    itself (it asks again every 20 s), and the servers browser, once refreshed, lists the home server and no other.
// 3. The feed cannot be read (it answers 502): two failed reads change nothing, the page still follows; it leaves
//    server mode, and says so, only once the feed it last read is two minutes old.
// 4. The followed server leaves the feed (its writer stops, the feed grows old): at its next read the page leaves
//    server mode (no `server` in the URL, no choice in the dropdown, the servers button and the sync timer off, the
//    layer left as it was) and says so once. The dropdown no longer offers the server, and offers it again when the
//    feed has it again, without a reload and without the page following by itself.
// 5. The user leaves server mode (no message), the server moves to another layer, the user chooses it again in the
//    dropdown: the page opens the layer played now and never the one of its last read.
// 6. The followed server moves to a layer of a map the calculator does not have, then, followed again, to an entry
//    without factions: each time the page leaves server mode and says it has no data for the layer; the dropdown lists
//    the server as unavailable.
// 7. With a feed ten minutes old: the server is not offered, /?server=<home id> falls back to the plain page, and the
//    servers browser says it has no server (in words, also when the feed was read before the translations).
// 8. The user leaves server mode while the map of the server's next layer is still loading (its list of layers held
//    back): when the list arrives, the page opens none of the server's layers and says nothing.
// 9. The request for the layer the server plays fails once: the page still follows the server and opens the layer at
//    its next read of the feed.
// 10. A page opened on another map with ?server=: the list of that map's layers arrives after the server's layer has
//    loaded, and the layer selector keeps the server map's layers.
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
// The page reads the feed again every 20 s; a step that waits for that read gives a loaded machine this long
const NEXT_READ_MS = 90000;
// HOME_FEED_MAX_AGE_MS of src/js/serversSource.js: how long the page goes by a feed it has read
const FEED_MAX_AGE_MS = 120000;
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
// Every toast of the page since its load, as [type, title key, text key]
await context.addInitScript(() => {
    window.__toasts = [];
    let app;
    Object.defineProperty(window, "__App", {
        get: () => app,
        set: (value) => {
            app = value;
            const openToast = value.openToast;
            value.openToast = function (...message) {
                window.__toasts.push(message);
                return openToast.apply(this, message);
            };
        },
    });
});
const page = await context.newPage();
const problems = [];
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

/**
 * What the page shows: the layer, the map, the factions; the server chosen in the dropdown, the servers it offers and
 * those it lists as unavailable; the server followed, its sync timer and the servers button; the toasts so far and the
 * text of the last one
 */
const shown = () => page.evaluate(() => {
    const app = window.__App;
    const options = [...app.SERVER_SELECTOR[0].options].filter(option => option.value);
    return {
        layer: app.minimap?.layer?.layerData?.rawName ?? null,
        map: app.minimap?.activeMap?.name ?? null,
        team1: app.FACTION1_SELECTOR.val(), team2: app.FACTION2_SELECTOR.val(),
        server: app.SERVER_SELECTOR.val(),
        offered: options.filter(option => !option.disabled).map(option => option.value),
        unavailable: options.filter(option => option.disabled).map(option => option.value),
        url: window.location.search,
        followed: app.squadServersBrowser?.selectedServer ?? null,
        timer: Boolean(app.squadServersBrowser?.syncInterval),
        button: document.querySelector("#servers").classList.contains("active"),
        toasts: window.__toasts,
        said: [...document.querySelectorAll("#toast-message h4, #toast-message p")].map(line => line.textContent.trim()).join(" / "),
    };
});
/** Whether the page gets to `state` (a function run in the page, given `argument`) within `timeout` ms */
const reaches = (state, argument, timeout) => page.waitForFunction(state, argument, { timeout }).then(() => true, () => false);
const waitLayer = (layer, timeout) => page.waitForFunction((name) => {
    const app = window.__App;
    return app?.minimap?.layer?.layerData?.rawName === name && app.FACTION1_SELECTOR.val() && app.FACTION2_SELECTOR.val();
}, layer, { timeout });
/** Whether the page has left server mode within the time of its next read of the feed */
const leaves = () => reaches(() => !new URLSearchParams(window.location.search).has("server") && !window.__App.squadServersBrowser.selectedServer,
    null, NEXT_READ_MS);
/** Whether the dropdown offers the home server within the time of the page's next read of the feed */
const offersAgain = () => reaches(() => [...window.__App.SERVER_SELECTOR[0].options].some(option => option.value === "deadline" && !option.disabled),
    null, NEXT_READ_MS);
/** The state of a page that follows no server and marks none as followed */
const notFollowing = (state) => !state.url.includes("server=") && !state.server && !state.followed && !state.timer && !state.button;
/** The toasts of `state` that tell of a failure */
const errors = (state) => JSON.stringify(state.toasts.filter(([type]) => type === "error"));
/** Whether the last toast of `state` shows a title and a text in words, not the keys of missing translations */
const worded = (state) => /^\S.{4,} \/ \S.{4,}$/.test(state.said) && !/server(Not|Layer)|tooltips:/.test(state.said);
/** The user chooses the home server in the menu's dropdown (which select2 leaves open after its choice was cleared) */
const choose = async () => {
    if (!await page.$("#serverSelector .select2-container--open")) await page.click("#serverSelector .select2-selection");
    await page.click("#serverSelector li.select2-results__option[id$='-deadline']");
};
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
/** Answers the feed's requests with an error from now on; `failedReads` counts them */
let failedReads = 0;
const unreadable = () => { feed = "unreadable"; failedReads = 0; };
await context.route(`**${FEED}`, async (route) => {
    if (!feed) return route.continue();
    if (feed === "unreadable") {
        failedReads++;
        return route.fulfill({ status: 502, body: "" });
    }
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
await waitLayer("AlBasrah_Seed_v1", NEXT_READ_MS);
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

// 3. The feed cannot be read: nothing changes while the feed last read is fresh, then the page leaves server mode
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await waitLayer("Mutaha_Seed_v1", 120000);
unreadable();
let started = Date.now();
while (failedReads < 2 && Date.now() - started < NEXT_READ_MS) await page.waitForTimeout(500);
state = await shown();
check("two reads of the feed that fail do not end following", failedReads >= 2 && state.followed === "deadline" && state.timer && state.button
    && state.url.includes("server=deadline") && state.layer === "Mutaha_Seed_v1" && errors(state) === "[]", `${failedReads} failed reads: ${JSON.stringify(state)}`);
let left = await reaches(() => !new URLSearchParams(window.location.search).has("server") && !window.__App.squadServersBrowser.selectedServer,
    null, FEED_MAX_AGE_MS + NEXT_READ_MS);
let seconds = Math.round((Date.now() - started) / 1000);
state = await shown();
check("with the feed unreadable the page stops following once its last read is two minutes old", left && seconds >= 90 && seconds <= 150
    && notFollowing(state) && state.layer === "Mutaha_Seed_v1" && errors(state) === JSON.stringify([["error", "serverNotFound", "serverNotFollowed"]]),
    `after ${seconds} s and ${failedReads} failed reads: ${JSON.stringify(state)}`);

// 4. The followed server leaves the feed, and comes back
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await waitLayer("Mutaha_Seed_v1", 120000);
serve([first], 600);
started = Date.now();
left = await leaves();
seconds = Math.round((Date.now() - started) / 1000);
state = await shown();
check("a server that left the feed is no longer followed", left && notFollowing(state) && !state.offered.includes("deadline")
    && state.layer === "Mutaha_Seed_v1", `after ${seconds} s: ${JSON.stringify(state)}`);
check("the page says once that it no longer follows the server", errors(state) === JSON.stringify([["error", "serverNotFound", "serverNotFollowed"]])
    && worded(state), `${errors(state)}, shown as "${state.said}"`);
serve([second]);
const back = await offersAgain();
state = await shown();
check("a server back in the feed is offered again, and followed only when chosen", back && notFollowing(state) && state.layer === "Mutaha_Seed_v1"
    && errors(state) === JSON.stringify([["error", "serverNotFound", "serverNotFollowed"]]), JSON.stringify(state));

// 5. Chosen again after the feed changed
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await waitLayer("Mutaha_Seed_v1", 120000);
await page.click("#serverSelector .select2-selection__clear");
state = await shown();
check("clearing the dropdown leaves server mode without a message", notFollowing(state) && state.offered.includes("deadline")
    && errors(state) === "[]", JSON.stringify(state));
// The page shows no layer of the server, and every layer it opens from now on is noted
await page.evaluate(() => {
    const app = window.__App;
    app.LAYER_SELECTOR.val("").trigger("change");
    window.__opened = [];
    app.LAYER_SELECTOR.on("change", (event) => window.__opened.push(event.target.value));
});
serve([second]);
await choose();
await waitLayer("AlBasrah_Seed_v1", 120000);
state = await shown();
const opened = await page.evaluate(() => window.__opened);
check("the server chosen again opens the layer it plays now, not the one of the page's last read", JSON.stringify(opened) === JSON.stringify(["AlBasrah_Seed_v1"])
    && state.followed === "deadline" && state.timer && state.button && state.server === "deadline" && state.url.includes("server=deadline")
    && state.team1 === second.team1 && state.team2 === second.team2, `layers opened ${JSON.stringify(opened)}, ${JSON.stringify(state)}`);

// 6. A layer the calculator cannot show: of a map it does not have, then without factions
const noData = JSON.stringify([["error", "serverLayerUnavailable", "serverNotFollowed"]]);
serve([{ ...second, attributes: { ...second.attributes, details: { map: "Belaya_AAS_v1" } } }]);
started = Date.now();
left = await leaves();
seconds = Math.round((Date.now() - started) / 1000);
state = await shown();
check("a server on a layer of an unknown map is no longer followed, and the page says once it has no data for the layer", left && notFollowing(state)
    && state.unavailable.includes("deadline") && !state.offered.includes("deadline") && state.layer === "AlBasrah_Seed_v1" && errors(state) === noData
    && worded(state), `after ${seconds} s: ${JSON.stringify(state)}`);
serve([second]);
const available = await offersAgain();
await choose();
const followedAgain = await reaches(() => window.__App.squadServersBrowser.selectedServer === "deadline" && Boolean(window.__App.squadServersBrowser.syncInterval)
    && new URLSearchParams(window.location.search).get("server") === "deadline", null, 60000);
await page.evaluate(() => { window.__toasts.length = 0; });
serve([{ id: second.id, attributes: second.attributes }]);
left = await leaves();
state = await shown();
check("a server whose entry has no factions is no longer followed, and the page says once it has no data for the layer", available && followedAgain
    && left && notFollowing(state) && state.unavailable.includes("deadline") && state.layer === "AlBasrah_Seed_v1" && errors(state) === noData,
JSON.stringify(state));

// 7. A feed whose writer has stopped
serve([first], 600);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.grid?.kpLines?.length > 0 && !new URLSearchParams(window.location.search).has("server"),
    null, { timeout: 120000 });
state = await shown();
check("a feed ten minutes old offers no server", !state.offered.includes("deadline") && !state.server && !state.url.includes("server="), JSON.stringify(state));
await page.click("#servers");
await page.click("#serversTableBody tr");
const emptyList = await page.evaluate(() => document.querySelector("#serversTableBody").innerText.trim());
state = await shown();
check("the servers browser of an empty feed says in words that it has no server, and a click on that line does nothing", emptyList.includes(" ")
    && !emptyList.includes("noServersFound") && notFollowing(state) && problems.length === 0,
`"${emptyList}", ${JSON.stringify(state)}, page errors: ${problems.join(" | ") || "none"}`);

// 8. Left while the server's next map loads
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
await waitLayer("Mutaha_Seed_v1", 120000);
let releaseLayers;
const held = new Promise((resolve) => { releaseLayers = resolve; });
const layersOfAlBasrah = /\/get\/layers\?map=AlBasrah$/;
await context.route(layersOfAlBasrah, async (route) => { await held; await route.continue(); });
await page.evaluate(() => {
    window.__opened = [];
    window.__App.LAYER_SELECTOR.on("change", (event) => window.__opened.push(event.target.value));
});
serve([second]);
const switching = await reaches(() => window.__App.minimap?.activeMap?.name === "AlBasrah", null, NEXT_READ_MS);
await page.click("#serverSelector .select2-selection__clear");
releaseLayers();
const listed = await reaches(() => window.__App.LAYER_SELECTOR.find("option[value='AlBasrah_Seed_v1']").length > 0, null, 60000);
const reopened = await reaches(() => window.__opened.length > 0, null, 10000);
await context.unroute(layersOfAlBasrah);
state = await shown();
check("leaving server mode while the server's next map loads stops the switch: no layer is opened when its layers arrive",
    switching && listed && !reopened && notFollowing(state) && errors(state) === "[]",
    `map switched ${switching}, layers listed ${listed}, layers opened ${JSON.stringify(await page.evaluate(() => window.__opened))}, ${JSON.stringify(state)}`);

// 9. The layer request fails once
let refusedLayers = 0;
const layerOfMutaha = /\/get\/layer\?name=Mutaha_Seed_v1$/;
await context.route(layerOfMutaha, (route) => (refusedLayers++ === 0 ? route.abort("failed") : route.fallback()));
serve([first]);
await page.goto(`${base}/?server=deadline`, { waitUntil: "load" });
const retried = await waitLayer("Mutaha_Seed_v1", NEXT_READ_MS).then(() => true, () => false);
await context.unroute(layerOfMutaha);
state = await shown();
check("a failed request for the server's layer is made again at the next read of the feed, and the page follows", retried && refusedLayers >= 2
    && state.followed === "deadline" && state.timer && state.url.includes("server=deadline"), `${refusedLayers} request(s), ${JSON.stringify(state)}`);

// 10. The list of the page's own map arrives last
let releaseList;
const heldList = new Promise((resolve) => { releaseList = resolve; });
const layersOfAlBasrahList = /\/get\/layers\?map=AlBasrah$/;
await context.route(layersOfAlBasrahList, async (route) => { await heldList; await route.fallback().catch(() => {}); });
serve([first]);
await page.goto(`${base}/?map=AlBasrah&server=deadline`, { waitUntil: "load" });
const loadedFirst = await waitLayer("Mutaha_Seed_v1", 120000).then(() => true, () => false);
releaseList();
await page.waitForTimeout(6000);
await context.unroute(layersOfAlBasrahList);
const options = await page.evaluate(() => [...window.__App.LAYER_SELECTOR[0].options].map((option) => option.value).filter(Boolean));
state = await shown();
check("a list of layers of the page's first map that arrives late leaves the server map's layers in the selector", loadedFirst && options.length > 0
    && options.every((layer) => layer.startsWith("Mutaha")) && state.layer === "Mutaha_Seed_v1" && state.followed === "deadline",
`${options.length} option(s), first ${JSON.stringify(options.slice(0, 3))}, ${JSON.stringify(state)}`);

check("no page errors", problems.length === 0, problems.join(" | ") || "none");
await browser.close();
process.exit(failures ? 1 : 0);
