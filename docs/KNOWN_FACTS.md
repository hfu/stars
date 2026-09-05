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
- Data lives at `/home/stars/data`, several hundred GB to low-TB scale across large
  pmtiles files (`z18.pmtiles` 424 GB, `seamlessphoto512.pmtiles` 767 GB,
  `kitaphoto17.pmtiles` 190 GB, `mapterhorn-japan-bridge.pmtiles` ~220 GB, plus many
  smaller files from various consumer projects). `abidjan.tif` (COG) has not been
  deployed — still no COG support in the production Martin build.
  - Disk usage moves day to day (files get added/removed regularly) — always re-check
    with `df -h` rather than trusting a previously-recorded percentage.
  - **Trusted contributors can have their own direct SSH/scp access to
    `/home/stars/data`**, bypassing the gatekeeper's own file-transfer step — confirmed
    with the user (`dwg7/ferspas57` is one such case): pmtiles files can be too large for
    gatekeeper-mediated transfer to scale to every case. This doesn't change who
    gatekeeps `config.yaml`/`styles/*.json` (still this session, via PR) — but don't
    assume the directory's contents only ever change via this session's own transfers.
- Log: `/home/stars/martin.log` (plain redirected stdout, not journald) — mostly
  historical now that the service runs under proper systemd supervision.

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
