#!/bin/bash
# Phase 2: the same origin, but reached through Cloudflare, to find what the
# site's uplink actually delivers to a public viewer.
#
# Phase 1 measured the Pi over the LAN and hit the 100 Mb/s switch port. A public
# viewer's path is longer: Martin -> cloudflared -> the home uplink -> Cloudflare's
# edge -> back down. This run keeps the same generator and tile lists and changes
# only the route, so the difference is the route.
#
# Every request carries a unique ?cb=, because an edge cache hit would measure
# Cloudflare, not this site. That also means every request reaches the origin:
# keep concurrency low (c <= 6, per Phase 1 finding 8) and the run short.
#
# Roles: this machine orchestrates and runs the temperature watchdog; $GEN
# generates load (must be wired, and free -- ask the other users first);
# $PI is sampled throughout, for both martin and cloudflared.
#
# Everything lands in benchmarks/<run id>/ in this repo.
set -euo pipefail

cd "$(dirname "$0")/../.."
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%MZ)-phase2}"
PI="${PI:-spacex.optgeo.org}"
GEN="${GEN:-slate.local}"
LAN_BASE="${LAN_BASE:-http://192.168.11.14:3000}"
CDN_BASE="${CDN_BASE:-https://stars.optgeo.org}"
GEN_DIR="${GEN_DIR:-/tmp/stars-bench}"
STEPS="${STEPS:-1,2,4,6}"
DUR="${DUR:-30}"
PAUSE="${PAUSE:-15}"
BASELINE_S="${BASELINE_S:-60}"
MAX_TEMP_C="${MAX_TEMP_C:-80}"
OUT="benchmarks/$RUN_ID"
PI_CSV="/tmp/bench/$RUN_ID-host.csv"
PI_CSV_CF="/tmp/bench/$RUN_ID-cloudflared.csv"
STOP="$GEN_DIR/STOP"
GEN_CSV="$GEN_DIR/$RUN_ID-gen.csv"

mkdir -p "$OUT"
log() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$OUT/run.log"; }

log "run $RUN_ID starting"
{
  echo "run_id: $RUN_ID"
  echo "repo_commit: $(git rev-parse HEAD)"
  echo "started_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "generator: $GEN ($(ssh "$GEN" 'sysctl -n machdep.cpu.brand_string; python3 --version' | tr '\n' ' '))"
  echo "generator_link: $(ssh "$GEN" 'ifconfig en0 | grep media' | sed 's/^[[:space:]]*//')"
  echo "lan_base: $LAN_BASE"
  echo "cdn_base: $CDN_BASE"
  echo "steps: $STEPS  duration_s: $DUR  pause_s: $PAUSE  max_temp_c: $MAX_TEMP_C"
  ssh "$PI" 'echo "kernel: $(uname -r)"
             echo "martin: $(/home/stars/.local/bin/martin --version)"
             echo "martin_since: $(systemctl --user show martin -p ActiveEnterTimestamp --value)"
             echo "cloudflared: $(cloudflared --version 2>&1 | head -1)"
             echo "eth0_speed_mbps: $(cat /sys/class/net/eth0/speed)"
             echo "throttled_at_start: $(vcgencmd get_throttled)"
             echo "temp_at_start: $(vcgencmd measure_temp)"
             echo "rx_pause_at_start: $(/usr/sbin/ethtool -S eth0 | awk "/rx_pause:/{print \$2}")"'
} > "$OUT/environment.txt"

ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-before.txt"
scp -q monitoring/bench/host-sampler.sh "$PI":/tmp/bench/host-sampler.sh
# Two samplers: Martin's own process, and cloudflared, which carries this route
# and is the one new moving part compared with Phase 1.
# One SSH per sampler: starting both from a single command left the second one
# dead on the 2026-09-16 run (cloudflared.csv had only its header).
ssh "$PI" "setsid nohup bash /tmp/bench/host-sampler.sh $PI_CSV 2 martin --user >/dev/null 2>&1 < /dev/null &"
ssh "$PI" "setsid nohup bash /tmp/bench/host-sampler.sh $PI_CSV_CF 2 cloudflared >/dev/null 2>&1 < /dev/null &"
sleep 5
ssh "$PI" "wc -l < $PI_CSV_CF" | awk '{ if ($1 < 2) print "WARNING: cloudflared sampler produced no rows" }' 
ssh "$GEN" "rm -f $STOP"
# Sample the generator too. The 2026-09-17 soak ended with a watchdog reset on the
# generator and nothing recorded about its state; see docs/BENCHMARKS.md.
scp -q monitoring/bench/gen-sampler.sh "$GEN":"$GEN_DIR/gen-sampler.sh"
ssh "$GEN" "cd $GEN_DIR && nohup bash gen-sampler.sh $GEN_CSV 5 en0 >/dev/null 2>&1 < /dev/null &"
log "samplers started on Pi; baseline ${BASELINE_S}s"

(
  while true; do
    t=$(ssh -o ConnectTimeout=10 "$PI" 'cat /sys/class/thermal/thermal_zone0/temp' 2>/dev/null || echo 0)
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
  scp -q "$PI:$PI_CSV_CF" "$OUT/cloudflared.csv" || true
  ssh "$PI" "curl -s http://127.0.0.1:3000/_/metrics" > "$OUT/metrics-after.txt" || true
  ssh "$PI" 'echo "throttled_at_end: $(vcgencmd get_throttled)"
             echo "temp_at_end: $(vcgencmd measure_temp)"
             echo "rx_pause_at_end: $(/usr/sbin/ethtool -S eth0 | awk "/rx_pause:/{print \$2}")"' >> "$OUT/environment.txt" || true
  ssh "$GEN" 'pkill -f "bash gen-sampler.sh"' || true
  scp -q "$GEN:$GEN_CSV" "$OUT/generator.csv" || true
  log "collected results into $OUT"
}
trap cleanup EXIT

sleep "$BASELINE_S"

run() {  # name, base, loadgen args...
  local name=$1 base=$2; shift 2
  if ssh "$GEN" "test -e $STOP"; then log "skipping $name: STOP present"; return; fi
  log "test $name ($base): $*"
  ssh "$GEN" "cd $GEN_DIR && python3 monitoring/bench/loadgen.py --base $base --concurrency $STEPS \
      --duration $DUR --pause $PAUSE --stop-file $STOP --out results/$name.json $*" | tee -a "$OUT/run.log"
  scp -q "$GEN:$GEN_DIR/results/$name.json" "$OUT/$name.json"
  sleep "$PAUSE"
}

# P: the same tiles over the LAN, as this run's own reference point. Phase 1's
# numbers are a day old and the Pi's state has changed since, so the comparison
# has to be measured here, not quoted.
run P-lan-kitaphoto17  "$LAN_BASE" --source kitaphoto17 --tile-list kitaphoto17.txt
# Q: the public route. Same tiles, same steps, every request cache-busted so it
# reaches the origin.
run Q-cdn-kitaphoto17  "$CDN_BASE" --source kitaphoto17 --tile-list kitaphoto17.txt --cache-bust
# R: small raster tiles through the CDN -- more requests per MB, so this
# separates "requests per second through the tunnel" from "bytes per second".
run R-cdn-freetown     "$CDN_BASE" --source freetown-mapterhorn --tile-list freetown.txt --cache-bust
# S: what a real viewer gets, edge cache included. No cache-bust: the first pass
# fills the edge, the rest should be hits. Read it as the best case, not as the
# origin's capacity.
run S-cdn-cached       "$CDN_BASE" --source freetown-mapterhorn --tile-list freetown.txt --hot-set 200

log "run $RUN_ID finished"
