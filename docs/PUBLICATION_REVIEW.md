# Publication Review

Patchdeck is directionally publishable, but it is not ready for a public 1.0 release yet.

## Product Scope

Patchdeck should remain narrow:

- Docker and Docker Compose only.
- No automatic updates.
- No built-in authorization.
- One selected service update per user action.

## Image Readiness

The current Dockerfile can build the app image. The missing public-image decision is Docker tooling:

1. Bundle Docker CLI and Docker Compose in the image.
   - Better user experience.
   - More maintenance burden because Docker CLI/Compose versions must be tracked.

2. Require users to mount host Docker CLI and Compose plugin.
   - Matches the current development/deployment model.
   - Less portable because binary paths differ by distribution.

Recommendation before public release: bundle Docker CLI and Compose in the image or provide a very explicit compatibility matrix for host-binary mounts.

## Repository Readiness

Ready or mostly ready:

- Core FastAPI app exists.
- Docker scan/import exists.
- Manual per-service update flow exists.
- Local icon cache exists.
- Basic tests exist.
- README now avoids private deployment details.

Needs work before public release:

- Move UI translations out of inline JavaScript into standalone files.
- Add documented language contribution flow.
- Add release/version display in the UI.
- Add GitHub release and container publishing workflow.
- Decide image Docker CLI/Compose strategy.
- Add public install docs with generic Linux paths.
- Remove generated or local-only artifacts before making the repository public.
- Consider user-facing warnings about Docker socket privileges without framing Patchdeck as an auth/security product.

## Versioning

Use SemVer:

- Continue with `0.x` while configuration and install method can still change.
- Tag public images as both immutable versions, e.g. `0.2.0`, and moving tracks such as `0` or `latest` only when intentionally desired.
- Reserve `1.0.0` for the first stable public install path.
