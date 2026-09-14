# Benchmarks

Measured limits of `stars.optgeo.org`. Raw data for each run lives in
[`benchmarks/<run id>/`](../benchmarks/) (environment, generator JSON per test, the
Pi-side sampler CSV, Martin `/_/metrics` before and after, and a generated
`summary.md` joining the two). Tooling is in [`monitoring/bench/`](../monitoring/bench/).
Confirmed limits are also carried into [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.

## Method (shared across runs)

- **Measure the Pi, not Cloudflare.** Load goes straight to Martin's origin on the LAN
  (`http://192.168.11.14:3000`). The public URL is edge-cached and would mostly measure
  Cloudflare.
- **The load generator must be wired and must not be the Pi.** A Wi-Fi client measured
  its own jitter (RTT stddev 20 ms, p99 57 ms on a near-free endpoint); the wired
  `slate.local` gives RTT 0.5 ms and reached 15,298 rps on Martin's `/health` at 32
  concurrent connections, so the client is not what caps any tile result below.
- **Only local sources.** `loadgen.py` refuses any source backed by a remote URL in
  `config/martin.yaml` — load on those lands on third parties (GSI, OSM Japan, Source
  Cooperative, smellman's server).
- **Real tiles only.** `pmtiles_list.py` reads each archive's directories and lists the
  tiles that exist; random coordinates inside bounds mostly hit empty-tile 204s on sparse
  archives, and Mapterhorn builds declare whole-world bounds.
- **Send `Accept-Encoding` like a browser.** Without it Martin decompresses gzip-stored
  vector tiles on the fly and returns bodies 2–2.4× larger — a path real viewers never
  take. Test D omits it on purpose, as a CPU-bound variant.
- **Pi-side sampling every 2 s** with `host-sampler.sh` (`/proc` + `/sys` only; column
  schema shared with the `rpi-geoserver0` project so Pi 4B hardware limits compare
  across OSes).
- **Brakes:** generator stops a test above 5% errors; the orchestrator's watchdog stops
  the run at 80 °C.
- **Report tile size next to latency.** Two tile sets can differ in latency because
  their tiles differ in weight (e.g. 1 m vs 10 m DEM coverage in
  `mapterhorn-japan-bridge`), not because conditions differed.

## 2026-09-15 — Phase 1: origin curves (`20260914T2330Z-phase1`)

**Question:** with the Pi's Ethernet negotiating at 100 Mb/s, does the Pi give out before
the link does?

**Answer: no.** Every workload plateaued at the link — 11.3–11.7 MB/s of tile bodies,
12.40 MB/s peak on the wire against a 12.5 MB/s line rate — while the Pi still had
headroom in CPU, disk and temperature.

Environment: Pi 4 Model B Rev 1.5, 8 GB, kernel 6.12.75+rpt-rpi-v8, Martin 1.14.0,
USB SSD (WD Elements SE), eth0 **100 Mb/s**; generator `slate.local` (Apple M4, wired
100BASE-TX); concurrency steps 1–32, 30 s each; repo commit `da10829`.

| test | workload | plateau | MB/s | tile KB | Pi CPU % at plateau | disk busy % | bound by |
|---|---|---|---:|---:|---:|---:|---|
| A | `vbm`, 62 MB, fully in page cache, gzip pbf | 275–280 rps (c ≥ 8) | 11.4–11.7 | 42 | 56–61 | 0 | link |
| B | `freetown-mapterhorn`, 13 GB WebP raster | 800–814 rps (c 8–16) | 11.3–11.6 | 14 | 11–15 | ≤ 3 | link |
| C | `kitaphoto17`, 178 GB JPEG, random tiles (cold vs 8 GB RAM) | 139–144 rps (c ≥ 4) | 11.3–11.7 | 81 | 10–15 | ≤ 9 | link |
| D | `vbm` without `Accept-Encoding` (forced decompression) | 170–176 rps (c ≥ 8) | 11.5–11.7 | 68 | 60–69 | 0 | link |
| E | `mapterhorn-japan-bridge`, 258 GB terrarium, z16 block, sustained c=6 | 110 rps | 11.7 | 107 | 10 | ≤ 6 | link |
| F1–F3 | same archive, three never-fetched 196-tile z16 blocks, **fetched once** at c=6 | 1.55–2.16 s per block | 11.6–11.7 | 92–128 | ≤ 8 | ≤ 3 | link |

Latency before saturation (c=1–2) was p50 3–16 ms. Once the link was full, p50 ranged
5–120 ms depending on concurrency (worst: C at c=32) and the tail stretched: p99
70 ms–1.2 s, and a handful of requests hit the generator's 30 s timeout (error rate
≤ 0.09%). Full per-step numbers:
[`benchmarks/20260914T2330Z-phase1/summary.md`](../benchmarks/20260914T2330Z-phase1/summary.md).

**Findings**

1. **The 100 Mb/s link is the binding limit for every tile type tested**, including the
   one designed to stress the disk (C: 178 GB of random reads against 8 GB of RAM kept
   the SSD ≤ 9% busy) and the one designed to stress the CPU (D: forced decompression
   peaked at 69%). Upgrading the link is what would raise stars' ceiling; the Pi is not
   yet the constraint.
2. **The batch time for a cold block is simply bytes ÷ link rate.** F1–F3 took
   1.66 s / 1.55 s / 2.16 s for 19.3 / 18.0 / 25.1 MB — each exactly its size over
   ~11.6 MB/s. The heavier block (F3, 128 KB/tile) is slower because its tiles are
   heavier, not because the server behaved differently.
3. **Gzip vector tiles cost far more CPU per request than raster, even passed through.**
   A (gzip pbf, `Accept-Encoding` sent) ran the Pi at 56–61% CPU for ~280 rps, while B
   (WebP) used 11–15% for ~800 rps at the same byte rate. Cause not yet identified — the
   bodies match stored compressed sizes, so it isn't obviously re-compression. This is
   the likeliest *next* limit: on a gigabit link, vector-tile serving would probably run
   out of CPU somewhere above 100 Mb/s. Not measured; an inference to test if the link is
   upgraded.
4. **Overload degrades raster throughput.** B fell from 814 rps to 596 rps (8.4 MB/s) at
   c=32 with the Pi at 11% CPU — not a Pi limit. Likely TCP congestion or drops on the
   saturated link/switch; unconfirmed, because TCP retransmit counters weren't sampled.
5. **Thermal:** 55.5 → 69.6 °C over ~20 minutes of load, highest during the CPU-heavy D;
   `get_throttled` showed no active throttling in any 2 s sample (the sticky
   "has occurred" bits were already set before the run, so only the live bits are
   informative). A ~10 °C margin to the 80 °C firmware throttle point after 20 minutes is
   why a multi-hour soak is still worth running.
6. Martin's RSS grew 81 → 502 MB across the run (caches filling); open file descriptors
   peaked at 64.

**Caveats**

- These are **LAN-direct origin** numbers. Public viewers additionally go through
  Cloudflare (edge cache hits are faster; misses add the tunnel) and the site's ISP
  uplink, which may be narrower than 100 Mb/s — to be measured in Phase 2.
- The generator's own link is also 100BASE-TX, so this run cannot separate "Pi NIC" from
  "generator NIC" as the 100 Mb/s wall. It doesn't change the answer to the question
  asked (the Pi had headroom either way).
- Public traffic shares the same saturated link, so viewers were slowed during the run.

**Next:** add TCP retransmit counters to sampling (to confirm finding 4); Phase 2
(through Cloudflare, low rate) to find the uplink limit; Phase 3 soak for thermal
behaviour over hours; profile finding 3 before any link upgrade.
