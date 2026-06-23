# Releasing Patchdeck

Patchdeck publishes container images to GitHub Container Registry through `.github/workflows/container.yml`.

## One-time GitHub Setup

1. Push the repository to GitHub.
2. Ensure GitHub Actions is enabled for the repository.
3. Ensure workflow permissions allow packages to be written. The workflow requests `packages: write` and uses the built-in `GITHUB_TOKEN`.
4. After the first successful image push, open the package page for `patchdeck` on GitHub and make the package public if the repository should be publicly installable.

No separate GHCR token is required for the included workflow.

## Release Checklist

1. Update the project version in `pyproject.toml`.
2. Update `src/patchdeck/__init__.py` and the FastAPI/UI-visible version.
3. Update the OCI version label in `Dockerfile`.
4. Update the version tag in `README.md` and `deploy/docker-compose.example.yml`.
5. Run tests locally:

```bash
.venv/bin/pytest
```

6. Build the image locally:

```bash
docker build -t patchdeck:test .
```

7. Check Docker Compose inside the image:

```bash
docker run --rm patchdeck:test docker compose version
```

8. Check the app imports in the image:

```bash
docker run --rm patchdeck:test python -c "from patchdeck.main import app, healthz; print(app.title, healthz())"
```

9. Commit the release changes.
10. Create and push a SemVer tag prefixed with `v`:

```bash
git tag v0.3.3
git push origin main
git push origin v0.3.3
```

The tag push publishes `ghcr.io/bxjrke/patchdeck:0.3.3` and `ghcr.io/bxjrke/patchdeck:0.3`.

## Workflow Behavior

Pull requests build the image but do not push it. Pushes to `main` publish a `main` image. Version tags publish SemVer image tags.

The workflow builds for `linux/amd64` and `linux/arm64` using Docker Buildx and QEMU.

## Before a Public Announcement

- Confirm the GHCR package visibility is public.
- Test the published image on a clean host with a real Compose stack mounted under the same path inside the Patchdeck container.
- Review the README security warning around `/var/run/docker.sock`.
