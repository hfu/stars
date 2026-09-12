# Known Facts

This document has two parts. Section A is what's confirmed true of production
(`stars.optgeo.org` / `spacex.optgeo.org`) — treat it as authoritative over anything in
Section B or in other docs in this repo. Section B is the target design this repo was
originally written to describe, most of which has not been implemented.

Section A is compacted periodically (most recently 2026-09-05) by folding resolved
"correction chains" into single current statements once they're no longer actively
useful history. New facts that turn out wrong should still be corrected by *appending* a
correction rather than silently rewriting — compaction is an occasional cleanup pass, not
a change to that ongoing convention.

## A. Confirmed Facts About Current Production

### Host and access
- Public hostname `stars.optgeo.org` and the SSH-reachable host `spacex.optgeo.org` are
  the same physical machine.
- SSH access lands directly as the `stars` user (a regular sudo-capable login user, not a
  nologin system account).

### No repo checkout in production
- `/opt/stars` exists but is an **empty directory owned by root**, untouched since
  creation. It is not a git repository — this repo (`hfu/stars`) has never been cloned
  onto this host, and there's no other checkout of it under `/home/stars` either.
  (`/home/stars/martin` **is** a git checkout, but of upstream
  `https://github.com/maplibre/martin.git`, used to build the Martin binary — unrelated
  to this repo.)
- GitHub `origin` (`git@github.com:hfu/stars`), by contrast, is fully up to date:
  README.md, docs/, systemd/, .github/, .gitignore, `styles/*.json`,
  `config/martin.yaml`, and CONTRIBUTING.md are all pushed to `main`. Production itself
  remains un-checked-out regardless — GitHub state and host state are independent facts.

### Martin
- Supervised by a working, `enabled` **user-level** systemd unit
  (`/home/stars/.config/systemd/user/martin.service`, `systemctl --user status martin`,
  `WantedBy=default.target`, `Restart=on-failure`) — this is the intended way to run
  Martin, not a raw background process.
- **Known failure mode:** `Restart=on-failure` only fires on a non-zero exit or signal
  death. Killing the systemd-managed process directly with a bare `kill`/`pkill` makes it
  exit cleanly (status 0) — systemd logs this as an intentional stop and does **not**
  restart it, leaving `systemctl --user status martin` stuck showing `inactive (dead)`
  even if someone relaunches it by hand (`nohup`/`setsid nohup`) afterward, since that
  doesn't restore systemd supervision. This has happened twice. **Correct procedure:**
  always use `systemctl --user stop/start/restart martin`, never a bare kill, even just
  to pick up a config change. If Martin must be killed directly for some reason, follow
  up with `systemctl --user start martin` (not a raw relaunch) to restore supervision.
- `loginctl enable-linger stars` has been run (self-linger, no sudo needed) —
  `Linger=yes` confirmed, so `martin.service` starts automatically at boot even with no
  `stars` login session (not yet verified against an actual reboot).
- Binary: `/home/stars/.local/bin/martin`, version **1.14.0** (upgraded from 1.10.1 via
  the official prebuilt `martin-aarch64-unknown-linux-gnu` release binary — checksum
  verified, no rebuild needed, install method unchanged: a raw binary, not
  package-managed). **`unstable-cog` remains a non-default, opt-in Cargo feature even in
  1.14.0** (confirmed against upstream's `Cargo.toml`) — COG is not served in production,
  and upgrading Martin's version alone doesn't change that; a separate
  `--features=unstable-cog` build would be needed. Also picked up in the 1.14.0 upgrade:
  filesystem-watch live-reload for local PMTiles/COG sources (upstream since v1.11.0, see
  below), and two security fixes (a `rendering`-only render-worker crash — not
  applicable, rendering is disabled; and a sprite-id amplification DoS — not currently
  exploitable, no `sprites:` sources are configured, but worth having patched anyway).
- Config: `/home/stars/.config/martin/config.yaml` (not `/opt/stars/config/martin.yaml`).
  Combines directory auto-discovery (`pmtiles.paths: [/home/stars/data]`, publishing
  every `*.pmtiles` file under a source ID derived from the filename) with explicit
  `sources:` entries for custom IDs/remote URLs (`bvmap`, `openstreetmap_jp_planet`, the
  `overture_*` Overture Maps mirrors, and others — see [config/martin.yaml](../config/martin.yaml),
  the canonical tracked copy, for the current full list). Also declares `styles.paths`
  pointing at `/home/stars/styles`, mirrored by this repo's [styles/](../styles/)
  directory. A timestamped backup is kept alongside on each edit
  (`config.yaml.bak.<timestamp>`, deleted once the change is verified live).
  - **Directory scan behavior, confirmed by reading Martin's source**
    (`martin-core/src/resources/walk.rs`, `walk_files`): the `pmtiles.paths` scan is
    **recursive** (walks subdirectories) but **strict-extension-filtered** (exact,
    case-sensitive match on `.pmtiles` only — everything else is silently skipped, not an
    error). So non-pmtiles data (e.g. 3D Tiles: `.glb`/`.json`/`.subtree`) can safely
    share a subdirectory under `/home/stars/data` without being picked up. Since the
    directory is also watched for filesystem changes (next bullet), uploading many small
    files (e.g. via `rsync`) can trigger repeated rescans mid-transfer — harmless, but
    staging elsewhere and `mv`-ing in as one atomic operation avoids the churn.
  - **Live-reload, confirmed live in production:** Martin's fs-watch reload for local
    PMTiles/COG sources (upstream since v1.11.0) means **swapping an existing pmtiles
    file's content at its already-registered path needs no restart at all** — an atomic
    `scp`-to-`.new`-then-`mv` replacement is picked up within seconds (new
    `minzoom`/`maxzoom`/`bounds` observed in TileJSON without touching the service).
    Registering a **new** source ID in `config.yaml` still needs
    `systemctl --user restart martin` — Martin only discovers the *set* of configured
    sources at startup/config-reload, not by scanning for new config entries live.
  - **`name`/`description`/`attribution` shown in `/catalog` come from the pmtiles file's
    own embedded metadata, not config.yaml** — Martin's `PmtConfig` struct has no
    per-source override field for these (confirmed by reading
    `martin/src/config/file/tiles/pmtiles.rs` upstream). To fix a bad name/description,
    edit the file itself: `pmtiles show --metadata <file>` to dump the current JSON,
    edit it, then `pmtiles edit <file> --metadata=<edited.json>` (the `pmtiles` CLI is at
    `/home/stars/.local/bin/pmtiles`). Picked up live via the same fs-watch reload as
    above — no restart needed, confirmed by testing on `hih-fishfarm-open.pmtiles`
    (2026-09-07). **Caveat: `pmtiles edit` rewrites the entire file**, not just a small
    header patch (confirmed even on a 1.2 MB test file — "writing file 100%") — treat
    this as a full-file operation for sizing/risk purposes, not a lightweight metadata
    tweak. Not viable for very large files (e.g. `kitaphoto17.pmtiles`, 190 GB) without
    healthy disk headroom for the rewrite. It does write to `<file>.tmp` and rename
    rather than editing in place, so an interrupted run leaves the original intact —
    confirmed the hard way on 2026-09-12, when a 13.7 GB rewrite outlived the two-minute
    SSH command timeout. **The remote `pmtiles edit` kept running after the SSH client
    gave up**; the right response was to wait for it, not to re-run or clean up. Budget
    well over two minutes per ~10 GB and run it detached rather than inside a
    timeout-bounded SSH command. (While checking whether it was still alive, `pgrep -f
    'pmtiles edit freetown'` reported it running *after* it had finished — the pattern
    matched the SSH command string doing the checking, exactly the self-match trap noted
    under "Practical implication" below. `ps -eo pid,comm,args | grep '^ *[0-9]* *pmtiles'`
    answers it correctly.) Only works on locally-stored files in the
    first place — sources pointing at a remote URL (`bvmap`, `openstreetmap_jp_planet`,
    `overture_*`) can't be fixed this way at all; `bvmap`'s current `name` (a leaked
    internal file-path concatenation string from GSI's own pipeline) is a known,
    currently-unfixable-from-here defect for exactly this reason.
  - **Gotcha: Martin silently drops `name` from `/catalog` if it equals the source ID.**
    Confirmed in `martin-core/src/tiles/source.rs`:
    `name: tilejson.name.as_ref().filter(|v| *v != id).cloned()`. Hit this directly
    (2026-09-07) setting `kitaphoto`'s embedded name to literally `"kitaphoto"` (matching
    its config.yaml/catalog source ID) — the edit was on disk and correct, but `/catalog`
    kept showing no `name` at all, which looks identical to the edit having silently
    failed or not propagated. It hadn't — the value just needs to differ from the id.
  - **2026-09-07 metadata cleanup**: 23 locally-stored sources' `name`/`description` were
    rewritten from pipeline-default placeholders (`{id}_raw`, or empty) to human-readable
    text, sourced from the contributing projects' own docs (`dwg7/ferspas57` for the 21
    FAO GAEZ/Hand-in-Hand layers, `kitaphoto17-navara-18` for `kitaphoto`,
    `faceless-cartographer-8b`/mapterhorn-japan-bridge for
    `mapterhorn-japan-bridge-lineage`) rather than guessed. Still open: `kitaphoto17.pmtiles`
    (190 GB), and `bvmap` (remote, unfixable from here, see above).
    `mapterhorn-japan-bridge.pmtiles` is now handled upstream — that project's publish
    pipeline sets `name`/`description` itself from 2号 onward (`hfu-mapterhorn` commit
    `010b558`), so no rewrite is needed here; its `pmtiles merge` step carries metadata
    through from the first input.
  - **Beware: a contributor's republish silently wipes metadata set here.** The 2026-09-11
    `mapterhorn-japan-bridge-lineage` replacement dropped the `name`/`description` set on
    2026-09-07, because their pipeline wrote only `attribution`. Re-applied 2026-09-12,
    and the durable fix was upstream (above), not repeated manual edits. For any source a
    contributor republishes on a cycle, get the metadata into *their* pipeline.
  - **2026-09-12, `freetown-mapterhorn`**: identified without an owning project by
    matching the archive against OpenAerialMap directly rather than guessing. Its data
    footprint, probed tile-by-tile at z13, is exactly the OAM record "Freetown Urban with
    Sensitive Areas Blurred" bbox rounded out to tile boundaries (so: one record, not a
    merge), and OAM's own TMS returns the same scene at the same z/x/y. Notable finding
    for anyone else citing OAM: **its top-level `license` field is null on all 30 records
    covering Freetown** — the real value is in `properties.license`, and those disagree
    between neighbouring records of the same programme (`CC-BY 4.0` here vs `CC BY-SA 4.0`
    for `Aberdeen_Freetown`, a materially different licence). `provider` likewise mixes
    orgs, tools, communities, individuals and companies; `contact` is sometimes a tool's
    generic address; some drone flights are tagged `platform: aircraft`. Verify a specific
    record's `properties.license` rather than assuming a programme-wide licence.
- **2026-09-11: `japan-seamless-aerial-z18` and `seamlessphoto512` switched from local
  files to remote Source Cooperative URLs** (`data.source.coop/smartmaps/japan-seamlessphoto/pmtiles/{z18,seamlessphoto512}.pmtiles`
  — same pattern already used by `bvmap`/`openstreetmap_jp_planet`/`overture_*`), and the
  now-redundant local copies (`z18.pmtiles` 424 GB, `seamlessphoto512.pmtiles` 767 GB)
  deleted, freeing `/home/stars/data` from 76% to **13%** used (announced in advance via
  [UNopenGIS/7#999](https://github.com/UNopenGIS/7/issues/999), no objections in the
  comment window). Remote serving confirmed *before* deletion by renaming the local file
  aside and re-testing (not just inferring from timing) — both sources kept serving
  fresh, never-before-requested tile coordinates successfully.
  - **Gotcha hit along the way**: switching `japan-seamless-aerial-z18`'s config value
    from a local path to a remote URL freed up that local file path from being "claimed"
    by an explicit source, so `pmtiles.paths` auto-discovery picked `z18.pmtiles` back up
    as a *separate* bare-id `z18` source (duplicate of `japan-seamless-aerial-z18`,
    same content) until the local file was actually deleted. Registering
    `seamlessphoto512` as an explicit source while the identically-named local file was
    still auto-discovered under the same id did *not* produce a visible duplicate in
    `/catalog` (only one `seamlessphoto512` entry ever showed) — the explicit entry won
    the id collision silently; confirmed by the same rename-and-retest method, not by
    trusting that just because only one entry was visible.
- Data lives at `/home/stars/data`, currently a few hundred GB (13% used as of
  2026-09-11, see above) across pmtiles files from various consumer projects — sizes
  worth knowing: `kitaphoto17.pmtiles` 190 GB, `mapterhorn-japan-bridge.pmtiles` 315 GB
  (confirmed 2026-09-07, it's actually the 1.5号 archive despite the stable filename).
  `abidjan.tif` (COG) has not been deployed — still no COG support in the production
  Martin build.
  - Disk usage moves day to day (files get added/removed regularly) — always re-check
    with `df -h` rather than trusting a previously-recorded percentage.
  - **Trusted contributors can have their own direct SSH/scp access to
    `/home/stars/data`**, bypassing the gatekeeper's own file-transfer step — confirmed
    with the user (`dwg7/ferspas57` is one such case): pmtiles files can be too large for
    gatekeeper-mediated transfer to scale to every case. This doesn't change who
    gatekeeps `config.yaml`/`styles/*.json` (still this session, via PR) — but don't
    assume the directory's contents only ever change via this session's own transfers.
- Log: `/home/stars/martin.log` (plain redirected stdout, not journald) — mostly
  historical now that the service runs under proper systemd supervision. Request-level
  text logging via `RUST_LOG` is not currently configured (unset in the systemd unit), so
  `journalctl --user -u martin` retains zero entries.
- **Prometheus metrics endpoint, confirmed live in production (2026-09-06):** `/_/metrics`
  (not `/metrics` — that 404s) returns HTTP 200 with real counters
  (`curl https://stars.optgeo.org/_/metrics`), even though this is gated behind a
  non-default upstream Cargo feature (`metrics`) with no flag or note anywhere in this
  repo — the prebuilt 1.14.0 release binary apparently already has it built in. Exposes
  `martin_http_requests_total` / `martin_http_requests_duration_seconds` (labeled by
  **route pattern**, e.g. `/{source_ids}/{z}/{x}/{y}`, plus method/status — **not** by
  concrete source ID) and `martin_tile_cache_requests_total` /
  `martin_cache_requests_total` (pmtiles-directory cache hit/miss, broken down by zoom
  level). Counters reset on every Martin restart. No per-source-id breakdown is available
  from this endpoint as shipped; Martin's own changelog explicitly invites metric feature
  requests upstream. Being origin-side, these metrics (like any Martin-side logging) only
  see Cloudflare edge-cache **misses** — a tile response served straight from Cloudflare's
  edge cache (see cloudflared section below) never reaches Martin and is invisible here;
  real end-user demand for a popular/cached tileset can't be measured this way.

### cloudflared
- Managed by systemd (`cloudflared.service`, real, `enabled`, long-running) — the one
  piece of the target design that actually matches reality in shape.
- Config: `/etc/cloudflared/config.yml` (root-owned, needs `sudo`) — not
  `/opt/stars/config/cloudflared/config.yaml`. Credentials:
  `/home/stars/.cloudflared/<uuid>.json` — not
  `/opt/stars/secrets/cloudflared/<uuid>.json`.
- **The tunnel is shared across multiple projects, not dedicated to stars.** Ingress
  rules route `spacex.optgeo.org` → `ssh://localhost:22`, `stars.optgeo.org` →
  `http://localhost:3000` (Martin), and `depot.optgeo.org` → `http://localhost:8080` (a
  separate service — do not assume changes here are stars-only). Restarting
  `cloudflared.service` affects all three simultaneously.
- **`depot.optgeo.org` (`:8080`), confirmed via `/etc/caddy/Caddyfile`** (world-readable,
  no sudo needed): a plain Caddy `file_server browse` with `root * /home/stars/data` and
  permissive CORS (`Access-Control-Allow-Origin *`) — i.e. it's a raw directory
  listing/download of the **exact same** directory Martin scans for pmtiles. Dropping a
  file there makes it both raw-downloadable via `depot.optgeo.org/<path>` and (if it's a
  `.pmtiles` file) auto-discovered by Martin — the two aren't independent. Caddy itself
  correctly honors HTTP Range requests even for very large files (tested up to 424 GB via
  direct-to-origin access), **but Cloudflare's proxy silently drops Range support for
  large files served through the public domain** — confirmed empirically: a 190 GB file
  got a correct `206 Partial Content` through the public URL, a 424 GB file got `200`
  (full content) instead. The exact size threshold is somewhere between those two and
  hasn't been pinned down further. This matters for anyone planning to have a browser
  make direct range-based reads (e.g. a COG reader) against a large file hosted here —
  Martin-mediated pmtiles serving is unaffected, since Martin does the range reading
  server-side and returns ordinary tile responses to the client either way.
- Installed version **2026.8.2** (upgraded from 2026.6.0 via Cloudflare's official apt
  repository — `/etc/apt/sources.list.d/cloudflared.list`,
  `sudo apt-get install --only-upgrade cloudflared`), confirmed live via `cloudflared
  --version` and a successful `systemctl restart cloudflared.service` (tunnel
  reconnected, all 4 connections re-registered).
- Cloudflare edge-caches `/catalog`, style/tile responses, and other GETs for up to 4
  hours (`cache-control: max-age=14400`). After restarting Martin or changing sources,
  verify with a cache-busting query string (`curl
  https://stars.optgeo.org/catalog?cb=$(date +%s)`) — an unbusted request can return
  stale pre-change content for up to 4 hours (`cf-cache-status: HIT`).

### Style.json gatekeeper workflow

- This repo's [styles/](../styles/) directory is the canonical, versioned source for
  production's `/home/stars/styles/*.json`. Contributors PR against `styles/*.json`
  here; this session reviews, merges, and deploys. See
  [CONTRIBUTING.md](../CONTRIBUTING.md)'s Precedent list for the full history of PRs
  under this workflow (`dwg7/kaga0`'s VBM/VLCM zoom-tier redesign, `dwg7/height-coverage`'s
  Positron basemap, `dwg7/zukaku`'s GSI std raster style, `dwg7/vientiane-planning-map`'s
  zoning overlay, and others) — `dwg7/kaga0` in particular treats `hfu/stars` as the
  design master for VBM/VLCM, keeping only a mechanical path-substitution diff locally.
- The public style-serving endpoint is `stars.optgeo.org/style/<id>` (e.g.
  `/style/vbm`) — **not** `/styles/<id>.json`, which 301-redirects.
- Martin serves style files straight off disk per request. **Replacing an *existing*
  style file's content needs no restart** — takes effect immediately on the next
  request. **Adding a brand-new style file does need a restart**
  (`systemctl --user restart martin`) before it's reachable — Martin only discovers the
  *set* of available style IDs by scanning `styles.paths` at startup (confirmed via
  `styles/positron.json` 404ing until restarted). Same same-file/new-file split as
  pmtiles sources above.
- Deploy sequence: back up the target file → copy the merged file over → verify
  checksums match → confirm live via a cache-busted `curl` against the `style/<id>`
  endpoint → delete the backup once confirmed.

### config.yaml gatekeeper workflow

- [config/martin.yaml](../config/martin.yaml) is the canonical, tracked mirror of
  `/home/stars/.config/martin/config.yaml`.
- Treated as **higher-risk than styles/**, with a stricter review bar:
  - A config.yaml PR that adds a `pmtiles_foo: /home/stars/data/foo.pmtiles`-style entry
    is only valid if `foo.pmtiles` already exists at that exact path on production — the
    file itself can't ride along in a GitHub PR (too large). **Verify the referenced
    file exists via SSH before merging.**
  - A bad config.yaml (syntax error, wrong path) can stop Martin from serving *every*
    source, not just degrade one layer's look the way a bad style.json would — validate
    YAML before merging, and don't apply the same "diff matches description → merge" bar
    used for styles/.
- Deploying a config.yaml change **requires a Martin restart** only when registering a
  *new* source ID (swapping existing content at an already-registered path doesn't — see
  the Martin section above). Sequence: back up
  `/home/stars/.config/martin/config.yaml` → copy the merged file over → verify
  checksums → get explicit user confirmation before restarting (this briefly takes down
  all tile serving) → restart → verify via cache-busted `curl .../catalog` → delete the
  backup.

### Monitoring dashboard (added 2026-09-06/07)
- `monitoring/collect.py` (GitHub Actions, cron every 10 min, see
  `.github/workflows/monitoring.yml`) scrapes Martin's `/_/metrics` endpoint (see above)
  and `https://depot.optgeo.org/host-status.json`, and appends one row to
  `telemetry/uptime.jsonl` on the `gh-pages` branch (capped at 12,000 lines, ~83 days at
  this cadence). The dashboard (`monitoring/dashboard/index.html`, a real Open MCT
  object/view loaded from the unpkg CDN, custom SVG panels rather than the stock Plot
  view per `dwg7/m3xx-fleet-ops`'s implementation notes) is synced to the same branch and
  served at `https://hfu.github.io/stars/`.
- **Specs snapshot (added 2026-09-11)**: `monitoring/collect-specs.py` runs daily at
  **19:00 UTC / 04:00 JST** (`.github/workflows/specs.yml`) and writes
  `specs/specs.json` + an append-only `specs/changes.jsonl` to `gh-pages`, surfaced as a
  「諸元」folder in the dashboard. Separate cadence from telemetry on purpose: 41 TileJSON
  + 7 style fetches every 10 minutes would be ~7k pointless origin requests/day. It
  captures three things nothing else does:
  - **Per-dataset provenance from TileJSON** — builder and version (`tippecanoe`,
    `tile-join`, `planetiler:version`/`buildtime`/`githash`) and, for
    `openstreetmap_jp_planet`, `planetiler:osm:osmosisreplicationtime` (i.e. how stale
    the OSM extract is).
  - **Repo-vs-production style drift** — hashes `styles/*.json` here against what
    `/style/<id>` actually serves, making the CLAUDE.md gatekeeper invariant
    (repo is canonical, production is the deploy target) continuously checked rather
    than checked by hand. Verified working; all 7 matched at first run.
  - **Catalog-vs-disk reconciliation** — cross-checks Martin's catalog against
    `host-inventory.json` (below), in both directions (configured but no file on disk /
    file on disk that nothing serves).
    - **Known blind spot, found immediately in practice:** this check cannot see an
      *auto-discovered* source vanishing, because when its file goes away the source
      disappears from the catalog at the same moment — so both sides agree and the
      reconciliation reports "clean". `mapterhorn-japan-bridge.pmtiles` going missing on
      2026-09-11 was in fact caught by the **snapshot diff** (`dataset_removed` in
      `changes.jsonl`), not by reconciliation. Only explicitly-registered sources are
      protected by reconciliation itself.
    - That particular disappearance turned out to be a **publish in progress**, not a
      deletion: `dwg7/mapterhorn-japan-bridge` was mid-transfer of a new 258 GB archive,
      staged as a dotfile (`.mapterhorn-japan-bridge.pmtiles.new.<rand>`) — invisible
      both to Martin's `*.pmtiles` scan and to `host-inventory.sh`'s own glob. Verified
      independently via SSH rather than taken on the peer's word. Their publish script
      deleted the old archive *before* transferring the new one (a leftover from when
      stars had no headroom); with 1.5 TB now free they've switched to
      transfer-then-swap (their D159/D160), so this gap shouldn't recur. **When a large
      source vanishes, check for a staged dotfile before concluding it was deleted.**
  - Caution when reading it: a dataset with no stars-hosted style is **not** unused —
    only 5 of 41 are dressed in a stars-hosted style, and the rest are consumed by
    external projects shipping their own. The view is worded to avoid that misreading;
    keep it that way.
- **`host-inventory.service`/`host-inventory.timer` (added 2026-09-11)**: hourly
  user-level timer running `/home/stars/.local/bin/host-inventory.sh`, writing the
  `*.pmtiles` file inventory (name/size/mtime, ~3 KB) to
  `/home/stars/data/host-inventory.json` for the daily specs collector to read via
  `depot.optgeo.org`. Deliberately separate from `host-status.sh` (every 2 min): this
  payload is larger and changes rarely, and it must **not** be folded into
  `uptime.jsonl`'s per-row telemetry (12,000 rows × ~3 KB would be tens of MB in git).
- **Two dashboard gotchas found while verifying the specs views on the live site**
  (2026-09-11), both of which had been silently wrong before anyone looked closely:
  - **Open MCT rewrites a view container's `className`** (to add
    `is-object-type-<type>`), which silently drops any class the view adds to that
    element in `show()`. The dashboard's own CSS had therefore never actually applied in
    production — what looked "styled" was Open MCT's theme plus browser defaults. Scope
    custom styles with a wrapper `<div>` the view owns, not by classing the container.
  - **`fetch(..., {cache: "no-store"})` only bypasses the *browser* cache, not the CDN.**
    GitHub Pages served a `404` that its CDN had captured during the window between a
    `gh-pages` push and the Pages deploy finishing, so the specs view kept reporting
    "specs fetch failed: 404" well after the file was live. Cache-bust data fetches with
    a query string, exactly as required against `stars.optgeo.org` (see cloudflared
    section). Note Pages also sends `cache-control: max-age=600` on `index.html` itself,
    so a browser can keep running the previous dashboard build for up to 10 minutes
    after a deploy — expected, not a bug, but it makes "did my fix deploy?" checks
    misleading unless the URL is varied.
- **Cloudflare 403s requests with Python's default `urllib` User-Agent** (curl is fine).
  Any collector must send an explicit `User-Agent` — hit this while surveying TileJSON
  endpoints, where all 41 returned `403 Forbidden` until a UA header was added.
- **`host-status.service`/`host-status.timer`, confirmed live in production**: unlike
  every other file in [systemd/](../systemd/) (which is target-design only, see Section
  B), these two **are** actually deployed — user-level units
  (`/home/stars/.config/systemd/user/host-status.{service,timer}`), running
  `/home/stars/.local/bin/host-status.sh` every 2 minutes. The script snapshots
  uptime/load average/temperature (`vcgencmd measure_temp` — confirmed available; this
  host is a real Raspberry Pi 4 Model B, not just aarch64 in the abstract) and
  `/home/stars/data` disk headroom into `/home/stars/data/host-status.json` (atomic
  write-then-`mv`), which `depot.optgeo.org`'s static file serving then exposes
  automatically — no new Martin/Cloudflare config needed, and no SSH credentials in
  GitHub Actions (a deliberate choice after `dwg7/m3xx-fleet-ops` reported their own
  fleet-status collector runs from a personal machine's `launchd`, SSHing into their
  bastion, specifically because GitHub-hosted Actions runners can't reach either fleet's
  internal network — not viable for stars' design goal of no SSH secrets in CI).
- Gotcha hit while building the collector: Prometheus label values can themselves contain
  literal `{`/`}` (Martin's own `endpoint` label is literally
  `/{source_ids}/{z}/{x}/{y}`) — a naive `\{([^}]*)\}` regex stops at the first `}` inside
  the value itself and silently truncates, not errors. Match greedily through the *last*
  `}` on the line instead.
- Gotcha hit deploying the GitHub Actions workflow: `rsync --delete` deleted the
  `gh-pages` git worktree's `.git` link file on the first two runs (it isn't part of the
  dashboard source being synced in, so `--delete` treated it as cruft to remove) — this
  silently collapsed the worktree back into a plain subdirectory of the main checkout,
  so both commits landed on `main`'s own tree instead of an isolated `gh-pages` branch.
  Fixed by adding `--exclude '.git'` alongside the existing `--exclude 'telemetry'`.

### Practical implication for future changes
- Restarting the Martin process affects only `stars.optgeo.org` (nothing else routes to
  port 3000).
- Restarting `cloudflared.service` affects `stars.optgeo.org`, `depot.optgeo.org`, and
  SSH routing over the tunnel simultaneously — treat it as shared-infrastructure change,
  not a stars-only action.
- Restart gotcha: kill the Martin PID **by exact number**, not via `pgrep -f
  "martin ..."` run inside the same SSH command string — the remote shell's own
  `bash -c '...'` argv contains that same substring, so the pattern matches the shell
  itself too and a broad kill/pgrep can target the wrong process. Confirm the port is
  free (`ss -ltnp | grep 3000`) before starting a replacement process, since Martin fails
  to bind (and silently exits) if the old one is still listening.

## B. Target Design (not yet implemented on production)

The rest of this repo (README.md, PROJECT_PLAN.md, RASPBERRY_PI_OS_SETUP.md,
CLOUDFLARED_NAMED_TUNNEL.md, SYSTEMD_SERVICES.md, systemd/*.service,
COG_COMPATIBILITY_NOTES.md) describes a design that was never carried out end-to-end:

- stars is a practical edition derived from x-24b; x-24b combined Martin, Caddy, and
  cloudflared; stars removes Caddy.
- Data files intended to be tracked under `data/` (`.pmtiles`, `.cog.tiff`), served via a
  Martin build with `cargo install martin --features=unstable-cog`.
- Internet exposure via a **dedicated** cloudflared named tunnel, credentials at
  `/opt/stars/secrets/cloudflared/<UUID>.json`.
- Startup via `martin.service` and `cloudflared.service` systemd units, running as a
  dedicated `stars` system user (nologin), repo checked out at `/opt/stars` (0750),
  secrets directory at `/opt/stars/secrets/cloudflared` (0700), credentials at 0600.
- Raspberry Pi OS target: latest (experimental phase).

None of this should be assumed true of the current production host. If/when a migration
to this design is undertaken, it needs to account for the existing shared cloudflared
tunnel (depot.optgeo.org) and the large existing data footprint under `/home/stars/data`.

## Assumptions To Verify (target design, Section B)
- Required Martin config keys for COG in the chosen version.
- Exact COG generation profile needed for stable Martin acceptance on target data.
