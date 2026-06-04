# Patchdeck

Patchdeck is a small web UI for explicitly updating selected Docker Compose services on a Linux server.

It is intentionally narrow in scope:

- Docker and Docker Compose only.
- No automatic updates.
- No authorization layer in Patchdeck itself.
- Updates are triggered one service at a time by a user who already controls the server.

Patchdeck is meant for private homelabs where the operator wants a comfortable web surface for selected container updates without running a broad auto-updater.

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

## Installation Status

Patchdeck is not release-ready yet. The current Dockerfile builds the application, but update execution still depends on Docker CLI and Docker Compose being available in the container. For a public image, this needs either:

- a documented compose setup that mounts the host Docker binary and Compose plugin, or
- a self-contained image that includes compatible Docker CLI and Compose tooling.

The second option is better for broad public use and is still open work.

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

## Road To Public Release

- Publish a working container image, preferably via GitHub Container Registry.
- Decide whether the image bundles Docker CLI/Compose or documents host-binary mounts.
- Move translations into standalone language files so new languages can be added by PR.
- Remove private example data from the repository before making it public.
- Add a public install guide based on a generic Linux server.
- Add UI feedback for autosave success/failure.
- Add release/version display in the UI.
