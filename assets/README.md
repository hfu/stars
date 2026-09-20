# assets/ — things stars serves that someone else made

Until 2026-09-20 every style on stars fetched its glyphs (and some its sprites) from
somebody else's web server. The tiles were ours; the labels were on loan. If
`gsi-cyberjapan.github.io` or `tile.openstreetmap.jp` went away — or simply changed a
path — maps served from stars would render without text, and nothing here would have
warned us.

This directory is the record of moving those pieces onto stars without losing track of
where they came from.

## The rule

**Copy the source, not somebody's build, and keep the receipt.**

For fonts that means: fetch the font files (OFL / Unlicense — redistributable, with the
licence texts kept in [licenses/](licenses/)) and let Martin generate the glyph PBFs on
request. We do not mirror anyone's rendered glyphs. Each file is pinned in
[fonts.json](fonts.json) to an upstream commit or release tag, recorded with its sha256
and size, and carries the licence it ships under, the attribution line it requires, and
the styles and font names that depend on it.

A copy without that record is worse than the link it replaced: it looks self-sufficient
while quietly going stale.

## Using it

```bash
python3 assets/fetch-fonts.py /path/to/dest      # download + verify against fonts.json
python3 assets/fetch-fonts.py /path/to/dest --record   # re-record hashes (new font / moved pin)
python3 assets/fetch-fonts.py --check            # ask upstream whether the pins are current
```

`--check` needs `gh`; it prints one line per font and exits non-zero if any pin has moved.
A moved pin is not a failure — it is a prompt to look at what changed and decide whether
to follow. Upstream is the authority on the font; we are the authority on when stars
takes a new version of it.

Production install path is `/home/stars/fonts`; Martin's `fonts.paths` points there
(`config/martin.yaml`) and serves `https://stars.optgeo.org/font/{fontstack}/{range}` —
no `.pbf` suffix, unlike the hosts this replaced.

Sprites work the same way ([sprites.json](sprites.json), `assets/fetch-sprites.py`,
installed under `/home/stars/sprites/<id>/`): Martin builds the sheet from SVG sources at
startup and serves `/sprite/<id>.json|.png` plus the `@2x` pair. **`sprites.paths` takes
one directory *per sprite*, and the directory's own name becomes the sprite id** — point
it at a parent and you get `/sprite/sprites` with icons named `positron/circle-11`, which
is how the first deploy went before it was corrected.

## Font names changed with the move

Martin names a font from the file's own family and style, which is not always what the
previous host called it. Styles in this repo were updated to match:

| was | now | why |
|---|---|---|
| `NotoSansJP-Regular` | `Noto Sans JP Regular` | GSI's glyph directory naming vs. the font's own name |
| `NotoSerifJP-SemiBold` | `Noto Serif JP SemiBold` | same |
| `Open Sans Semibold` | `Open Sans SemiBold` | the font calls its style `SemiBold` |

Downstream consumers that substitute their own glyph host (e.g. `dwg7/kaga0`, which runs
these styles offline) need the same names available locally, or their labels disappear.

## What is still on loan

- `styles/std.json` draws GSI's raster tiles directly. That style exists to show GSI's
  service, so the dependency is the point, not a defect.
- The GSI sprite (`optimal_bvmap/sprite/std`) is published as a built PNG + JSON with no
  SVG sources, and Martin's sprite support takes SVG. Still to be decided.
- ~~The positron sprite~~ — done 2026-09-20: two SVG icons, BSD-3-Clause, now
  `/sprite/positron`. Upstream's published sheet held exactly those two icons, which is
  also all the style asks for, so nothing was lost in the move.

The dashboard's 諸元 → styles panel counts these; the number there is the honest measure
of how much of stars stands on its own.
