#!/bin/bash
# Per-request CPU of Martin vs the size of a source's TileJSON metadata.
#
# Serves three copies of the same archive from a throwaway Martin on
# 127.0.0.1:3999 (production Martin is not touched): unchanged, with `tilestats`
# removed from the metadata, and with `tilestats` + `vector_layers` removed. Tile
# bytes are identical across the three, so any difference in Martin's CPU time is
# the metadata. Requests are sequential keep-alive over loopback, so the network
# is out of the picture. Copies live in /tmp (tmpfs) and are removed on exit.
#
# Usage (on the Pi): tilejson-probe.sh <archive.pmtiles> <tile list from pmtiles_list.py> [n=600]
# Found 2026-09-15; see docs/BENCHMARKS.md finding 3.
set -euo pipefail
export PATH=$HOME/.local/bin:$PATH
SRC="${1:?archive}"; LIST="${2:?tile list}"; N="${3:-600}"
W=/tmp/bench/tilejson-probe; MP=
trap 'kill $MP 2>/dev/null; rm -rf $W' EXIT
rm -rf $W; mkdir -p $W
cp "$SRC" $W/full.pmtiles
cp "$SRC" $W/nostats.pmtiles
cp "$SRC" $W/minimal.pmtiles
pmtiles show --metadata $W/full.pmtiles > $W/meta.json
python3 -c "import json; d=json.load(open('$W/meta.json')); d.pop('tilestats', None); json.dump(d, open('$W/nostats.json','w'))"
python3 -c "import json; d=json.load(open('$W/meta.json')); [d.pop(k, None) for k in ('tilestats','vector_layers')]; json.dump(d, open('$W/minimal.json','w'))"
pmtiles edit $W/nostats.pmtiles --metadata $W/nostats.json >/dev/null 2>&1
pmtiles edit $W/minimal.pmtiles --metadata $W/minimal.json >/dev/null 2>&1
ls -l $W/*.pmtiles
martin --listen-addresses 127.0.0.1:3999 $W/full.pmtiles $W/nostats.pmtiles $W/minimal.pmtiles > $W/martin.log 2>&1 &
MP=$!
for i in $(seq 60); do curl -sf http://127.0.0.1:3999/health >/dev/null && break; sleep 0.5; done
for id in full nostats minimal; do echo "$id tilejson=$(curl -s http://127.0.0.1:3999/$id | wc -c)B"; done
head -n "$N" "$LIST" > $W/var
probe() {
  CFG=$(mktemp)
  while read -r t; do printf 'url = "http://127.0.0.1:3999/%s/%s"\noutput = "/dev/null"\n' "$1" "$t"; done < $W/var > $CFG
  read -r u0 k0 < <(awk '{print $14, $15}' /proc/$MP/stat)
  s=$(date +%s.%N); curl -s -H "Accept-Encoding: gzip, deflate, br" -K $CFG -w '%{http_code} %{size_download}\n' > $W/codes; e=$(date +%s.%N)
  read -r u1 k1 < <(awk '{print $14, $15}' /proc/$MP/stat)
  awk -v id="$1" -v s=$s -v e=$e -v u=$((u1-u0)) -v k=$((k1-k0)) '{n++; b+=$2; if($1!=200)bad++} END{printf "  %-8s n=%d non200=%d mean=%.0fB wall=%.2fs rps=%.0f user=%.2fs sys=%.2fs => %.2f ms/req\n", id, n, bad, b/n, e-s, n/(e-s), u/100, k/100, 10*(u+k)/n}' $W/codes
  rm -f $CFG
}
for r in 1 2; do probe full; probe nostats; probe minimal; done
