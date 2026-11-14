# Phase 1 test A only, re-run on a freshly restarted Martin (`20261113T2148Z-phase1-gbit-A`)

Same setup as `20261111T1030Z-phase1-gbit` (slate → Pi over the LAN, `vbm` warm, gzip pbf,
steps 1–32 × 30 s), run with `ONLY=A`. Martin had been (re)started at
**2026-11-13 15:56:26 JST by someone else** (`NRestarts=0`, `Result=success`, i.e. a
deliberate `systemctl --user restart`, not a crash); RSS 205 MB at the start.

| c | rps | MB/s | p50 ms | p99 ms | Pi CPU % mean | RSS MB |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 152.2 | 6.4 | 6.5 | 9.7 | 23 | 263 |
| 4 | 385.9 | 16.4 | 9.3 | 20.1 | 87 | 267 |
| 8 | 401.2 | 16.9 | 17.6 | 39.2 | 95 | 269 |
| 16 | 400.0 | 16.7 | 35.1 | 76.1 | 97 | 271 |
| 32 | 393.5 | 16.3 | 70.9 | 154.9 | 93 | 274 |

Zero errors, `tx_errors` 0, throttled 0x0, temperature max 67.2 °C.

## What this says about the 420 vs 289 rps discrepancy

| run | Martin age at the run | RSS at start | plateau |
|---|---|---|---|
| `20261108T2155Z` (partial) | ~22 h | 91 MB | 420 rps |
| `20261113T2148Z` (this one) | ~15 h | 205 MB | 400 rps |
| `20261111T1030Z` (complete) | ~3 days | 598 MB | 289 rps |

The slow run is the one with the oldest, largest Martin; both runs on a younger Martin gave
~400–420. That fits "Martin gets slower as it ages / grows", and is **not proven**: the
generator and the day differ too, and nothing was changed on purpose between runs. A
controlled check would be: let Martin age again and re-test, or restart it at the end of a
slow period and re-test immediately. A second repeat at the same Martin age was started
and abandoned (the benchmark machines were unreachable), so run-to-run variance at one
Martin age is still unmeasured.
