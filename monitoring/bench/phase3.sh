#!/bin/bash
# Phase 3: a soak. Three hours of steady load at the concurrency a real consumer
# uses, to see what only time reveals: thermal drift, memory growth, and whether
# the NIC transmit stalls of Phase 1 finding 8 appear at c=6 when the link is
# held full for hours rather than 30 seconds.
#
# Concurrency stays at 6 throughout -- this is a duration test, not a limit test.
# Load is split between two archives: kitaphoto17 (190 GB, the familiar one) and
# mapterhorn-japan-bridge (272 GB, replaced 2026-09-17 02:16 JST and never yet
# read under sustained load).
#
# The work is done as many fixed-length legs rather than one long run, so the
# result file carries a time series (throughput, latency, errors per leg) instead
# of a single average that would hide drift.
#
# Roles: this machine orchestrates and watches temperature; $GEN generates load
# (wired, and free -- ask the other users first); $PI is sampled throughout.
set -euo pipefail

cd "$(dirname "$0")/../.."
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%MZ)-phase3}"
PI="${PI:-spacex.optgeo.org}"
GEN="${GEN:-slate.local}"
BASE="${BASE:-http://192.168.11.14:3000}"
GEN_DIR="${GEN_DIR:-/tmp/stars-bench}"
CONC="${CONC:-6}"
LEG_S="${LEG_S:-600}"          # one leg
LEGS_PER_SOURCE="${LEGS_PER_SOURCE:-9}"  # 9 x 600 s = 90 min per archive
BASELINE_S="${BASELINE_S:-120}"
MAX_TEMP_C="${MAX_TEMP_C:-80}"
SAMPLE_S="${SAMPLE_S:-5}"
OUT="benchmarks/$RUN_ID"
PI_CSV="/tmp/bench/$RUN_ID-host.csv"
STOP="$GEN_DIR/STOP"
GEN_CSV="$GEN_DIR/$RUN_ID-gen.csv"

mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$OUT/run.log"; }
steps() { python3 -c "print(','.join(['$CONC']*$LEGS_PER_SOURCE))"; }

log "run $RUN_ID starting: c=$CONC, ${LEGS_PER_SOURCE} x ${LEG_S}s per source"
{
  echo "run_id: $RUN_ID"
  echo "repo_commit: $(git rev-parse HEAD)"
  echo "started_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "generator: $GEN ($(ssh "$GEN" 'sysctl -n machdep.cpu.brand_string; python3 --version' | tr '\n' ' '))"
  echo "generator_link: $(ssh "$GEN" 'ifconfig en0 | grep media' | sed 's/^[[:space:]]*//')"
  echo "generator_note: nodeodm container resident but idle on $GEN (tokachi20260911)"
  echo "base: $BASE"
  echo "concurrency: $CONC  leg_s: $LEG_S  legs_per_source: $LEGS_PER_SOURCE  max_temp_c: $MAX_TEMP_C"
  ssh "$PI" 'echo "kernel: $(uname -r)"
             echo "martin: $(/home/stars/.local/bin/martin --version)"
             echo "martin_since: $(systemctl --user show martin -p ActiveEnterTimestamp --value)"
             echo "eth0_speed_mbps: $(cat /sys/class/net/eth0/speed)"
             echo "throttled_at_start: $(vcgencmd get_throttled)"
             echo "temp_at_start: $(vcgencmd measure_temp)"
             echo "rx_pause_at_start: $(/usr/sbin/ethtool -S eth0 | awk "/rx_pause:/{print \$2}")"
             echo "tx_errors_at_start: $(cat /sys/class/net/eth0/statistics/tx_errors)"
             echo "netdev_watchdog_lines_at_start: $(dmesg 2>/dev/null | grep -c "NETDEV WATCHDOG" || true)"
             echo "disk_at_start: $(df -h /home/stars/data | tail -1)"'
} > "$OUT/environment.txt"

ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-before.txt"
scp -q monitoring/bench/host-sampler.sh "$PI":/tmp/bench/host-sampler.sh
ssh "$PI" "setsid nohup bash /tmp/bench/host-sampler.sh $PI_CSV $SAMPLE_S martin --user >/dev/null 2>&1 < /dev/null &"
ssh "$GEN" "rm -f $STOP"
# Sample the generator too. The 2026-09-17 soak ended with a watchdog reset on the
# generator and nothing recorded about its state; see docs/BENCHMARKS.md.
scp -q monitoring/bench/gen-sampler.sh "$GEN":"$GEN_DIR/gen-sampler.sh"
ssh "$GEN" "cd $GEN_DIR && nohup bash gen-sampler.sh $GEN_CSV 5 en0 >/dev/null 2>&1 < /dev/null &"
log "sampler started (every ${SAMPLE_S}s); baseline ${BASELINE_S}s"

(
  while true; do
    t=$(ssh -o ConnectTimeout=10 "$PI" 'cat /sys/class/thermal/thermal_zone0/temp' 2>/dev/null || echo 0)
    case "$t" in ''|*[!0-9]*) t=0 ;; esac
    if [ "$t" -ge $((MAX_TEMP_C * 1000)) ]; then
      ssh "$GEN" "touch $STOP"
      echo "[$(date -u +%H:%M:%SZ)] WATCHDOG: temp ${t} m°C >= ${MAX_TEMP_C} C, STOP issued" >> "$OUT/run.log"
      break
    fi
    sleep 30
  done
) &
WATCHDOG=$!

cleanup() {
  kill "$WATCHDOG" 2>/dev/null || true
  ssh "$PI" 'pkill -f "^bash /tmp/bench/host-sampler.sh"' || true
  scp -q "$PI:$PI_CSV" "$OUT/host.csv" || true
  ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-after.txt" || true
  ssh "$PI" 'echo "throttled_at_end: $(vcgencmd get_throttled)"
             echo "temp_at_end: $(vcgencmd measure_temp)"
             echo "rx_pause_at_end: $(/usr/sbin/ethtool -S eth0 | awk "/rx_pause:/{print \$2}")"
             echo "tx_errors_at_end: $(cat /sys/class/net/eth0/statistics/tx_errors)"
             echo "netdev_watchdog_lines_at_end: $(dmesg 2>/dev/null | grep -c "NETDEV WATCHDOG" || true)"
             echo "disk_at_end: $(df -h /home/stars/data | tail -1)"
             echo "martin_active_since_at_end: $(systemctl --user show martin -p ActiveEnterTimestamp --value)"' >> "$OUT/environment.txt" || true
  ssh "$PI" 'dmesg 2>/dev/null | grep -A3 "NETDEV WATCHDOG" | tail -60' > "$OUT/kernel-eth0.log" 2>/dev/null || true
  ssh "$GEN" 'pkill -f "bash gen-sampler.sh"' || true
  scp -q "$GEN:$GEN_CSV" "$OUT/generator.csv" || true
  log "collected results into $OUT"
}
trap cleanup EXIT

sleep "$BASELINE_S"

soak() {  # name, loadgen args...
  local name=$1; shift
  if ssh "$GEN" "test -e $STOP"; then log "skipping $name: STOP present"; return; fi
  log "soak $name: $*"
  ssh "$GEN" "cd $GEN_DIR && python3 monitoring/bench/loadgen.py --base $BASE --concurrency $(steps) \
      --duration $LEG_S --pause 5 --stop-file $STOP --out results/$name.json $*" | tee -a "$OUT/run.log"
  scp -q "$GEN:$GEN_DIR/results/$name.json" "$OUT/$name.json"
}

soak T-kitaphoto17 --source kitaphoto17 --tile-list kitaphoto17.txt
soak U-mapterhorn-japan-bridge --source mapterhorn-japan-bridge --tile-list mjb.txt

log "run $RUN_ID finished"
