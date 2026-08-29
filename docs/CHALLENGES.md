# Challenges To Tackle

## 1. Build Provenance and Compatibility
Challenge:
- Keep Martin experimental COG builds reproducible on latest Raspberry Pi OS.

Why it matters:
- Experimental support can change quickly and break compatibility.

Action:
- Define apt prerequisites and cargo-based install steps for reproducibility.
- Record a known-good Martin version/commit timeline as validation data.
- Add compatibility matrix for architecture and OS version.

## 2. Data Layout and Performance
Challenge:
- Optimize local storage and read patterns for PMTiles and COG serving.

Why it matters:
- I/O bottlenecks on Raspberry Pi hardware can degrade response time.

Action:
- Define recommended filesystem layout and storage class.
- Define COG profile guidance that aligns with Martin unstable COG expectations.
- Establish baseline performance checks for representative datasets.

## 3. Service Orchestration Without Caddy
Challenge:
- Build robust startup and recovery with only Martin + cloudflared + systemd.

Why it matters:
- Missing startup ordering or restart policy can lead to downtime.

Action:
- Define unit dependencies, restart policies, and health probes.
- Capture failure scenarios and recovery runbooks.

## 4. Secure Internet Publication
Challenge:
- Publish via cloudflared safely while minimizing exposed attack surface.

Why it matters:
- Tunnel credentials and endpoint configuration are high-value assets.

Action:
- Define secrets handling and file permissions.
- Define named tunnel configuration baseline and operational rotation steps.
- Define least-privilege execution users and directories.

## 5. Operability and Handover
Challenge:
- Keep operations simple enough for repeatable deployment and team handover.

Why it matters:
- Operational complexity slows iteration and increases incident risk.

Action:
- Write concise runbooks for install, start, restart, update, rollback.
- Add validation checklist for post-reboot health.
