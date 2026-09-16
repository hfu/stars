# Phase 2 summary: 20260916T1920Z-phase2

Question: what does the public route deliver, and where is this site's uplink limit?
Method: same generator (`slate.local`, wired 100BASE-TX), same tile lists and steps as the
LAN reference run in the same session; only the route changes. Every origin-bound request
carries a unique `?cb=`, so no edge cache hit can stand in for the origin.
Martin 1.14.0, cloudflared 2026.8.2, eth0 at 100 Mb/s, 60.8 → 61.3 °C over the run.

| test | route | c | rps | MB/s | tile | p50 | p95 | p99 | err | cf-cache |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P | LAN | 1 | 88.4 | 7.18 | 81 KB | 11.3 | 15.1 | 16.4 | 0 | — |
| P | LAN | 2 | 135.6 | 11.08 | 82 KB | 11.3 | 34.1 | 41.6 | 0 | — |
| P | LAN | 4 | 142.7 | 11.68 | 82 KB | 12.7 | 131.7 | 253.9 | 0 | — |
| P | LAN | 6 | 143.4 | 11.72 | 82 KB | 16.1 | 155.9 | 596.9 | 0 | — |
| Q | Cloudflare, cache-busted | 1 | 15.4 | 1.25 | 81 KB | 64.7 | 73.2 | 78.0 | 0 | MISS 470 |
| Q | Cloudflare, cache-busted | 2 | 32.0 | 2.62 | 82 KB | 61.2 | 73.1 | 84.2 | 0 | MISS 976 |
| Q | Cloudflare, cache-busted | 4 | 64.7 | 5.26 | 81 KB | 60.3 | 73.9 | 83.1 | 0 | MISS 1971 |
| Q | Cloudflare, cache-busted | 6 | 93.4 | 7.68 | 82 KB | 62.9 | 76.6 | 85.4 | 0 | MISS 2847 |
| R | Cloudflare, cache-busted | 1 | 19.3 | 0.28 | 14 KB | 50.3 | 59.1 | 68.7 | 0 | MISS 588 |
| R | Cloudflare, cache-busted | 2 | 38.7 | 0.57 | 15 KB | 50.8 | 59.6 | 63.9 | 0 | MISS 1179 |
| R | Cloudflare, cache-busted | 4 | 79.3 | 1.11 | 14 KB | 49.5 | 59.2 | 64.9 | 0 | MISS 2417 |
| R | Cloudflare, cache-busted | 6 | 114.5 | 1.61 | 14 KB | 51.3 | 60.8 | 67.9 | 0 | MISS 3494 |
| S | Cloudflare, edge cached | 1 | 32.4 | 0.52 | 16 KB | 25.4 | 52.5 | 58.8 | 0 | HIT 787 / MISS 197 |
| S | Cloudflare, edge cached | 2 | 74.5 | 1.17 | 16 KB | 26.0 | 32.2 | 36.3 | 0 | HIT 2266 / MISS 3 |
| S | Cloudflare, edge cached | 4 | 144.9 | 2.26 | 16 KB | 26.5 | 34.0 | 39.0 | 0 | HIT 4411 |
| S | Cloudflare, edge cached | 6 | 214.1 | 3.29 | 15 KB | 27.4 | 35.1 | 40.1 | 0 | HIT 6533 |

Pi-side, per test: CPU% max 10.6 (P), 26.5 (Q), 20.4 (R), 10.0 (S); eth0 TX max 12.34,
8.64, 2.06, 0.37 MB/s; temp max 62.3–64.3 °C; Martin RSS flat at 606 MB.
`tx_errors` unchanged at 103 for the whole run; `rx_pause` +4 (11,925 → 11,929).

## Findings

1. **The uplink limit was not reached, and this run cannot state it.** Through Cloudflare,
   throughput rose almost exactly linearly with concurrency (1.25 → 2.62 → 5.26 → 7.68
   MB/s) while latency stayed flat (p50 ~61 ms at every step) and errors stayed at zero.
   That is the signature of a *per-connection* limit, not a pipe that is full. All that
   can be said is: **the uplink delivers at least 7.7 MB/s (61 Mb/s)**, measured at c=6.
2. **What limits one connection is the round trip, not bandwidth.** Requests are issued
   one at a time per connection, so each tile costs a full round trip: ~50 ms for a 14 KB
   tile and ~61 ms for an 82 KB tile. The 11 ms difference across 68 KB implies ~6 MB/s
   *within* a single connection; six of them in parallel reached 7.68 MB/s.
3. **The public route costs ~5× the latency of the LAN and ~4× the CPU per request.**
   LAN p50 was 11 ms against 61 ms through Cloudflare for the same tiles. Per request
   served, the Pi used ~0.07% CPU on the LAN and ~0.29% through the tunnel (10.6% at
   143 rps vs 26.5% at 93 rps) — cloudflared's TLS and tunnel framing, on top of Martin.
4. **An edge cache hit halves the wait and removes the origin from the path.** S ran at
   p50 25–27 ms (vs ~50 ms for the same tiles when cache-busted), and the Pi's TX peaked
   at 0.37 MB/s while serving 214 rps to the client. For real viewers, Cloudflare's 4 h
   `max-age` is doing most of the work; the origin numbers above are the cold path.
5. **Nothing on the Pi was under strain.** CPU ≤26.5%, temperature ≤64.3 °C, no
   throttling, Martin's memory flat, and — unlike Phase 1 — no NIC transmit stalls
   (`tx_errors` 103 → 103) and essentially no PAUSE frames (+4). At the byte rates this
   route produces (≤8.6 MB/s), the conditions that caused Phase 1's stalls don't arise.

## Caveats

- The generator sits on the same LAN as the Pi, so its downstream and the Pi's upstream
  share the household line. If the line is asymmetric, this measures whichever direction
  is narrower.
- Both measured machines negotiate 100BASE-TX, so any figure at or near 11.6 MB/s is
  suspect as a link artefact; the Cloudflare numbers here (≤7.7 MB/s) are below that.
- The per-process sampler for `cloudflared` produced only a header (both samplers were
  started from one SSH command; the second didn't survive). Tunnel CPU is therefore only
  visible in the system-wide column. Fixed for future runs by starting them separately.
- `--hot-set 200` in S means 200 distinct tiles; a real viewer's working set is larger,
  so S is an optimistic view of the cache-hit path, not a forecast of hit rate.

## Next

To find the actual uplink ceiling, the same Q test has to be pushed past c=6 (c=8, 12, 16)
while watching `tx_errors` and `rx_pause`. That exceeds the standing "c ≤ 6" rule from
Phase 1 finding 8, so it needs an explicit decision: the byte rates involved (~8–12 MB/s)
are in the range where the NIC stalled during Phase 1, though the tunnel route reached
only 8.6 MB/s at c=6.
