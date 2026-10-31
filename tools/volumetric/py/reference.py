"""Exact reference ray/segment queries against the collision triangles, independent of the voxel builder.

Shares nothing with columns.py except the input triangle soup: no sampling, no voxels. Triangles are
bucketed by the TILE_M horizontal tiles their bounding box overlaps; a segment gathers the triangles of the
tiles it crosses and tests each with Moller-Trumbore in float64. Used to judge the heightmap and the voxel
columns, never in the product.
"""

import numpy as np

TILE_M = 8.0


class TriangleIndex:
    """Tile-bucketed triangle soup. ``tris`` float32 [n, 3, 3] world metres; ``mask`` uint8 query-class bits."""

    def __init__(self, tris, mask, min_x, min_y, width_m, height_m):
        self.tris, self.mask = tris, mask
        self.min_x, self.min_y = min_x, min_y
        self.nx = int(np.ceil(width_m / TILE_M))
        self.ny = int(np.ceil(height_m / TILE_M))
        lo = tris.min(axis=1)
        hi = tris.max(axis=1)
        x0 = np.clip(((lo[:, 0] - min_x) // TILE_M).astype(np.int64), 0, self.nx - 1)
        x1 = np.clip(((hi[:, 0] - min_x) // TILE_M).astype(np.int64), 0, self.nx - 1)
        y0 = np.clip(((lo[:, 1] - min_y) // TILE_M).astype(np.int64), 0, self.ny - 1)
        y1 = np.clip(((hi[:, 1] - min_y) // TILE_M).astype(np.int64), 0, self.ny - 1)
        ids, tile = [], []
        span_x, span_y = x1 - x0, y1 - y0
        for dy in range(int(span_y.max()) + 1):
            for dx in range(int(span_x.max()) + 1):
                sel = np.nonzero((span_x >= dx) & (span_y >= dy))[0]
                ids.append(sel.astype(np.int32))
                tile.append((y0[sel] + dy) * self.nx + x0[sel] + dx)
        ids, tile = np.concatenate(ids), np.concatenate(tile)
        order = np.argsort(tile, kind="stable")
        self.ids = ids[order]
        self.start = np.searchsorted(tile[order], np.arange(self.nx * self.ny + 1))

    def tiles_on(self, p0, p1):
        """Tile ids crossed by the horizontal projection of a segment (sampled at TILE_M / 4)."""
        n = max(2, int(np.ceil(np.hypot(*(p1[:2] - p0[:2])) / (TILE_M / 4))) + 1)
        t = np.linspace(0, 1, n)[:, None]
        pts = p0[None, :2] + t * (p1[:2] - p0[:2])[None, :]
        ix = np.clip(((pts[:, 0] - self.min_x) // TILE_M).astype(np.int64), 0, self.nx - 1)
        iy = np.clip(((pts[:, 1] - self.min_y) // TILE_M).astype(np.int64), 0, self.ny - 1)
        return np.unique(iy * self.nx + ix)

    def candidates(self, p0, p1, bit):
        tiles = self.tiles_on(p0, p1)
        ids = np.unique(np.concatenate([self.ids[self.start[t]:self.start[t + 1]] for t in tiles]))
        return ids[(self.mask[ids] & bit) != 0]

    def hits(self, p0, p1, bit):
        """Hits of segment p0->p1 with triangles blocking `bit`: (t in [0,1] sorted, triangle ids, normal z)."""
        ids = self.candidates(np.asarray(p0, float), np.asarray(p1, float), bit)
        if len(ids) == 0:
            return np.empty(0), np.empty(0, np.int64), np.empty(0)
        t = self.tris[ids].astype(np.float64)
        a, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        d = np.asarray(p1, float) - np.asarray(p0, float)
        h = np.cross(d[None, :], e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = np.asarray(p0, float)[None, :] - a
        u = inv * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, e1)
        v = inv * (q @ d)
        tt = inv * np.einsum("ij,ij->i", e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (tt >= 0) & (tt <= 1)
        n = np.cross(e1[hit], e2[hit])
        nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
        order = np.argsort(tt[hit])
        return tt[hit][order], ids[hit][order], nz[order]

    def blocked(self, p0, p1, bit, ignore_ends_m=0.0):
        """True when any blocking triangle crosses the open segment (ends trimmed by `ignore_ends_m`)."""
        t, ids, _ = self.hits(p0, p1, bit)
        length = np.linalg.norm(np.asarray(p1, float) - np.asarray(p0, float))
        margin = ignore_ends_m / max(length, 1e-9)
        return bool(((t > margin) & (t < 1 - margin)).any()), ids[(t > margin) & (t < 1 - margin)]

    def floors(self, x, y, z_top, z_bottom, bit, headroom_m=1.9):
        """Standable surfaces on the vertical line (x, y): z of up-facing hits (normal.z > 0.7) with at least
        `headroom_m` free above them (next hit above, up- or down-facing, is farther than that)."""
        t, ids, nz = self.hits([x, y, z_top], [x, y, z_bottom], bit)
        z = z_top + t * (z_bottom - z_top)
        out = []
        for i in range(len(z)):
            if nz[i] > 0.7 and (i == 0 or z[i - 1] - z[i] >= headroom_m):
                out.append(float(z[i]))
        return out
