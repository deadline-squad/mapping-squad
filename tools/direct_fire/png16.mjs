// The 16-bit grayscale heightmap.png of tools/heightmaps, read in Node without a package: what the benches and checks
// of tools/direct_fire and tools/browser_check compare the page with. Not interlaced, filters 0 to 4 (PNG 1.2).
import { inflateSync } from "node:zlib";

/**
 * Decode a 16-bit grayscale PNG
 * @param {Uint8Array} bytes - the file
 * @returns {{width: number, height: number, data: Uint16Array}} - the levels, row-major
 * @throws {Error} - another kind of PNG, or a damaged one
 */
export function decodePng16(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (view.getUint32(0) !== 0x89504e47 || view.getUint32(4) !== 0x0d0a1a0a) throw new Error("not a PNG");
    let width = 0;
    let height = 0;
    const compressed = [];
    for (let offset = 8; offset + 8 <= bytes.length;) {
        const length = view.getUint32(offset);
        const type = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8));
        const data = bytes.subarray(offset + 8, offset + 8 + length);
        if (type === "IHDR") {
            width = view.getUint32(offset + 8);
            height = view.getUint32(offset + 12);
            const [depth, colorType, , , interlace] = data.subarray(8);
            if (depth !== 16 || colorType !== 0 || interlace !== 0) throw new Error("not a 16-bit grayscale PNG without interlace");
        } else if (type === "IDAT") {
            compressed.push(data);
        } else if (type === "IEND") {
            break;
        }
        offset += 12 + length;
    }
    const stride = width * 2;
    const raw = inflateSync(Buffer.concat(compressed));
    if (raw.length !== (stride + 1) * height) throw new Error(`PNG data of ${raw.length} bytes for ${width} x ${height}`);
    const data = new Uint16Array(width * height);
    for (let y = 0; y < height; y++) {
        const row = y * (stride + 1) + 1;
        const above = row - stride - 1;
        const filter = raw[row - 1];
        for (let i = 0; i < stride; i++) {
            const left = i >= 2 ? raw[row + i - 2] : 0;
            const up = y > 0 ? raw[above + i] : 0;
            const upLeft = y > 0 && i >= 2 ? raw[above + i - 2] : 0;
            let predictor = 0;
            if (filter === 1) predictor = left;
            else if (filter === 2) predictor = up;
            else if (filter === 3) predictor = (left + up) >> 1;
            else if (filter === 4) {
                const estimate = left + up - upLeft;
                const [toLeft, toUp, toUpLeft] = [Math.abs(estimate - left), Math.abs(estimate - up), Math.abs(estimate - upLeft)];
                predictor = toLeft <= toUp && toLeft <= toUpLeft ? left : toUp <= toUpLeft ? up : upLeft;
            } else if (filter !== 0) throw new Error(`PNG filter ${filter}`);
            raw[row + i] = (raw[row + i] + predictor) & 0xFF;
        }
        for (let x = 0; x < width; x++) data[y * width + x] = (raw[row + 2 * x] << 8) | raw[row + 2 * x + 1];
    }
    return { width, height, data };
}
