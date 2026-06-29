# Publication Review

Patchdeck is publicly available as a `0.x` homelab tool. The core image, release path, Docker deployment documentation, and manual update flow are in place. It is not a stable `1.0` yet.

## Product Scope

Patchdeck should remain narrow:

- Docker and Docker Compose only.
- No automatic updates.
- No built-in authorization.
- One selected service update per user action.
- No additional permanent service for Patchdeck self-updates.

## Image Readiness

Ready:

- The image bundles Patchdeck, Docker CLI, and Docker Compose.
- The image exposes `/healthz` and persists state in `/data`.
- GitHub Actions builds `linux/amd64` and `linux/arm64` images.
- Versioned tags are published from SemVer Git tags.
- The GHCR package is public and anonymous manifest access has been verified.

## Repository Readiness

Ready or mostly ready:

- Core FastAPI app exists.
- Docker scan/import exists.
- Manual per-service update flow exists.
- Patchdeck self-updates use an ephemeral helper container that survives the app-container recreate and removes itself afterward.
- MQTT disabled state no longer becomes enabled just because an MQTT host is configured.
- Local icon cache exists.
- Basic tests exist.
- MIT license exists.
- Public Docker deployment docs exist.

Still worth doing before `1.0`:

- Improve registry/version handling for more image naming schemes.
- Add UI feedback for autosave success/failure.

## Versioning

Use SemVer:

- Continue with `0.x` while configuration and install method can still change.
- Tag public images as immutable versions, for example `0.1.1`, and minor tracks such as `0.1`.
- Avoid moving already-pushed release tags.
- Reserve `1.0.0` for the first stable public install path.
