# Patchdeck

Patchdeck is a small web UI for explicitly updating selected Docker Compose services on a Linux server.

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
- Docker scan/import via the local Docker socket.
- Docker/Compose metadata detection for container name, image, compose file, project directory, and compose service.
- Per-service update trigger using `docker compose pull` and `docker compose up -d --no-deps`.
- Global update lock and last-run/audit state.
- Local registry cache for latest-image checks.
- Local icon cache for detected service icons.
- Optional icon path override per service.
- Optional release-notes link per service.
- Autosaving settings UI.
- English UI with German translation.

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
    image: ghcr.io/bxjrke/patchdeck:0.1.0
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

Patchdeck stores settings, service configuration, audit state, registry cache, and cached icons in `/data`. The image already sets `PATCHDECK_DATA_DIR=/data`, so no environment variable is required for the default Docker setup. Override it only when using a different data path.

Mount every host directory that contains Compose files Patchdeck should update. The mount path inside the Patchdeck container should match the host path because Docker Compose labels usually store absolute project paths. For example, if a service was started from `/opt/stacks/media/compose.yaml`, mount `/opt/stacks:/opt/stacks`.

Mounting `/var/run/docker.sock` gives Patchdeck control over the host Docker daemon. Only expose Patchdeck on a trusted private network or put it behind an authentication layer such as a reverse proxy.

More details: [Docker deployment](docs/DOCKER.md) and [Release process](docs/RELEASING.md).

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

