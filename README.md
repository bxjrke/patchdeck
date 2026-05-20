# Patchdeck

Private early-stage project for a service-oriented homelab update hub.

Patchdeck tracks update availability across homelab services, exposes a web UI,
publishes optional Home Assistant MQTT update entities, and can later coordinate
approved update runs with health checks and rollback hooks.

The goal is not to be another Watchtower clone. Docker containers are one update
source, not the whole product.

## Initial Scope

- Configure services in the web UI.
- Configure global settings in the web UI:
  - update interval
  - MQTT enabled/disabled
  - MQTT discovery prefix and base topic
  - Docker auto-import enabled/disabled
- Import existing Docker containers through the Docker API where available.
- Publish status through HTTP APIs first, with MQTT/Home Assistant support next.
- Keep theme customization as a later UI feature.

## Planned Adapter Model

Patchdeck should grow around adapters:

- Docker/Compose containers
- Home Assistant container updates
- OpenClaw/npm package updates
- Linux package updates through SSH
- Git/Compose stack updates
- Future: Proxmox/LXC, custom scripts, webhooks

Each adapter should support the same rough lifecycle:

1. Check current version/status.
2. Check latest available version.
3. Provide release notes or a release URL where possible.
4. Offer a dry-run or impact preview where possible.
5. Run an approved update.
6. Run a post-update health check.
7. Record an audit entry.

## Safety Principles

- No secrets in repo or service config examples.
- Updating must be explicit unless a service is deliberately marked for auto-update.
- Docker socket access is powerful; keep the permission model visible.
- Prefer health checks and reversible hooks before unattended updates.

## Development

This repository currently contains the first minimal backend skeleton. The
existing homeserver proof-of-concept lives outside this repo and should be
ported gradually, not dumped in wholesale with local paths and secrets.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
uvicorn patchdeck.main:app --reload
```

Open: http://127.0.0.1:8000

