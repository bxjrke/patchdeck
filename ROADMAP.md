# Roadmap

## Milestone 0: Project Shape

- [x] Create private GitHub repository.
- [x] Add initial backend skeleton.
- [x] Document product direction and safety model.
- [ ] Decide final name before public release.

## Milestone 1: Configurable Core

- [ ] Persistent settings store.
- [ ] CRUD API for services.
- [ ] Web UI for service configuration.
- [ ] Web UI for global settings.
- [ ] Basic audit log.

## Milestone 2: Docker Import

- [ ] Docker API client.
- [ ] Auto-import running containers.
- [ ] Detect Compose project/service labels.
- [ ] Let users accept/reject imported services.
- [ ] Store image, container, compose project, and update policy metadata.

## Milestone 3: MQTT / Home Assistant

- [ ] MQTT settings UI.
- [ ] Home Assistant MQTT discovery for update entities.
- [ ] Publish installed/latest version state.
- [ ] Publish release URL and JSON attributes.
- [ ] Support install command through MQTT only when explicitly enabled.

## Milestone 4: Update Execution

- [ ] Docker/Compose update adapter independent of Watchtower.
- [ ] Dry-run/update preview.
- [ ] Pre-update hook.
- [ ] Post-update health check.
- [ ] Update progress tracking.
- [ ] Rollback guidance or hook support.

## Later

- [ ] Dark/light theme.
- [ ] Per-user auth.
- [ ] Notification channels.
- [ ] Linux package update adapter.
- [ ] Git/Compose stack update adapter.
- [ ] Public release hardening.

