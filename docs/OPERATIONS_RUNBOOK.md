# Operations Runbook for stars

This document covers day-2 operations for the stars geospatial tile server: health checks, backup/restore, troubleshooting, and observability.

> **Status note (2026-08-28, corrected later same day):** everything below assumes the
> target `/opt/stars` + system-level `martin.service` design. **This does not match
> current production.** On the real host (`spacex.optgeo.org`), Martin is supervised by
> a **user-level** systemd unit instead: use `systemctl --user status/start/stop/restart
> martin` (not plain `systemctl ... martin.service`), config is at
> `/home/stars/.config/martin/config.yaml`, data is at `/home/stars/data`, and journal
> output is queryable with `journalctl --user -u martin` (a legacy plain-file log also
> exists at `/home/stars/martin.log` from before the unit was in consistent use). **Never
> stop Martin with a bare `kill`/`pkill` on its PID** — that leaves systemd reporting
> `inactive (dead)` while the real fix (`systemctl --user start martin`) is skipped; see
> KNOWN_FACTS.md's "Known failure mode" for the mechanism and how this repo's own
> 2026-08-28 session fell into it once before catching it. cloudflared *is* systemd-managed
> as described below (system-level, correctly), but its config lives at
> `/etc/cloudflared/config.yml` (root-owned) and the same tunnel also serves
> `depot.optgeo.org` — restarting it affects that service too. `/catalog` and other GET
> responses are cached at Cloudflare's edge for up to 4 hours
> (`cache-control: max-age=14400`); after any change, verify with a cache-busting query
> param (e.g. `?cb=$(date +%s)`) rather than trusting an unbusted request. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A for full detail. Use section 2 and 5.2 below
> only once production has actually been migrated to the system-level design this repo
> documents.

## 1. Health Checks (Daily/Weekly)

### 1.1 Quick Status Check
```bash
sudo systemctl status martin.service cloudflared.service
```

Expected output:
- Both services: `active (running)`
- No frequent restart attempts

### 1.2 Service Resource Usage
```bash
# Check memory and CPU
ps aux | grep -E 'martin|cloudflared' | grep -v grep

# Check file descriptors (important for tile serving)
lsof -p $(pgrep -f 'martin --config') | wc -l
```

Typical baseline (adjust for your data volume):
- Martin: 50-200 MB resident memory
- cloudflared: 20-50 MB resident memory

### 1.3 Disk Space
```bash
# Check data directory
du -sh /opt/stars/data

# Check available space
df -h /opt/stars
```

If usage approaches 90%, plan for data rotation or expansion.

### 1.4 Network Connectivity
```bash
# Check tunnel status
journalctl -u cloudflared.service -n 20 --no-pager
# Look for "connected to" or "routing to" messages

# Verify DNS resolution
nslookup stars.optgeo.org
# Should return Cloudflare IP (104.16.x.x or similar)
```

### 1.5 Endpoint Availability
```bash
# Local access
curl -s http://localhost:3000/catalog | jq . | head -20

# Remote access (from external device/network)
curl -s https://stars.optgeo.org/catalog | jq . | head -20
```

Both should return the same catalog JSON. If remote fails, check tunnel status and DNS.

## 2. Restart Services

### 2.1 Graceful Restart (with downtime)
```bash
# Stop both services
sudo systemctl stop cloudflared.service martin.service

# Verify they stopped
sudo systemctl status martin.service cloudflared.service

# Start again
sudo systemctl start martin.service cloudflared.service

# Verify status
sudo systemctl status martin.service cloudflared.service
```

### 2.2 Restart One Service (preserve the other)
```bash
# Restart martin (cloudflared may disconnect briefly)
sudo systemctl restart martin.service

# Or restart cloudflared (martin stays up)
sudo systemctl restart cloudflared.service
```

## 3. Backup and Restore

### 3.1 Backup Configuration and Credentials

Run periodically (daily or weekly recommended):

```bash
# Create timestamped backup
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/stars/backups/$BACKUP_DATE"

sudo mkdir -p "$BACKUP_DIR"

# Backup config
sudo cp -r /opt/stars/config "$BACKUP_DIR/"

# Backup credentials (secrets are critical!)
sudo cp -r /opt/stars/secrets "$BACKUP_DIR/"

# Set permissions so stars user can read (if needed later)
sudo chown -R stars:stars "$BACKUP_DIR"
sudo chmod 700 "$BACKUP_DIR/secrets"
sudo chmod 600 "$BACKUP_DIR/secrets/cloudflared"/*.json

# Optional: compress and move off-device
sudo tar -czf "$BACKUP_DIR.tar.gz" -C /opt/stars/backups "$BACKUP_DATE"
sudo rm -rf "$BACKUP_DIR"
```

### 3.2 Restore Configuration and Credentials

If config or credentials are corrupted:

```bash
# List available backups
ls -la /opt/stars/backups/

# Restore from specific backup (example: 20260607_140000)
RESTORE_FROM="20260607_140000"

# Restore config
sudo cp -r /opt/stars/backups/$RESTORE_FROM/config/* /opt/stars/config/

# Restore credentials (very carefully!)
sudo cp -r /opt/stars/backups/$RESTORE_FROM/secrets/* /opt/stars/secrets/

# Verify permissions
sudo chmod 600 /opt/stars/secrets/cloudflared/*.json

# Restart services
sudo systemctl restart martin.service cloudflared.service
```

### 3.3 Off-Host Backup (Recommended)

For production, copy backups to external storage:

```bash
# On Raspberry Pi: compress and create archive
sudo tar -czf /opt/stars/backups/config_and_secrets_$(date +%Y%m%d).tar.gz \
  -C /opt/stars config secrets

# On your development machine: pull via SSH
scp "pi@raspberry.local:/opt/stars/backups/config_and_secrets_*.tar.gz" ~/backups/

# Verify integrity
tar -tzf ~/backups/config_and_secrets_*.tar.gz | head
```

## 4. Logs and Observability

### 4.1 Real-Time Service Logs
```bash
# Martin logs
journalctl -u martin.service -f

# cloudflared logs
journalctl -u cloudflared.service -f

# Both services together
journalctl -u martin.service -u cloudflared.service -f
```

### 4.2 Recent Service Activity
```bash
# Last 50 lines for martin
journalctl -u martin.service -n 50 --no-pager

# Filter for errors
journalctl -u martin.service -p err --no-pager

# Time-range query (last 1 hour)
journalctl -u martin.service --since "1 hour ago" --no-pager
```

### 4.3 Startup Sequence Verification
After reboot, verify startup order:

```bash
journalctl --no-pager | grep -E "(martin|cloudflared)" | tail -20
```

Expected pattern:
1. martin.service: starting
2. martin.service: started successfully
3. cloudflared.service: waiting for martin.service
4. cloudflared.service: starting
5. cloudflared.service: connected

### 4.4 Performance Baseline
Monitor over time to detect degradation:

```bash
# Count successful requests (HTTP 200)
journalctl -u martin.service --since "1 hour ago" | grep "200" | wc -l

# Track error rates
journalctl -u martin.service --since "1 hour ago" | grep -E "(4[0-9]{2}|5[0-9]{2})" | wc -l
```

## 5. Troubleshooting

### 5.1 Services Not Auto-Starting After Reboot
```bash
# Check if enabled
sudo systemctl is-enabled martin.service
sudo systemctl is-enabled cloudflared.service
# Should return "enabled"

# If not enabled:
sudo systemctl enable martin.service cloudflared.service

# Check boot logs
journalctl -b -0 | grep -E "(martin|cloudflared)" | head -20
```

### 5.2 Martin Won't Start
```bash
# Check logs for errors
journalctl -u martin.service --no-pager | tail -50

# Common issues:
# - Config file not found: verify /opt/stars/config/martin.yaml exists
# - Port in use: netstat -tlnp | grep 3000
# - Data directory permissions: ls -la /opt/stars/data
# - Insufficient memory: free -h
```

### 5.3 cloudflared Won't Connect
```bash
# Check logs
journalctl -u cloudflared.service --no-pager | tail -50

# Common issues:
# - Credentials file missing: ls -la /opt/stars/secrets/cloudflared/
# - Credentials file permissions wrong: stat /opt/stars/secrets/cloudflared/*.json
# - Martin not listening: netstat -tlnp | grep 3000
# - Network connectivity: ping 1.1.1.1
```

### 5.4 Remote Endpoint Not Responding (Local Works)
```bash
# Verify tunnel is connected
journalctl -u cloudflared.service --since "5 minutes ago" --no-pager

# Check DNS propagation
nslookup stars.optgeo.org
dig stars.optgeo.org +short

# Test tunnel locally first
curl -v http://localhost:3000/catalog

# Then test through tunnel (if you have curl access to cloudflared)
# Or use external tool: curl https://stars.optgeo.org/catalog

# If still failing, check Cloudflare dashboard for tunnel status
```

### 5.5 Restart Loop (Service Keeps Restarting)
```bash
# Check restart policy in service file
systemctl cat martin.service | grep -A3 "Restart="

# Check for repeated errors in logs
journalctl -u martin.service --no-pager | grep -i "error\|failed" | tail -20

# Typical causes:
# - Corrupted config file
# - Insufficient resources (memory/disk)
# - Missing data directory

# Temporary disable auto-restart to debug
sudo systemctl set-property martin.service Restart=no
# Fix the issue
# Then re-enable
sudo systemctl set-property martin.service Restart=on-failure
```

## 6. Planned Maintenance

### 6.1 Update Martin (When New Version Released)
```bash
# Build new Martin with experimental COG support
cargo install martin --features=unstable-cog

# Verify new binary
martin --version

# Stop service
sudo systemctl stop martin.service

# Restart (now using new binary)
sudo systemctl start martin.service

# Verify it started
sudo systemctl status martin.service
```

### 6.2 Update cloudflared
```bash
# Check for updates
sudo apt update
sudo apt list --upgradable | grep cloudflared

# Upgrade
sudo apt upgrade -y cloudflared

# Restart service
sudo systemctl restart cloudflared.service

# Verify
sudo systemctl status cloudflared.service
```

### 6.3 Update Data Files
```bash
# Place new .pmtiles or .cog.tiff in data/
# (No service restart needed; Martin auto-detects)

# To verify new data is served:
curl http://localhost:3000/catalog

# Check if new data appears in sources
```

## 7. Emergency Procedures

### 7.1 Immediate Shutdown
```bash
sudo systemctl stop martin.service cloudflared.service
```

Services will not auto-restart (they hit Restart=on-failure which respects manual stops).

### 7.2 Force Revert to Known-Good State
```bash
# Stop services
sudo systemctl stop martin.service cloudflared.service

# Restore from backup (see section 3.2)
sudo cp -r /opt/stars/backups/20260607_120000/config/* /opt/stars/config/
sudo cp -r /opt/stars/backups/20260607_120000/secrets/* /opt/stars/secrets/

# Restart
sudo systemctl start martin.service cloudflared.service

# Verify
curl http://localhost:3000/catalog
```

### 7.3 Collect Debug Information for Support
```bash
# Create diagnostic bundle
DEBUG_BUNDLE="/tmp/stars_debug_$(date +%Y%m%d_%H%M%S).tar.gz"

tar -czf "$DEBUG_BUNDLE" \
  /opt/stars/config/martin.yaml \
  /opt/stars/config/cloudflared/config.yaml \
  <(journalctl -u martin.service -n 100) \
  <(journalctl -u cloudflared.service -n 100) \
  <(sudo systemctl status martin.service cloudflared.service)

# This creates a bundle (without credentials) for debugging
echo "Debug bundle ready: $DEBUG_BUNDLE"
```

## 8. Monitoring Recommendations (Future Enhancement)

Suggested metrics to monitor for production:
- Service restart frequency (target: 0 per day)
- Tunnel connection stability (target: 99.9% uptime)
- HTTP error rate (target: < 1%)
- Response latency (baseline: < 500ms for typical PMTiles/COG requests)
- Disk usage growth (alert if > 80%)
- Memory usage spikes (investigate if > 500MB)
