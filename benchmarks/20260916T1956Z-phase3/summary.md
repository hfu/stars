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

- **The run did not finish on its own: the generator rebooted.** `slate.local` came back
  up at 07:56:38 JST (`kern.boottime`), ~6.5 minutes into the 18th leg and ~3.5 minutes
  before the run would have ended; that is what produced the SSH timeout
  (`Read from remote host slate.local: Operation timed out`, run exit 255) and lost
  `U-mapterhorn-japan-bridge.json`. So: **load ran 2 h 58 m, 17 of 18 legs completed**,
  and the per-leg lines for those 17 survive in `run.log`. Do not read this run as "three
  hours, completed".
- **What the reboot was:** a kernel panic at 07:56:48 JST followed by a watchdog reset at
  07:56:50 (`ResetCounter-2026-09-17-075650.diag`: `Boot faults: wdog,reset_in_1`). The
  panic is in the PCIe link to the machine's Ethernet controller:
  `apcie[2:lan-1gb]::handleCompletionTimeoutInterrupt: completion timeout
  linksts=0x8b000001 pcielint=0x00800010 linkcdmsts=0x00000100 (ltssm 0x11=L0)`
  @AppleT8132PCIePort.cpp:1404, with `AppleEmbeddedPCIE` / `AppleT8132PCIe` in the
  backtrace (`panic-full-2026-09-17-075648.0002.panic`, read directly). An earlier note
  here and in this session's reports said there was *no* panic file: that was wrong — the
  report is in `DiagnosticReports/Retired/`, not the top-level directory, and "I looked
  in one place and found nothing" was written up as "there is nothing". The Pi side is
  unaffected and its sampling is complete to 22:57:11Z, which is independent evidence
  that only the generator went down.
- **This is not the Pi's problem in a different place.** The Pi's stalls are its own
  transmit queue (bcmgenet, inside that chassis); the generator's panic is a PCIe
  completion timeout between its SoC and its Ethernet controller (inside that chassis).
  Two different layers at the two ends of the same cable. Whether three hours of
  saturated transfer contributed to either is unknown. The tempting link to the earlier
  "both ends negotiate 100BASE-TX, so suspect the switch" observation does not hold:
  that is outside the chassis, this is inside it.
- **Whether the load caused it is unknown, and this run cannot say.** The generator was
  doing modest work for an M4 (6 threads, ~148 req/s, ~11.7 MB/s inbound, bodies
  discarded) but had been doing it for three hours. Nothing in the run recorded the
  generator's own CPU, memory or thermals — **only the Pi was sampled**, which is the gap
  this exposed. The nearest other event on that machine is a `JetsamEvent` at
  2026-09-16 21:09 JST, ~10.75 h earlier and outside this run. Temporal proximity is not
  causation; the honest statement is that the machine reset under sustained use and we
  have no instrumentation to say more.
- **For future runs:** sample the generator the same way the Pi is sampled — and sample
  the *layer that can fail*. CPU, memory and temperature would not have caught this one;
  interface error counters and link state might. `gen-sampler.sh` now records `Ierrs`,
  `Oerrs`, collisions and link status/media alongside load and memory. (Point made by
  `tokachi20260911`: which quantities to record is decided by the layer you suspect.)
  `slate.local` is shared, so a reset there costs other projects, not just this one.
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
