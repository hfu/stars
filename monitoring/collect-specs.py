#!/usr/bin/env python3
"""Snapshot the *specifications* of everything stars.optgeo.org serves:
per-dataset TileJSON facts, per-style structure and external dependencies,
repo-vs-production style drift, and catalog-vs-disk reconciliation.

Unlike collect.py (10-minute telemetry time series), specs change rarely, so
this runs daily and writes a current-state snapshot plus an append-only log of
what actually changed between runs.

Requires PyYAML (to read config/martin.yaml); everything else is stdlib.
"""
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

BASE = "https://stars.optgeo.org"
INVENTORY_URL = "https://depot.optgeo.org/host-inventory.json"
# Cloudflare 403s requests with no/!default User-Agent (python-urllib's default
# is blocked); every fetch here must send one.
UA = {"User-Agent": "stars-monitoring/1.0"}
TIMEOUT_S = 30

# TileJSON fields worth keeping. `tilestats` and the full `vector_layers`
# bodies are deliberately dropped -- together they're ~80% of the raw payload
# and none of it belongs in an at-a-glance spec view.
KEEP_FIELDS = [
    "minzoom", "maxzoom", "bounds", "center", "format", "type", "version",
    "attribution", "name", "description", "generator", "generator_options",
    "planetiler:version", "planetiler:buildtime", "planetiler:githash",
    "planetiler:osm:osmosisreplicationtime",
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, as_json=True):
    req = urllib.request.Request(f"{url}?cb={int(time.time() * 1000)}", headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        if resp.status != 200:
            raise RuntimeError(f"status {resp.status}")
        raw = resp.read()
    return json.loads(raw) if as_json else raw


def canon_hash(obj):
    """Stable hash of a JSON document, independent of key order/whitespace."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def host_of(url):
    if not url:
        return None
    if not url.startswith("http"):
        return "(relative)"
    return urlparse(url).netloc or None


def classify_backing(source_id, explicit_sources):
    """local(explicit) / remote / local(auto-discovered), from config/martin.yaml."""
    if source_id in explicit_sources:
        value = str(explicit_sources[source_id])
        if value.startswith("http"):
            return "remote", host_of(value)
        return "local", None
    return "local-auto", None


def collect_datasets(catalog, explicit_sources):
    datasets = {}
    for sid in sorted(catalog.get("tiles", {})):
        entry = {"id": sid}
        backing, remote_host = classify_backing(sid, explicit_sources)
        entry["backing"] = backing
        if remote_host:
            entry["remote_host"] = remote_host
        entry["content_type"] = catalog["tiles"][sid].get("content_type")
        try:
            tj = fetch(f"{BASE}/{sid}")
        except (urllib.error.URLError, RuntimeError, TimeoutError, ValueError) as e:
            entry["error"] = str(e)
            datasets[sid] = entry
            continue
        for field in KEEP_FIELDS:
            if field in tj:
                entry[field] = tj[field]
        if "vector_layers" in tj:
            entry["layer_count"] = len(tj["vector_layers"])
            entry["layer_ids"] = [lyr.get("id") for lyr in tj["vector_layers"]]
        datasets[sid] = entry
    return datasets


def collect_styles(catalog, repo_root):
    styles = {}
    for sid in sorted(catalog.get("styles", {})):
        entry = {"id": sid}
        try:
            deployed = fetch(f"{BASE}/style/{sid}")
        except (urllib.error.URLError, RuntimeError, TimeoutError, ValueError) as e:
            entry["error"] = str(e)
            styles[sid] = entry
            continue

        entry["name"] = deployed.get("name")
        entry["layer_count"] = len(deployed.get("layers", []))
        entry["deployed_hash"] = canon_hash(deployed)

        sources = {}
        for name, src in (deployed.get("sources") or {}).items():
            url = src.get("url") or (src.get("tiles") or [None])[0]
            sources[name] = {"type": src.get("type"), "host": host_of(url)}
        entry["sources"] = sources
        entry["glyphs_host"] = host_of(deployed.get("glyphs"))
        entry["sprite_host"] = host_of(deployed.get("sprite"))

        # Repo copy is canonical (see CLAUDE.md); production is the deploy
        # target. Drift means someone edited production directly.
        repo_file = repo_root / "styles" / f"{sid}.json"
        if repo_file.exists():
            repo_hash = canon_hash(json.loads(repo_file.read_text()))
            entry["repo_hash"] = repo_hash
            entry["drift"] = repo_hash != entry["deployed_hash"]
        else:
            entry["repo_hash"] = None
            entry["drift"] = None  # unknown: no canonical copy tracked in-repo
        styles[sid] = entry
    return styles


def style_source_references(styles, dataset_ids, repo_root):
    """Which datasets are referenced by a stars-hosted style.

    NOTE: a dataset with no stars-hosted style is NOT unused -- most are
    consumed by external consumer projects that ship their own styles. Callers
    must not label these "orphaned".
    """
    referenced = set()
    for sid in styles:
        repo_file = repo_root / "styles" / f"{sid}.json"
        if not repo_file.exists():
            continue
        text = repo_file.read_text()
        for did in dataset_ids:
            if re.search(r"/%s(?:[/\"?]|\b)" % re.escape(did), text):
                referenced.add(did)
    return referenced


def external_dependencies(styles):
    """Hosts other than stars.optgeo.org that styles depend on at render time."""
    deps = {}
    for sid, s in styles.items():
        if "error" in s:
            continue
        for kind, host in (("glyphs", s.get("glyphs_host")),
                           ("sprite", s.get("sprite_host"))):
            if host and host != "stars.optgeo.org":
                deps.setdefault(host, []).append(f"{sid}:{kind}")
        for name, src in (s.get("sources") or {}).items():
            host = src.get("host")
            if host and host != "stars.optgeo.org":
                deps.setdefault(host, []).append(f"{sid}:source/{name}")
    return {h: sorted(v) for h, v in sorted(deps.items())}


def reconcile_with_disk(datasets, explicit_sources):
    """Compare the served catalog against what's actually on the host's disk.

    Surfaces large files that vanished (or appeared) without a config change --
    /home/stars/data is writable by trusted contributors directly, so the
    catalog and the disk can diverge without this session doing anything.
    """
    try:
        inv = fetch(INVENTORY_URL)
    except (urllib.error.URLError, RuntimeError, TimeoutError, ValueError) as e:
        return {"available": False, "error": str(e)}

    files = inv.get("pmtiles", {})
    on_disk = set(files)

    # An explicit source's id need not match its filename (e.g.
    # pmtiles_jma_1saibun_hkd -> jma_1saibun_hkd.pmtiles), so map explicit
    # local entries through their configured path; auto-discovered ids are
    # the filename stem by definition.
    expected = set()
    for sid, d in datasets.items():
        backing = d.get("backing")
        if backing == "local":
            path = str(explicit_sources.get(sid, ""))
            stem = path.rsplit("/", 1)[-1]
            if stem.endswith(".pmtiles"):
                stem = stem[: -len(".pmtiles")]
            if stem:
                expected.add(stem)
        elif backing == "local-auto":
            expected.add(sid)

    return {
        "available": True,
        "collected_at": inv.get("ts"),
        "file_count": len(files),
        "total_bytes": sum(f.get("size", 0) for f in files.values()),
        "largest": sorted(
            ({"file": k, "size": v.get("size", 0)} for k, v in files.items()),
            key=lambda x: x["size"], reverse=True,
        )[:10],
        # On disk but nothing serves it: dead weight, or a file mid-upload.
        "on_disk_not_served": sorted(on_disk - expected),
        # Configured but the file is gone: a source that will 404.
        "served_but_missing_on_disk": sorted(expected - on_disk),
        "files": files,
    }


def diff_snapshots(prev, cur):
    """Human-meaningful changes between two snapshots (empty list if none)."""
    if not prev:
        return [{"kind": "initial", "detail": "first snapshot"}]
    changes = []

    for section in ("datasets", "styles"):
        old, new = prev.get(section, {}), cur.get(section, {})
        for sid in sorted(set(new) - set(old)):
            changes.append({"kind": f"{section[:-1]}_added", "id": sid})
        for sid in sorted(set(old) - set(new)):
            changes.append({"kind": f"{section[:-1]}_removed", "id": sid})
        for sid in sorted(set(old) & set(new)):
            if canon_hash(old[sid]) != canon_hash(new[sid]):
                fields = sorted(
                    k for k in set(old[sid]) | set(new[sid])
                    if old[sid].get(k) != new[sid].get(k)
                )
                changes.append({"kind": f"{section[:-1]}_changed", "id": sid,
                                "fields": fields})

    old_disk = (prev.get("disk") or {}).get("files") or {}
    new_disk = (cur.get("disk") or {}).get("files") or {}
    if old_disk or new_disk:
        for f in sorted(set(old_disk) - set(new_disk)):
            changes.append({"kind": "file_removed", "id": f,
                            "size": old_disk[f].get("size")})
        for f in sorted(set(new_disk) - set(old_disk)):
            changes.append({"kind": "file_added", "id": f,
                            "size": new_disk[f].get("size")})
    return changes


def main():
    if len(sys.argv) != 3:
        print("usage: collect-specs.py <repo-root> <out-dir>", file=sys.stderr)
        sys.exit(1)
    repo_root = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = yaml.safe_load((repo_root / "config" / "martin.yaml").read_text())
    explicit_sources = (cfg.get("pmtiles") or {}).get("sources") or {}

    catalog = fetch(f"{BASE}/catalog")
    datasets = collect_datasets(catalog, explicit_sources)
    styles = collect_styles(catalog, repo_root)
    referenced = style_source_references(styles, set(datasets), repo_root)
    for did, d in datasets.items():
        d["referenced_by_stars_style"] = did in referenced

    snapshot = {
        "ts": now_iso(),
        "datasets": datasets,
        "styles": styles,
        "external_dependencies": external_dependencies(styles),
        "disk": reconcile_with_disk(datasets, explicit_sources),
        "summary": {
            "dataset_count": len(datasets),
            "style_count": len(styles),
            "backing": {
                b: sum(1 for d in datasets.values() if d.get("backing") == b)
                for b in ("local", "local-auto", "remote")
            },
            "styled_by_stars": len(referenced),
            "styles_with_drift": sorted(
                s for s, v in styles.items() if v.get("drift") is True
            ),
        },
    }

    specs_path = out_dir / "specs.json"
    prev = None
    if specs_path.exists():
        try:
            prev = json.loads(specs_path.read_text())
        except json.JSONDecodeError:
            prev = None

    # `ts` always differs; compare everything else so a no-op day logs nothing.
    def body(s):
        return {k: v for k, v in s.items() if k != "ts"} if s else None

    changes = diff_snapshots(body(prev), body(snapshot))
    if changes:
        with (out_dir / "changes.jsonl").open("a") as f:
            f.write(json.dumps({"ts": snapshot["ts"], "changes": changes},
                               ensure_ascii=False, separators=(",", ":")) + "\n")

    specs_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"specs: {len(datasets)} datasets, {len(styles)} styles, "
          f"{len(changes)} change(s), {specs_path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
