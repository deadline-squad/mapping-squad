// Node hooks for the checks: SquadCalc's ../app.js (the whole UI) and leaflet are replaced by stubs.
import { registerHooks } from "node:module";

registerHooks({
    resolve(specifier, context, next) {
        if (specifier === "../app.js") return { url: new URL("./stub-app.mjs", import.meta.url).href, shortCircuit: true };
        // Leaflet needs a browser; the pure functions under test do not use it
        if (specifier === "leaflet") return { url: new URL("./stub-leaflet.mjs", import.meta.url).href, shortCircuit: true };
        return next(specifier, context);
    },
});
