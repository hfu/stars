#!/bin/bash
# Sample Raspberry Pi hardware + one service's process state to CSV at a fixed
# interval, for benchmark and soak runs.
#
# Columns are read only from /proc and /sys so the same schema works on
# Raspberry Pi OS and Ubuntu Server alike (agreed with rpi-geoserver0, which
# runs Ubuntu where `vcgencmd get_throttled` is unavailable -- /dev/vcio is
# missing). `throttled_hex` is the one optional column: filled where vcgencmd
# works, left empty elsewhere.
#
# Usage: host-sampler.sh <out.csv> [interval_s=5] [systemd unit=martin] [--user]
#   Run it on the Pi itself (it's cheap); run the load generator elsewhere.
set -euo pipefail

OUT="${1:?usage: host-sampler.sh <out.csv> [interval_s] [unit] [--user]}"
INTERVAL="${2:-5}"
UNIT="${3:-martin}"
SCOPE="${4:-}"
NET_IF="${NET_IF:-eth0}"
DISK="${DISK:-sda}"

cpu_totals() { awk '/^cpu /{idle=$5+$6; tot=0; for(i=2;i<=NF;i++) tot+=$i; print tot, idle}' /proc/stat; }
net_bytes()  { awk -v i="$NET_IF:" '$1==i{print $2, $10}' /proc/net/dev; }
disk_stats() { awk -v d="$DISK" '$3==d{print $6*512, $10*512, $13}' /proc/diskstats; }
svc_pid()    { systemctl $SCOPE show -p MainPID --value "$UNIT" 2>/dev/null || echo 0; }
# PAUSE-frame counters exist only in the driver's ethtool stats (not /sys), and
# not every driver names them rx_pause/tx_pause; print empty fields when absent.
ETHTOOL="$(command -v ethtool || { [ -x /usr/sbin/ethtool ] && echo /usr/sbin/ethtool; } || true)"
pause_ctrs() {
  [ -n "$ETHTOOL" ] || { echo ","; return; }
  "$ETHTOOL" -S "$NET_IF" 2>/dev/null |
    awk '$1=="rx_pause:"{rx=$2} $1=="tx_pause:"{tx=$2} END{print rx "," tx}'
}

# Units are spelled out in every column name; all rates are bytes per second.
# net_tx_errors (cumulative, from /sys/class/net/<IF>/statistics) was appended after
# Phase 1: the Pi's Ethernet driver logged 103 transmit-queue watchdog timeouts under
# high-concurrency load while CPU, disk and temperature all looked fine, so nothing in
# the original columns showed it. Kept as a trailing column so older CSVs still parse.
echo "ts_utc,uptime_s,load1,cpu_util_pct,cpu_freq_khz,temp_c,mem_available_kb,swap_used_kb,net_rx_bytes_s,net_tx_bytes_s,disk_read_bytes_s,disk_write_bytes_s,disk_busy_pct,svc_rss_kb,svc_threads,svc_fds,throttled_hex,net_tx_errors,net_rx_pause,net_tx_pause" > "$OUT"

read -r c_tot0 c_idle0 < <(cpu_totals)
read -r rx0 tx0 < <(net_bytes)
read -r dr0 dw0 dio0 < <(disk_stats)
t0=$(date +%s.%N)

while sleep "$INTERVAL"; do
  t1=$(date +%s.%N)
  dt=$(awk -v a="$t0" -v b="$t1" 'BEGIN{print b-a}')
  read -r c_tot1 c_idle1 < <(cpu_totals)
  read -r rx1 tx1 < <(net_bytes)
  read -r dr1 dw1 dio1 < <(disk_stats)

  pid=$(svc_pid)
  if [ "$pid" != "0" ] && [ -r "/proc/$pid/status" ]; then
    rss=$(awk '/^VmRSS:/{print $2}' "/proc/$pid/status")
    thr=$(awk '/^Threads:/{print $2}' "/proc/$pid/status")
    fds=$(ls "/proc/$pid/fd" 2>/dev/null | wc -l)
  else
    rss=""; thr=""; fds=""
  fi

  thr_hex=""
  if command -v vcgencmd >/dev/null 2>&1; then
    thr_hex=$(vcgencmd get_throttled 2>/dev/null | sed -n 's/^throttled=//p' || true)
  fi

  awk -v ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)" -v dt="$dt" \
      -v ct0="$c_tot0" -v ci0="$c_idle0" -v ct1="$c_tot1" -v ci1="$c_idle1" \
      -v rx0="$rx0" -v tx0="$tx0" -v rx1="$rx1" -v tx1="$tx1" \
      -v dr0="$dr0" -v dw0="$dw0" -v di0="$dio0" -v dr1="$dr1" -v dw1="$dw1" -v di1="$dio1" \
      -v up="$(cut -d' ' -f1 /proc/uptime)" -v load="$(cut -d' ' -f1 /proc/loadavg)" \
      -v freq="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)" \
      -v temp="$(cat /sys/class/thermal/thermal_zone0/temp)" \
      -v mema="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)" \
      -v swt="$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)" \
      -v swf="$(awk '/^SwapFree:/{print $2}' /proc/meminfo)" \
      -v rss="$rss" -v thr="$thr" -v fds="$fds" -v th="$thr_hex" \
      -v txerr="$(cat "/sys/class/net/$NET_IF/statistics/tx_errors" 2>/dev/null)" \
      -v pause="$(pause_ctrs)" \
      'BEGIN{
         dtot=ct1-ct0; util=(dtot>0)?100*(1-(ci1-ci0)/dtot):0
         printf "%s,%d,%s,%.1f,%s,%.1f,%s,%d,%.0f,%.0f,%.0f,%.0f,%.1f,%s,%s,%s,%s,%s,%s\n",
           ts, up, load, util, freq, temp/1000, mema, swt-swf,
           (rx1-rx0)/dt, (tx1-tx0)/dt, (dr1-dr0)/dt, (dw1-dw0)/dt,
           100*(di1-di0)/(dt*1000), rss, thr, fds, th, txerr, pause
       }' >> "$OUT"

  c_tot0=$c_tot1; c_idle0=$c_idle1; rx0=$rx1; tx0=$tx1; dr0=$dr1; dw0=$dw1; dio0=$dio1; t0=$t1
done
