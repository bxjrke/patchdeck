# Docker Deployment

Patchdeck is published as a self-contained container image at:

```text
ghcr.io/bxjrke/patchdeck
```

The image contains:

- Patchdeck and its Python runtime dependencies
- Docker CLI
- Docker Compose v2 plugin
- A `/healthz` healthcheck
- `/data` as the default persistent data directory

## Compose Example

```yaml
services:
  patchdeck:
    image: ghcr.io/bxjrke/patchdeck:0.1.1
    container_name: patchdeck
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - patchdeck-data:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks

volumes:
  patchdeck-data:
```

Open Patchdeck at `http://SERVER:8000`.

## Volumes

`patchdeck-data:/data` stores Patchdeck state:

- `settings.json`
- `services.json`
- `audit.log`
- update lock and last-run state
- registry cache
- cached icons

The Dockerfile sets `PATCHDECK_DATA_DIR=/data`, so the Compose file does not need an `environment` entry for normal deployments. A volume alone provides storage; `PATCHDECK_DATA_DIR` tells Patchdeck which path to use. Because the image default already points to `/data`, the volume is enough.

`/var/run/docker.sock:/var/run/docker.sock` lets Patchdeck inspect containers and run Compose updates against the host Docker daemon.

`/opt/stacks:/opt/stacks` is an example mount for Compose projects. Replace it with the directory that contains your own Compose files. Keep host and container paths identical whenever possible. Patchdeck discovers absolute Compose paths from Docker labels, and those paths must exist inside the Patchdeck container.

## MQTT

MQTT stays disabled unless it is enabled in the settings UI or with `PATCHDECK_MQTT_ENABLED=true`. Setting `PATCHDECK_MQTT_HOST` alone configures the host but does not enable MQTT publishing.

## Security

Mounting the Docker socket gives Patchdeck effective control over the host Docker daemon. Treat access to Patchdeck like access to Docker itself.

Recommended deployment:

- Keep Patchdeck on a private LAN or VPN.
- Put it behind a reverse proxy with authentication if it is reachable by more than trusted operators.
- Do not expose it directly to the public internet.
- Back up the `/data` volume before major upgrades.

## Image Tags

The release workflow publishes:

- `ghcr.io/bxjrke/patchdeck:0.1.1` for version tags like `v0.1.1`
- `ghcr.io/bxjrke/patchdeck:0.1` for the matching minor line
- `ghcr.io/bxjrke/patchdeck:main` for pushes to `main`
- `ghcr.io/bxjrke/patchdeck:sha-...` for immutable commit images

Use a version tag for normal installs. Use `main` only for testing unreleased changes.

## Architectures

The GitHub Actions workflow builds multi-arch images for:

- `linux/amd64`
- `linux/arm64`

This should cover common x86 servers, NAS systems, and ARM homelab machines.
