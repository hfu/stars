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


def build_row(agg_or_none, prev_row, up):
    ts = now_iso()
    if not up or agg_or_none is None:
        return {"ts": ts, "up": False}

    agg = agg_or_none
    row = {"ts": ts, "up": True, "restarted": False, "_raw": agg}

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
        text = fetch_metrics()
        samples = parse_metrics(text)
        agg = aggregate(samples)
        row = build_row(agg, prev_row, up=True)
    except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
        print(f"scrape failed: {e}", file=sys.stderr)
        row = build_row(None, prev_row, up=False)

    with out_path.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")

    lines = out_path.read_text().splitlines()
    if len(lines) > MAX_LINES:
        out_path.write_text("\n".join(lines[-MAX_LINES:]) + "\n")


if __name__ == "__main__":
    main()
