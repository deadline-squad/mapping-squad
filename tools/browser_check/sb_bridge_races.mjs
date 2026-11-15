// Correctness of the window.squadBallistics bridge against Squad Ballistics' own page scripts
// (maplink.py bridge_script / WATCH_SCRIPT, exported like for sb_bridge_probe.mjs): a host model that
// polls with the revision it knows (exactly what webmap.MapPage.on_bridge_result keeps) must end every
// step with the page's truth: the newest target, its profile and the weapon.
//
//     python3 -c "import json, maplink, ballistics; json.dump({'bridge': maplink.bridge_script(None), 'watch': maplink.WATCH_SCRIPT, 'renamed': ballistics.RENAMED_WEAPONS}, open('/tmp/sb_scripts.json', 'w'))"   # in a Squad Ballistics checkout
//     node sb_bridge_races.mjs <site URL> [/tmp/sb_scripts.json]
//
// Steps: every kind of change (target added, moved, deleted, all deleted; weapon marker moved, raised, deleted;
// weapon and shell switched, by name and by an old name), a double-click pair 40 ms apart, the heights loading
// after the target was placed (meta.json held back), a map switch with the old map's heights still loading, and
// the weapon-name mapping of Squad Ballistics' weapons.json (and its RENAMED_WEAPONS) onto SquadCalc's.
// Environment as browser_check.mjs. Exits with 1 on any failure.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");
const { readFileSync } = await import("node:fs");

const base = process.argv[2];
if (!base) {
    console.error("usage: node sb_bridge_races.mjs <site URL> [/tmp/sb_scripts.json]");
    process.exit(2);
}
const scripts = JSON.parse(readFileSync(process.argv[3] ?? "/tmp/sb_scripts.json", "utf8"));

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
await context.route(/\/src\/js\/main\.[0-9a-f]+\.min\.js$/, async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    await route.fulfill({ response, body: body.replace("window.squadBallistics={", "window.__App=this,window.squadBallistics={") });
});
// meta.json of the heightmaps held back while `holdMeta` is set (a slow network: the heights arrive late)
let holdMeta = null;
await context.route(/\/heightmaps\/[a-z0-9_-]+\/meta\.json/, async (route) => {
    if (holdMeta) await holdMeta;
    await route.continue();
});
const page = await context.newPage();
const announcements = [];
page.on("console", (message) => { if (message.text() === "sb:changed") announcements.push(Date.now()); });
await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.__App?.minimap?.heightmap?.ready, null, { timeout: 120000 });
await page.waitForTimeout(1000);

/**
 * The host of Squad Ballistics, in the page: keeps what webmap.MapPage keeps (known revision, last targets,
 * last weapon), and `poll` runs the real bridge script with the revision it knows.
 */
await page.evaluate(({ bridge }) => {
    window.__host = { known: null, targets: [], weapon: null, polls: 0 };
    window.__poll = () => {
        const host = window.__host;
        const answer = JSON.parse(window.eval(bridge.replace(/, null\)$/, `, ${host.known})`)));
        host.polls++;
        host.weapon = answer.weapon ?? host.weapon;
        if ("targets" in answer) {
            host.known = answer.revision;
            host.targets = answer.targets;
        }
        return answer;
    };
}, { bridge: scripts.bridge });
const poll = () => page.evaluate(() => window.__poll());
const truth = () => page.evaluate(() => {
    const bridge = window.squadBallistics;
    const last = bridge.targets().at(-1) ?? null;
    return { last, weapon: bridge.weapon(), revision: bridge.revision() };
});
const hostView = () => page.evaluate(() => ({ targets: window.__host.targets, weapon: window.__host.weapon }));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Poll once like the host does after a change and compare what it holds with the page's truth */
async function compare(label) {
    await poll();
    const [real, host] = await Promise.all([truth(), hostView()]);
    const seen = host.targets.at(-1) ?? null;
    check(label, same(real.last, seen) && real.weapon === host.weapon,
        `newest target ${seen ? `${seen.distance.toFixed(1)} m, bearing ${seen.bearing.toFixed(1)}, profile ${seen.profile ? seen.profile.heights.length : "none"}` : "none"}, weapon ${host.weapon}, revision ${real.revision}`);
}

const view = () => page.evaluate(() => {
    const map = window.__App.minimap;
    map.setView([-map.pixelSize / 2, map.pixelSize / 2], 5, { animate: false });
    const box = map.getContainer().getBoundingClientRect();
    return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
});
const centre = await view();
const at = (dx, dy) => [centre.x + dx, centre.y + dy];
const revision = () => page.evaluate(() => window.squadBallistics.revision());

// Weapon, then targets by double-click as the user does
await page.evaluate(() => { const map = window.__App.minimap; map.createWeapon({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }); });
await page.waitForTimeout(300);
await compare("weapon placed, no target");

await page.mouse.dblclick(...at(-120, -150));
await page.waitForTimeout(300);
await compare("first target");
await page.mouse.dblclick(...at(100, -200));
await page.waitForTimeout(300);
await compare("second target is the newest");

// Two targets 40 ms apart: the host polls once after both
await page.mouse.dblclick(...at(-200, -60));
await page.waitForTimeout(40);
await page.mouse.dblclick(...at(200, -90));
await compare("two double-clicks 40 ms apart, polled at once");
await page.waitForTimeout(400);
await compare("... and again after they settled");

// Moves: the newest target, then an older one (the newest is unchanged, revision still moves)
let before = await revision();
// (a real drag of the marker with the mouse)
const dragFrom = await page.evaluate(() => {
    const map = window.__App.minimap;
    const icon = map.activeTargetsMarkers.getLayers().at(-1).getElement().getBoundingClientRect();
    return { x: icon.left + icon.width / 2, y: icon.top + icon.height / 2 };
});
await page.mouse.move(dragFrom.x, dragFrom.y);
await page.mouse.down();
await page.mouse.move(dragFrom.x + 20, dragFrom.y + 15, { steps: 6 });
await page.mouse.move(dragFrom.x + 40, dragFrom.y + 30, { steps: 6 });
await page.mouse.up();
await page.waitForTimeout(300);
check("moving the newest target moves the revision", (await revision()) > before, `revision ${before} -> ${await revision()}`);
await compare("newest target moved");

// Delete the newest: the previous one becomes the newest
before = await revision();
const countBefore = await page.evaluate(() => window.squadBallistics.targets().length);
await page.evaluate(() => window.__App.minimap.activeTargetsMarkers.getLayers().at(-1).delete());
await page.waitForTimeout(100);
check("deleting the newest target moves the revision", (await revision()) > before, `targets ${countBefore} -> ${await page.evaluate(() => window.squadBallistics.targets().length)}`);
await compare("newest deleted, the host holds the previous one");

// The weapon marker raised and moved
before = await revision();
await page.evaluate(() => { const weapon = window.__App.minimap.activeWeaponsMarkers.getLayers()[0]; weapon.heightPadding = 7; weapon.map.updateTargets(); });
await page.waitForTimeout(100);
check("raising the weapon moves the revision", (await revision()) > before, `revision ${before} -> ${await revision()}`);
await compare("weapon raised");

// Weapon switch: by name, by an old name, to one with no name, and the shell
const names = await page.evaluate(() => window.__App.WEAPON_SELECTOR.find("option").length);
for (const [label, name, expected] of [
    ["selectWeapon by current name", "Hell Cannon", "Hell Cannon"],
    ["selectWeapon by an old Squad Ballistics name (QLZ87)", "QLZ87", "QLZ87 · optic (RMB ×3)"],
    ["selectWeapon by an old Squad Ballistics name (AGS-17)", "AGS-17 · emplacement", "AGS-17 · emplacement · optic (RMB ×2.5)"],
    ["selectWeapon by an older rename (MK19 / AGS-17 / AGS-30)", "MK19 / AGS-17 / AGS-30", "MK19"],
    ["selectWeapon by an older rename (Carl Gustav)", "Carl Gustav / M3 MAAWS · HEAT", "M3 MAAWS · HEAT / Smoke"],
    ["selectWeapon by an older rename (Tank AP)", "Tank AP · L30A1 (Challenger 2)", "Tank AP · L30A1 (Challenger 2) / M68A2"],
]) {
    before = await revision();
    const known = await page.evaluate((n) => window.squadBallistics.selectWeapon(n), name);
    const weapon = await page.evaluate(() => window.squadBallistics.weapon());
    check(label, known === true && weapon === expected, `returned ${known}, weapon() ${weapon}, revision ${before} -> ${await revision()}`);
    await compare(`  host follows (${label})`);
}
before = await revision();
await page.evaluate(() => window.squadBallistics.selectWeapon("Mortar (M252 / 2B14 / L16 / Type 63)"));
const shells = await page.evaluate(() => window.__App.SHELL_SELECTOR.find("option").length);
if (shells > 1) {
    const afterWeapon = await revision();
    await page.evaluate(() => window.__App.SHELL_SELECTOR.val(1).trigger("change"));
    check("switching the shell moves the revision", (await revision()) > afterWeapon, `revision ${afterWeapon} -> ${await revision()}`);
}
await compare("after the shell switch");

// Race: the host polls between two page-side steps (a task apart), with the weapon switched and its targets solved
before = await revision();
await page.evaluate(() => { window.squadBallistics.selectWeapon("Hell Cannon"); });
const raced = await poll();
const afterSwitch = await truth();
check("a poll right after selectWeapon already holds the new weapon", raced.weapon === afterSwitch.weapon && afterSwitch.weapon === "Hell Cannon", `weapon ${raced.weapon}`);

// Weapon marker removed
before = await revision();
await page.evaluate(() => { const map = window.__App.minimap; map.activeWeaponsMarkers.getLayers()[0].delete?.(); });
await page.waitForTimeout(150);
const weaponGone = await page.evaluate(() => window.squadBallistics.targets().length);
await compare(`weapon marker deleted (targets left: ${weaponGone})`);

// All targets deleted
await page.evaluate(() => { const map = window.__App.minimap; if (!map.activeWeaponsMarkers.getLayers().length) map.createWeapon({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }); });
await page.mouse.dblclick(...at(-80, -120));
await page.waitForTimeout(300);
await compare("a target on a new weapon");
await page.evaluate(() => window.__App.minimap.deleteTargets());
await page.waitForTimeout(150);
await compare("every target deleted: the host holds none");
const lastAfter = await page.evaluate(() => window.squadBallistics.lastTarget());
check("lastTarget() is null without targets", lastAfter === null, JSON.stringify(lastAfter));

// Announcements: which of the changes above reached the page's own console.info
const pushed = announcements.length;
check("the page announced changes itself", pushed > 5, `${pushed} sb:changed messages`);

// The heights load after the target was placed
await page.evaluate(() => window.__App.minimap.deleteTargets());
let release;
holdMeta = new Promise((resolve) => { release = resolve; });
await page.evaluate(() => { const map = window.__App.minimap; document.querySelector(".dropbtn1, #mapSelector"); });
const otherMap = await page.evaluate(() => {
    const select = window.__App.MAP_SELECTOR;
    return select.find("option").toArray().map((o) => o.value).find((v) => v !== String(select.val()));
});
await page.evaluate((value) => window.__App.MAP_SELECTOR.val(value).trigger("change"), otherMap);
await page.waitForTimeout(300);
const during = await page.evaluate(() => ({ ready: window.__App.minimap.heightmap.ready, targets: window.squadBallistics.targets().length }));
check("map switched, heightmap pending", during.ready === false && during.targets === 0, JSON.stringify(during));
const centre2 = await view();
await page.evaluate(() => { const map = window.__App.minimap; map.createWeapon({ lat: -map.pixelSize / 2, lng: map.pixelSize / 2 }); });
await page.mouse.dblclick(centre2.x - 100, centre2.y - 140);
await page.waitForTimeout(300);
await compare("target placed while the heights load");
const early = await page.evaluate(() => window.squadBallistics.lastTarget());
check("  heightDiff and profile are unknown while the heights load", early && early.heightDiff === null && early.profile === null, JSON.stringify(early && { heightDiff: early.heightDiff, profile: early.profile }));
const revEarly = await revision();
release();
await page.waitForFunction(() => window.__App.minimap.heightmap.ready, null, { timeout: 120000 });
await page.waitForTimeout(500);
check("the heights arriving move the revision", (await revision()) > revEarly, `revision ${revEarly} -> ${await revision()}`);
await compare("heights loaded: the host holds the profile");
const late = await page.evaluate(() => window.squadBallistics.lastTarget());
check("  heightDiff and profile known after the heights loaded", late && Number.isFinite(late.heightDiff) && late.profile && late.profile.heights.length > 10, `heightDiff ${late?.heightDiff}, profile ${late?.profile?.heights.length}`);
holdMeta = null;

// Map switch with the old map's heights still loading: only the last map's heights count
await page.evaluate(() => window.__App.minimap.deleteTargets());
let release2;
holdMeta = new Promise((resolve) => { release2 = resolve; });
const third = await page.evaluate(() => {
    const select = window.__App.MAP_SELECTOR;
    const options = select.find("option").toArray().map((o) => o.value);
    return { options, current: String(select.val()) };
});
const [first, second] = third.options.filter((value) => value !== third.current).slice(0, 2);
await page.evaluate(([a, b]) => { const select = window.__App.MAP_SELECTOR; select.val(a).trigger("change"); select.val(b).trigger("change"); }, [first, second]);
const nameNow = await page.evaluate(() => window.__App.minimap.activeMap.name);
release2();
await page.waitForFunction(() => window.__App.minimap.heightmap.ready, null, { timeout: 120000 });
await page.waitForTimeout(500);
const settled = await page.evaluate(() => ({ map: window.__App.minimap.activeMap.name, resolution: window.__App.minimap.heightmap.resolution, height: window.__App.minimap.heightmap.getHeight({ lat: -128, lng: 128 }) }));
check("two quick map switches: the heights are those of the last map", settled.map === nameNow && settled.resolution > 0 && Number.isFinite(settled.height), JSON.stringify(settled));
holdMeta = null;

// Weapon names: every old name of Squad Ballistics' RENAMED_WEAPONS (exported in the scripts file) must select
// the weapon of its current name; a script file without "renamed" skips this
for (const [old, current] of Object.entries(scripts.renamed ?? {})) {
    const result = await page.evaluate((names) => ({ known: window.squadBallistics.selectWeapon(names.old), weapon: window.squadBallistics.weapon() }), { old, current });
    check(`RENAMED_WEAPONS: ${old}`, result.known === true && result.weapon === current, `selectWeapon returned ${result.known}, weapon() ${result.weapon}, expected ${current}`);
}

const unknown = await page.evaluate(() => window.squadBallistics.selectWeapon("no such weapon"));
check("selectWeapon of an unknown name returns false", unknown === false, String(unknown));

await browser.close();
console.log(failures ? `${failures} FAILED` : "all ok");
process.exit(failures ? 1 : 0);
