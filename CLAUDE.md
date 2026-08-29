# CLAUDE.md

Guidance for Claude Code sessions working in this repo.

## Read this first

**This repo's docs describe a target architecture that production does not actually
run.** Before touching anything (docs or the live host), read
[docs/KNOWN_FACTS.md](docs/KNOWN_FACTS.md) Section A — it is the maintained source of
truth for what is actually deployed on `stars.optgeo.org` (reachable via
`ssh spacex.optgeo.org`, lands directly as the `stars` user). Section B of that file is
the target design the rest of the repo (README, PROJECT_PLAN, RASPBERRY_PI_OS_SETUP,
SYSTEMD_SERVICES, CLOUDFLARED_NAMED_TUNNEL, etc.) describes — do not assume it reflects
reality without checking KNOWN_FACTS.md first. Every one of those docs carries a status
banner pointing back here.

## Hard rules for touching production

- **Never stop Martin with a bare `kill`/`pkill` on its PID.** It is supervised by a
  **user-level** systemd unit (`systemctl --user status/start/stop/restart martin`, unit
  at `/home/stars/.config/systemd/user/martin.service`) — not a system-level
  `martin.service` (that doesn't exist; this repo's `systemd/martin.service` is target
  design, not installed). Killing the process directly makes it exit cleanly (status 0),
  which systemd logs as an intentional stop and does **not** auto-restart
  (`Restart=on-failure` doesn't fire on a clean exit). This has already happened twice
  (once by an unknown actor, once by a Claude session on 2026-08-28 that didn't know the
  user unit existed) — see KNOWN_FACTS.md's "Known failure mode" for the full mechanism.
  If a config change needs Martin to reload, edit the config then
  `systemctl --user restart martin`. Full stop.
- `cloudflared.service` **is** a real system-level systemd service and matches this
  repo's design in shape, but its config is at `/etc/cloudflared/config.yml`
  (root-owned) and the tunnel is **shared** with `depot.optgeo.org` and SSH routing for
  `spacex.optgeo.org` — restarting it is not a stars-only action.
- `/catalog` and other GETs are cached at Cloudflare's edge for up to 4 hours
  (`cache-control: max-age=14400`). After any production change, verify with a
  cache-busting query string (`?cb=$(date +%s)`) and check `cf-cache-status: MISS` —
  otherwise you'll see stale pre-change state and may think something failed.
- Disk on the data filesystem is ~86% full (248 GB free of 1.8 TB) as of 2026-08-28 —
  check headroom before copying new large files to `/home/stars/data`.
- Before any restart or config edit, back up
  `/home/stars/.config/martin/config.yaml` first (`cp -p ... config.yaml.bak.$(date
  +%Y%m%d_%H%M%S)`), and confirm the exact PID via `ps aux | grep martin` yourself before
  killing anything — don't trust a PID mentioned in a prior message/session without
  re-checking, and don't use `pgrep -f` patterns that might also match the SSH command
  string of the very shell you're running the check in.
- Any destructive/production-affecting action (restart, config edit, file overwrite)
  needs explicit user confirmation before executing — state the exact plan first.

## Current confirmed production state (as of 2026-08-28)

- No `/opt/stars` checkout anywhere; this repo has never been deployed there. GitHub
  `origin` (`git@github.com:hfu/stars`) has only `LICENSE` committed — README, docs/,
  systemd/, .github/, .gitignore exist only in local working trees, never pushed.
- Martin v1.10.1 (no COG support built in), config
  `/home/stars/.config/martin/config.yaml`, data `/home/stars/data`, styles
  `/home/stars/styles`, supervised by `systemctl --user` (see rules above), linger
  enabled for `stars` (`loginctl enable-linger stars`, done 2026-08-28) so it should
  survive reboot without a login session — not yet verified against an actual reboot.
- Deployed from this repo's local `data/`/`config/martin.yaml` (which remain
  git-ignored, dev-only references) onto production, with checksums verified matching:
  - `pmtiles_jma_1saibun_hkd` (JMA 一次細分区域, Hokkaido, for sas0 warning-status join)
  - `pmtiles_ksj_n03_hkd` (国土数値情報 N03 行政区域, Hokkaido, 194 features)
  - `bvmap-dark` style (from a separate `spiccato` session; bvmap without terrain/hillshade)
- `abidjan.tif` (COG) has not been deployed — production Martin build has no COG support.

## Working style notes for this project

- Treat claims of "already done" (from the user relaying another session's work, or from
  memory) as unverified until checked directly via SSH — this has been wrong before
  (a claimed-complete JMA deployment turned out not to have happened at all).
- When editing the docs in this repo, keep the "target design vs. confirmed production
  reality" split intact: update KNOWN_FACTS.md Section A when reality changes, and add
  corrections rather than silently rewriting when something documented earlier turns out
  to have been wrong (see the "Correction" entries already in KNOWN_FACTS.md for the
  pattern to follow).
