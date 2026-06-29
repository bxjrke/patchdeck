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
    image: ghcr.io/bxjrke/patchdeck:0.3.5
    container_name: patchdeck
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - /your/own/path/patchdeck:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /your/compose/files:/your/compose/files
```

Open Patchdeck at `http://SERVER:8000`.

## Volumes

`/your/own/path/patchdeck:/data` stores Patchdeck state:

- `settings.json`
- `services.json`
- `audit.log`
- update lock and last-run state
- registry cache
- cached icons

The host path can be any persistent directory you choose, for example `/opt/docker/patchdeck:/data`, `/srv/patchdeck:/data`, or a named Docker volume like `patchdeck-data:/data`. The important part is the container path: keep it as `/data` unless you also change `PATCHDECK_DATA_DIR`.

`/var/run/docker.sock:/var/run/docker.sock` lets Patchdeck inspect containers and run Compose updates against the host Docker daemon.

`/your/compose/files:/your/compose/files` is optional and should be replaced with the real host directory that contains Compose files Patchdeck should update. There is no required `stacks` folder. Use whatever layout you already have. If your Compose files live in `/srv/compose`, mount `/srv/compose:/srv/compose`; if they live in `/opt/stacks`, mount `/opt/stacks:/opt/stacks`. Keeping the host path and container path identical is useful because Docker Compose labels usually contain absolute paths, and Patchdeck needs those paths to exist inside its container.

If you only want Patchdeck to discover containers and show update status at first, you can omit the Compose-files mount. Add it later when you want Patchdeck to run `docker compose pull` and `docker compose up` for selected services.

Patchdeck self-updates do not require a second long-running service. When you trigger a Patchdeck update from the UI, Patchdeck starts a temporary helper container through the mounted Docker socket. That helper inherits Patchdeck's mounts with `--volumes-from`, updates only the detected Patchdeck Compose service, waits for the replacement container to become healthy, writes the result to `/data`, and removes itself automatically.

Self-update requires Patchdeck itself to run as a Docker Compose service. Docker's Compose labels must contain absolute Compose file and project paths, and those paths must exist inside the Patchdeck container. Mount the directory containing Patchdeck's own Compose file at the same absolute path on the host and in the container.

## MQTT

MQTT stays disabled unless it is enabled in the settings UI or with `PATCHDECK_MQTT_ENABLED=true`. Setting `PATCHDECK_MQTT_HOST` alone configures the host but does not enable MQTT publishing.

When MQTT is active, Patchdeck publishes Home Assistant MQTT discovery for one `update` entity per configured service. The default discovery prefix is `homeassistant`, and the default base topic is `patchdeck`. Home Assistant sends update commands to `patchdeck/<service-id>/command` with the payload `install`; Patchdeck accepts that command only while MQTT is currently enabled and the service itself allows updates.

If MQTT is disabled after it was active, Patchdeck publishes empty retained discovery/state messages for its configured services to remove stale Home Assistant entities.

## Security

Mounting the Docker socket gives Patchdeck effective control over the host Docker daemon. Treat access to Patchdeck like access to Docker itself.

Recommended deployment:

- Keep Patchdeck on a private LAN or VPN.
- Put it behind a reverse proxy with authentication if it is reachable by more than trusted operators.
- Do not expose it directly to the public internet.
- Back up the `/data` volume before major upgrades.

## Image Tags

The release workflow publishes:

- `ghcr.io/bxjrke/patchdeck:0.3.5` for version tags like `v0.3.5`
- `ghcr.io/bxjrke/patchdeck:0.3` for the matching minor line
- `ghcr.io/bxjrke/patchdeck:main` for pushes to `main`
- `ghcr.io/bxjrke/patchdeck:sha-...` for immutable commit images

Use a version tag for normal installs. Use `main` only for testing unreleased changes.

## Architectures

The GitHub Actions workflow builds multi-arch images for:

- `linux/amd64`
- `linux/arm64`

This should cover common x86 servers, NAS systems, and ARM homelab machines.
