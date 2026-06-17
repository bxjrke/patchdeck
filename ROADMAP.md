# Roadmap

## Product Direction

Patchdeck is a Docker-only web UI for manually updating selected containers. It should not become an automatic updater, a general server-management suite, or an authorization system.

## Release Blockers

- [x] Make the GHCR package public and verify anonymous pulls.
- [x] Fix MQTT publishing when MQTT is disabled. The UI can show MQTT as inactive while Patchdeck still publishes MQTT messages; disabled MQTT must fully suppress MQTT publishing and background MQTT behavior.

## Public Release Track

- [x] Provide a public multi-arch container image via GitHub Container Registry.
- [x] Bundle Docker CLI and Docker Compose in the image instead of relying on host-binary mounts.
- [x] Add a generic Docker installation guide.
- [x] Add SemVer-based container release workflow.
- [x] Choose and add a project license before wider public announcement.
- [x] Remove private sample data before repository publication.
- [x] Add visible app version and release metadata.

## Core Docker Flow

- [x] Persistent settings store.
- [x] CRUD API for services.
- [x] Web UI for service configuration.
- [x] Web UI for global settings.
- [x] Autosave for global and service settings.
- [x] Docker API client.
- [x] Manual Docker scan/import.
- [x] Detect Compose project/service labels.
- [x] Store image, container, compose project, compose file, service name, and update metadata.
- [x] Trigger one selected Docker Compose service update at a time.
- [ ] Fix Patchdeck self-update orchestration. Current self-updates can pull the new image and stop the old container, but the background `docker compose up` process may be killed with the old container before the replacement container starts, leaving the new container in `Created`.
- [x] Global update lock and last-run/audit state.
- [x] Cache detected service icons locally.

## Release Notes

- [x] Built-in Home Assistant release-notes helper.
- [x] Custom fixed release-notes URLs per service.
- [x] Custom URL templates with `{version}`, `{version_url}`, `{major}`, `{minor}`, and `{patch}`.
- [ ] UI preview/test action for release-notes links.

## Internationalization

- [x] English and German UI strings exist.
- [ ] Move translations out of inline JavaScript into standalone language files.
- [ ] Document how to add a new language by pull request.
- [ ] Ensure source code and default UI copy are English-only.

## Later

- [ ] Improve registry/version handling for more image naming schemes.
- [ ] Add UI feedback for autosave success/failure.
- [ ] Add update dry-run/preview if Docker tooling allows it cleanly.
- [ ] Public release hardening and documentation pass.
