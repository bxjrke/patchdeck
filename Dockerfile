FROM docker:29.2.1-cli AS docker-cli

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Patchdeck" \
      org.opencontainers.image.description="A small web UI for explicitly updating selected Docker Compose services." \
      org.opencontainers.image.source="https://github.com/bxjrke/patchdeck" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="0.1.1"

WORKDIR /app

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --root-user-action=ignore .

ENV PATCHDECK_DATA_DIR=/data \
    PATCHDECK_DOCKER_BIN=/usr/local/bin/docker \
    DOCKER_CONFIG=/tmp/.docker

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/healthz\", timeout=3).read()"]

CMD ["uvicorn", "patchdeck.main:app", "--host", "0.0.0.0", "--port", "8000"]
