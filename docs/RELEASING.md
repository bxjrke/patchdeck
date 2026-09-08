# Releasing Patchdeck

Patchdeck publishes container images to GitHub Container Registry through `.github/workflows/container.yml`.

## One-time GitHub Setup

1. Push the repository to GitHub.
2. Ensure GitHub Actions is enabled for the repository.
3. Ensure workflow permissions allow packages to be written. The workflow requests `packages: write` and uses the built-in `GITHUB_TOKEN`.
4. After the first successful image push, open the package page for `patchdeck` on GitHub and make the package public if the repository should be publicly installable.

No separate GHCR token is required for the included workflow.

## Release Checklist

1. Update the project version in `pyproject.toml`. Installed package metadata, FastAPI, and the UI read this value; there is no second source-code version constant.
2. Refresh and verify the dependency lock:

```bash
uv lock
uv sync --locked --extra dev
```

3. Update the version tag in `README.md`, `docs/DOCKER.md`, and `deploy/docker-compose.example.yml`.
4. Run all local quality gates:

```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync mypy src/patchdeck
```

5. Build the image locally with the release version as its OCI label:

```bash
docker build --build-arg PATCHDECK_VERSION=0.6.0 -t patchdeck:test .
```

6. Check Docker Compose inside the image:

```bash
docker run --rm patchdeck:test docker compose version
```

7. Check the app and packaged browser assets inside the image:

```bash
docker run --rm patchdeck:test python -c "from importlib.resources import files; from patchdeck import __version__; print(__version__, files('patchdeck').joinpath('static/common.js').is_file())"
```

8. Confirm the OCI label:

```bash
docker image inspect patchdeck:test --format '{{ index .Config.Labels "org.opencontainers.image.version" }}'
```

9. Commit the release changes.
10. Create and push a SemVer tag prefixed with `v`:

```bash
git tag v0.6.0
git push origin main
git push origin v0.6.0
```

The tag push publishes `ghcr.io/bxjrke/patchdeck:0.6.0` and `ghcr.io/bxjrke/patchdeck:0.6`.

## Workflow Behavior

Pull requests first run tests, Ruff, and Mypy on Python 3.11 and 3.12, then build the image without pushing it. Pushes to `main` publish a `main` image. Version tags publish SemVer image tags.

The workflow builds for `linux/amd64` and `linux/arm64` using Docker Buildx and QEMU. Published images include SBOM and provenance attestations; workflow actions and base images are pinned.

## Before a Public Announcement

- Confirm the GHCR package visibility is public.
- Test the published image on a clean host with a real Compose stack mounted under the same path inside the Patchdeck container.
- Review the README security warning around `/var/run/docker.sock`.
