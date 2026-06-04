from __future__ import annotations

import json
import re
import socket
from urllib.parse import quote
from typing import Any

from .models import AdapterKind, DockerImportCandidate, ServiceConfig, UpdatePolicy

DOCKER_SOCKET = "/var/run/docker.sock"
GENERIC_ICON_SLUGS = {"docker", "linuxserver"}


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")
    return normalized[:64] or "container"


def icon_slug_for_service(name: str, image: str) -> str | None:
    haystack = f"{name} {image}".lower()
    matches = {
        "homeassistant": ("homeassistant", "home-assistant", "homeassistant"),
        "adguard": ("adguard", "adguardhome", "adguard"),
        "infisical": ("infisical",),
        "bazarr": ("bazarr",),
        "filebrowser": ("filebrowser", "file-browser", "file browser"),
        "jellyfin": ("jellyfin",),
        "jellyseerr": ("jellyseerr",),
        "radarr": ("radarr",),
        "sonarr": ("sonarr",),
        "prowlarr": ("prowlarr",),
        "lidarr": ("lidarr",),
        "qbittorrent": ("qbittorrent", "qbit"),
        "sabnzbd": ("sabnzbd",),
        "portainer": ("portainer",),
        "vaultwarden": ("vaultwarden", "bitwarden"),
        "paperless-ngx": ("paperless", "paperless-ngx"),
        "immich": ("immich",),
        "nextcloud": ("nextcloud",),
        "uptime-kuma": ("uptime-kuma", "uptimekuma"),
        "docker": ("docker",),
        "linuxserver": ("linuxserver",),
        "watchtower": ("watchtower",),
        "nginx": ("nginx",),
        "postgresql": ("postgres", "postgresql"),
        "mariadb": ("mariadb",),
        "redis": ("redis",),
        "grafana": ("grafana",),
        "prometheus": ("prometheus",),
    }
    for icon_slug, needles in matches.items():
        if any(needle in haystack for needle in needles):
            return icon_slug
    return None


def preferred_icon_slug(base: ServiceConfig | None, detected: str | None) -> str | None:
    existing = base.icon_slug if base else None
    if detected and (not existing or existing in GENERIC_ICON_SLUGS):
        return detected
    return existing or detected


def service_from_container(container: str, base: ServiceConfig | None = None, socket_path: str = DOCKER_SOCKET) -> ServiceConfig:
    details = docker_get(f"/containers/{quote(container, safe='')}/json", socket_path=socket_path)
    name = str(details.get("Name") or container).lstrip("/") or container
    config = details.get("Config") or {}
    labels = config.get("Labels") or {}
    image = str(config.get("Image") or details.get("Image") or "")
    compose_service = labels.get("com.docker.compose.service")
    compose_file = labels.get("com.docker.compose.project.config_files")
    compose_project_dir = labels.get("com.docker.compose.project.working_dir")
    service_id = base.id if base else slug(compose_service or name)
    display_name = (compose_service or name).replace("-", " ").replace("_", " ").title()
    detected_icon = icon_slug_for_service(compose_service or name, image)
    return ServiceConfig(
        id=service_id,
        name=(base.name if base and base.name else display_name),
        adapter=base.adapter if base else AdapterKind.DOCKER,
        enabled=True if base is None else base.enabled,
        update_policy=base.update_policy if base else UpdatePolicy.DISABLED,
        description=base.description if base else None,
        logo_url=base.logo_url if base else None,
        icon_slug=preferred_icon_slug(base, detected_icon),
        container=name,
        image=image,
        repo=base.repo if base else None,
        compose_file=compose_file or (base.compose_file if base else None),
        compose_project_dir=compose_project_dir or (base.compose_project_dir if base else None),
        compose_service=compose_service or (base.compose_service if base else None),
        release_notes=base.release_notes if base else None,
        update_enabled=base.update_enabled if base else False,
        metadata=base.metadata if base else {},
    )


def docker_get(path: str, socket_path: str = DOCKER_SOCKET) -> Any:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(5)
        sock.connect(socket_path)
        request = f"GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()

    raw = b"".join(chunks)
    header, _, body = raw.partition(b"\r\n\r\n")
    header_lines = header.splitlines()
    status_line = header_lines[0].decode("ascii", errors="replace") if header_lines else ""
    if " 200 " not in status_line:
        raise RuntimeError(status_line or "Docker API returned no status")
    headers = {
        key.decode("ascii", errors="ignore").lower(): value.decode("ascii", errors="ignore").strip().lower()
        for line in header_lines[1:]
        if b":" in line
        for key, value in [line.split(b":", 1)]
    }
    if headers.get("transfer-encoding") == "chunked":
        body = decode_chunked(body)
    return json.loads(body.decode("utf-8"))


def decode_chunked(body: bytes) -> bytes:
    decoded = bytearray()
    cursor = 0
    while True:
        line_end = body.find(b"\r\n", cursor)
        if line_end == -1:
            break
        size_line = body[cursor:line_end].split(b";", 1)[0]
        size = int(size_line, 16)
        cursor = line_end + 2
        if size == 0:
            break
        decoded.extend(body[cursor:cursor + size])
        cursor += size + 2
    return bytes(decoded)


def list_container_candidates(configured_ids: set[str], socket_path: str = DOCKER_SOCKET) -> list[DockerImportCandidate]:
    containers = docker_get("/containers/json?all=1", socket_path=socket_path)
    candidates: list[DockerImportCandidate] = []
    for item in containers:
        names = item.get("Names") or []
        name = str(names[0]).lstrip("/") if names else item.get("Id", "")[:12]
        labels = item.get("Labels") or {}
        compose_project = labels.get("com.docker.compose.project")
        compose_service = labels.get("com.docker.compose.service")
        compose_file = labels.get("com.docker.compose.project.config_files")
        compose_project_dir = labels.get("com.docker.compose.project.working_dir")
        service_id = slug(compose_service or name)
        image = str(item.get("Image") or "")
        service = ServiceConfig(
            id=service_id,
            name=(compose_service or name).replace("-", " ").replace("_", " ").title(),
            adapter=AdapterKind.DOCKER,
            enabled=True,
            update_policy=UpdatePolicy.DISABLED,
            container=name,
            image=image,
            icon_slug=icon_slug_for_service(compose_service or name, image),
            compose_file=compose_file,
            compose_project_dir=compose_project_dir,
            compose_service=compose_service,
            update_enabled=True,
            metadata={
                "container": name,
                "image": image,
                "icon_slug": icon_slug_for_service(compose_service or name, image),
                "compose_project": compose_project,
                "compose_file": compose_file,
                "compose_project_dir": compose_project_dir,
                "compose_service": compose_service,
                "update_action_enabled": True,
            },
        )
        candidates.append(
            DockerImportCandidate(
                id=str(item.get("Id", ""))[:12],
                name=name,
                image=image,
                state=str(item.get("State") or "unknown"),
                compose_project=compose_project,
                compose_service=compose_service,
                already_configured=service_id in configured_ids,
                suggested_service=service,
            )
        )
    return candidates
