# Known Facts

This document has two parts. Section A is what was directly observed on the production
host on 2026-08-28 (via `ssh spacex.optgeo.org`) — treat it as authoritative over anything
in Section B or in other docs in this repo. Section B is the target design this repo was
originally written to describe, most of which has not been implemented.

## A. Confirmed Facts About Current Production (observed 2026-08-28)

### Host and access
- Public hostname `stars.optgeo.org` and the SSH-reachable host `spacex.optgeo.org` are
  the same physical machine.
- SSH access lands directly as the `stars` user (a regular sudo-capable login user, not a
  nologin system account).

### No repo checkout in production
- `/opt/stars` exists but is an **empty directory owned by root**, created 2026-06-07 and
  untouched since. It is not a git repository. This repo (`hfu/stars`) has never been
  cloned onto this host.
- There is no other checkout of this repo anywhere under `/home/stars` either.
- Separately, `/home/stars/martin` **is** a git checkout — but of upstream
  `https://github.com/maplibre/martin.git` (used to build the Martin binary from source),
  not of this repo.
- On GitHub, `origin` (`git@github.com:hfu/stars`) contains only `LICENSE` in a single
  `Initial commit`. README.md, docs/, systemd/, .github/, and .gitignore exist only in
  local working trees and have not been pushed. So even "clone the repo to production"
  would not currently bring over most of what's in this working tree.
  **Correction (2026-08-29/30):** this is no longer true of GitHub — README.md, docs/,
  systemd/, .github/, .gitignore, and (2026-08-30) styles/ have all been pushed to
  `origin/main`. Production itself is still not a checkout of this repo; nothing above
  changed on the host, only on GitHub.

### Martin
- **Correction (2026-08-28, later same day):** the original version of this document said
  no `martin.service` unit exists anywhere. That was checked only at **system** scope
  (`systemctl status martin.service`, `/etc/systemd/*`) and missed the **user** scope.
  There *is* a working, `enabled` **user-level** systemd unit:
  `/home/stars/.config/systemd/user/martin.service` (`systemctl --user status martin`,
  `WantedBy=default.target`, `Restart=on-failure`). This is the intended way to run
  Martin — a raw background process is a degraded fallback state, not the design.
- **Known failure mode:** because `Restart=on-failure` only fires on a non-zero exit or
  signal death, killing the systemd-managed Martin process directly with a plain
  `kill <pid>` (or `pkill`) makes it exit cleanly (status 0) — systemd then logs this as
  an intentional stop (`inactive (dead)`) and does **not** restart it. Whoever needs
  Martin running again then tends to launch it by hand
  (`nohup .../martin ... &` / `setsid nohup ...`), which works for serving traffic but
  leaves `systemctl --user status martin` permanently showing `inactive (dead)` while an
  unmanaged process actually holds port 3000. This happened at least twice on
  2026-08-28: once by an unknown actor before this session started, and again at 13:41
  JST when this session killed the process by PID (to change `config.yaml`) and
  restarted it with `setsid nohup` instead of `systemctl --user restart martin` — not
  knowing the user-level unit existed. **Correct procedure:** always use
  `systemctl --user stop/start/restart martin`, never a bare `kill`/`pkill` on its PID,
  even when the goal is just to pick up a config change. If Martin must be killed
  directly for some reason, follow up with `systemctl --user start martin` (not a raw
  relaunch) to restore proper supervision.
- **Update (2026-08-28, later same day):** `loginctl enable-linger stars` has been run
  (as `stars`, no sudo needed — self-linger doesn't require elevated privileges).
  `Linger=yes` confirmed, marker file `/var/lib/systemd/linger/stars` present. This means
  `martin.service` (and the other `enabled` user units: `mpris-proxy.service` and several
  gpg-agent/ssh-agent/dirmngr sockets — all harmless desktop-session defaults, inert
  without a GUI session) will now start automatically at boot even with no `stars` login
  session, closing the gap noted below. Not yet verified against an actual reboot.
- Binary: `/home/stars/.local/bin/martin`, version **1.10.1**. `martin --help` has no
  COG-related flags — this is a normal release build, **not** a `--features=unstable-cog`
  build. COG is not currently served in production.
  **Correction (2026-08-30):** upgraded to **v1.14.0**, installed by swapping in the
  official `martin-aarch64-unknown-linux-gnu` prebuilt release binary (checksum verified,
  backed up the old binary, restarted via `systemctl --user restart martin`, deleted the
  backup once the catalog and a spot-check of every source type came back matching
  pre-upgrade). Confirmed `unstable-cog` is still a non-default Cargo feature as of 1.14.0
  (checked Cargo.toml directly) — the COG gap is unchanged, still not a version issue.
  Picked up along the way: v1.11.0 added filesystem-watch live-reload for PMTiles/COG
  sources (no restart needed when the underlying file changes) and two 1.14.0 security
  fixes (a `rendering`-only render-worker crash, not applicable since rendering is
  disabled; and a sprite-id amplification DoS, not currently exploitable since no
  `sprites:` sources are configured, but worth having patched regardless).
- Config: `/home/stars/.config/martin/config.yaml` (not `/opt/stars/config/martin.yaml`).
  It combines directory auto-discovery (`pmtiles.paths: [/home/stars/data]`, which
  publishes every `*.pmtiles` file under a source ID derived from the filename) with a
  few explicit `sources:` entries for custom IDs/URLs (e.g. `bvmap`,
  **Confirmed by reading Martin's source (2026-08-30, `martin-core/src/resources/walk.rs`,
  `walk_files`):** this directory scan is **recursive** (walks subdirectories) but
  **strict-extension-filtered** (exact, case-sensitive match on `.pmtiles` only;
  everything else — `.glb`, `.json`, `.subtree`, etc. — is silently skipped, not an
  error). So dropping non-pmtiles data (e.g. 3D Tiles) into a subdirectory under
  `/home/stars/data` is safe from Martin's perspective; it just won't be discovered as a
  tile source. One caveat: since Martin v1.11.0 (in production as of the 1.14.0 upgrade)
  watches this directory for filesystem changes and reloads, uploading many small files
  (e.g. via `rsync`) can trigger repeated rescans while the transfer is in progress —
  harmless, but staging the upload elsewhere and `mv`-ing it in as one atomic operation
  avoids the churn.
  `openstreetmap_jp_planet`, and — as of 2026-08-28 — `pmtiles_jma_1saibun_hkd` and
  `pmtiles_ksj_n03_hkd`, deployed from this repo's `data/` using the same source IDs as
  the local `config/martin.yaml`). It also declares a `styles.paths` pointing at
  `/home/stars/styles`, which this repo's config has no equivalent for. A timestamped
  backup is kept alongside on each edit (`config.yaml.bak.<timestamp>`).
  **Correction (2026-08-30):** this repo now does have an equivalent —
  [styles/](../styles/) is the canonical, versioned copy of `/home/stars/styles`. See
  "Style.json gatekeeper workflow" below.
- Data lives at `/home/stars/data` — currently ~1.5 TB across large pmtiles files
  (`z18.pmtiles` 424 GB, `seamlessphoto512.pmtiles` 767 GB, `kitaphoto17.pmtiles` 190 GB,
  `mapterhorn-japan-bridge.pmtiles` 211 GB, plus smaller files), plus (as of 2026-08-28)
  `jma_1saibun_hkd.pmtiles` (558 KB) and `ksj_n03_hkd.pmtiles` (2.3 MB) copied from this
  repo's `data/` — checksums verified identical to the local copies. `abidjan.tif` (COG)
  has not been deployed; COG is still not supported by the production Martin build.
- Disk usage on the data filesystem is **86% full** (1.5 TB used / 1.8 TB total, 248 GB
  free) — worth checking before adding new large files.
  **Correction (2026-08-29):** re-measured at 76% full (440 GB free of 1.8 TB) the next
  day — the figure moves day to day (large files get added/removed), so treat both numbers
  as stale and re-run `df -h` rather than trusting either.
- Log: `/home/stars/martin.log` (plain redirected stdout, not journald).
- Nothing currently auto-restarts Martin on boot or on crash (no systemd unit, no cron
  entry — `crontab -l` is empty). It stays up only because it was started manually and
  hasn't crashed.

### cloudflared
- **Is** managed by systemd (`cloudflared.service` is real, `enabled`, and was `active
  (running)` for 2+ weeks at last check) — this is the one piece of the target design
  that actually matches reality.
- Config: `/etc/cloudflared/config.yml` (root-owned, needs `sudo` to read/edit) — not
  `/opt/stars/config/cloudflared/config.yaml`.
- Credentials: `/home/stars/.cloudflared/<uuid>.json` — not
  `/opt/stars/secrets/cloudflared/<uuid>.json`.
- **The tunnel is shared across multiple projects, not dedicated to stars.** Ingress
  rules route:
  - `spacex.optgeo.org` → `ssh://localhost:22`
  - `stars.optgeo.org` → `http://localhost:3000` (the Martin process above)
  - `depot.optgeo.org` → `http://localhost:8080` (a separate, unrelated service — do not
    assume changes here are stars-only)
  - **Confirmed 2026-08-30** (`/etc/caddy/Caddyfile`, world-readable, no sudo needed):
    `:8080` is a plain Caddy `file_server browse` with `root * /home/stars/data` and
    permissive CORS (`Access-Control-Allow-Origin *`) — i.e. `depot.optgeo.org` is a raw
    directory listing/download of the **exact same** `/home/stars/data` directory Martin
    scans for pmtiles. Dropping a file there makes it both raw-downloadable via
    `depot.optgeo.org/<path>` and (if it's a `.pmtiles` file) auto-discovered by Martin —
    the two aren't independent.
- Installed version is `2026.6.0`; logs show a standing warning that `2026.8.2` is
  available. Not urgent, but it means a routine `apt upgrade cloudflared` restart will
  also affect `depot.optgeo.org`, not just stars.
  **Correction (2026-08-29):** upgraded to `2026.8.2` via Cloudflare's official apt
  repository (added `/etc/apt/sources.list.d/cloudflared.list`,
  `sudo apt-get install --only-upgrade cloudflared`), confirmed live via `cloudflared
  --version` and a successful `systemctl restart cloudflared.service` (tunnel
  reconnected, all 4 connections re-registered, `stars.optgeo.org` verified reachable
  post-restart with `cf-cache-status: MISS`).
- Cloudflare edge-caches `/catalog` and other GET responses for up to 4 hours
  (`cache-control: max-age=14400`, confirmed via response headers). After restarting
  Martin or changing sources, verify with a cache-busting query string
  (`curl https://stars.optgeo.org/catalog?cb=$(date +%s)`) — an unbusted request can
  return a stale pre-change catalog for up to 4 hours (`cf-cache-status: HIT`).

### Style.json gatekeeper workflow (added 2026-08-30)

- This repo's [styles/](../styles/) directory is the canonical, versioned source for
  production's `/home/stars/styles/*.json`. This session/repo is the designated gatekeeper:
  contributors (e.g. the `dwg7/kaga0` Raspberry Pi appliance project, session name
  `kaga0-01`) PR against `styles/*.json` here; this session reviews, merges, and deploys.
  First instance: [pull/1](https://github.com/hfu/stars/pull/1) (VBM label text-size and
  onsen icon-size fixes, found while tuning `dwg7/kaga0` on a real 1440p display). Second:
  [pull/2](https://github.com/hfu/stars/pull/2) (thinned VBM road line-width ~40%). Third:
  [pull/3](https://github.com/hfu/stars/pull/3) (staggered 35 point/symbol/line layers'
  `minzoom` across z10-14 instead of 38 layers switching on simultaneously at z11 —
  the "z11 団子" fix; style-only, no tile/data change; user-confirmed improvement on
  kaga's real hardware 2026-08-30). pull/3 was also the first PR under the
  `dwg7/kaga0`-proposed division of labor: `hfu/stars` stays the design master, and
  `dwg7/kaga0`'s local copy carries only a mechanical source/glyphs/sprite path
  substitution on top of it — design changes always land here first.
- The public style-serving endpoint is `stars.optgeo.org/style/<id>` (e.g.
  `/style/vbm`) — **not** `/styles/<id>.json`, which 301-redirects.
- Martin serves style files straight off disk per request — replacing an *existing*
  style file's content (e.g. `/home/stars/styles/vbm.json`) took effect immediately with
  **no Martin restart needed** (confirmed 2026-08-30).
  **Correction (2026-08-30, same day):** this doesn't extend to adding a brand-new style
  file. Deploying `styles/positron.json` (new file, new style ID, from
  [pull/5](https://github.com/hfu/stars/pull/5)) 404'd until
  `systemctl --user restart martin` — Martin only discovers the *set* of available style
  IDs by scanning `styles.paths` at startup, though it re-reads a *known* file's content
  fresh on every request. So: same-file content edits don't need a restart, new files do.
  This still differs from tile *sources*, which always need a restart regardless.
- Deploy sequence: back up the target file → copy the merged file over → verify checksums
  match → confirm live via a cache-busted `curl` against the `style/<id>` endpoint →
  delete the backup once confirmed.

### config.yaml gatekeeper workflow (added 2026-08-30)

- [config/martin.yaml](../config/martin.yaml) is the canonical, tracked mirror of
  `/home/stars/.config/martin/config.yaml` (checksums verified matching 2026-08-30).
  **Correction (2026-08-30, same day):** this file previously described a gitignored,
  dev-only *target design* (relative `./data` paths, COG sources, cache tuning) separate
  from a parallel `config/martin.production.yaml`. That split was collapsed the same day
  it was introduced — one canonical file, matching the `styles/` precedent, rather than
  two files whose relationship needed remembering. The target-design tuning intent is
  preserved in [MARTIN_SOURCES.md](MARTIN_SOURCES.md), not lost, just no longer live in a
  file nothing runs.
- Treated as **higher-risk than styles/**, with a stricter review bar:
  - A config.yaml PR that adds a `pmtiles_foo: /home/stars/data/foo.pmtiles`-style entry
    is only valid if `foo.pmtiles` already exists at that exact path on production — the
    file itself can't ride along in a GitHub PR (too large; see the pmtiles size note
    elsewhere in this doc). **Verify the referenced file exists via SSH before merging.**
  - A bad config.yaml (syntax error, wrong path) can stop Martin from serving *every*
    source, not just degrade one layer's look the way a bad style.json would — validate
    YAML before merging, and don't apply the same "diff matches description → merge" bar
    used for styles/.
- Deploying a config.yaml change **requires a Martin restart**
  (`systemctl --user restart martin`), unlike style.json changes. Sequence: back up
  `/home/stars/.config/martin/config.yaml` → copy the merged file over → verify checksums
  → get explicit user confirmation before restarting (this briefly takes down all tile
  serving, not just one source) → restart → verify via cache-busted `curl .../catalog` →
  delete the backup.
  **Correction (2026-09-04):** the restart is specifically for registering a *new*
  source ID. **Swapping an existing pmtiles file's content at its already-registered path
  needs no restart** — confirmed live when `dwg7/ferspas57` atomically replaced 6
  `.pmtiles` files in place (`scp` to `.new`, then `mv`); Martin served the new content
  (different bounds/zoom in TileJSON) within seconds. This is Martin's fs-watch reload
  for local PMTiles/COG sources (upstream since v1.11.0, active here since the 1.14.0
  upgrade) — pmtiles now behaves the same as styles/*.json for same-path content swaps.
- **Trusted contributors can have direct SSH/scp access to `/home/stars/data`,
  independent of this session (added 2026-09-04).** The ferspas57 overwrite above
  happened without the gatekeeper doing the file transfer — confirmed directly with the
  user, whose stated reason: pmtiles files can be very large, so routing every data
  change through the gatekeeper doesn't scale. This doesn't change who gatekeeps
  `config.yaml`/`styles/*.json` (still this session, via PR), but it means the contents
  of `/home/stars/data` shouldn't be assumed to only ever change via this session's own
  transfers — verify current state rather than trusting memory of what was transferred.

### Practical implication for future changes
- Restarting the Martin process affects only `stars.optgeo.org` (nothing else routes to
  port 3000).
- Restarting `cloudflared.service` affects `stars.optgeo.org`, `depot.optgeo.org`, and SSH
  routing over the tunnel simultaneously — treat it as a shared-infrastructure change, not
  a stars-only action.
- To add a data source to production today: copy the file to `/home/stars/data/`, add (or
  rely on auto-discovery for) a source entry in
  `/home/stars/.config/martin/config.yaml`, then restart the Martin process. This is a
  manual, undocumented-elsewhere procedure until an actual migration to this repo's
  systemd-based design happens. Done successfully 2026-08-28 for `jma_1saibun_hkd.pmtiles`
  and `ksj_n03_hkd.pmtiles`.
- Restart gotcha (hit 2026-08-28): kill the Martin PID **by exact number**, not via
  `pgrep -f "martin ..."` run inside the same SSH command string — the remote shell's own
  `bash -c '...'` argv contains that same substring, so the pattern matches the shell
  itself too and a broad kill/pgrep can target the wrong process. Confirm the port is
  free (`ss -ltnp | grep 3000`) before starting the replacement process, since Martin
  fails to bind (and silently exits) if the old one is still listening. Start the new
  process with `setsid nohup ... >> /home/stars/martin.log 2>&1 < /dev/null &`; this
  detaches it fully so it survives the SSH session closing (confirmed it kept running
  after the launching SSH connection was torn down).

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
tunnel (depot.optgeo.org) and the ~1.5 TB of existing data under `/home/stars/data`.

## Immediate Repository State
- The local working tree has README.md, docs/, systemd/, .github/, and .gitignore that
  have never been pushed to `origin`; only `LICENSE` exists on GitHub as of 2026-08-28.
  **Correction (2026-08-29/30):** all of the above, plus styles/, have since been pushed
  to `origin/main`. Only `LICENSE` was true as of 2026-08-28; it is not true anymore.

## Assumptions To Verify (target design, Section B)
- Required Martin config keys for COG in the chosen version.
- Exact COG generation profile needed for stable Martin acceptance on target data.
