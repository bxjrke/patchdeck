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
- Self-update support for Patchdeck itself when it runs from Docker Compose.
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

See the [Docker deployment guide](docs/DOCKER.md) for the Compose example, volume explanation, MQTT configuration, image tags, and security notes.

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

