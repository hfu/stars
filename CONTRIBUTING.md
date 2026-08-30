# Contributing to stars

This repo gatekeeps two kinds of production assets for `stars.optgeo.org`. If you're a
Claude Code session (or a human) that found an issue while consuming a `stars`-served map
or tile source — e.g. tuning a style on real hardware, like the `dwg7/kaga0` appliance
project did — this is how to get a fix upstreamed instead of only patching your own local
copy.

See [CLAUDE.md](CLAUDE.md) and [docs/KNOWN_FACTS.md](docs/KNOWN_FACTS.md) for the full
operational picture; this file only covers the contribution path.

## What you can PR

| Path | What it is | Deploy needs |
|---|---|---|
| [`styles/*.json`](styles/) | MapLibre style JSON served at `stars.optgeo.org/style/<id>` | No Martin restart |
| [`config/martin.yaml`](config/martin.yaml) | Martin's tile-source/style config, mirrors `/home/stars/.config/martin/config.yaml` exactly | Martin restart (brief full outage) |

Both are the canonical, versioned copies — treat them as the source of truth, not
production's live files.

## What you can't PR

- **pmtiles/COG data files.** Too large for GitHub (production sources run from tens of MB
  to hundreds of GB). If your fix needs a new or changed data file, say so in an issue or
  when reaching out to the gatekeeper session directly — the file transfer happens
  out-of-band (rsync/scp), separate from the config change that references it.
- **Fonts/sprites.** As of 2026-08-30, `stars` doesn't self-host any — every style
  references third-party glyph/sprite URLs (GSI, OSM Japan). A font/sprite *reference*
  change is just a URL edit inside a `styles/*.json` file, already covered above.

## How to submit

1. Open a PR against `hfu/stars` touching only the file(s) your fix actually needs.
2. Keep the diff scoped tightly to the described change — don't bundle unrelated edits.
   Reviews check that the diff matches the PR description; an unexplained extra hunk will
   hold up the merge.
3. In the PR description, say what the problem was and how you validated the fix (e.g.
   "tested on kaga's 1440p display, onsen icon no longer dominates at z10-11").
4. For a `config/martin.yaml` change that references a file under
   `/home/stars/data/`, make sure that file already exists on production (or say clearly
   that it doesn't yet, so the gatekeeper can coordinate the transfer before merging).

## What happens after you open a PR

The gatekeeper session verifies the diff itself — via `gh pr diff`/`gh pr checkout`, not
by trusting the PR description — checking that only the expected file(s) changed, every
hunk matches what's described, syntax is valid, and (for config changes) any referenced
data file actually exists on production. See CLAUDE.md's "PR review checklist and
escalation rules" for the exact steps. A diff that includes anything unexplained gets
escalated to the user rather than merged.

Once merged, it deploys to production: backup the target file → copy the merged version
over → verify checksums → confirm the change is live (cache-busted `curl`) → restart
Martin if the change was to `config/martin.yaml` → delete the backup. You'll get a report
back once it's live.

## Precedent

- [PR #1](https://github.com/hfu/stars/pull/1) — VBM label text-size and onsen icon-size
  fixes (`styles/vbm.json`), the first exercised instance of this workflow.
- [PR #2](https://github.com/hfu/stars/pull/2) — VBM road line-width thinning
  (`styles/vbm.json`).
- [PR #3](https://github.com/hfu/stars/pull/3) — staggered 35 VBM point/symbol/line
  layers' `minzoom` across z10-14 instead of 38 layers appearing simultaneously at z11
  (`styles/vbm.json`). The largest PR under this workflow so far (35 layers across 5
  logical groups, reviewed value-by-value against the PR's own before/after table) and
  the first exercised under the `dwg7/kaga0` design-master division of labor: their local
  copy is a mechanical path substitution on top of what's merged here, not an independent
  fork — design changes land here first.
