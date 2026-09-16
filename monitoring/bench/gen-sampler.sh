#!/bin/bash
# Sample the *load generator's* own state to CSV during a benchmark run.
#
# Why this exists: the 2026-09-17 soak ended when the generator (slate.local, a
# shared M4) took a hardware watchdog reset 6.5 minutes before the end. Only the
# Pi was being sampled, so nothing could be said about what the generator was
# doing at the time -- not even whether it was under memory pressure. A run that
# cannot describe the state of every machine it uses cannot explain its own
# failures. (`tokachi20260911` hit the mirror image of this: unable to prove its
# machine was quiet during a measurement.)
#
# macOS, no sudo: everything here comes from sysctl / vm_stat / netstat / pmset.
# Temperature is deliberately absent -- Apple Silicon needs `powermetrics` with
# sudo for that, and an empty column is better than a fake one.
#
# Usage: gen-sampler.sh <out.csv> [interval_s=5] [iface=en0]
set -euo pipefail

OUT="${1:?usage: gen-sampler.sh <out.csv> [interval_s] [iface]}"
INTERVAL="${2:-5}"
IF="${3:-en0}"
PAGE=$(vm_stat | sed -n '1s/.*page size of \([0-9]*\).*/\1/p')

net() { netstat -ibn 2>/dev/null | awk -v i="$IF" '$1==i && $3 ~ /Link/ {print $7, $10; exit}'; }

echo "ts_utc,load1,load5,mem_free_mb,mem_inactive_mb,swap_used_mb,net_rx_bytes_s,net_tx_bytes_s,top_cpu_pct,top_proc,thermal_note" > "$OUT"

read -r rx0 tx0 < <(net)
t0=$(date +%s)

while sleep "$INTERVAL"; do
  t1=$(date +%s); dt=$((t1 - t0)); [ "$dt" -gt 0 ] || dt=1
  read -r rx1 tx1 < <(net)
  read -r l1 l5 _ < <(sysctl -n vm.loadavg | tr -d '{}')
  free_p=$(vm_stat | awk '/Pages free/{gsub(/\./,"",$3); print $3}')
  inact_p=$(vm_stat | awk '/Pages inactive/{gsub(/\./,"",$3); print $3}')
  swap=$(sysctl -n vm.swapusage | sed -n 's/.*used = \([0-9.]*\)M.*/\1/p')
  # Highest-CPU process, to catch "something else woke up on this shared machine".
  top=$(ps -A -o %cpu,comm -r 2>/dev/null | sed -n 2p)
  top_pct=$(echo "$top" | awk '{print $1}')
  top_proc=$(echo "$top" | awk '{sub($1 FS,""); n=split($0,a,"/"); print a[n]}' | tr -d ',"')
  # pmset records thermal/performance warnings only when they happen; empty means none.
  therm=$(pmset -g therm 2>/dev/null | awk '/warning level/ && !/No /{print "warned"; exit}')

  printf '%s,%s,%s,%d,%d,%s,%d,%d,%s,%s,%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$l1" "$l5" \
    "$((free_p * PAGE / 1048576))" "$((inact_p * PAGE / 1048576))" "${swap:-}" \
    "$(( (rx1 - rx0) / dt ))" "$(( (tx1 - tx0) / dt ))" \
    "${top_pct:-}" "${top_proc:-}" "${therm:-}" >> "$OUT"

  rx0=$rx1; tx0=$tx1; t0=$t1
done
