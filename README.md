# stars

Decentralized geospatial data delivery server. Practical successor of [x-24b](https://github.com/unvt/x-24b).

Serves PMTiles and COG files from local storage using [Martin](https://maplibre.org/martin/), published to the internet via [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) named tunnel. Target host: **stars.optgeo.org**.

> **Status note (confirmed 2026-08-28):** everything below this line describes the *target* architecture this repo is designed around. The `stars.optgeo.org` host currently in production (reachable via `ssh spacex.optgeo.org`) runs a different, hand-maintained setup that predates this repo and has not been migrated to it — see [docs/KNOWN_FACTS.md](docs/KNOWN_FACTS.md) for what is actually running. In particular: there is no `/opt/stars` checkout, Martin is supervised by a **user-level** systemd unit (`systemctl --user`, not the system-level `martin.service` this repo's `systemd/` describes), and the production Martin binary does not have COG support built in. Do not assume the instructions below have been applied to production.

Stack (target design):
- **Martin** — tile server with experimental COG support, built from source
- **cloudflared** — named tunnel to Cloudflare network
- **Raspberry Pi OS** — systemd-managed startup (no Caddy)

## Repository Structure

```
config/
  martin.yaml               Martin configuration
  cloudflared/
    config.yaml             cloudflared named tunnel configuration
data/
  *.pmtiles                 PMTiles data files (add here)
  *_martin_compatible_cog.tif  COG data files (add here, see docs/COG_COMPATIBILITY_NOTES.md)
systemd/
  martin.service            systemd unit for Martin
  cloudflared.service       systemd unit for cloudflared
docs/
  PROJECT_PLAN.md           Project plan and milestones
  KNOWN_FACTS.md            Confirmed technical decisions
  CHALLENGES.md             Known challenges and actions
  RASPBERRY_PI_OS_SETUP.md  Host OS setup: apt packages, Martin build, cloudflared install
  CLOUDFLARED_NAMED_TUNNEL.md  Named tunnel bootstrap and credential setup
  SYSTEMD_SERVICES.md       systemd install and lifecycle operations
  OPERATIONS_RUNBOOK.md     Day-2 operations: health checks, backups, troubleshooting
  MARTIN_SOURCES.md         How data/ files are published and named
  COG_COMPATIBILITY_NOTES.md  COG format requirements for Martin experimental support
```

## Development (macOS)

Install Martin with experimental COG support:

```bash
cargo install martin --features=unstable-cog
```

Run Martin locally:

```bash
martin --config config/martin.yaml
```

Verify:

```bash
curl http://localhost:3000/catalog
```

## Deployment (Raspberry Pi OS) — target design, not yet applied

See [docs/RASPBERRY_PI_OS_SETUP.md](docs/RASPBERRY_PI_OS_SETUP.md) for full prerequisite setup. **This has not been carried out on the current production host** — see the status note above and [docs/KNOWN_FACTS.md](docs/KNOWN_FACTS.md) for what to actually do to change production today.

```bash
# 1. Install apt packages, rustc/cargo, cloudflared
# 2. Build Martin
cargo install martin --features=unstable-cog

# 3. Create stars user
sudo useradd -r -s /usr/sbin/nologin -d /opt/stars -m stars

# 4. Clone repo and set permissions
sudo git clone <this repo> /opt/stars
sudo chown -R stars:stars /opt/stars
sudo chmod 750 /opt/stars

# 5. Create secrets directory for tunnel credentials
sudo mkdir -p /opt/stars/secrets/cloudflared
sudo chown stars:stars /opt/stars/secrets/cloudflared
sudo chmod 700 /opt/stars/secrets/cloudflared

# 6. Configure cloudflared tunnel
# See docs/CLOUDFLARED_NAMED_TUNNEL.md for bootstrap and credentials placement
# Update config/cloudflared/config.yaml with tunnel UUID and credentials path

# 7. Add local data and config
# Place data files in data/
# Place config/martin.yaml locally

# 8. Install and enable systemd services
sudo cp /opt/stars/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable martin.service cloudflared.service
sudo systemctl start martin.service cloudflared.service
```

## Adding Data — target design, not yet applied

Place files under `data/`. **Note:** this repo's `data/` and `config/martin.yaml` are not what production currently reads; today, adding data to production means placing files under `/home/stars/data` and editing `/home/stars/.config/martin/config.yaml` directly on the host (see [docs/KNOWN_FACTS.md](docs/KNOWN_FACTS.md)).

| Format | Pattern | Notes |
|--------|---------|-------|
| PMTiles | `*.pmtiles` | Auto-discovered from `data/` |
| COG | `*_martin_compatible_cog.tif` | Register explicitly in `config/martin.yaml` |

For COG preparation, see [docs/COG_COMPATIBILITY_NOTES.md](docs/COG_COMPATIBILITY_NOTES.md).

## License

See [LICENSE](LICENSE).
