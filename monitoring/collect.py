#!/usr/bin/env python3
"""Scrape stars.optgeo.org's Martin /_/metrics endpoint and append one summary
row to a capped JSONL telemetry file. Stdlib-only (no third-party deps) so it
runs on a bare GitHub Actions runner.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

METRICS_URL = "https://stars.optgeo.org/_/metrics"
HOST_STATUS_URL = "https://depot.optgeo.org/host-status.json"
HOST_INVENTORY_URL = "https://depot.optgeo.org/host-inventory.json"
TILE_ENDPOINT = "/{source_ids}/{z}/{x}/{y}"
MAX_LINES = 12000
TIMEOUT_S = 15

# Label values (e.g. endpoint="/{source_ids}/{z}/{x}/{y}") can themselves
# contain literal braces, so the label-block regex must be greedy and match
# through to the *last* "}" on the line, not stop at the first one.
LINE_WITH_LABELS_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{(.*)\}\s+(\S+)$')
LINE_NO_LABELS_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+(\S+)$')
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_metrics():
    url = f"{METRICS_URL}?cb={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "stars-monitoring/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        if resp.status != 200:
            raise RuntimeError(f"unexpected status {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


def fetch_host_status():
    """Fetch the small JSON snapshot host-status.sh writes on the host itself.
    Independent of Martin's own liveness -- the OS can be fine even if Martin
    isn't, or vice versa."""
    url = f"{HOST_STATUS_URL}?cb={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "stars-monitoring/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        if resp.status != 200:
            raise RuntimeError(f"unexpected status {resp.status}")
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_host_inventory():
    """Fetch the hourly listing of what actually sits in /home/stars/data.

    `/home/stars/data` is written directly by trusted contributors, so a 272 GB archive
    can be swapped without anything in this repo doing it. That happened on 2026-09-19
    and went unnoticed for a week: the change *was* recorded daily, but nothing put it
    where anyone would look. Reading the inventory here, on the 10-minute cadence, is
    what turns "recorded" into "noticed".
    """
    url = f"{HOST_INVENTORY_URL}?cb={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "stars-monitoring/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        if resp.status != 200:
            raise RuntimeError(f"unexpected status {resp.status}")
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def inventory_fingerprint(inventory):
    """{name: [size, mtime]} for the served archives -- staging files are excluded.

    A file being written is not a change to what is served; it becomes one only when it
    is renamed into place, which is exactly when its size or mtime under the served name
    moves.
    """
    return {name: [v.get("size"), v.get("mtime")]
            for name, v in (inventory.get("pmtiles") or {}).items()}


def inventory_changes(prev_fp, cur_fp):
    """What changed between two fingerprints, in terms a reader can act on."""
    changes = []
    for name in sorted(set(prev_fp) | set(cur_fp)):
        before, after = prev_fp.get(name), cur_fp.get(name)
        if before == after:
            continue
        if before is None:
            changes.append({"name": name, "kind": "added",
                            "size": after[0], "mtime": after[1]})
        elif after is None:
            changes.append({"name": name, "kind": "removed",
                            "size_before": before[0], "mtime_before": before[1]})
        else:
            changes.append({"name": name, "kind": "replaced",
                            "size_before": before[0], "size": after[0],
                            "size_delta": (after[0] or 0) - (before[0] or 0),
                            "mtime_before": before[1], "mtime": after[1]})
    return changes


def find_last_with(path, key):
    """Most recent row carrying `key`.

    The full inventory fingerprint is written only on the rows where it changed -- at
    ~1.3 KB for 33 archives, writing it every 10 minutes would add roughly 15 MB to a
    12,000-line file that exists to be fetched by a browser.
    """
    if not path.exists():
        return None
    for line in reversed(path.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if key in row:
            return row
    return None


def parse_metrics(text):
    """Return list of (name, labels_dict, float_value)."""
    samples = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = LINE_WITH_LABELS_RE.match(line)
        if m:
            name, label_str, value = m.groups()
            labels = dict(LABEL_RE.findall(label_str))
        else:
            m = LINE_NO_LABELS_RE.match(line)
            if not m:
                continue
            name, value = m.groups()
            labels = {}
        try:
            value = float(value)
        except ValueError:
            continue
        samples.append((name, labels, value))
    return samples


def aggregate(samples):
    """Reduce raw samples to the cumulative counters we track."""
    agg = {
        "requests_total": 0.0,
        "requests_2xx": 0.0,
        "requests_3xx": 0.0,
        "requests_4xx": 0.0,
        "requests_5xx": 0.0,
        "duration_sum": 0.0,
        "duration_count": 0.0,
        "cache_hit": 0.0,
        "cache_miss": 0.0,
    }
    for name, labels, value in samples:
        if name == "martin_http_requests_total" and labels.get("endpoint") == TILE_ENDPOINT:
            agg["requests_total"] += value
            status = labels.get("status", "")
            bucket = f"requests_{status[:1]}xx" if status[:1] in "12345" else None
            if bucket in agg:
                agg[bucket] += value
        elif name == "martin_http_requests_duration_seconds_sum" and labels.get("endpoint") == TILE_ENDPOINT:
            agg["duration_sum"] += value
        elif name == "martin_http_requests_duration_seconds_count" and labels.get("endpoint") == TILE_ENDPOINT:
            agg["duration_count"] += value
        elif name == "martin_tile_cache_requests_total" and labels.get("cache") == "pmtiles_directory":
            if labels.get("result") == "hit":
                agg["cache_hit"] += value
            elif labels.get("result") == "miss":
                agg["cache_miss"] += value
    return agg


def find_last_raw(path):
    """Scan the jsonl backwards for the last row carrying cumulative ('_raw') values."""
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_raw" in row:
            return row
    return None


def apply_host_status(row, host_status):
    """host-status.sh reports point-in-time gauges, not cumulative counters,
    so these are copied straight across -- no delta/rate math needed."""
    if host_status is None:
        row["host_ok"] = False
        return
    row["host_ok"] = True
    row["host_uptime_days"] = round(host_status["uptime_s"] / 86400.0, 2)
    row["host_load1"] = host_status["load1"]
    row["host_load5"] = host_status["load5"]
    row["host_load15"] = host_status["load15"]
    row["host_temp_c"] = host_status["temp_c"]
    row["host_disk_avail_gb"] = host_status["disk_avail_gb"]
    row["host_disk_used_pct"] = host_status["disk_used_pct"]
    # The one cumulative counter in host-status.json: NIC transmit-queue stalls since
    # boot. Kept as both the raw value and a per-interval delta, because what matters
    # operationally is "are new ones happening", not the total. A reboot resets the
    # counter, so a negative delta is reported as None rather than a negative count.
    tx_err = host_status.get("net_tx_errors")
    if tx_err is not None:
        row["host_net_tx_errors"] = tx_err


def build_row(agg_or_none, prev_row, up, host_status=None):
    ts = now_iso()
    if not up or agg_or_none is None:
        row = {"ts": ts, "up": False}
        apply_host_status(row, host_status)
        return row

    agg = agg_or_none
    row = {"ts": ts, "up": True, "restarted": False, "_raw": agg}
    apply_host_status(row, host_status)

    if prev_row is None:
        return row

    prev = prev_row["_raw"]
    prev_ts = datetime.strptime(prev_row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    elapsed_s = (datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - prev_ts).total_seconds()

    def delta(key):
        d = agg[key] - prev.get(key, 0.0)
        if d < 0:
            row["restarted"] = True
            return agg[key]
        return d

    d_req = delta("requests_total")
    d_2xx = delta("requests_2xx")
    d_3xx = delta("requests_3xx")
    d_4xx = delta("requests_4xx")
    d_5xx = delta("requests_5xx")
    d_dur_sum = delta("duration_sum")
    d_dur_count = delta("duration_count")
    d_hit = delta("cache_hit")
    d_miss = delta("cache_miss")

    if elapsed_s > 0:
        row["requests_per_min"] = round(d_req / (elapsed_s / 60.0), 3)
    row["requests_2xx"] = d_2xx
    row["requests_3xx"] = d_3xx
    row["requests_4xx"] = d_4xx
    row["requests_5xx"] = d_5xx
    if d_dur_count > 0:
        row["tile_latency_avg_ms"] = round((d_dur_sum / d_dur_count) * 1000.0, 2)
    cache_total = d_hit + d_miss
    if cache_total > 0:
        row["cache_hit_rate"] = round(d_hit / cache_total, 4)

    # New NIC transmit-queue stalls since the previous sample. The counter is cumulative
    # since boot, and what matters is whether new ones are appearing; a host reboot
    # resets it, which shows up as a negative difference and is reported as no data
    # rather than a negative count.
    tx_now, tx_prev = row.get("host_net_tx_errors"), prev_row.get("host_net_tx_errors")
    if tx_now is not None and tx_prev is not None and tx_now >= tx_prev:
        row["host_net_tx_errors_delta"] = tx_now - tx_prev

    return row


def main():
    if len(sys.argv) != 2:
        print("usage: collect.py <path-to-jsonl>", file=sys.stderr)
        sys.exit(1)
    from pathlib import Path
    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    prev_row = find_last_raw(out_path)

    try:
        host_status = fetch_host_status()
    except (urllib.error.URLError, RuntimeError, TimeoutError, ValueError, KeyError) as e:
        print(f"host-status scrape failed: {e}", file=sys.stderr)
        host_status = None

    try:
        text = fetch_metrics()
        samples = parse_metrics(text)
        agg = aggregate(samples)
        row = build_row(agg, prev_row, up=True, host_status=host_status)
    except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
        print(f"scrape failed: {e}", file=sys.stderr)
        row = build_row(None, prev_row, up=False, host_status=host_status)

    # What is actually on disk, and whether it moved since the last time we looked.
    try:
        fp = inventory_fingerprint(fetch_host_inventory())
        prev_fp_row = find_last_with(out_path, "_inv")
        prev_fp = (prev_fp_row or {}).get("_inv")
        if prev_fp is None:
            row["_inv"] = fp          # first run: record the baseline, claim nothing
        elif prev_fp != fp:
            row["_inv"] = fp
            row["data_changes"] = inventory_changes(prev_fp, fp)
        row["served_archive_count"] = len(fp)
    except (urllib.error.URLError, RuntimeError, TimeoutError, ValueError, KeyError) as e:
        print(f"host-inventory scrape failed: {e}", file=sys.stderr)

    with out_path.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")

    lines = out_path.read_text().splitlines()
    if len(lines) > MAX_LINES:
        out_path.write_text("\n".join(lines[-MAX_LINES:]) + "\n")


if __name__ == "__main__":
    main()
