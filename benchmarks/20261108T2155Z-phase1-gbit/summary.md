# Phase 1 re-run at gigabit — PARTIAL (`20261108T2155Z-phase1-gbit`)

Generator `slate.local` (wired, 1000baseT/Full), origin `http://192.168.50.244:3000`,
Pi 4B on kernel 6.18.39, Martin 1.14.0, eth0 1000 Mb/s. Script:
`monitoring/bench/phase1-gbit.sh` (tests A–D of `phase1.sh`; E/F omitted).

**Only test A completed. Test B stopped during its c=8 step; C and D never ran.**
`analyze_phase1.py` was not used: it hard-codes a 100 Mb/s line rate.

## A — `vbm` (62 MB, warm, gzip pbf, Accept-Encoding sent)

| c | rps | body MB/s | p50 ms | p99 ms | Pi CPU % mean / max | temp °C |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 168.3 | 7.11 | 5.9 | 9.0 | 22.4 / 26.7 | 55.5 |
| 2 | 325.0 | 13.73 | 6.0 | 9.3 | 44.8 / 50.1 | 58.9 |
| 4 | 405.8 | 17.15 | 9.3 | 18.0 | 85.7 / 93.4 | 62.3 |
| 8 | 419.5 | 17.64 | 18.4 | 35.7 | 93.0 / 100.0 | 63.8 |
| 16 | 421.5 | 17.68 | 36.6 | 71.8 | 95.8 / 100.0 | 65.7 |
| 32 | 422.2 | 17.64 | 67.8 | 142.4 | 98.1 / 100.0 | 67.2 |

Zero errors, `net_tx_errors` 0, PAUSE frames 0/0 throughout; peak wire TX 19.7 MB/s
(~16% of the 125 MB/s line rate).

## B — `freetown-mapterhorn` (partial)

c=1: 931.9 rps, 13.1 MB/s; c=2: 2274 rps, 32.2 MB/s; c=4: 4412 rps, 62.2 MB/s
(p50 ≤ 0.9 ms, p99 ≤ 2.9 ms, no errors). During c=8 the Pi's TX peaked at **107.4 MB/s**
(22:05:24Z, Pi CPU 74%), then **all tile traffic stopped at 22:05:26Z**. Nothing was
recorded after that: both samplers' last rows are 22:14:40Z (Pi) / 22:14:44Z (generator),
and the orchestrator's SSH to the generator ended with `Connection reset by peer`
(script exited, results collected 22:29:53Z).

## What is and is not known about the stop

- Not a Pi TX stall as understood from 2026-09: `tx_errors` stayed 0, no
  `NETDEV WATCHDOG` lines in the kernel log, Pi uptime unbroken, Martin/caddy/cloudflared
  healthy afterwards.
- The generator (`slate`, up 11 days, no reboot) had no loadgen/sampler process left when
  checked ~1 h later, and its unified log showed nothing in the window.
- Cause **not established**. Candidates not yet tested: the generator's own Ethernet path
  (the 2026-09-17 soak ended on a PCIe/NIC watchdog on this same machine), the router at
  near line rate, or the generator-side process. A plain single-stream transfer at line
  rate would separate path from software.
