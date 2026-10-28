// Node hooks for solve.mjs: SquadCalc's ../app.js (the whole UI) is replaced by stub-app.mjs.
import { registerHooks } from "node:module";

registerHooks({
    resolve(specifier, context, next) {
        if (specifier === "../app.js") return { url: new URL("./stub-app.mjs", import.meta.url).href, shortCircuit: true };
        return next(specifier, context);
    },
});
