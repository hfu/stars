#!/usr/bin/env python3
"""Tile load generator for stars benchmark/soak runs. Stdlib only.

Run it from a machine other than the Pi (it measures the Pi, so it must not
compete with it for CPU). Point it at Martin's origin on the LAN
(http://stars.local:3000) to measure the Pi itself; the public URL goes through
Cloudflare's edge cache and would mostly measure Cloudflare instead.

Safety rails, enforced in code rather than left to the operator:
  * Sources backed by a remote URL in config/martin.yaml are refused: load on
    them lands on third parties (GSI, OSM Japan, Source Cooperative, ...).
  * Runs stop early if the error rate over the last window exceeds
    --max-error-rate, or if the stop file (--stop-file) appears.
  * Optional --temp-cmd is polled; the run stops at --max-temp-c.

Examples:
  # calibrate the client itself against a near-free endpoint
  loadgen.py --base http://stars.local:3000 --health --concurrency 1,4,16 --duration 5
  # step concurrency on one local source, random tiles across its coverage
  loadgen.py --base http://stars.local:3000 --source vbm --concurrency 1,2,4,8,16,32 \\
      --duration 30 --out results.json
"""
import argparse
import http.client
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from urllib.parse import urlparse

UA = "stars-bench/1.0"
REPO = Path(__file__).resolve().parents[2]


def remote_sources():
    """Source ids whose config value is a remote URL. Parsed by line so this
    has no PyYAML dependency; config/martin.yaml is simple and canonical."""
    ids = set()
    for line in (REPO / "config" / "martin.yaml").read_text().splitlines():
        s = line.strip()
        if ":" in s:
            key, _, val = s.partition(":")
            if val.strip().startswith(("http://", "https://")):
                ids.add(key.strip())
    return ids


def connect(u, addr=None):
    """One HTTP(S) connection to `u`.

    Phase 2 measures through Cloudflare, so https is supported: there the
    hostname (not a pre-resolved IP) is used, because the TLS handshake needs
    SNI and Cloudflare's anycast address is resolved per connection anyway.
    Plain http keeps the Phase 1 behaviour of connecting to a pinned address.
    """
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=30)
    return http.client.HTTPConnection(addr or u.hostname, u.port or 80, timeout=30)


def get_json(base, path):
    u = urlparse(base)
    c = connect(u)
    c.request("GET", path, headers={"User-Agent": UA})
    r = c.getresponse()
    body = r.read()
    c.close()
    if r.status != 200:
        raise RuntimeError(f"GET {path}: {r.status}")
    return json.loads(body)


def tile_range(tj, zooms):
    """All z/x/y inside the TileJSON bounds for the given zooms."""
    w, s, e, n = tj["bounds"]
    out = []
    for z in zooms:
        k = 2 ** z
        x0 = int((w + 180) / 360 * k)
        x1 = int((e + 180) / 360 * k)
        y0 = int((1 - math.asinh(math.tan(math.radians(n))) / math.pi) / 2 * k)
        y1 = int((1 - math.asinh(math.tan(math.radians(s))) / math.pi) / 2 * k)
        for x in range(max(x0, 0), min(x1, k - 1) + 1):
            for y in range(max(y0, 0), min(y1, k - 1) + 1):
                out.append((z, x, y))
    return out


def size_stats(sizes):
    """Per-tile body size of successful responses.

    Latency differences between two tile sets can come from the tiles
    themselves rather than the server or network: mapterhorn-japan-bridge
    merges 1 m / 5 m / 10 m DEMs, so a block covered by 1 m survey carries more
    detail per tile and weighs more. Reporting size next to latency is what
    lets a reader tell "different place" from "different conditions".
    """
    if not sizes:
        return {"tile_bytes_mean": None, "tile_bytes_p50": None}
    s = sorted(sizes)
    return {"tile_bytes_mean": round(sum(s) / len(s)), "tile_bytes_p50": s[len(s) // 2]}


def bust(path, args):
    """Append a unique query string so a CDN edge can't answer from cache.

    Phase 2 measures the origin's uplink, not Cloudflare's cache, so every
    request must miss the edge. Martin ignores unknown query parameters for
    pmtiles sources, so the tile served is the same one.
    """
    if not getattr(args, "cache_bust", False):
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}cb={random.getrandbits(48):012x}"


def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


class Run:
    def __init__(self, base, paths, concurrency, duration, args):
        self.base, self.paths = urlparse(base), paths
        # Resolve once up front. Connecting by name re-resolves on every new
        # connection, and `stars.local` goes through mDNS, which added ~1s to
        # each thread's first request in calibration -- enough to pollute p99
        # and max at every concurrency level. The Host header keeps the name.
        self.addr = None if self.base.scheme == "https" else socket.gethostbyname(self.base.hostname)
        self.headers = {"User-Agent": UA}
        if self.base.scheme != "https":
            # Only meaningful when connecting to a pinned address.
            self.headers["Host"] = self.base.netloc
        # Browsers always send Accept-Encoding. Without it Martin *decompresses*
        # gzip-stored vector tiles on the fly and returns bodies ~2-2.4x larger
        # (measured on vbm), i.e. a code path real viewers never hit. Off only
        # via --no-accept-encoding, as a deliberate CPU-bound variant.
        if not args.no_accept_encoding:
            self.headers["Accept-Encoding"] = "gzip, deflate, br"
        self.concurrency, self.duration, self.args = concurrency, duration, args
        self.lock = threading.Lock()
        self.lat, self.status, self.bytes = [], Counter(), 0
        self.sizes = []  # body bytes of 200 responses, for per-tile size stats
        self.window = deque(maxlen=200)  # recent (ok: bool) for the error-rate brake
        self.cdn = Counter()  # cf-cache-status values, when going through a CDN
        self.stop_reason = None
        self.stop = threading.Event()

    def worker(self, seed):
        rng = random.Random(seed)
        conn = None
        while not self.stop.is_set():
            path = bust(rng.choice(self.paths), self.args)
            t = time.perf_counter()
            try:
                if conn is None:
                    conn = connect(self.base, self.addr)
                conn.request("GET", path, headers=self.headers)
                r = conn.getresponse()
                n = len(r.read())
                code = r.status
                cf = r.getheader("cf-cache-status")
            except Exception as e:  # connection reset, timeout, ...
                code, n, cf = type(e).__name__, 0, None
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
            dt = (time.perf_counter() - t) * 1000
            ok = isinstance(code, int) and code < 500
            with self.lock:
                self.lat.append(dt)
                self.status[code] += 1
                self.bytes += n
                if code == 200:
                    self.sizes.append(n)
                if cf:
                    self.cdn[cf] += 1
                self.window.append(ok)

    def guard(self):
        a = self.args
        next_temp = 0
        end = time.monotonic() + self.duration
        while time.monotonic() < end and not self.stop.is_set():
            time.sleep(0.5)
            with self.lock:
                w = list(self.window)
            if len(w) >= 50 and (w.count(False) / len(w)) > a.max_error_rate:
                self.stop_reason = f"error rate {w.count(False)/len(w):.1%} > {a.max_error_rate:.0%}"
                break
            if a.stop_file and os.path.exists(a.stop_file):
                self.stop_reason = f"stop file {a.stop_file}"
                break
            if a.temp_cmd and time.monotonic() >= next_temp:
                next_temp = time.monotonic() + a.temp_interval
                try:
                    out = subprocess.run(a.temp_cmd, shell=True, capture_output=True, text=True, timeout=20).stdout
                    temp = float(out.strip()) / (1000 if float(out.strip()) > 200 else 1)
                    if temp >= a.max_temp_c:
                        self.stop_reason = f"temperature {temp:.1f}C >= {a.max_temp_c}C"
                        break
                except Exception:
                    pass  # a failed poll must not abort the run by itself
        self.stop.set()

    def go(self):
        threads = [threading.Thread(target=self.worker, args=(i,), daemon=True)
                   for i in range(self.concurrency)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        self.guard()
        for t in threads:
            t.join(timeout=35)
        elapsed = time.monotonic() - t0
        lat = sorted(self.lat)
        n = len(lat)
        errors = sum(v for k, v in self.status.items() if not (isinstance(k, int) and k < 500))
        return {
            "concurrency": self.concurrency,
            "elapsed_s": round(elapsed, 2),
            "requests": n,
            "rps": round(n / elapsed, 1) if elapsed else None,
            "mb_per_s": round(self.bytes / elapsed / 1e6, 2) if elapsed else None,
            **size_stats(self.sizes),
            "latency_ms": {p: (round(pct(lat, p), 1) if n else None) for p in (50, 90, 95, 99)}
                          | {"max": round(lat[-1], 1) if n else None},
            "status": {str(k): v for k, v in sorted(self.status.items(), key=lambda kv: str(kv[0]))},
            **({"cf_cache_status": dict(self.cdn)} if self.cdn else {}),
            "error_rate": round(errors / n, 4) if n else None,
            "stopped_early": self.stop_reason,
        }


def run_once(base, paths, concurrency, args):
    """Fetch every path exactly once, `concurrency` at a time, and report how
    long the whole batch took to complete.

    This is the question a caching consumer actually has ("how long until this
    block of tiles is all here?"), and it differs from sustained throughput: a
    consumer that caches never fetches the same block twice, so a timed loop
    over the same tiles overstates its wait once the Pi's page cache warms up.
    Use a block nothing has requested recently if the point is a cold fetch.
    """
    u = urlparse(base)
    addr = None if u.scheme == "https" else socket.gethostbyname(u.hostname)
    headers = {"User-Agent": UA}
    if u.scheme != "https":
        headers["Host"] = u.netloc
    if not args.no_accept_encoding:
        headers["Accept-Encoding"] = "gzip, deflate, br"
    queue = deque(paths)
    lock = threading.Lock()
    lat, status, total, sizes = [], Counter(), [0], []

    def worker():
        conn = None
        while True:
            with lock:
                if not queue:
                    break
                path = queue.popleft()
            t = time.perf_counter()
            try:
                if conn is None:
                    conn = connect(u, addr)
                conn.request("GET", bust(path, args), headers=headers)
                r = conn.getresponse()
                n, code = len(r.read()), r.status
            except Exception as e:
                n, code = 0, type(e).__name__
                conn = None
            with lock:
                lat.append((time.perf_counter() - t) * 1000)
                status[code] += 1
                total[0] += n
                if code == 200:
                    sizes.append(n)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall = time.perf_counter() - t0
    s = sorted(lat)
    return {
        "mode": "once",
        "concurrency": concurrency,
        "tiles": len(s),
        "wall_s": round(wall, 3),
        "tiles_per_s": round(len(s) / wall, 1),
        "mb": round(total[0] / 1e6, 2),
        "mb_per_s": round(total[0] / 1e6 / wall, 2),
        **size_stats(sizes),
        "latency_ms": {p: round(pct(s, p), 1) for p in (50, 90, 95, 99)} | {"max": round(s[-1], 1)},
        "status": {str(k): v for k, v in sorted(status.items(), key=lambda kv: str(kv[0]))},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", help="local source id to load")
    g.add_argument("--health", action="store_true", help="hit /health (client calibration)")
    ap.add_argument("--tile-list", help="file of z/x/y lines (from pmtiles_list.py) -- real tiles "
                                        "only; without it, coordinates are enumerated from bounds")
    ap.add_argument("--once", action="store_true",
                    help="fetch each listed tile exactly once and report batch wall time "
                         "(uses the first --concurrency value)")
    ap.add_argument("--no-accept-encoding", action="store_true",
                    help="omit Accept-Encoding (forces Martin to decompress gzip tiles: CPU-bound variant)")
    ap.add_argument("--zooms", help="e.g. 12-17 (default: the source's full zoom range)")
    ap.add_argument("--hot-set", type=int, default=0,
                    help="restrict to N random tiles (warm-cache case); 0 = whole coverage (cold)")
    ap.add_argument("--concurrency", default="1,2,4,8,16")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--pause", type=float, default=10, help="idle seconds between steps")
    ap.add_argument("--max-error-rate", type=float, default=0.05)
    ap.add_argument("--stop-file")
    ap.add_argument("--temp-cmd", help="shell command printing temperature (C or millidegrees)")
    ap.add_argument("--temp-interval", type=float, default=30)
    ap.add_argument("--max-temp-c", type=float, default=80)
    ap.add_argument("--cache-bust", action="store_true",
                    help="unique ?cb= per request, so a CDN edge cannot serve from cache "
                         "(Phase 2: measuring the origin through Cloudflare)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()

    meta = {"base": a.base, "tool": "stars loadgen.py", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if a.health:
        paths = ["/health"]
        meta["target"] = "/health"
    else:
        if a.source in remote_sources():
            sys.exit(f"refusing: '{a.source}' is backed by a remote URL; load would land on a third party")
        tj = get_json(a.base, f"/{a.source}")
        zooms = range(tj["minzoom"], tj["maxzoom"] + 1)
        if a.zooms:
            lo, _, hi = a.zooms.partition("-")
            zooms = range(int(lo), int(hi or lo) + 1)
        if a.tile_list:
            tiles = [tuple(int(v) for v in ln.split("/")) for ln in Path(a.tile_list).read_text().split()
                     if not ln.startswith("#")]
            tiles = [t for t in tiles if t[0] in zooms]
        else:
            tiles = tile_range(tj, zooms)
        rng = random.Random(a.seed)
        if a.hot_set:
            tiles = rng.sample(tiles, min(a.hot_set, len(tiles)))
        paths = [f"/{a.source}/{z}/{x}/{y}" for z, x, y in tiles]
        meta |= {"target": a.source, "zooms": [min(zooms), max(zooms)], "candidate_tiles": len(paths),
                 "tile_list": a.tile_list, "hot_set": a.hot_set, "bounds": tj["bounds"],
                 "format": tj.get("format")}
    meta["accept_encoding"] = not a.no_accept_encoding

    if a.once:
        c = int(a.concurrency.split(",")[0])
        res = run_once(a.base, paths, c, a)
        lm = res["latency_ms"]
        print(f"once c={c} tiles={res['tiles']} wall={res['wall_s']}s ({res['tiles_per_s']} tiles/s, "
              f"{res['mb']} MB, {res['mb_per_s']} MB/s, tile mean {res['tile_bytes_mean']} B)  "
              f"p50={lm[50]} p95={lm[95]} p99={lm[99]} max={lm['max']}ms  status={res['status']}", flush=True)
        if a.out:
            Path(a.out).write_text(json.dumps({"meta": meta, "steps": [res]}, indent=1))
            print(f"wrote {a.out}")
        return

    steps = []
    levels = [int(c) for c in a.concurrency.split(",")]
    for i, c in enumerate(levels):
        res = Run(a.base, paths, c, a.duration, a).go()
        steps.append(res)
        lm = res["latency_ms"]
        print(f"c={c:3d}  rps={res['rps']:>8}  p50={lm[50]}  p95={lm[95]}  p99={lm[99]}  max={lm['max']}ms  "
              f"err={res['error_rate']}  {res['mb_per_s']}MB/s  tile mean {res['tile_bytes_mean']}B  "
              f"status={res['status']}"
              + (f"  STOPPED: {res['stopped_early']}" if res["stopped_early"] else ""), flush=True)
        if res["stopped_early"]:
            break
        if i < len(levels) - 1:
            time.sleep(a.pause)

    report = {"meta": meta, "steps": steps}
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
