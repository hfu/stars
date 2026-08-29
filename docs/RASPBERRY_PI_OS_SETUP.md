# Raspberry Pi OS Setup Baseline

> **Status note (2026-08-28):** this describes a target setup, not the current state of
> the production host. See [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A for what is
> actually installed and running on `spacex.optgeo.org` today.

## 1. Scope
This document defines the baseline setup for latest Raspberry Pi OS to run:
- Martin with experimental COG support
- cloudflared named tunnel
- systemd startup services

## 2. Install prerequisites with apt
Run:

```bash
sudo apt update
sudo apt install -y \
  ca-certificates \
  curl \
  git \
  build-essential \
  pkg-config \
  clang \
  cmake \
  libssl-dev \
  rustc \
  cargo \
  gdal-bin \
  libgdal-dev
```

Why:
- rustc and cargo are required to build Martin from source with feature flags.
- build-essential, clang, cmake, pkg-config, and libssl-dev are common Rust native build dependencies.
- gdal-bin and libgdal-dev support COG validation and geospatial workflows.

## 3. Install Martin experimental COG build
Run:

```bash
cargo install martin --features=unstable-cog
```

Verify:

```bash
martin --help
martin --version
```

## 4. cloudflared baseline
Use named tunnel mode.

Install cloudflared (Debian package via Cloudflare repository):

```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install -y cloudflared
```

Planned service naming:
- martin.service
- cloudflared.service

DNS and TLS authority:
- Cloudflare for stars.optgeo.org

## 5. Create `stars` user for service execution

```bash
sudo useradd -r -s /usr/sbin/nologin -d /opt/stars -m stars
```

Verify:

```bash
id stars
```

## 6. Clone repository and set permissions

```bash
sudo git clone <repo-url> /opt/stars
sudo chown -R stars:stars /opt/stars
sudo chmod 750 /opt/stars
```

## 6.1 Create and protect secrets directory

```bash
sudo mkdir -p /opt/stars/secrets/cloudflared
sudo chown stars:stars /opt/stars/secrets/cloudflared
sudo chmod 700 /opt/stars/secrets/cloudflared
```

Tunnel credentials will be placed here (see CLOUDFLARED_NAMED_TUNNEL.md).

## 7. Notes for latest Raspberry Pi OS
- Because this is an experimental project, track package versions in deployment logs.
- If apt-provided rustc/cargo is too old for a future Martin release, document and adopt a controlled rust toolchain update path.
- Keep installation logs so the exact setup can be reproduced on another host.
- The `stars` user is system-only (nologin) and should not have interactive shell access.
