// Writers of the VCOL1 and TER2 files (the format of tools/volumetric/py/codec.py and terrain_raster.py) for synthetic scenes,
// so that the checks can feed the volume layer (squadVolume.js, volumeWorker.js, volumeTerrain.js) without game data.
import { gzipSync } from "node:zlib";

const varints = (values) => {
    const out = [];
    for (let v of values) {
        while (v >= 0x80) { out.push((v & 0x7f) | 0x80); v = Math.floor(v / 128); }
        out.push(v);
    }
    return out;
};

/**
 * gzip'd VCOL1 file
 * @param {{minX: number, minY: number, cell: number, dz: number, zMin: number, width: number, height: number}} grid
 * @param {Map<number, number[][]>} columns - column id (row * width + col) -> runs [first z index, exclusive last z index]
 */
export function writeVolume(grid, columns) {
    const ids = [...columns.keys()].sort((a, b) => a - b);
    const body = [];
    let last = 0;
    for (const id of ids) {
        const runs = columns.get(id).sort((a, b) => a[0] - b[0]);
        body.push(...varints([id - last, runs.length]));
        let end = 0;
        for (const [start, stop] of runs) {
            body.push(...varints([start - end, stop - start - 1]));
            end = stop;
        }
        last = id;
    }
    const head = Buffer.alloc(40);
    head.write("VCOL1", 0, "latin1");
    [grid.minX, grid.minY, grid.cell, grid.dz, grid.zMin].forEach((v, i) => head.writeFloatLE(v, 8 + 4 * i));
    head.writeUInt32LE(grid.width, 28);
    head.writeUInt32LE(grid.height, 32);
    head.writeUInt32LE(ids.length, 36);
    return gzipSync(Buffer.concat([head, Buffer.from(body)]));
}

/**
 * gzip'd TER2 file with a vertex axes aligned with the world (yaw 0)
 * @param {{minX: number, minY: number, cell: number, zMin: number, step: number, width: number, height: number}} grid
 *   - minX, minY: world position of vertex (0, 0)
 * @param {function(number, number): number|null} heightAt - landscape height of the vertex (column, row); null: no landscape
 * @param {number[]} [holes] - vertex indices (row * width + column) of the holes
 */
export function writeTerrain(grid, heightAt, holes = []) {
    const { width, height } = grid;
    const levels = new Int32Array(width * height);
    for (let row = 0; row < height; row++) {
        for (let col = 0; col < width; col++) {
            const z = heightAt(col, row);
            levels[row * width + col] = z === null ? 0 : Math.round((z - grid.zMin) / grid.step) + 1;
        }
    }
    const count = width * height;
    const planes = Buffer.alloc(2 * count);
    for (let row = 0; row < height; row++) {
        for (let col = 0; col < width; col++) {
            const i = row * width + col;
            const left = col > 0 ? levels[i - 1] : 0;
            const above = row > 0 ? levels[i - width] : 0;
            const aboveLeft = row > 0 && col > 0 ? levels[i - width - 1] : 0;
            let residual = (levels[i] - (left + above - aboveLeft)) & 0xffff;
            if (residual >= 0x8000) residual -= 0x10000;
            const zigzag = ((residual << 1) ^ (residual >> 15)) & 0xffff;
            planes[i] = zigzag & 0xff;
            planes[count + i] = zigzag >> 8;
        }
    }
    const head = Buffer.alloc(56);
    head.write("TER2", 0, "latin1");
    [grid.minX, grid.minY, grid.cell].forEach((v, i) => head.writeDoubleLE(v, 8 + 8 * i));
    [0, grid.zMin, grid.step].forEach((v, i) => head.writeFloatLE(v, 32 + 4 * i));
    head.writeUInt32LE(width, 44);
    head.writeUInt32LE(height, 48);
    head.writeUInt32LE(holes.length, 52);
    const holeBytes = [];
    let previous = 0;
    for (const hole of [...holes].sort((a, b) => a - b)) {
        holeBytes.push(...varints([hole - previous]));
        previous = hole;
    }
    return gzipSync(Buffer.concat([head, planes, Buffer.from(holeBytes)]));
}
