"""Binary form of the sparse voxel columns ("VCOL1"): row-run-length columns, varint packed, then gzip.

Layout (little endian), before gzip:
    magic "VCOL1\\0\\0\\0", float32 min_x, min_y, cell, dz, z_min, uint32 width, height, n_columns
    then for every occupied column in key order: varint (column id delta), varint run count, and per run
    varint (z index delta from the previous run's end; the first from 0), varint (run length - 1).
A run is a maximal stack of occupied voxels in one column. The browser reads it with
DecompressionStream("gzip") and a ~40 line decoder (see decode.mjs).
"""

import gzip
import struct

import numpy as np

import columns

MAGIC = b"VCOL1\0\0\0"
HEADER = "<8s5f3I"


def _varints(values):
    out = bytearray()
    for v in values:
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80)
            v >>= 7
        out.append(v)
    return out


def encode(occupied, grid):
    """gzip bytes of the VCOL1 file for sorted unique voxel keys `occupied`."""
    mask = (1 << columns.Z_BITS) - 1
    column = occupied >> columns.Z_BITS
    z = occupied & mask
    breaks = np.nonzero((np.diff(column) != 0) | (np.diff(z) != 1))[0] + 1
    starts = np.concatenate([[0], breaks])
    ends = np.concatenate([breaks, [len(occupied)]])
    run_col, run_z, run_len = column[starts], z[starts], ends - starts
    first = np.concatenate([[True], np.diff(run_col) != 0])
    col_ids = run_col[first]
    col_index = np.cumsum(first) - 1
    runs_per_col = np.bincount(col_index)
    prev_end = np.where(first, 0, np.concatenate([[0], (run_z + run_len)[:-1]]))
    z_delta = run_z - prev_end
    body = bytearray()
    run_cursor = 0
    last = 0
    for c, (cid, n) in enumerate(zip(col_ids.tolist(), runs_per_col.tolist())):
        body += _varints([cid - last, n])
        for k in range(run_cursor, run_cursor + n):
            body += _varints([int(z_delta[k]), int(run_len[k]) - 1])
        run_cursor += n
        last = cid
    head = struct.pack(HEADER, MAGIC, grid.min_x, grid.min_y, grid.cell, grid.dz, grid.z_min, grid.width, grid.height, len(col_ids))
    return gzip.compress(bytes(head) + bytes(body), 6)


def decode(blob):
    """(occupied keys, header dict) from `encode` output; inverse for tests and the evaluation."""
    raw = gzip.decompress(blob)
    size = struct.calcsize(HEADER)
    magic, min_x, min_y, cell, dz, z_min, width, height, n_columns = struct.unpack_from(HEADER, raw, 0)
    if magic != MAGIC:
        raise ValueError("not a VCOL1 file")
    pos = size
    keys = []
    last = 0

    def varint():
        nonlocal pos
        shift = value = 0
        while True:
            b = raw[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if b < 0x80:
                return value
            shift += 7

    for _ in range(n_columns):
        last += varint()
        end = 0
        for _ in range(varint()):
            start = end + varint()
            length = varint() + 1
            keys.append((last << columns.Z_BITS) + np.arange(start, start + length))
            end = start + length
    header = dict(min_x=min_x, min_y=min_y, cell=cell, dz=dz, z_min=z_min, width=width, height=height)
    return np.concatenate(keys).astype(np.int64), header
