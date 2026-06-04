# Roadmap

## Product Direction

Patchdeck is a Docker-only web UI for manually updating selected containers. It should not become an automatic updater, a general server-management suite, or an authorization system.

## Public Release Track

- [ ] Provide a public container image.
- [ ] Decide Docker CLI/Compose strategy for the image.
- [ ] Add a generic installation guide.
- [ ] Remove private sample data before repository publication.
- [ ] Add visible app version and release metadata.
- [ ] Add SemVer-based release workflow.

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
