# Phase 3 summary: 20260916T1956Z-phase3 (3-hour soak)

2026-09-17 04:57–07:57 JST. LAN only (Cloudflare not involved), concurrency fixed at 6,
17 legs of 10 minutes: 9 on kitaphoto17 (190 GB), 8 on mapterhorn-japan-bridge (272 GB,
replaced 02:16 JST the same night). Pi sampled every 5 s (2,109 samples). This is a
duration test, not a limit test.

## What held

- **Throughput never moved:** 12.29–12.30 MB/s on the wire in every 10-minute bucket,
  143–149 tiles/s, for three hours. Per-leg payload 10.91–11.73 MB/s; the spread across
  legs (~7%) is this run's own noise floor, so nothing smaller than that counts as drift.
- **Zero errors** in ~1.55 million requests (all 200).
- **No thermal problem:** 58.9 → 66–67 °C plateau within 30 minutes, max 68.7 °C, and
  the last hour *fell* to 64–65 °C. `throttled` stayed at its boot-time sticky value
  (0xe0000) with no new bits, and the CPU sat at ~7% median.
- **Martin stayed up** (same `ActiveEnterTimestamp` at the end as at the start), memory
  went 613 → 732 MB and flattened for the final 40 minutes — consistent with caches
  filling on a newly-swapped 272 GB archive, not with a leak. File descriptors flat at
  ~37. Swap touched 22 MB. Disk free unchanged.

## What broke (the reason to run a soak at all)

**The NIC's transmit queue stalls at c=6 — Phase 1 concluded it didn't.** `tx_errors`
went 103 → 832: **729 `NETDEV WATCHDOG: transmit queue timed out` events in three hours**,
and kernel timestamps confirm the same count. Phase 1 tested each concurrency for 30
seconds and saw none at c=6; it takes minutes, not seconds, for the first one to appear.

- Rate was highest early (up to 14.8/min in the 20-minute bucket) and settled to
  1–4/min later; 541 during the kitaphoto17 half, 188 during the mapterhorn half.
- Every 10-minute leg had at least one request taking 2.8–27 s while its median stayed at
  13–43 ms. Those maxima are the stalls: p50 and p95 barely notice, the tail is brutal.
- Nothing else registers them: CPU, disk, memory and temperature all look calm.

**The PAUSE-frame explanation is wrong, or at least not this.** Phase 1 proposed that
flow-control PAUSE frames from the switch hold the queue past the watchdog. Sampling both
this time: `rx_pause` rose by 80,005, but **76,000 of those arrived in one ~60-second
burst (21:08–21:09Z) during which stalls were zero**, and across 37 five-minute buckets
the correlation between PAUSE frames and stalls is **r = −0.03**. Whatever causes the
stalls, it isn't tracking PAUSE frames.

## Caveats

- The final leg's result JSON was lost: the SSH session to the generator timed out at the
  end (`Read from remote host slate.local: Operation timed out`, run exit 255). The
  per-leg lines survive in `run.log`; only `U-mapterhorn-japan-bridge.json` is missing.
  17 of 18 planned legs ran.
- The two halves differ in archive *and* in position in the run, so "kitaphoto17 stalls
  more than mapterhorn" cannot be separated from "early stalls more than late".
- Generator and Pi both negotiate 100BASE-TX; this run says nothing about behaviour at
  gigabit.

## What this changes

1. **"c ≤ 6 is safe" is retired.** The rule was based on 30-second steps. At c=6 the link
   is full and stalls accumulate at a few per minute. Keep c ≤ 6 for *load tests* (it
   keeps the rate low), but don't state that it avoids the stalls.
2. **For consumers:** a client fetching a large block at c=6 should expect occasional
   multi-second pauses on individual tiles. Retries are not needed (no errors), but a
   fixed per-tile timeout below ~30 s will fire eventually.
3. **Next on the NIC question:** the remaining candidates are the bcmgenet driver's
   handling of a long-saturated queue and the switch port itself. A test at a *rate limit*
   just below saturation (e.g. 9–10 MB/s) would say whether it is saturation itself or
   duration that produces them.
