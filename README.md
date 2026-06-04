# Patchdeck

Patchdeck is a small web UI for explicitly updating selected Docker Compose services on a Linux server and exposing those updates as Home Assistant MQTT update entities.

Its key feature is MQTT publishing for Home Assistant: Patchdeck can create one `update` entity per configured service, report installed/latest versions, and let Home Assistant trigger the same manual update action.

It is intentionally narrow in scope:

- Docker and Docker Compose only.
- No automatic updates.
- No authorization layer in Patchdeck itself.
- Updates are triggered one service at a time by a user who already controls the server.

Patchdeck is meant for private homelabs where the operator wants a comfortable web surface for selected container updates without running a broad auto-updater.

## Installation

The recommended installation path is Docker Compose with the published container image. See the [Docker deployment guide](docs/DOCKER.md) for the full setup, required volume mounts, and security notes.

## Current Features

- Service overview with current/latest version information where it can be detected.
- Home Assistant MQTT discovery for per-service `update` entities.
- MQTT state publishing for installed version, latest version, update progress, and release-note URLs.
- Optional Home Assistant-triggered install commands for services that allow updates.
- Docker scan/import via the local Docker socket.
- Docker/Compose metadata detection for container name, image, compose file, project directory, and compose service.
- Per-service update trigger using `docker compose pull` and `docker compose up -d --no-deps`.
- Global update lock and last-run/audit state.
- Local registry cache for latest-image checks.
- Local icon cache for detected service icons.
- Optional icon path override per service.
- Optional release-notes link per service.
- Autosaving settings UI.
- Version display in the UI footer.
- English UI with German translation.

## MQTT and Home Assistant

MQTT is disabled by default. Enable it in the settings UI or set both `PATCHDECK_MQTT_ENABLED=true` and `PATCHDECK_MQTT_HOST`. A configured host alone does not enable publishing.

When MQTT is active, Patchdeck publishes one Home Assistant `update` entity per configured service through MQTT discovery. Each entity reports the installed version, latest version, update availability, update progress, and an optional release-notes URL. If the service allows manual updates in Patchdeck, Home Assistant can trigger the same update action by sending the entity install command.

Default topics:

```text
homeassistant/update/patchdeck_<service-id>/config
patchdeck/<service-id>/state
patchdeck/<service-id>/latest_version
patchdeck/<service-id>/json
patchdeck/<service-id>/command
```

The discovery prefix and base topic can be changed in the settings UI. When MQTT is switched from active to inactive, Patchdeck clears retained discovery and state topics for the configured services so stale Home Assistant entities are removed instead of lingering as retained MQTT data.

## Release Notes

Each service has an optional release-notes source.

Supported values:

- Empty: no release-notes link is shown.
- `homeassistant`: uses Patchdeck built-in Home Assistant release-notes lookup. This is currently the only service-specific helper shipped by Patchdeck.
- A full `https://` or `http://` URL: shown as the release-notes link.
- A URL template with placeholders: Patchdeck replaces placeholders from the detected latest version.

Supported placeholders:

- `{version}`: raw detected version, for example `1.2.3`.
- `{version_url}`: URL-encoded version.
- `{major}`, `{minor}`, `{patch}`: dot-separated version parts when present.

Examples:

```text
homeassistant
https://github.com/example/app/releases/tag/{version}
https://example.test/changelog/{major}/{minor}
https://example.test/releases
```

## Docker Image

Patchdeck is designed to run as a container that controls the host Docker daemon through the Docker socket. The published image includes Patchdeck, Docker CLI, and Docker Compose v2. Images are published to GitHub Container Registry as `ghcr.io/bxjrke/patchdeck`.

Quick start:

```yaml
services:
  patchdeck:
    image: ghcr.io/bxjrke/patchdeck:0.1.1
    container_name: patchdeck
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - /your/own/path/patchdeck:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /your/compose/files:/your/compose/files
```

Patchdeck stores settings, service configuration, audit state, registry cache, and cached icons in `/data`. The host side can be any persistent directory, for example `/opt/docker/patchdeck:/data`, `/srv/patchdeck:/data`, or a named Docker volume like `patchdeck-data:/data`. The important part is the container path: keep it as `/data` unless you also change `PATCHDECK_DATA_DIR`.

The Compose-files mount is only needed for services that Patchdeck should update with `docker compose pull` and `docker compose up`. Patchdeck reads absolute Compose paths from Docker labels, such as `/srv/compose/media/docker-compose.yml`, and that same path must exist inside the Patchdeck container. If your Compose files live in `/srv/compose`, mount `/srv/compose:/srv/compose`. If they live in `/opt/stacks`, mount `/opt/stacks:/opt/stacks`. If you do not want Patchdeck to run Compose updates yet, you can omit this mount and still use the UI for discovery/status where Docker metadata is available.

Mounting `/var/run/docker.sock` gives Patchdeck control over the host Docker daemon. Only expose Patchdeck on a trusted private network or put it behind an authentication layer such as a reverse proxy.

More details: [Docker deployment](docs/DOCKER.md) and [Release process](docs/RELEASING.md).

## License

Patchdeck is released under the [MIT License](LICENSE).

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest
uvicorn patchdeck.main:app --reload
```

Open: http://127.0.0.1:8000

## Versioning

Patchdeck should use SemVer once releases begin:

- `0.x`: pre-release iteration, breaking changes allowed.
- `1.0.0`: first stable public image and documented install path.
- Patch releases: bug fixes only.
- Minor releases: backwards-compatible features.
- Major releases: breaking configuration or API changes.

