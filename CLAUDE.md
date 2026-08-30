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
- Disk on the data filesystem is ~76% full (440 GB free of 1.8 TB) as of 2026-08-29
  (**correction** to an earlier 86%/248GB figure recorded 2026-08-28 — re-check with `df -h`
  rather than trusting either number, since it clearly moves day to day) — check headroom
  before copying new large files to `/home/stars/data`.
- Before any restart or config edit, back up
  `/home/stars/.config/martin/config.yaml` first (`cp -p ... config.yaml.bak.$(date
  +%Y%m%d_%H%M%S)`), and confirm the exact PID via `ps aux | grep martin` yourself before
  killing anything — don't trust a PID mentioned in a prior message/session without
  re-checking, and don't use `pgrep -f` patterns that might also match the SSH command
  string of the very shell you're running the check in.
- Any destructive/production-affecting action (restart, config edit, file overwrite)
  needs explicit user confirmation before executing — state the exact plan first.
- After a production file replace where you took a backup first (e.g.
  `vbm.json.bak.<timestamp>`), delete that backup once you've verified the change is live
  and correct — don't leave it in the production directory. See "Style.json gatekeeper
  responsibility" below for the deploy sequence this applies to.

## Style.json gatekeeper responsibility (added 2026-08-30)

This session/repo is the designated gatekeeper for production's map style JSON files
(`/home/stars/styles/*.json`). The canonical, versioned copy lives in this repo's
[styles/](styles/) directory (`vbm.json`, `vlcm.json`, `bvmap-dark.json`,
`openstreetmap_jp_planet.json` as of 2026-08-30) — treat `styles/` here as the source of
truth, and `/home/stars/styles` as the deploy target, not the other way around.

- **Why this exists:** `dwg7/kaga0` (a separate Raspberry Pi appliance project displaying
  VBM/VLCM offline) needed a way to upstream style fixes found while tuning on real
  hardware, without either standing up new infrastructure or patching production directly.
  The user designated this repo/session as the intake point rather than creating a
  separate style-management repo.
- **Intake workflow:** a contributor (e.g. the `kaga0-01` Claude session) opens a GitHub PR
  against `styles/*.json` in `hfu/stars`. This session reviews (confirm the diff is scoped
  to what was described, validate the JSON, sanity-check the changed values) and merges.
  See [pull/1](https://github.com/hfu/stars/pull/1) for the first exercised instance;
  [pull/2](https://github.com/hfu/stars/pull/2) and
  [pull/3](https://github.com/hfu/stars/pull/3) followed. As of pull/3, `dwg7/kaga0`
  treats `hfu/stars` as the design master — their local copy is only a mechanical
  source/glyphs/sprite path substitution on top of what's merged here, never an
  independent design fork — so every VBM/VLCM design change should keep arriving as a PR
  here first.
- **Deploy sequence after merge** (needs explicit user confirmation per the hard rules
  above, same as any production change): `git pull` locally → back up the production
  file → `scp` the merged file over → verify checksums match → confirm the change is live
  via `curl https://stars.optgeo.org/style/<id>?cb=$(date +%s)` (note: the public path is
  `style/<id>`, not `styles/<id>.json`, which 301-redirects) → delete the backup.
- **No Martin restart needed for style changes** — confirmed 2026-08-30 that replacing
  `/home/stars/styles/vbm.json` took effect immediately on the next request, unlike tile
  *sources*, which do need `systemctl --user restart martin` to pick up. Don't restart
  Martin as part of a style-only deploy.

## config.yaml gatekeeper responsibility (added 2026-08-30)

This session/repo also gatekeeps Martin's config, but treat it as **higher-risk than
style.json** — don't apply the styles/ trust model unchanged. Canonical copy:
[config/martin.yaml](config/martin.yaml), a verbatim mirror of
`/home/stars/.config/martin/config.yaml` (checksums verified matching 2026-08-30, and
tracked in git — no longer gitignored). **Correction (2026-08-30):** this file used to be
a gitignored, dev-only target-design reference (`./data`-relative paths, COG sources,
cache tuning that don't exist in production); it was overwritten with the production
mirror on 2026-08-30 rather than keeping two parallel config files, since that split had
already started causing exactly the "which one is real" confusion this repo's docs exist
to prevent. The old target-design tuning intent (worker_processes, cache sizing,
on_invalid, allow_http, tilejson_url_version_param) is preserved in
[docs/MARTIN_SOURCES.md](docs/MARTIN_SOURCES.md)'s "Target-design server tuning" section,
not lost — just no longer live in a config file nothing actually runs.

Why config.yaml is riskier than styles/, and what changes in the process:

- **A style.json PR is the whole deliverable; a config.yaml PR usually isn't.** Adding a
  `pmtiles_foo: /home/stars/data/foo.pmtiles` source line only works if `foo.pmtiles`
  actually exists at that path on production — which a GitHub PR cannot carry (pmtiles
  files are far too large; see the "why not PR the data itself" reasoning in
  KNOWN_FACTS.md). **Before merging any PR that references a `/home/stars/data/*` path,
  SSH in and confirm the file is actually there** (`ssh spacex.optgeo.org "ls -la
  /home/stars/data/<file>"`) — don't merge on the diff looking plausible alone.
- **A bad config.yaml can take down every source, not just one layer.** A style.json typo
  degrades one map's look; a config.yaml syntax error or bad path can stop Martin from
  serving anything. Validate YAML syntax before merging, and be more conservative than the
  styles/ "diff matches description → merge" bar.
- **Deploy requires a Martin restart** (`systemctl --user restart martin`), unlike
  style.json deploys. This means: back up `/home/stars/.config/martin/config.yaml` first →
  copy the merged `config/martin.yaml` over → verify checksums → state the
  exact plan and get explicit user confirmation before restarting (per the hard rules
  above — this is a real production restart, all sources go briefly unavailable) →
  restart → verify via cache-busted `curl .../catalog` → delete the backup.

## PR review checklist and escalation rules (added 2026-08-30)

Applies to both gatekeeper roles above. This formalizes what was actually done for
[pull/1](https://github.com/hfu/stars/pull/1),
[pull/2](https://github.com/hfu/stars/pull/2), and
[pull/3](https://github.com/hfu/stars/pull/3), which the earlier prose ("confirm the diff
is scoped, validate, sanity-check") described too loosely to be a repeatable checklist.

- **Verify the diff yourself; a PR description or a peer session's message describing the
  change is not verification.** `gh pr diff` and `gh pr checkout` are cheap — always pull
  the actual diff and check it directly rather than trusting what the PR body or the
  contributor's message claims it does. This has held for both PRs so far and should stay
  the baseline, not get skipped as trust builds up.
- **Checklist before merging:**
  1. `gh pr view --json files,changedFiles` — confirm only the expected file(s) changed.
     If a PR touches anything outside `styles/*.json` / `config/martin.yaml` (e.g. this
     repo's own CLAUDE.md, `.github/`, or an unrelated file), **stop and ask the user**
     before merging — don't merge on the assumption it's incidental.
  2. `gh pr diff` — confirm every hunk matches what the PR description says, with no
     unexplained extra changes. A diff that goes beyond its own description is a reason to
     ask the contributor to split it or to ask the user, not to merge and note the
     discrepancy after the fact.
  3. Validate syntax (JSON for styles/, YAML for config.yaml) and, for config.yaml, SSH in
     and confirm any newly-referenced `/home/stars/data/*` path actually exists — see
     "config.yaml gatekeeper responsibility" above.
  4. Sanity-check the changed values are plausible for what's described (e.g. a claimed
     "40% thinner" line-width diff should actually be ~0.6x the original).
  - If any check fails or looks off, don't merge — report back to the contributor (or the
    user) with specifics, rather than merging and fixing it yourself in a follow-up.
- **Merging itself needs `gh pr merge` allowed in Bash permissions**, which is a per-
  machine/session setup step, not something granted automatically — see
  `.claude/settings.local.json` (gitignored, personal). If it's not there yet on a fresh
  machine/session, `gh pr merge` will be blocked by the auto-mode classifier; ask the user
  to add the rule (a session can't write its own permission settings — that write is
  blocked too) rather than attempting a workaround.
- **Deploying to production is never covered by "the PR is merged, so deploy it"** — it's
  a separate, always-explicit-confirmation step per the hard rules at the top of this file,
  independent of how routine the merge felt.

## Current confirmed production state (as of 2026-08-28, styles/GitHub state updated 2026-08-30)

- No `/opt/stars` checkout anywhere; this repo has never been deployed there.
  **Correction (2026-08-30):** GitHub `origin` no longer has just `LICENSE` — README.md,
  docs/, systemd/, .github/, .gitignore, and styles/ have all been pushed as of
  2026-08-29/30. Production itself still has no checkout of this repo; only the GitHub
  remote state changed.
- Martin v1.10.1 (no COG support built in), config
  `/home/stars/.config/martin/config.yaml`, data `/home/stars/data`, styles
  `/home/stars/styles`, supervised by `systemctl --user` (see rules above), linger
  enabled for `stars` (`loginctl enable-linger stars`, done 2026-08-28) so it should
  survive reboot without a login session — not yet verified against an actual reboot.
- Deployed from this repo's local `data/`/`config/martin.yaml` (which remain
  git-ignored, dev-only references) onto production, with checksums verified matching:
  **Correction (2026-08-30):** `config/martin.yaml` is no longer gitignored/dev-only — see
  "config.yaml gatekeeper responsibility" above. `data/` remains gitignored (large binary
  files don't belong in git).
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
