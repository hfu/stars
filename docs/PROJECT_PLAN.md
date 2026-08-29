# stars Project Plan

> **Status note (2026-08-28):** the milestone checkmarks below reflect documentation
> completeness only. Direct inspection of the production host (`spacex.optgeo.org` /
> `stars.optgeo.org`, 2026-08-28) found that M3 and M4 have not actually been carried out
> there — there is no `martin.service`, no `/opt/stars` checkout, and Martin runs without
> COG support. See [docs/KNOWN_FACTS.md](KNOWN_FACTS.md) Section A for the real state and
> Section B for what remains to be done to make this plan true. Milestone statuses below
> are corrected accordingly.

## 1. Purpose
Build a practical production edition of x-24b focused on decentralized geospatial delivery with Martin.

The stack serves files in data/:
- .pmtiles
- .cog.tiff

The stack components are:
- Martin (with experimental COG support)
- cloudflared
- Raspberry Pi OS native startup management

Not used in this project:
- Caddy

Target host:
- stars.optgeo.org

## 2. Scope
In scope:
- Data hosting from local storage under data/
- Tile and COG serving through Martin
- Tunnel publication through cloudflared
- Boot-time service startup on Raspberry Pi OS
- Operations documentation and troubleshooting notes

Out of scope (for now):
- Multi-node orchestration
- Managed Kubernetes deployment
- Dynamic autoscaling

## 3. Architecture Direction
1. Martin process reads configuration and serves PMTiles and COG endpoints.
2. cloudflared publishes Martin endpoint to stars.optgeo.org.
3. systemd manages startup order, restart policy, and logs.
4. Operations rely on reproducible config files and service units committed to this repo.

## 3.1 Confirmed Technical Decisions
- Martin experimental COG build command: cargo install martin --features=unstable-cog
- cloudflared mode: named tunnel
- DNS/TLS authority for stars.optgeo.org: Cloudflare
- Raspberry Pi OS target: latest (experimental)
- systemd service naming: martin.service and cloudflared.service

## 4. Milestones
## M1: Baseline docs and conventions ✅ DONE
- Define known facts, constraints, and risks
- Define service naming convention
- Define expected directory structure

## M2: Local runtime baseline ✅ DONE (docs and local dev only)
- Add apt-based prerequisite install steps for cargo/rust toolchain and geospatial dependencies
- Add Martin config for PMTiles and experimental COG
- Add cloudflared config and runbook
- Verify local access and tunnel publication
- Note: verified on macOS local dev only (see README.md "Development (macOS)"). Not
  applied to the production host.

## M3: Boot automation on Raspberry Pi OS ❌ NOT DONE (docs only, not applied)
- Add systemd unit files — done in this repo (systemd/*.service), but **not installed**
  on production: `martin.service` does not exist on `spacex.optgeo.org`, and Martin runs
  there as an unmanaged background process instead.
- Add dependencies and startup ordering — designed, not deployed.
- Verify boot-to-ready behavior (checklist in SYSTEMD_SERVICES.md, section 8) — the
  checklist itself was written aspirationally and has not actually been run against
  production. See docs/KNOWN_FACTS.md Section A.

## M4: Hardening ❌ NOT DONE (runbook assumes an architecture that isn't deployed)
- Add health checks and restart strategy (OPERATIONS_RUNBOOK.md, section 1-2) — written,
  but several commands (e.g. `systemctl status martin.service`) do not apply to the
  current production process model.
- Add backup/restore notes for config and credentials (OPERATIONS_RUNBOOK.md, section 3)
  — paths referenced (`/opt/stars/...`) do not exist on production.
- Add minimal observability checks (OPERATIONS_RUNBOOK.md, section 4-5) — same caveat.

## 5. Deliverables
- Agent file for focused development workflow
- Plan, known facts, and challenge documents
- COG compatibility notes derived from issue-based validation
- Runtime config templates
- service unit templates
- operator runbook

## 6. Definition of Done
- Martin serves both PMTiles and COG from data/ — **not met**: production Martin has no
  COG support built in, and does not read this repo's `data/`.
- Public access works through cloudflared and stars.optgeo.org — **met**, but via a
  hand-run process and a tunnel shared with other domains, not the design in this repo.
- Services auto-start after reboot on Raspberry Pi OS — **not met** for Martin (no
  systemd unit, no restart-on-failure, no boot-start); met for cloudflared only.
- Docs are sufficient for another operator to reproduce deployment — **not met** as of
  2026-08-28; see docs/KNOWN_FACTS.md for the gap between documented and actual state.
