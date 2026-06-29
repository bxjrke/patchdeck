# Patchdeck

Patchdeck is a focused web UI for manually updating selected Docker Compose services on a Linux server. It discovers Compose metadata from Docker, shows available image updates, runs controlled service updates, and can expose the same actions as Home Assistant MQTT update entities.

Patchdeck is designed for private homelabs:

- Docker and Docker Compose only.
- Updates run only when explicitly requested.
- One selected service is updated at a time.
- No built-in authentication or authorization layer.
- No additional host service is required for Patchdeck self-updates.

> [!WARNING]
> Mounting the Docker socket gives Patchdeck effective administrative control over the host. Keep it on a trusted network or behind authenticated access; do not expose it directly to the public internet.

## Quick Start

Create a Compose file:

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

Replace the two example host paths, then start Patchdeck:

```bash
docker compose up -d
```

Open `http://SERVER:8000`, scan Docker, import the services you want to manage, and enable updates only for the selected services.

The Compose-files mount is optional for discovery and update-status checks, but required before Patchdeck can run Compose updates. Keep host and container paths identical where possible because Docker Compose labels normally contain absolute host paths.

See the [Docker deployment guide](docs/DOCKER.md) for volume details, MQTT setup, image tags, architectures, and deployment guidance.

## Features

- Service overview with installed and latest image versions where they can be detected.
- Manual updates through `docker compose pull` and `docker compose up -d --no-deps`.
- Docker scan/import with automatic Compose project, file, service, image, and container detection.
- Safe Patchdeck self-updates through an ephemeral helper container.
- Persistent update progress, last-run results, audit log, and global update lock.
- Registry-result caching and manual forced refresh.
- Home Assistant MQTT discovery with one `update` entity per configured service.
- MQTT install commands, installed/latest versions, release-note links, and update progress.
- Local icon cache with optional per-service icon overrides.
- Optional release-note URLs and version-based URL templates.
- English UI with German translation.
- Multi-architecture images for `linux/amd64` and `linux/arm64`.

## Translations

Patchdeck's default UI copy is English. Translations live in standalone JSON files under `src/patchdeck/static/i18n/`, with one file per language code, for example `en.json` and `de.json`.

To add a language by pull request:

1. Copy `src/patchdeck/static/i18n/en.json` to a new file named with a simple language code such as `fr.json` or `pt-BR.json`.
2. Translate every value, keep every key unchanged, and make sure the new file has the same key set as `en.json`.
3. Add an option for the language in the settings page language selector in `src/patchdeck/main.py`.
4. Run the test suite before opening the pull request.

## Self-Updates

Patchdeck updates itself without a second permanent service or a separate host installation.

When a self-update is requested, Patchdeck starts a temporary container named:

```text
patchdeck-self-update-helper-<job-id>
```

The helper inherits Patchdeck's existing mounts, validates the running Patchdeck container and its Compose labels, pulls the image, recreates only the Patchdeck Compose service, waits for the replacement container to become healthy, and writes the result to `/data`. It then removes itself automatically.

The helper runs independently from the Patchdeck app container, so stopping the old app container does not interrupt the Compose recreate operation.

Self-updates require:

- the Docker socket mounted read-write;
- Patchdeck itself running as a Docker Compose service;
- absolute Compose file and project paths in Docker's Compose labels;
- Patchdeck's Compose files available inside the container at those same paths;
- persistent `/data` storage.

## MQTT and Home Assistant

MQTT is optional and disabled by default. Enable it in the settings UI or set:

```text
PATCHDECK_MQTT_ENABLED=true
PATCHDECK_MQTT_HOST=your-mqtt-broker
```

A configured MQTT host alone does not enable publishing.

When active, Patchdeck publishes one Home Assistant `update` entity per configured service. Entities can report the installed version, latest version, update availability, release-note URL, and update progress. If updates are enabled for the service, Home Assistant can trigger the same manual update action.

Default topics:

```text
homeassistant/update/patchdeck_<service-id>/config
patchdeck/<service-id>/state
patchdeck/<service-id>/latest_version
patchdeck/<service-id>/json
patchdeck/<service-id>/command
```

The JSON topic is the Home Assistant entity state topic and includes `in_progress` and `update_percentage`. The plain-string `/state` topic remains available for compatibility with other consumers.

When MQTT is disabled after being active, Patchdeck clears its retained discovery and state messages so stale Home Assistant entities do not linger.

## Release Notes

Each service can optionally provide a release-notes source:

- Empty: no release-notes link.
- `homeassistant`: Patchdeck's built-in Home Assistant release-notes lookup.
- A fixed `https://` or `http://` URL.
- A URL template containing `{version}`, `{version_url}`, `{major}`, `{minor}`, or `{patch}`.

Examples:

```text
homeassistant
https://github.com/example/app/releases/tag/{version}
https://example.test/changelog/{major}/{minor}
```

## Security

Mounting `/var/run/docker.sock` gives Patchdeck effective control over the host Docker daemon. Treat access to Patchdeck like administrative access to the server.

Recommended deployment:

- Keep Patchdeck on a private LAN or VPN.
- Use a reverse proxy with authentication if more than trusted operators can reach it.
- Do not expose Patchdeck directly to the public internet.
- Enable update actions only for services you intend Patchdeck to manage.
- Back up `/data` before major upgrades.

Patchdeck intentionally does not implement its own user or permission system.

## Container Images

Images are published at:

```text
ghcr.io/bxjrke/patchdeck
```

Use a versioned tag for normal installations. The `main` tag tracks unreleased development and is intended for testing.

Release and deployment details:

- [Docker deployment guide](docs/DOCKER.md)
- [Release history](https://github.com/bxjrke/patchdeck/releases)
- [Roadmap](ROADMAP.md)

## License

Patchdeck is released under the [MIT License](LICENSE).
