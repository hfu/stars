#!/usr/bin/env python3
"""Fetch the sprite icon sources listed in assets/sprites.json.

Same rule as the fonts (see assets/README.md): copy the SVG sources and let Martin build
the sprite sheet, rather than mirroring somebody's rendered PNG. Each icon is pinned to an
upstream commit and checked by hash.

Layout: one directory per sprite id under the destination, because Martin takes the
directory name as the sprite id -- `<dest>/positron/*.svg` is served as `/sprite/positron`.

Usage:
  fetch-sprites.py <dest-dir>            download and verify against sprites.json
  fetch-sprites.py <dest-dir> --record   download and write the hashes into the manifest
  fetch-sprites.py --check               ask upstream whether the pins are still current
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "sprites.json"

# Share the download/hash/pin-check helpers with the font fetcher rather than keeping two
# copies that can drift apart.
_spec = importlib.util.spec_from_file_location("fetch_fonts", HERE / "fetch-fonts.py")
_ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ff)


def do_fetch(dest_dir, record):
    manifest = json.loads(MANIFEST.read_text())
    failures = []
    for sprite in manifest["sprites"]:
        out_dir = Path(dest_dir) / sprite["sprite_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        if sprite.get("kind") == "derived_from_sheet":
            failures += do_sheet(sprite, out_dir, record)
            continue
        for icon in sprite["icons"]:
            out = out_dir / icon["file"]
            try:
                _ff.fetch(_ff.raw_url(icon["source"]), out)
            except Exception as e:  # noqa: BLE001 - report and continue to the next icon
                failures.append(f"{sprite['sprite_id']}/{icon['file']}: {e}")
                print(f"  FAIL {icon['file']}: {e}")
                continue
            digest = _ff.sha256(out)
            if record:
                icon["sha256"] = digest
                icon["size_bytes"] = out.stat().st_size
                print(f"  {sprite['sprite_id']}/{icon['file']:<20} {digest[:16]}… recorded")
            elif icon.get("sha256") != digest:
                failures.append(f"{sprite['sprite_id']}/{icon['file']}: sha256 mismatch")
                print(f"  MISMATCH {icon['file']}")
            else:
                print(f"  {sprite['sprite_id']}/{icon['file']:<20} ok ({out.stat().st_size} B)")
    if record:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"wrote hashes into {MANIFEST}")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(" ", f)
        return 1
    return 0


def do_sheet(sprite, out_dir, record):
    """A sprite published only as a built sheet: fetch the sheet, then cut it up.

    The SVGs are generated, not downloaded, so what gets hashed here is the sheet --
    the thing upstream actually publishes and the thing that would change if GSI
    redrew an icon.
    """
    failures = []
    sheet_dir = out_dir.parent / f".{sprite['sprite_id']}-sheet"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    for part in sprite["sheet"]:
        out = sheet_dir / part["file"]
        try:
            _ff.fetch(_ff.raw_url(part["source"]), out)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{sprite['sprite_id']}/{part['file']}: {e}")
            print(f"  FAIL {part['file']}: {e}")
            continue
        digest = _ff.sha256(out)
        if record:
            part["sha256"] = digest
            part["size_bytes"] = out.stat().st_size
            print(f"  {sprite['sprite_id']}/{part['file']:<12} {digest[:16]}… recorded")
        elif part.get("sha256") != digest:
            failures.append(f"{sprite['sprite_id']}/{part['file']}: sha256 mismatch")
            print(f"  MISMATCH {part['file']}")
        else:
            print(f"  {sprite['sprite_id']}/{part['file']:<12} ok ({out.stat().st_size:,} B)")
    if not failures:
        names = [p["file"] for p in sprite["sheet"]]
        sheet_json = sheet_dir / next(n for n in names if n.endswith(".json"))
        sheet_png = sheet_dir / next(n for n in names if n.endswith(".png"))
        rc = subprocess.run([sys.executable, str(HERE / "build-sprite-from-sheet.py"),
                             str(sheet_json), str(sheet_png), str(out_dir)])
        if rc.returncode != 0:
            failures.append(f"{sprite['sprite_id']}: build-sprite-from-sheet.py failed")
    return failures


def do_check():
    manifest = json.loads(MANIFEST.read_text())
    rc = 0
    for sprite in manifest["sprites"]:
        for icon in sprite.get("icons", []) + sprite.get("sheet", []):
            src = icon["source"]
            out = subprocess.run(
                ["gh", "api", "-X", "GET", f"repos/{src['repo']}/commits",
                 "-f", f"path={src['path']}", "-f", "per_page=1",
                 "--jq", '.[0] | .sha + " " + .commit.committer.date'],
                capture_output=True, text=True).stdout.strip().split(" ")
            sha, date = (out + ["?", "?"])[:2]
            state = "current" if sha == src["ref"] else f"UPSTREAM MOVED to {sha[:12]} ({date})"
            if "MOVED" in state:
                rc = 1
            print(f"{sprite['sprite_id']}/{icon['file']:<20} {state}")
    return rc


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        sys.exit(do_check())
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(do_fetch(args[0], "--record" in args))
