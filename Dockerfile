FROM docker:29.8.2-cli@sha256:b1805116a6a86cc591b5d5f60a910a0715cdcc9d18d866ad68b1457ead25c35c AS docker-cli

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS python-builder

ARG UV_VERSION=0.10.6

WORKDIR /app

RUN python -m pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

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
