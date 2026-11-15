/**
 * A SquadHeightmap in the state of its constructor before any load, without the constructor (which starts the
 * heightmap worker, absent in Node): the checks hand it a worker's result through `receive`, which reads it with the
 * engine's core (public/engine of the checkout, built by `npm run build:engine`; register.mjs gives the heightmap its
 * loader).
 * @param {typeof import("SquadHeightmap")} SquadHeightmap - the class of the checkout under test
 * @param {object} map - the map it belongs to ({pixelSize}); `map.heightmap` is set to the new heightmap
 * @returns {object} the heightmap
 */
export function blankHeightmap(SquadHeightmap, map) {
    const heightmap = Object.assign(Object.create(SquadHeightmap.prototype), {
        map, core: null, toEngine: null, resolution: 0, ready: false, failed: false, detailFailed: false, detailError: "", worker: null,
    });
    map.heightmap = heightmap;
    return heightmap;
}
