#!/bin/bash
# Phase 1: origin throughput/latency curves for a few local sources, measured
# over the wired LAN (Cloudflare bypassed), with the Pi sampled throughout.
#
# Roles:
#   this machine  - orchestrator; runs the temperature watchdog over SSH
#   $GEN          - load generator (must be wired; Wi-Fi measured Wi-Fi jitter)
#   $PI           - the Pi under test; runs host-sampler.sh only
#
# Everything lands in benchmarks/<run id>/ in this repo.
set -euo pipefail

cd "$(dirname "$0")/../.."
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%MZ)-phase1}"
PI="${PI:-spacex.optgeo.org}"
GEN="${GEN:-slate.local}"
BASE="${BASE:-http://192.168.11.14:3000}"
GEN_DIR="${GEN_DIR:-/tmp/stars-bench}"
STEPS="${STEPS:-1,2,4,8,16,32}"
DUR="${DUR:-30}"
PAUSE="${PAUSE:-15}"
BASELINE_S="${BASELINE_S:-120}"
MAX_TEMP_C="${MAX_TEMP_C:-80}"
OUT="benchmarks/$RUN_ID"
PI_CSV="/tmp/bench/$RUN_ID-host.csv"
STOP="$GEN_DIR/STOP"

mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$OUT/run.log"; }

log "run $RUN_ID starting"
{
  echo "run_id: $RUN_ID"
  echo "repo_commit: $(git rev-parse HEAD)"
  echo "started_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "generator: $GEN ($(ssh "$GEN" 'sysctl -n machdep.cpu.brand_string; python3 --version' | tr '\n' ' '))"
  echo "generator_link: $(ssh "$GEN" 'ifconfig en0 | grep media' | sed 's/^[[:space:]]*//')"
  echo "base: $BASE"
  echo "steps: $STEPS  duration_s: $DUR  pause_s: $PAUSE  max_temp_c: $MAX_TEMP_C"
  ssh "$PI" 'echo "pi_model: $(tr -d "\0" < /proc/device-tree/model)"
             echo "kernel: $(uname -r)"
             echo "martin: $(/home/stars/.local/bin/martin --version)"
             echo "martin_since: $(systemctl --user show martin -p ActiveEnterTimestamp --value)"
             echo "eth0_speed_mbps: $(cat /sys/class/net/eth0/speed)"
             echo "throttled_at_start: $(vcgencmd get_throttled)"
             echo "temp_at_start: $(vcgencmd measure_temp)"
             echo "mem: $(free -m | awk "/Mem:/{print \$2\" MB total, \"\$7\" MB available\"}")"'
} > "$OUT/environment.txt"

ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-before.txt"
scp -q monitoring/bench/host-sampler.sh "$PI":/tmp/bench/host-sampler.sh
ssh "$PI" "setsid nohup bash /tmp/bench/host-sampler.sh $PI_CSV 2 martin --user >/dev/null 2>&1 < /dev/null &"
ssh "$GEN" "rm -f $STOP"
log "sampler started on Pi; baseline ${BASELINE_S}s"

# Temperature watchdog: the load generator can't see the Pi, this machine can.
(
  while true; do
    t=$(ssh -o ConnectTimeout=10 "$PI" 'cat /sys/class/thermal/thermal_zone0/temp' 2>/dev/null || echo 0)
    # Under `set -e` a non-numeric reading would kill this subshell silently and
    # leave the run with no watchdog at all; treat it as "no reading" instead.
    case "$t" in ''|*[!0-9]*) t=0 ;; esac
    if [ "$t" -ge $((MAX_TEMP_C * 1000)) ]; then
      ssh "$GEN" "touch $STOP"
      echo "[$(date -u +%H:%M:%SZ)] WATCHDOG: temp ${t} m°C >= ${MAX_TEMP_C} C, STOP issued" >> "$OUT/run.log"
      break
    fi
    sleep 10
  done
) &
WATCHDOG=$!

cleanup() {
  kill "$WATCHDOG" 2>/dev/null || true
  ssh "$PI" 'pkill -f "^bash /tmp/bench/host-sampler.sh"' || true
  scp -q "$PI:$PI_CSV" "$OUT/host.csv" || true
  ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-after.txt" || true
  ssh "$PI" 'echo "throttled_at_end: $(vcgencmd get_throttled)"; echo "temp_at_end: $(vcgencmd measure_temp)"' >> "$OUT/environment.txt" || true
  log "collected results into $OUT"
}
trap cleanup EXIT

sleep "$BASELINE_S"

run() {  # name, loadgen args...
  local name=$1; shift
  if ssh "$GEN" "test -e $STOP"; then log "skipping $name: STOP present"; return; fi
  log "test $name: $*"
  ssh "$GEN" "cd $GEN_DIR && python3 monitoring/bench/loadgen.py --base $BASE --concurrency $STEPS \
      --duration $DUR --pause $PAUSE --stop-file $STOP --out results/$name.json $*" | tee -a "$OUT/run.log"
  scp -q "$GEN:$GEN_DIR/results/$name.json" "$OUT/$name.json"
  sleep "$PAUSE"
}

# A: small archive, fully in page cache -> the Pi's serving path
run A-vbm-warm           --source vbm --tile-list vbm.txt
# B: raster WebP (not gzip-stored), 13 GB
run B-freetown           --source freetown-mapterhorn --tile-list freetown.txt
# C: 178 GB archive vs 8 GB RAM, random tiles -> cold reads from the USB SSD
run C-kitaphoto17-cold   --source kitaphoto17 --tile-list kitaphoto17.txt
# E: a real consumer's access pattern. tokachi20260911 samples
# mapterhorn-japan-bridge (258 GB terrarium) in contiguous z16 blocks, 6 in
# parallel; this is a 60x60 z16 block around Tokachidake at exactly c=6.
# (Later --concurrency/--duration override the defaults; argparse keeps the last.)
run E-mjb-z16-c6         --source mapterhorn-japan-bridge --tile-list mjb-z16.txt --concurrency 6 --duration 60
# D: same as A but forcing on-the-fly gzip decompression -> CPU-bound variant
run D-vbm-decompress     --source vbm --tile-list vbm.txt --no-accept-encoding

log "run $RUN_ID finished"
