# stars User and Secrets Setup

> **Status note (2026-08-28):** target design, not applied. The `stars` account on
> production is a regular sudo-capable login user (SSH access works directly as `stars`),
> not the nologin system user described below, and there is no `/opt/stars` checkout. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.

**NOTE:** This document has been partially consolidated into:
- RASPBERRY_PI_OS_SETUP.md (sections 5-6: user creation and directory setup)
- SYSTEMD_SERVICES.md (section 6: permissions)
- CLOUDFLARED_NAMED_TUNNEL.md (sections 2-3: secrets placement)

Use this document as a consolidated reference checklist for user and secrets setup.

## 1. Create stars system user

On Raspberry Pi OS:

```bash
sudo useradd -r -s /usr/sbin/nologin -d /opt/stars -m stars
```

Verify:

```bash
id stars
```

## 2. Repository placement and ownership

```bash
sudo git clone <this repo> /opt/stars
sudo chown -R stars:stars /opt/stars
sudo chmod 750 /opt/stars
```

## 3. Secrets directory for cloudflared credentials

```bash
sudo mkdir -p /opt/stars/secrets/cloudflared
sudo chown stars:stars /opt/stars/secrets/cloudflared
sudo chmod 700 /opt/stars/secrets/cloudflared
```

Place tunnel credentials JSON at:

```
/opt/stars/secrets/cloudflared/<TUNNEL_UUID>.json
```

Restrict permissions:

```bash
sudo chmod 600 /opt/stars/secrets/cloudflared/<TUNNEL_UUID>.json
```

## 4. Martin binary (installed via cargo)

After building Martin:

```bash
# Verify location
which martin

# Should be available on system PATH:
martin --version
```

systemd will invoke Martin as the `stars` user via `/usr/local/bin/martin` (or wherever cargo installed it).

## 5. cloudflared binary

After installing cloudflared via apt:

```bash
which cloudflared
cloudflared --version
```

Should be available at `/usr/bin/cloudflared`.

## 6. Configuration

Edit `config/cloudflared/config.yaml` with the real tunnel UUID (see CLOUDFLARED_NAMED_TUNNEL.md):

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /opt/stars/secrets/cloudflared/<YOUR_TUNNEL_UUID>.json
```

## 7. Pre-systemd Validation Checklist

Before enabling systemd services, verify:

- [ ] stars user exists and cannot log in: `id stars`
- [ ] /opt/stars is owned by stars and readable: `ls -la /opt/stars`
- [ ] Martin is executable: `martin --version`
- [ ] cloudflared is executable: `cloudflared --version`
- [ ] Tunnel credentials exist: `sudo ls -la /opt/stars/secrets/cloudflared/`
- [ ] Credentials are 600 mode: `stat /opt/stars/secrets/cloudflared/*.json | grep Access`
- [ ] config/cloudflared/config.yaml has correct tunnel UUID: `grep "tunnel:" /opt/stars/config/cloudflared/config.yaml`
- [ ] Manual Martin test works: `sudo -u stars martin --config /opt/stars/config/martin.yaml` (then Ctrl+C after startup)
- [ ] Manual cloudflared test works: `sudo -u stars cloudflared --config /opt/stars/config/cloudflared/config.yaml tunnel run` (briefly)

Once all checks pass, proceed to SYSTEMD_SERVICES.md for service installation and boot testing.
