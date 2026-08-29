# systemd Services for stars

> **Status note (2026-08-28, corrected later same day):** the system-level `martin.service`
> described below does not exist on production. Martin *is* supervised by systemd there,
> but as a **user-level** unit (`systemctl --user status martin`,
> `/home/stars/.config/systemd/user/martin.service`), not a system-level one — an earlier
> version of this note wrongly said no unit existed at all because only system scope had
> been checked. Manage it with `systemctl --user start/stop/restart martin`, never a bare
> `kill`/`pkill` on its PID (see KNOWN_FACTS.md's "Known failure mode" for why that leaves
> it in a `inactive (dead)`-but-actually-running-unmanaged state). `cloudflared.service`
> does exist and matches the shape described here, but with a different config path
> (`/etc/cloudflared/config.yml`) and a tunnel shared with other domains. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.

## 1. Service files in this repository
- systemd/martin.service
- systemd/cloudflared.service

## 2. Install service files

```bash
sudo cp /opt/stars/systemd/martin.service /etc/systemd/system/martin.service
sudo cp /opt/stars/systemd/cloudflared.service /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
```

## 3. Enable startup

```bash
sudo systemctl enable martin.service
sudo systemctl enable cloudflared.service
```

## 4. Start and check

```bash
sudo systemctl start martin.service
sudo systemctl start cloudflared.service
sudo systemctl status martin.service --no-pager
sudo systemctl status cloudflared.service --no-pager
```

## 5. Logs

```bash
journalctl -u martin.service -f
journalctl -u cloudflared.service -f
```

## 6. User and Permissions
Both services run under the `stars` user (system user, non-login shell):
- User: stars
- Group: stars
- WorkingDirectory: /opt/stars

Ensure permissions are set:

```bash
sudo chown -R stars:stars /opt/stars
sudo chmod 750 /opt/stars
sudo mkdir -p /opt/stars/secrets/cloudflared
sudo chmod 700 /opt/stars/secrets/cloudflared
```

Tunnel credentials (when placed) should have restricted permissions:

```bash
sudo chmod 600 /opt/stars/secrets/cloudflared/*.json
```

## 7. Dependency design
- martin.service starts after network-online.target.
- cloudflared.service starts after martin.service and network-online.target.
- Both services restart on failure.

## 8. Boot-to-Ready Verification (M3 Validation)

After reboot, verify that both services auto-start and are healthy.

### 8.1 After reboot, check service status
```bash
sudo systemctl status martin.service
sudo systemctl status cloudflared.service
```

Both should show:
- Status: **active (running)**
- Restart count: 0 (no restarts yet)

### 8.2 Verify Martin is listening
```bash
netstat -tlnp | grep 3000
# Should show: tcp 0 0 0.0.0.0:3000 0.0.0.0:* LISTEN <martin-pid>/martin
```

Or:

```bash
curl http://localhost:3000/catalog
# Should return 200 with JSON catalog
```

### 8.3 Verify tunnel is connected
```bash
# Check tunnel status in logs
journalctl -u cloudflared.service --no-pager | head -20
# Should show "connected to" or "routing to" messages
```

### 8.4 Verify public endpoint
```bash
# From external device or different network:
curl https://stars.optgeo.org/catalog
# Should return 200 with same JSON as localhost:3000
```

### 8.5 Boot-to-ready success criteria
- [x] martin.service is active and listening on 127.0.0.1:3000
- [x] cloudflared.service is active and connected
- [x] Local curl works: http://localhost:3000/catalog
- [x] Remote curl works: https://stars.optgeo.org/catalog
- [x] No restart loops in journalctl
- [x] Both services show Restart Count: 0
