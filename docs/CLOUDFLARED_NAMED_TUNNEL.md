# cloudflared Named Tunnel Setup

> **Status note (2026-08-28):** describes a target dedicated tunnel at
> `/opt/stars/config/cloudflared/config.yaml`. In production, cloudflared is real and
> systemd-managed, but its config is at `/etc/cloudflared/config.yml` (root-owned) and
> the tunnel is **shared** with `depot.optgeo.org` and SSH routing for
> `spacex.optgeo.org` — not dedicated to stars. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A before touching it.

## 1. Prerequisites
- Cloudflare account with DNS authority for stars.optgeo.org
- cloudflared CLI installed on Raspberry Pi OS host
- Repository checked out at /opt/stars
- stars user created (see RASPBERRY_PI_OS_SETUP.md)

## 2. Repository Layout for secrets

Create and protect secrets directory:

```bash
sudo mkdir -p /opt/stars/secrets/cloudflared
sudo chown stars:stars /opt/stars/secrets/cloudflared
sudo chmod 700 /opt/stars/secrets/cloudflared
```

Expected layout:

```
/opt/stars/
├── config/
│   ├── martin.yaml                  (local, tracked by .gitignore)
│   └── cloudflared/
│       └── config.yaml              (template, edited locally)
└── secrets/
    └── cloudflared/
        └── <TUNNEL_UUID>.json       (credentials, never committed)
```

## 3. Tunnel Bootstrap (One-Time)

### 3.1 Create tunnel
Run as regular user (not stars):

```bash
cloudflared tunnel login
```

This creates `~/.cloudflared/cert.pem` for Cloudflare account authentication.

Create the tunnel:

```bash
cloudflared tunnel create stars
```

Output includes:
- Tunnel UUID
- Credentials file location (usually `~/.cloudflared/<UUID>.json`)

Save the UUID for next steps.

### 3.2 Configure tunnel in repository
Edit `config/cloudflared/config.yaml`:

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /opt/stars/secrets/cloudflared/<YOUR_TUNNEL_UUID>.json
```

### 3.3 Place credentials securely
Copy tunnel credentials to secrets directory:

```bash
sudo cp ~/.cloudflared/<TUNNEL_UUID>.json /opt/stars/secrets/cloudflared/
sudo chown stars:stars /opt/stars/secrets/cloudflared/<TUNNEL_UUID>.json
sudo chmod 600 /opt/stars/secrets/cloudflared/<TUNNEL_UUID>.json
```

Verify:

```bash
ls -la /opt/stars/secrets/cloudflared/
```

## 4. DNS Route (One-Time)

Create DNS route in Cloudflare (maps hostname to tunnel):

```bash
cloudflared tunnel route dns stars stars.optgeo.org
```

Verify in Cloudflare dashboard:
- Go to **Cloudflare Dashboard → stars.optgeo.org → DNS → Records**
- Should see a CNAME record pointing to your tunnel

## 5. Local Test Before systemd

### 5.1 Start Martin separately (Terminal 1)
```bash
martin --config /opt/stars/config/martin.yaml
```

### 5.2 Test tunnel in separate terminal (Terminal 2)
```bash
cloudflared --config /opt/stars/config/cloudflared/config.yaml tunnel run
```

### 5.3 Verify remote access
In a third terminal (or on another device):

```bash
# Check via tunnel (public)
curl https://stars.optgeo.org/catalog

# Should match local access:
curl http://localhost:3000/catalog
```

### 5.4 Check tunnel status
```bash
cloudflared tunnel list
```

## 6. Troubleshooting

### Tunnel not routing traffic
```bash
# Check DNS resolution
nslookup stars.optgeo.org
# Should return Cloudflare IP (e.g., 104.16.x.x)

# Check tunnel credentials
cloudflared tunnel info stars
```

### Credentials permission denied
```bash
# Verify stars user can read credentials
sudo -u stars ls -la /opt/stars/secrets/cloudflared/
```

### Martin endpoint unreachable
```bash
# Verify Martin is listening on 127.0.0.1:3000
netstat -tlnp | grep 3000

# Verify config.yaml ingress points to correct service
grep "service:" /opt/stars/config/cloudflared/config.yaml
```

## 7. Next Steps
- Install systemd services (see SYSTEMD_SERVICES.md)
- Enable auto-start on boot
- Monitor logs: `journalctl -u cloudflared.service -f`
