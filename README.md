# Patchdeck

Private early-stage project for a service-oriented homelab update hub.

Patchdeck tracks update availability across homelab services, exposes a web UI,
publishes optional Home Assistant MQTT update entities, and can run explicit
Docker/Compose updates for configured services. Docker is the first adapter, not
the whole product.

## Current Features

- FastAPI backend with file-backed settings and service configuration.
- Built-in responsive web UI for the service overview and settings.
- Docker scan/import through the local Docker socket.
- Docker/Compose metadata detection for container name, image, compose file,
  project directory, and compose service.
- Explicit per-service Docker Compose updates with a global update lock, progress
  state, audit log, and last-run state.
- Registry checks with digest/label heuristics and a local cache.
- Home Assistant MQTT discovery and command handling for update entities.
- Local icon cache for detected service icons, plus an `Icon Pfad` override for a
  local path or URL.
- Autosaving global settings and service settings in the web UI.
- Light/dark/system theme selection.

## Release Notes

Each service has a `Release Notes Quelle` field. It is optional.

Supported values:

- Empty: no release-notes link is shown.
- `homeassistant`: uses Patchdeck built-in Home Assistant release-notes lookup.
  This is currently the only service-specific template shipped by Patchdeck.
- A full `https://` or `http://` URL: shown as the release-notes link.
- A URL template with placeholders: Patchdeck replaces placeholders from the
  detected latest version.

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

## Safety Principles

- No secrets in repo or service config examples.
- Updating must be explicit unless a service is deliberately marked for auto-update
  in a future adapter.
- Docker socket access is powerful; keep the permission model visible.
- Prefer health checks and reversible hooks before unattended updates.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest
uvicorn patchdeck.main:app --reload
```

Open: http://127.0.0.1:8000

## Homeserver Deployment

On the Smartheim homeserver, Patchdeck is deployed as a Docker Compose stack:

```bash
docker compose -f /opt/stacks/patchdeck/docker-compose.yml up -d --build patchdeck
```

The live stack builds from `/home/bxjrke/projects/patchdeck` and stores state in
`/opt/docker/patchdeck`. Keep the repo current, run tests, then rebuild the
container so https://patchdeck.smartheim.eu receives the changes.

## Open TODOs

- Add authentication and authorization before any broader exposure.
- Add dry-run/update preview before update execution.
- Add pre-update and post-update hooks with health checks.
- Add rollback guidance or rollback hooks.
- Broaden adapters beyond Docker/Compose, for example Git/Compose stacks, Linux
  packages over SSH, and custom scripts.
- Improve registry/version handling for more image naming schemes.
- Add UI feedback for autosave success/failure.
- Add user-managed release-note helpers only when there is a clear reusable need;
  for now only Home Assistant has a built-in helper.
