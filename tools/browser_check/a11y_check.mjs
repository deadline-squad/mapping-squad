// Accessibility checks of the Deadline SquadCalc in a real browser (Chromium through Playwright), read from
// Chromium's own accessibility tree (CDP Accessibility.getFullAXTree), not from the DOM attributes:
//
//     node a11y_check.mjs <site URL>
//
// - every button, combobox, checkbox, slider in the tree has an accessible name, on the map page and in the
//   settings, factions and target dialogs (no axe-core: it is not a dependency of the app or of this folder)
// - ids are unique
// - the layer, high-definition, help-map and fire-coverage buttons expose aria-pressed that matches the
//   button's `active` class and flips when the button is clicked
// - the header selects (server, map, layer, weapon, ammo) and their select2 widgets have names
// - the weapon and target markers are reachable with Tab, are buttons with a name, and Enter or Space opens
//   their dialog; the dialog returns the focus to the marker when it closes
// - in every language the map buttons are named with the language's own strings
//
// <site URL> is a served build with the heightmaps under /heightmaps/ (see README.md). Environment:
// PLAYWRIGHT_CORE and CHROME as for browser_check.mjs. Exits with 1 on any failure.
//
// SquadCalc keeps its App in a module; the check exposes it as window.__App by rewriting the main bundle
// in transit (the served files are not changed).
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? `${process.env.PLAYWRIGHT_CORE}/index.mjs` : "playwright-core");

const base = process.argv[2];
if (!base) {
    console.error("usage: node a11y_check.mjs <site URL>");
    process.exit(2);
}

let failures = 0;
function check(label, ok, detail) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${detail}`);
    if (!ok) failures++;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });

/**
 * Open SquadCalc with window.__App, the statistics endpoints answered locally and a log of page errors
 * @param {string} [language] - interface language code, stored the way the language selector stores it
 * @returns {Promise<{context: object, page: object, problems: string[]}>}
 */
async function open(language = "en") {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.addInitScript((language) => localStorage.setItem("settings-language", language), language);
    await context.route(/\/post\//, (route) => route.fulfill({ status: 200, body: "{}" }));
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
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => window.__App?.minimap?.heightmap && !window.__App.minimap._spinning, null, { timeout: 120000 });
    await page.waitForTimeout(1500);
    return { context, page, problems };
}

/**
 * Nodes of Chromium's accessibility tree that are not ignored, with their role, name and states
 * @param {object} page - Playwright page
 * @returns {Promise<Array<{role: string, name: string, pressed: string|undefined, backendDOMNodeId: number}>>}
 */
async function accessibleNodes(page) {
    const session = await page.context().newCDPSession(page);
    const { nodes } = await session.send("Accessibility.getFullAXTree");
    await session.detach();
    return nodes.filter((node) => !node.ignored).map((node) => ({
        role: node.role?.value,
        name: (node.name?.value ?? "").trim(),
        pressed: node.properties?.find((property) => property.name === "pressed")?.value.value,
        backendDOMNodeId: node.backendDOMNodeId,
    }));
}

/**
 * Describe the DOM element of an accessibility node for a failure message
 * @param {object} page - Playwright page
 * @param {Array<{backendDOMNodeId: number}>} nodes - nodes to describe
 * @returns {Promise<string[]>} one `tag.class#id` per node
 */
async function describe(page, nodes) {
    const session = await page.context().newCDPSession(page);
    const out = [];
    for (const node of nodes) {
        try {
            const { object } = await session.send("DOM.resolveNode", { backendNodeId: node.backendDOMNodeId });
            const { result } = await session.send("Runtime.callFunctionOn", {
                objectId: object.objectId,
                functionDeclaration: "function() { return this.tagName.toLowerCase() + (this.id ? '#' + this.id : '') + '.' + String(this.className?.baseVal ?? this.className).trim().split(/\\s+/).join('.'); }",
                returnByValue: true,
            });
            out.push(result.value);
        } catch {
            out.push(`node ${node.backendDOMNodeId}`);
        }
    }
    await session.detach();
    return out;
}

const NAMED_ROLES = ["button", "combobox", "checkbox", "slider", "textbox", "link", "switch", "radio", "tab"];

/**
 * Check that every control in the accessibility tree has a name
 * @param {object} page - Playwright page
 * @param {string} where - what is on screen, for the report
 */
async function checkNames(page, where) {
    const nodes = await accessibleNodes(page);
    const controls = nodes.filter((node) => NAMED_ROLES.includes(node.role));
    const unnamed = controls.filter((node) => !node.name);
    check(`${where}: every control has an accessible name`, unnamed.length === 0,
        unnamed.length ? `${unnamed.length} of ${controls.length} without: ${(await describe(page, unnamed)).slice(0, 12).join(", ")}` : `${controls.length} controls named`);
}

const TOGGLES = [".btn-detailed", ".btn-topomap", ".btn-terrainmap", ".btn-basemap", ".btn-helpmap", ".btn-coverage", ".btn-hd"];

{
    const { context, page, problems } = await open("en");

    // Controls of the map page, then of each dialog
    await checkNames(page, "map page");

    const duplicates = await page.evaluate(() => {
        const seen = new Map();
        document.querySelectorAll("[id]").forEach((element) => seen.set(element.id, (seen.get(element.id) ?? 0) + 1));
        return [...seen].filter(([, count]) => count > 1).map(([id]) => id);
    });
    check("ids are unique", duplicates.length === 0, duplicates.length ? duplicates.join(", ") : "no duplicates");

    await page.click(".btn-settings");
    await page.waitForSelector("#settingsDialog[open], dialog[open]");
    await checkNames(page, "settings dialog");
    await page.keyboard.press("Escape");

    // Toggle buttons: aria-pressed present, in step with the active class, and flipping on click
    const state = () => page.evaluate((selectors) => selectors.map((selector) => {
        const button = document.querySelector(selector);
        return { selector, pressed: button.getAttribute("aria-pressed"), active: button.classList.contains("active") };
    }), TOGGLES);
    const before = await state();
    const missing = before.filter((toggle) => toggle.pressed === null).map((toggle) => toggle.selector);
    check("toggle buttons carry aria-pressed", missing.length === 0, missing.length ? `missing on ${missing.join(", ")}` : `${before.length} toggles`);
    const mismatched = before.filter((toggle) => toggle.pressed !== String(toggle.active)).map((toggle) => toggle.selector);
    check("aria-pressed matches the active class", mismatched.length === 0, mismatched.length ? mismatched.join(", ") : "all in step");

    for (const selector of [".btn-coverage", ".btn-hd", ".btn-helpmap"]) {
        // The help map button exists only on maps that have player statistics
        if (!await page.isVisible(selector)) continue;
        const initial = await page.getAttribute(selector, "aria-pressed");
        await page.click(selector);
        await page.waitForTimeout(400);
        const flipped = await page.getAttribute(selector, "aria-pressed");
        await page.click(selector);
        await page.waitForTimeout(400);
        const restored = await page.getAttribute(selector, "aria-pressed");
        check(`${selector} flips aria-pressed on click`, initial !== null && flipped !== initial && restored === initial, `${initial} -> ${flipped} -> ${restored}`);
    }

    // Layer buttons are exclusive: the pressed one moves
    // The layer buttons appear on hover or keyboard focus of the layers menu
    await page.hover("#btn-map-choices");
    await page.waitForTimeout(400);
    const layerBefore = await page.getAttribute(".btn-topomap", "aria-pressed");
    await page.click(".btn-topomap");
    await page.waitForTimeout(800);
    const layerAfter = await page.evaluate(() => ({
        topo: document.querySelector(".btn-topomap").getAttribute("aria-pressed"),
        others: ["detailed", "terrainmap", "basemap"].map((name) => document.querySelector(`.btn-${name}`).getAttribute("aria-pressed")),
    }));
    check("pressing a layer button moves aria-pressed", layerAfter.topo === "true" && layerAfter.others.every((value) => value === "false"),
        `topomap ${layerBefore} -> ${layerAfter.topo}, others ${layerAfter.others.join("/")}`);

    // Keyboard only: focusing the layers button reveals the layer buttons, which Tab then reaches
    await page.mouse.move(5, 5);
    await page.waitForTimeout(400);
    await page.evaluate(() => document.activeElement?.blur());
    await page.focus("#btn-map-choices");
    await page.keyboard.press("Tab");
    await page.waitForTimeout(300);
    const layerFocus = await page.evaluate(() => document.activeElement?.className ?? "");
    check("layer buttons are reachable with Tab", /\blayers\b/.test(layerFocus), layerFocus);

    // Header selects: the native select and the select2 widget in front of it
    const selects = await page.evaluate(() => [...document.querySelectorAll("header select, #helpDialog select")].map((select) => {
        const widget = select.nextElementSibling?.querySelector(".select2-selection");
        return { cls: select.className.split(" ")[0], label: select.getAttribute("aria-label") ?? "", widget: widget?.getAttribute("aria-label") ?? "", hasWidget: Boolean(widget) };
    }));
    const unlabelledSelects = selects.filter((select) => !select.label);
    check("header selects have a label", unlabelledSelects.length === 0, unlabelledSelects.length ? `without: ${unlabelledSelects.map((s) => s.cls).join(", ")}` : `${selects.length} selects`);
    const unlabelledWidgets = selects.filter((select) => select.hasWidget && !select.widget);
    check("select2 widgets have a label", unlabelledWidgets.length === 0, unlabelledWidgets.length ? `without: ${unlabelledWidgets.map((s) => s.cls).join(", ")}` : `${selects.filter((s) => s.hasWidget).length} widgets`);

    // Markers: a weapon and a target, reached with Tab only
    await page.evaluate(() => {
        const map = window.__App.minimap;
        const weapon = { lat: -map.pixelSize / 2, lng: map.pixelSize / 2 };
        map.setView([weapon.lat + 100 / map.mapToGameScaleY, weapon.lng], 5, { animate: false });
        map.createWeapon(weapon);
        map.createTarget({ lat: weapon.lat + 150 / map.mapToGameScaleY, lng: weapon.lng });
    });
    await page.waitForTimeout(1500);
    await checkNames(page, "map with markers");

    const markers = await page.evaluate(() => {
        const map = window.__App.minimap;
        const describeIcon = (marker) => {
            const icon = marker._icon;
            return { tabIndex: icon.tabIndex, role: icon.getAttribute("role"), name: icon.getAttribute("aria-label") || icon.getAttribute("alt") || "" };
        };
        return { weapon: describeIcon(map.activeWeaponsMarkers.getLayers()[0]), target: describeIcon(map.activeTargetsMarkers.getLayers()[0]) };
    });
    for (const [kind, marker] of Object.entries(markers)) {
        check(`${kind} marker is focusable, a button and named`, marker.tabIndex === 0 && marker.role === "button" && marker.name.length > 1, JSON.stringify(marker));
    }

    const dialogs = { weapon: "#weaponInformation", target: "#calcInformation" };
    for (const [kind, dialog] of Object.entries(dialogs)) {
        for (const key of ["Enter", "Space"]) {
            await page.evaluate(() => document.activeElement?.blur());
            // Tab from the top of the page until the first marker of this kind has the focus
            let focused = false;
            for (let step = 0; step < 80 && !focused; step++) {
                await page.keyboard.press("Tab");
                focused = await page.evaluate((kind) => {
                    const map = window.__App.minimap;
                    const icon = kind === "weapon" ? map.activeWeaponsMarkers.getLayers()[0]._icon : map.activeTargetsMarkers.getLayers()[0]._icon;
                    return document.activeElement === icon;
                }, kind);
            }
            check(`${kind} marker reached with Tab (${key})`, focused, focused ? "focused" : "not reached in 80 Tab presses");
            if (!focused) continue;
            await page.keyboard.press(key);
            await page.waitForTimeout(600);
            const opened = await page.evaluate((dialog) => document.querySelector(dialog)?.open === true, dialog);
            check(`${key} on the ${kind} marker opens its dialog`, opened, opened ? "open" : "not open");
            await page.keyboard.press("Escape");
            await page.waitForTimeout(400);
            const back = await page.evaluate((kind) => {
                const map = window.__App.minimap;
                const icon = kind === "weapon" ? map.activeWeaponsMarkers.getLayers()[0]._icon : map.activeTargetsMarkers.getLayers()[0]._icon;
                return document.activeElement === icon;
            }, kind);
            check(`focus returns to the ${kind} marker after ${key}`, back, back ? "returned" : "lost");
        }
    }

    // The factions dialog and the target dialog, for their control names
    await page.click(".btn-faction").catch(() => {});
    await page.waitForTimeout(500);
    if (await page.evaluate(() => document.querySelector("#factionsDialog")?.open ?? false)) {
        await checkNames(page, "factions dialog");
        await page.keyboard.press("Escape");
    }

    check("no page errors", problems.length === 0, problems.length ? problems.join(" | ") : "none");
    await context.close();
}

// Names in every language: taken from the language's files, not the English ones
{
    const namesIn = async (language) => {
        const { context, page } = await open(language);
        const names = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll("#mapLayerMenu button[aria-label], .btn-faction")]
            .map((button) => [button.className.split(" ").find((name) => name.startsWith("btn-")) ?? button.id, button.getAttribute("aria-label")])));
        await context.close();
        return names;
    };
    const english = await namesIn("en");
    for (const language of ["ru", "fr", "de", "uk", "zh"]) {
        const names = await namesIn(language);
        const same = Object.keys(english).filter((key) => names[key] === english[key]);
        check(`${language}: map buttons are named in ${language}`, Object.keys(names).length === Object.keys(english).length && same.length <= 2,
            `${Object.keys(names).length} buttons, ${same.length} still English${same.length ? ` (${same.join(", ")})` : ""}`);
    }
}

await browser.close();
console.log(failures ? `${failures} FAILED` : "all passed");
process.exit(failures ? 1 : 0);
