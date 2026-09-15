#!/usr/bin/env python3
"""Join a Phase 1 run's load-generator results with the Pi-side sampler CSV and
decide, per step, whether the plateau was the network link or the Pi.

Usage: analyze_phase1.py benchmarks/<run id>
Writes <run id>/summary.md and prints it.
"""
import csv
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LINK_BYTES_S = 100e6 / 8  # eth0 negotiated 100 Mb/s
# A step counts as link-bound when payload throughput sits within this fraction
# of the line rate. TCP/IP + HTTP framing costs ~5-8%, so ~11.6 MB/s of body
# bytes already means the wire is full.
LINK_FULL_FRACTION = 0.90


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_host(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            r["_t"] = parse_ts(r["ts_utc"])
            rows.append(r)
    return rows


def window(rows, start, end):
    return [r for r in rows if start <= r["_t"] <= end]


def fnum(rows, key):
    out = []
    for r in rows:
        try:
            out.append(float(r.get(key)))
        except (TypeError, ValueError):
            pass
    return out


def counter_delta(rows, key):
    """Increase of a cumulative counter across a window; '-' when the column is
    absent (older CSVs) or empty (driver without that stat)."""
    vals = fnum(rows, key)
    return f"{vals[-1] - vals[0]:.0f}" if len(vals) >= 2 else "-"


def step_windows(run_log):
    """(test name, start, end) per test from run.log timestamps."""
    marks = []
    for line in run_log.read_text().splitlines():
        if line.startswith("[") and ("] test " in line or "] run " in line):
            hhmmss = line[1:9]
            marks.append((hhmmss, line))
    return marks


def main():
    run = Path(sys.argv[1])
    host = load_host(run / "host.csv")
    day = host[0]["_t"].date()

    # Test start times from run.log; each test ends where the next begins.
    starts = []
    for line in (run / "run.log").read_text().splitlines():
        if "] test " in line or line.rstrip().endswith("finished"):
            t = datetime.strptime(f"{day} {line[1:9]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            name = line.split("] test ")[1].split(":")[0] if "] test " in line else "END"
            starts.append((name, t))

    out = ["# Phase 1 summary: " + run.name, ""]
    out.append(f"Link line rate: {LINK_BYTES_S/1e6:.1f} MB/s (eth0 at 100 Mb/s). "
               f"A step is **link-bound** when body throughput >= {LINK_FULL_FRACTION:.0%} of that "
               f"({LINK_BYTES_S*LINK_FULL_FRACTION/1e6:.2f} MB/s).")
    out.append("")
    out.append("| test | c | rps | MB/s | tile KB | p50 | p95 | p99 | max ms | err | Pi CPU% max | disk busy% max | temp °C max | tx err Δ | rx pause Δ | verdict |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")

    for i, (name, t0) in enumerate(starts[:-1]):
        t_end = starts[i + 1][1]
        res = json.loads((run / f"{name}.json").read_text())
        steps = res["steps"]
        # Steps run sequentially inside [t0, t_end]; apportion by elapsed time.
        cursor = t0
        for s in steps:
            dur = s.get("elapsed_s") or s.get("wall_s") or 0
            w = window(host, cursor, cursor + timedelta(seconds=max(dur, 2)))
            cursor += timedelta(seconds=dur + (15 if "elapsed_s" in s else 0))
            cpu = fnum(w, "cpu_util_pct")
            disk = fnum(w, "disk_busy_pct")
            temp = fnum(w, "temp_c")
            mbps = s.get("mb_per_s") or 0
            lat = s["latency_ms"]
            link_bound = mbps * 1e6 >= LINK_BYTES_S * LINK_FULL_FRACTION
            pi_hot = (cpu and max(cpu) >= 85) or (disk and max(disk) >= 90) or (temp and max(temp) >= 80)
            verdict = "link" if link_bound and not pi_hot else ("Pi" if pi_hot else "below both")
            if link_bound and pi_hot:
                verdict = "link + Pi"
            rps = s.get("rps") or s.get("tiles_per_s")
            out.append(
                f"| {name} | {s['concurrency']} | {rps} | {mbps} | "
                f"{(s.get('tile_bytes_mean') or 0)/1000:.0f} | {lat['50']} | {lat['95']} | {lat['99']} | "
                f"{lat['max']} | {s.get('error_rate', 0)} | "
                f"{max(cpu) if cpu else '-':>} | {max(disk) if disk else '-'} | {max(temp) if temp else '-'} | "
                f"{counter_delta(w, 'net_tx_errors')} | {counter_delta(w, 'net_rx_pause')} | {verdict} |"
            )

    base = window(host, host[0]["_t"], starts[0][1])
    out.append("")
    out.append(f"Baseline ({len(base)} samples before the first test): CPU% median "
               f"{statistics.median(fnum(base,'cpu_util_pct')):.1f}, temp max {max(fnum(base,'temp_c')):.1f} °C.")
    all_temp = fnum(host, "temp_c")
    out.append(f"Whole run: temp {min(all_temp):.1f}–{max(all_temp):.1f} °C; "
               f"CPU% max {max(fnum(host,'cpu_util_pct')):.1f}; disk busy% max {max(fnum(host,'disk_busy_pct')):.1f}; "
               f"net tx max {max(fnum(host,'net_tx_bytes_s'))/1e6:.2f} MB/s; "
               f"throttled values seen: {sorted(set(r['throttled_hex'] for r in host))}; "
               f"Martin RSS {min(fnum(host,'svc_rss_kb'))/1024:.0f}–{max(fnum(host,'svc_rss_kb'))/1024:.0f} MB; "
               f"fds max {max(fnum(host,'svc_fds')):.0f}.")
    text = "\n".join(out) + "\n"
    (run / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
