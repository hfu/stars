#!/usr/bin/env python3
"""Ask upstream whether the asset pins in fonts.json / sprites.json are still current.

The point of pinning is that a copy stops tracking its source silently. This closes that
gap: it reports, per pinned file, whether the commit or release tag we took it from is
still what upstream publishes. A moved pin is information, not a fault — upstream decides
when the font changes, we decide when stars takes the new one.

`fetch-fonts.py --check` / `fetch-sprites.py --check` do the same thing through the `gh`
CLI for interactive use. This module exists so the daily specs collector can do it without
`gh` (stdlib + the GitHub REST API) and put the result on the dashboard.

Uses GH_TOKEN / GITHUB_TOKEN when present — unauthenticated GitHub allows 60 requests an
hour per address, and this makes ~18.

Usage:
  check-pins.py [repo-root]     print a table; exit 1 if any pin has moved
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
UA = "stars-assets/1.0 (+https://github.com/hfu/stars)"
TIMEOUT_S = 30


def _get(path):
    req = urllib.request.Request(API + path, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {tok}"}
           if (tok := os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")) else {}),
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def latest_commit(repo, path):
    q = urllib.parse.urlencode({"path": path, "per_page": 1})
    data = _get(f"/repos/{repo}/commits?{q}")
    if not data:
        raise RuntimeError("no commits for that path")
    return data[0]["sha"], data[0]["commit"]["committer"]["date"]


def latest_release(repo, tag):
    """Newest release whose tag starts the way this one does.

    Noto CJK ships `Sans2.004` and `Serif2.003` as separate lines, so "latest release"
    alone would compare a Sans pin against a Serif release.
    """
    prefix = "".join(c for c in tag if not c.isdigit() and c != ".")
    for rel in _get(f"/repos/{repo}/releases?per_page=100"):
        if rel["tag_name"].startswith(prefix):
            return rel["tag_name"], rel.get("published_at", "")
    raise RuntimeError(f"no release tagged {prefix}*")


def check_all(repo_root):
    """Return a compact report: what is pinned, what upstream has now."""
    root = Path(repo_root)
    entries = []
    fonts = json.loads((root / "assets" / "fonts.json").read_text())
    for f in fonts["fonts"]:
        entries.append((f["martin_name"], f["file"], f["source"]))
    sprites = json.loads((root / "assets" / "sprites.json").read_text())
    for s in sprites["sprites"]:
        for part in s.get("icons", []) + s.get("sheet", []):
            entries.append((s["sprite_id"], part["file"], part["source"]))

    cache, moved, errors, current = {}, [], [], 0
    for name, file, src in entries:
        try:
            if src["kind"] == "github_raw":
                key = ("c", src["repo"], src["path"])
                if key not in cache:
                    cache[key] = latest_commit(src["repo"], src["path"])
                upstream, when = cache[key]
                pinned = src["ref"]
            elif src["kind"] == "github_release_zip":
                key = ("r", src["repo"], src["tag"])
                if key not in cache:
                    cache[key] = latest_release(src["repo"], src["tag"])
                upstream, when = cache[key]
                pinned = src["tag"]
            else:
                raise RuntimeError(f"unknown source kind {src['kind']}")
        except (urllib.error.URLError, RuntimeError, KeyError, TimeoutError) as e:
            errors.append({"asset": name, "file": file, "error": str(e)})
            continue
        if upstream == pinned:
            current += 1
        else:
            moved.append({"asset": name, "file": file, "repo": src["repo"],
                          "pinned": pinned, "upstream": upstream, "upstream_date": when})

    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pins_checked": len(entries),
        "pins_current": current,
        "pins_moved": moved,
        "errors": errors,
        "fonts_served": len(fonts["fonts"]),
        "sprites_served": len(sprites["sprites"]),
        "sprite_icons": sum(s.get("icon_count", len(s.get("icons", [])))
                            for s in sprites["sprites"]),
    }


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    rep = check_all(root)
    for m in rep["pins_moved"]:
        print(f"MOVED   {m['asset']:<26} {m['file']:<28} {m['pinned'][:12]} -> "
              f"{m['upstream'][:12]} ({m['upstream_date']})")
    for e in rep["errors"]:
        print(f"ERROR   {e['asset']:<26} {e['file']:<28} {e['error']}")
    print(f"{rep['pins_current']}/{rep['pins_checked']} pins current; "
          f"{rep['fonts_served']} fonts, {rep['sprites_served']} sprites "
          f"({rep['sprite_icons']} icons) served by stars")
    sys.exit(1 if rep["pins_moved"] or rep["errors"] else 0)
