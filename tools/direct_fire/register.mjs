// Node hooks for the checks: SquadCalc's ../app.js (the whole UI) and leaflet are replaced by stubs, and the heightmap's
// engine loader (squadEngine.js) by the checkout's tests/stubs/engine.mjs.
import { registerHooks } from "node:module";

registerHooks({
    resolve(specifier, context, next) {
        // SquadHeightmap loads the engine from the page's URL; Node reads the checkout's own build (public/engine) through its test stub
        if (specifier === "./squadEngine.js" && context.parentURL?.endsWith("/src/js/squadHeightmaps.js")) {
            return { url: new URL("../../tests/stubs/engine.mjs", context.parentURL).href, shortCircuit: true };
        }
        if (specifier === "../app.js") return { url: new URL("./stub-app.mjs", import.meta.url).href, shortCircuit: true };
        // Leaflet needs a browser; the pure functions under test do not use it
        if (specifier === "leaflet") return { url: new URL("./stub-leaflet.mjs", import.meta.url).href, shortCircuit: true };
        return next(specifier, context);
    },
});
