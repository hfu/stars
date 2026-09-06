#!/bin/bash
# Snapshot uptime/load/temperature/disk headroom for stars.optgeo.org as a
# small JSON file served statically by depot.optgeo.org (Caddy), so the
# GitHub Actions monitoring collector can scrape it over plain HTTPS without
# needing SSH access to this host.
set -euo pipefail

OUT="${HOST_STATUS_OUT:-/home/stars/data/host-status.json}"
TMP="${OUT}.tmp"

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
uptime_s=$(awk '{print $1}' /proc/uptime)
read -r load1 load5 load15 _ < /proc/loadavg

temp_c=$(/usr/bin/vcgencmd measure_temp 2>/dev/null | sed -n "s/temp=\([0-9.]*\).*/\1/p")
temp_c="${temp_c:-null}"

df_line=$(df -k /home/stars/data | tail -1)
disk_avail_kb=$(echo "$df_line" | awk '{print $4}')
disk_used_pct=$(echo "$df_line" | awk '{print $5}' | tr -d '%')
disk_avail_gb=$(awk -v kb="$disk_avail_kb" 'BEGIN { printf "%.1f", kb/1024/1024 }')

jq -n \
  --arg ts "$ts" \
  --argjson uptime_s "$uptime_s" \
  --argjson load1 "$load1" \
  --argjson load5 "$load5" \
  --argjson load15 "$load15" \
  --argjson temp_c "$temp_c" \
  --argjson disk_avail_gb "$disk_avail_gb" \
  --argjson disk_used_pct "$disk_used_pct" \
  '{ts: $ts, uptime_s: $uptime_s, load1: $load1, load5: $load5, load15: $load15,
    temp_c: $temp_c, disk_avail_gb: $disk_avail_gb, disk_used_pct: $disk_used_pct}' \
  > "$TMP"

mv "$TMP" "$OUT"
