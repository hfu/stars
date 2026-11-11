# Phase 1 re-run at gigabit — complete (`20261111T1030Z-phase1-gbit`)

Generator `slate.local` (Apple M4, wired 1000baseT/Full; just rebooted, Spotlight
re-indexing at ~4 of 10 cores — `/health` calibration unaffected: 19.8k rps, p99 5.4 ms),
origin `http://192.168.50.244:3000`, Pi 4B, kernel 6.18.39, Martin 1.14.0 (up ~3 days,
RSS 598 MB at start), eth0 1000 Mb/s behind the RT-AX59U. Steps 1–32 concurrent, 30 s each.
Script `monitoring/bench/phase1-gbit.sh` (tests A–D only). Pi reached over LAN SSH.
Before the run: a 60 s single-stream read of `freetown-mapterhorn.pmtiles` through Caddy
:8080 held 116.6 MB/s (7.0 GB) with no stall.

| test | workload | plateau (c=32) | body MB/s | peak wire TX MB/s | Pi CPU % mean/max | disk busy % max | bound by |
|---|---|--:|--:|--:|--:|--:|---|
| A | `vbm` warm, gzip pbf | 289 rps (c ≥ 8) | 12.0 | 13.7 | 93–97 / 100 | 40 (one sample) | **Pi CPU** |
| B | `freetown-mapterhorn` WebP | 8,022 rps | 112.8 | 121.5 | 84 / 89 | 1 | **link** (CPU also high) |
| C | `kitaphoto17` cold, random | 1,371 rps | 112.2 | 124.7 | 86 / 99 | 27 | **link** |
| D | `vbm`, no Accept-Encoding | 252 rps (c ≥ 8) | 16.9 | 19.3 | 93–99 / 100 | 0 | **Pi CPU** |

Latency at c=32 (p50 / p99 ms): A 105 / 192, B 2.0 / 33.6, C 19.5 / 95.6, D 114 / 221.
At c=1: A 103 rps (p50 9.1), B 1,019 (0.8), C 337 (2.9), D 115 (8.4). Zero errors anywhere.

Whole run: `net_tx_errors` 0 → 0, PAUSE frames 0/0, no `transmit queue timed out` /
watchdog line in the kernel log, live `get_throttled` 0x0 throughout, temperature max
71.6 °C, Martin RSS 598 → 681 MB, fds ≤ 78. Wire TX on B/C reached 121–125 MB/s of the
125 MB/s line rate.

## Unexplained: A is slower than in the earlier partial run

Same test, same Pi, same kernel, same source file (`vbm.pmtiles`, unchanged since Jul 18):
`20261108T2155Z` plateaued at **420 rps / 17.6 MB/s** (c=1: 168 rps, p50 5.9 ms); this run
at **289 rps / 12.0 MB/s** (c=1: 103 rps, p50 9.1 ms). CPU is ~95% in both, so Pi CPU per
request rose ~1.4× (≈2.3 → ≈3.3 ms). CPU frequency (1.8 GHz), temperature and throttling
do not differ. B at c=1 is the same in both (932 vs 1,019 rps), so it is specific to the
vbm path. What differs: Martin's age and size (restarted 2026-11-08 23:47 JST; RSS 91 MB
at the earlier run's start, 598 MB at this one), and the generator (just rebooted, loaded).
The generator seems unlikely (B at c=1 unaffected, Pi CPU saturated), the Martin-state
hypothesis is **untested**. Test it by restarting Martin and re-running A alone.
