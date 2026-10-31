// Decoder and ray query for VCOL1 (see py/codec.py). Works in Node and, with DecompressionStream, in a browser.
import { gunzipSync } from "node:zlib";

/** Parse a gzip'd VCOL1 buffer into column-indexed run arrays. */
export function decode(gz) {
  const raw = gunzipSync(gz);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const header = {
    minX: view.getFloat32(8, true), minY: view.getFloat32(12, true), cell: view.getFloat32(16, true),
    dz: view.getFloat32(20, true), zMin: view.getFloat32(24, true),
    width: view.getUint32(28, true), height: view.getUint32(32, true),
  };
  const columns = view.getUint32(36, true);
  let pos = 40;
  const varint = () => {
    let value = 0, shift = 0, b;
    do { b = raw[pos++]; value += (b & 0x7f) * 2 ** shift; shift += 7; } while (b & 0x80);
    return value;
  };
  const ids = new Uint32Array(columns);
  const first = new Uint32Array(columns + 1); // index of each column's first run
  let runs = new Uint32Array(1 << 20); // pairs: z start, z end (exclusive)
  let n = 0, id = 0;
  for (let c = 0; c < columns; c++) {
    id += varint();
    ids[c] = id;
    first[c] = n;
    let end = 0;
    for (let k = varint(); k > 0; k--) {
      const start = end + varint();
      end = start + varint() + 1;
      if (2 * n + 2 > runs.length) { const grown = new Uint32Array(runs.length * 2); grown.set(runs); runs = grown; }
      runs[2 * n] = start; runs[2 * n + 1] = end; n++;
    }
  }
  first[columns] = n;
  return { header, ids, first, runs, runCount: n };
}

/** Whether voxel (col,row,zi) is occupied: binary search of the column id, then its runs. */
export function occupied(map, col, row, zi) {
  const { ids, first, runs, header } = map;
  const id = row * header.width + col;
  let lo = 0, hi = ids.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ids[mid] < id) lo = mid + 1; else if (ids[mid] > id) hi = mid - 1;
    else {
      for (let r = first[mid]; r < first[mid + 1]; r++) if (zi >= runs[2 * r] && zi < runs[2 * r + 1]) return true;
      return false;
    }
  }
  return false;
}

/** Segment test by sampling every min(cell, dz) / 3 metres; `terrain(x, y)` gives the landscape height. */
export function blocked(map, terrain, p0, p1) {
  const { header } = map;
  const step = Math.min(header.cell, header.dz) / 3;
  const length = Math.hypot(p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]);
  const n = Math.max(2, Math.ceil(length / step) + 1);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const x = p0[0] + t * (p1[0] - p0[0]), y = p0[1] + t * (p1[1] - p0[1]), z = p0[2] + t * (p1[2] - p0[2]);
    if (z < terrain(x, y)) return true;
    const col = Math.floor((x - header.minX) / header.cell), row = Math.floor((y - header.minY) / header.cell);
    if (col < 0 || row < 0 || col >= header.width || row >= header.height) continue;
    if (occupied(map, col, row, Math.floor((z - header.zMin) / header.dz))) return true;
  }
  return false;
}
