# Roadmap

## Milestone 0: Project Shape

- [x] Create private GitHub repository.
- [x] Add initial backend skeleton.
- [x] Document product direction and safety model.
- [ ] Decide final name before public release.

## Milestone 1: Configurable Core

- [x] Persistent settings store.
- [x] CRUD API for services.
- [x] Web UI for service configuration.
- [x] Web UI for global settings.
- [x] Autosave for global and service settings.
- [x] Basic audit log.

## Milestone 2: Docker Import

- [x] Docker API client.
- [x] Manual import of Docker containers.
- [x] Detect Compose project/service labels.
- [x] Let users accept imported services.
- [x] Store image, container, compose project, compose file, service name, and update metadata.
- [x] Cache detected service icons locally.

## Milestone 3: MQTT / Home Assistant

- [x] MQTT settings UI.
- [x] Home Assistant MQTT discovery for update entities.
- [x] Publish installed/latest version state.
- [x] Publish release URL and JSON attributes.
- [x] Support install command through MQTT only when explicitly enabled.

## Milestone 4: Update Execution

- [x] Docker/Compose update adapter independent of Watchtower.
- [ ] Dry-run/update preview.
- [ ] Pre-update hook.
- [ ] Post-update health check.
- [x] Update progress tracking.
- [ ] Rollback guidance or hook support.

## Release Notes

- [x] Built-in Home Assistant release-notes helper.
- [x] Custom fixed release-notes URLs per service.
- [x] Custom URL templates with `{version}`, `{version_url}`, `{major}`, `{minor}`, and `{patch}`.
- [ ] UI preview/test action for release-notes links.

## Later

- [x] Dark/light/system theme.
- [ ] Per-user auth.
- [ ] Notification channels.
- [ ] Linux package update adapter.
- [ ] Git/Compose stack update adapter.
- [ ] Public release hardening.
