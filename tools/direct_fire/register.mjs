// Node hooks for the checks: SquadCalc's ../app.js (the whole UI) and leaflet are replaced by stubs, the heightmap's
// engine loader (squadEngine.js) by the checkout's tests/stubs/engine.mjs, the volume worker's engine URL by the
// checkout's public/engine, and package.json, which webpack imports without the attribute Node needs, is served as a
// module (like the checkout's tests/loader.mjs).
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";

registerHooks({
    resolve(specifier, context, next) {
        // SquadHeightmap loads the engine from the page's URL; Node reads the checkout's own build (public/engine) through its test stub
        if (specifier === "./squadEngine.js" && context.parentURL?.endsWith("/src/js/squadHeightmaps.js")) {
            return { url: new URL("../../tests/stubs/engine.mjs", context.parentURL).href, shortCircuit: true };
        }
        // The volume worker imports the engine from the page's URL (/engine/index.mjs?v=<version>)
        if (context.parentURL?.endsWith("/src/js/volumeWorker.js") && /^https?:/.test(specifier)) {
            return { url: new URL(`../../public${new URL(specifier).pathname}`, context.parentURL).href, shortCircuit: true };
        }
        if (specifier === "../app.js") return { url: new URL("./stub-app.mjs", import.meta.url).href, shortCircuit: true };
        // Leaflet needs a browser; the pure functions under test do not use it
        if (specifier === "leaflet") return { url: new URL("./stub-leaflet.mjs", import.meta.url).href, shortCircuit: true };
        return next(specifier, context);
    },
    load(url, context, next) {
        if (!url.endsWith("/package.json") || context.importAttributes?.type === "json") return next(url, context);
        return { format: "module", source: `export default ${readFileSync(new URL(url), "utf8")};`, shortCircuit: true };
    },
});
