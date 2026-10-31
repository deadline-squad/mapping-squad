// node bench.mjs <file.vcol> [queries]: decode time, run count and the speed of 40 m eye-level segment tests.
import { readFileSync } from "node:fs";
import { decode, blocked } from "./vcol.mjs";

const gz = readFileSync(process.argv[2]);
const queries = Number(process.argv[3] ?? 20000);
let t = performance.now();
const map = decode(gz);
const decodeMs = performance.now() - t;
const { header } = map;
let seed = 12345;
const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);
const inObjects = () => { const k = Math.floor(rand() * map.ids.length), c = map.ids[k]; return [header.minX + (c % header.width + 0.5) * header.cell, header.minY + (Math.floor(c / header.width) + 0.5) * header.cell, header.zMin + header.dz * map.runs[2 * map.first[k]] + 1.6]; };
let voxels = 0;
for (let r = 0; r < map.runCount; r++) voxels += map.runs[2 * r + 1] - map.runs[2 * r];
let blockedCount = 0;
t = performance.now();
for (let i = 0; i < queries; i++) {
  const [x, y, z] = inObjects();
  const a = rand() * 6.283, d = 40;
  if (blocked(map, () => -1e9, [x, y, z], [x + d * Math.cos(a), y + d * Math.sin(a), z])) blockedCount++;
}
const queryMs = performance.now() - t;
console.log(JSON.stringify({ gzBytes: gz.length, decodeMs: Math.round(decodeMs), columns: map.ids.length, runs: map.runCount, voxels,
  heapMB: Math.round((map.ids.byteLength + map.first.byteLength + map.runs.byteLength) / 1e6), queries,
  usPerQuery: Math.round(1000 * queryMs / queries), blockedCount }));
