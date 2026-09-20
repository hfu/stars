#!/usr/bin/env python3
"""Fetch the fonts listed in assets/fonts.json, verifying each against its recorded hash.

Why this exists: stars' map styles used to pull their glyphs from two third-party hosts
(gsi-cyberjapan.github.io and tile.openstreetmap.jp). If either goes away, labels stop
rendering. Martin can serve glyphs itself from font files, so we host the fonts — but a
copy with no record of where it came from is worse than a link, so every file is pinned
to an upstream commit or release tag and checked by hash.

We copy the *fonts* (OFL / Unlicense, redistributable), never anyone's rendered glyph
PBFs, and Martin regenerates the glyphs on request.

Usage:
  fetch-fonts.py <dest-dir>            download and verify against recorded sha256
  fetch-fonts.py <dest-dir> --record   download and write the hashes into the manifest
                                       (for adding a font or moving a pin)
  fetch-fonts.py --check               ask upstream whether the pins are still current
                                       (no download; needs `gh`)

Stdlib only: this has to run on the Pi as well as on a laptop.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "fonts.json"
UA = "stars-assets/1.0 (+https://github.com/hfu/stars)"


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def raw_url(src):
    return (f"https://raw.githubusercontent.com/{src['repo']}/{src['ref']}/"
            + urllib.parse.quote(src["path"]))


def release_url(src):
    return (f"https://github.com/{src['repo']}/releases/download/"
            f"{urllib.parse.quote(src['tag'])}/{urllib.parse.quote(src['asset'])}")


def member_from_zip(zip_path, member, dest):
    """Pull one file out of a release zip.

    The CJK release zips carry several weights; we serve one or two of them, so the
    whole archive is downloaded and the wanted member extracted. Matching is on the
    trailing path so a changed top-level folder name doesn't break the fetch silently --
    an ambiguous or missing match raises instead.
    """
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(member) or n.endswith(Path(member).name)]
        exact = [n for n in names if n.endswith(member)]
        names = exact or names
        if len(names) != 1:
            raise RuntimeError(f"{member}: expected one match in {zip_path.name}, got {names}")
        with z.open(names[0]) as src, open(dest, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)


def do_fetch(dest_dir, record):
    manifest = json.loads(MANIFEST.read_text())
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zips = {}
        for font in manifest["fonts"]:
            out = dest_dir / font["file"]
            src = font["source"]
            try:
                if src["kind"] == "github_raw":
                    fetch(raw_url(src), out)
                elif src["kind"] == "github_release_zip":
                    key = (src["repo"], src["tag"], src["asset"])
                    if key not in zips:
                        zips[key] = tmp / src["asset"]
                        print(f"  downloading {src['asset']} ...", flush=True)
                        fetch(release_url(src), zips[key])
                    member_from_zip(zips[key], src["member"], out)
                else:
                    raise RuntimeError(f"unknown source kind {src['kind']}")
            except (urllib.error.URLError, RuntimeError, OSError) as e:
                failures.append(f"{font['file']}: {e}")
                print(f"  FAIL {font['file']}: {e}")
                continue

            digest = sha256(out)
            if record:
                font["sha256"] = digest
                font["size_bytes"] = out.stat().st_size
                print(f"  {font['file']:<28} {digest[:16]}… {out.stat().st_size:>9,} B  recorded")
            elif font.get("sha256") != digest:
                failures.append(f"{font['file']}: sha256 mismatch "
                                f"(manifest {font.get('sha256', '-')[:16]}…, got {digest[:16]}…)")
                print(f"  MISMATCH {font['file']}")
            else:
                print(f"  {font['file']:<28} ok  ({out.stat().st_size:>9,} B)")

    if record:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"wrote hashes into {MANIFEST}")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(" ", f)
        return 1
    print(f"\n{len(manifest['fonts'])} fonts in {dest_dir}")
    return 0


def do_check():
    """Report whether each pin is still what upstream serves as current.

    A pin going stale is not an error -- it is a prompt to look at what changed upstream
    and decide. Release-zip pins are compared against the newest release whose tag starts
    the same way (Sans…/Serif…), which is how the Noto CJK project versions them.
    """
    manifest = json.loads(MANIFEST.read_text())
    seen = {}
    rc = 0
    for font in manifest["fonts"]:
        src = font["source"]
        if src["kind"] == "github_raw":
            key = (src["repo"], src["path"])
            if key not in seen:
                out = subprocess.run(
                    ["gh", "api", "-X", "GET", f"repos/{src['repo']}/commits",
                     "-f", f"path={src['path']}", "-f", "per_page=1",
                     "--jq", '.[0] | .sha + " " + .commit.committer.date'],
                    capture_output=True, text=True).stdout.strip()
                seen[key] = out.split(" ") if out else ["?", "?"]
            sha, date = seen[key]
            state = "current" if sha == src["ref"] else f"UPSTREAM MOVED to {sha[:12]} ({date})"
        elif src["kind"] == "github_release_zip":
            prefix = "".join(c for c in src["tag"] if not c.isdigit() and c != ".")
            key = (src["repo"], prefix)
            if key not in seen:
                out = subprocess.run(
                    ["gh", "api", f"repos/{src['repo']}/releases", "--jq",
                     f'[.[] | select(.tag_name | startswith("{prefix}"))][0].tag_name'],
                    capture_output=True, text=True).stdout.strip()
                seen[key] = [out or "?", ""]
            latest = seen[key][0]
            state = "current" if latest == src["tag"] else f"UPSTREAM MOVED to {latest}"
        else:
            state = "unknown source kind"
        if "MOVED" in state:
            rc = 1
        print(f"{font['martin_name']:<26} {font['file']:<28} {state}")
    return rc


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        sys.exit(do_check())
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(do_fetch(args[0], "--record" in args))
