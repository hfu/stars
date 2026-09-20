#!/usr/bin/env python3
"""Rebuild a sprite published only as a built sheet into SVG sources Martin can serve.

The other assets here are copied from their sources. This one cannot be: GSI publishes
the sprite only as a built sheet (`std.png` + `std.json`), and Martin's sprite support
takes SVG. So each icon is cut out of the sheet at the coordinates GSI's own JSON gives
and wrapped in an SVG that embeds those exact pixels — a mechanical re-cut of GSI's
artwork, not a redrawing of it. Every pixel served is GSI's; use is under the 国土地理院
コンテンツ利用規約 with attribution (see assets/sprites.json).

None of the 119 icons is an SDF icon (checked: no `sdf` flag anywhere in std.json), so
nothing depends on the glyph-style recolouring that a raster wrap would break.

Upstream's `std@2x.png` is byte-for-byte the 1x sheet and its `@2x.json` declares
pixelRatio 1, so upstream has no high-resolution artwork and a retina client following it
draws the icons at double size. Martin generates a real @2x from these SVGs: upscaled
pixels (no new detail — there is none to be had) but with pixelRatio 2 declared, so the
icons come out the intended size. That is a deliberate difference from upstream, not a
mismatch.

Used for GSI's optimal_bvmap sprite and for derivatives of it (dwg7/bvmap's greyscale
`bvmap-starlight`), which are published the same way.

Usage:
  build-sprite-from-sheet.py <sheet.json> <sheet.png> <dest-dir>
"""
import base64
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # keep the failure legible: this is the one asset tool needing Pillow
    sys.exit("this script needs Pillow (python3 -m pip install pillow); the other asset "
             "tools are stdlib-only")


def build(sheet_json, sheet_png, dest_dir):
    dest_dir = Path(dest_dir)
    meta = json.loads(Path(sheet_json).read_text())
    sheet = Image.open(sheet_png).convert("RGBA")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("*.svg"):
        old.unlink()

    for name, m in sorted(meta.items()):
        w, h = m["width"], m["height"]
        icon = sheet.crop((m["x"], m["y"], m["x"] + w, m["y"] + h))
        png = dest_dir / f".{name}.png.tmp"
        icon.save(png, format="PNG", optimize=True)
        data = base64.b64encode(png.read_bytes()).decode("ascii")
        png.unlink()
        # A single <image> at natural size: resvg (Martin's renderer) draws embedded
        # rasters, so the sheet Martin builds carries GSI's pixels unchanged at 1x.
        (dest_dir / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<title>{name}</title>'
            f'<image width="{w}" height="{h}" xlink:href="data:image/png;base64,{data}"/>'
            f"</svg>\n"
        )
    print(f"wrote {len(meta)} SVGs to {dest_dir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(build(sys.argv[1], sys.argv[2], sys.argv[3]))
