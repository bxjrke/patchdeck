FROM docker:29.2.1-cli@sha256:cab69e2d0a1a2ea9a1ce1060252f439e83483ae41ec09317aecb33b08a0656a5 AS docker-cli

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS python-builder

ARG UV_VERSION=0.10.6

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

ARG PATCHDECK_VERSION=dev

LABEL org.opencontainers.image.title="Patchdeck" \
      org.opencontainers.image.description="A small web UI for explicitly updating selected Docker Compose services." \
      org.opencontainers.image.source="https://github.com/bxjrke/patchdeck" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${PATCHDECK_VERSION}" \
      io.patchdeck.version="${PATCHDECK_VERSION}"

WORKDIR /app

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY --from=python-builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATCHDECK_DATA_DIR=/data \
    PATCHDECK_DOCKER_BIN=/usr/local/bin/docker \
    DOCKER_CONFIG=/tmp/.docker

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/healthz\", timeout=3).read()"]

CMD ["uvicorn", "patchdeck.main:app", "--host", "0.0.0.0", "--port", "8000"]
