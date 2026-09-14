#!/usr/bin/env python3
"""List (or randomly sample) the tiles that actually exist in a local PMTiles v3
archive, by reading its directories directly. Stdlib only.

Why: benchmarking by picking random coordinates inside a source's bounds mostly
measures empty-tile (204) responses on sparse archives -- vbm has 1,531 tiles
scattered over a bounding box that holds tens of thousands of coordinates, and
some archives (Mapterhorn builds) declare whole-world bounds. Reading the
directory gives the real tile set without sending a single request to Martin.

Usage: pmtiles_list.py <archive.pmtiles> [--sample N] [--seed S] [--zooms 12-17]
Prints one `z/x/y` per line.
"""
import argparse
import gzip
import random
import struct
import sys


def read_varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def decode_directory(raw, compression):
    buf = gzip.decompress(raw) if compression == 2 else raw
    n, pos = read_varint(buf, 0)
    ids, runs, lens, offs = [0] * n, [0] * n, [0] * n, [0] * n
    last = 0
    for i in range(n):
        d, pos = read_varint(buf, pos)
        last += d
        ids[i] = last
    for i in range(n):
        runs[i], pos = read_varint(buf, pos)
    for i in range(n):
        lens[i], pos = read_varint(buf, pos)
    for i in range(n):
        v, pos = read_varint(buf, pos)
        # 0 means "immediately follows the previous entry" (spec: offset = prev + len)
        offs[i] = offs[i - 1] + lens[i - 1] if (v == 0 and i > 0) else v - 1
    return zip(ids, runs, lens, offs)


def rotate(n, x, y, rx, ry):
    if ry == 0:
        if rx == 1:
            x, y = n - 1 - x, n - 1 - y
        x, y = y, x
    return x, y


def tileid_to_zxy(tid):
    acc = 0
    for z in range(32):
        count = 1 << (2 * z)
        if acc + count > tid:
            pos, n = tid - acc, 1 << z
            x = y = 0
            s, t = 1, pos
            while s < n:
                rx = 1 & (t // 2)
                ry = 1 & (t ^ rx)
                x, y = rotate(s, x, y, rx, ry)
                x += s * rx
                y += s * ry
                t //= 4
                s *= 2
            return z, x, y
        acc += count
    raise ValueError(tid)


def walk(f, header):
    """Yield (first_tile_id, run_length) for every tile run in the archive."""
    root_off, root_len, _, _, leaf_off, _ = struct.unpack_from("<6Q", header, 8)
    compression = header[97]
    stack = [(root_off, root_len)]
    while stack:
        off, length = stack.pop()
        f.seek(off)
        for tid, run, ln, eoff in decode_directory(f.read(length), compression):
            if run == 0:
                stack.append((leaf_off + eoff, ln))  # leaf directory pointer
            else:
                yield tid, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--zooms")
    a = ap.parse_args()
    zlo, zhi = 0, 99
    if a.zooms:
        lo, _, hi = a.zooms.partition("-")
        zlo, zhi = int(lo), int(hi or lo)

    with open(a.archive, "rb") as f:
        header = f.read(127)
        if header[:7] != b"PMTiles" or header[7] != 3:
            sys.exit("not a PMTiles v3 archive")
        rng = random.Random(a.seed)
        reservoir, seen = [], 0
        for tid, run in walk(f, header):
            for t in range(tid, tid + run):
                z, x, y = tileid_to_zxy(t)
                if not zlo <= z <= zhi:
                    continue
                if not a.sample:
                    print(f"{z}/{x}/{y}")
                    continue
                seen += 1
                if len(reservoir) < a.sample:
                    reservoir.append((z, x, y))
                else:
                    j = rng.randrange(seen)
                    if j < a.sample:
                        reservoir[j] = (z, x, y)
        for z, x, y in reservoir:
            print(f"{z}/{x}/{y}")
        if a.sample:
            print(f"# sampled {len(reservoir)} of {seen} tiles", file=sys.stderr)


if __name__ == "__main__":
    main()
