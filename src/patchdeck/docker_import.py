from __future__ import annotations

import json
import re
import socket
from typing import Any

from .models import AdapterKind, DockerImportCandidate, ServiceConfig, UpdatePolicy

DOCKER_SOCKET = "/var/run/docker.sock"


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")
    return normalized[:64] or "container"


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
        service_id = slug(compose_service or name)
        image = str(item.get("Image") or "")
        service = ServiceConfig(
            id=service_id,
            name=(compose_service or name).replace("-", " ").replace("_", " ").title(),
            adapter=AdapterKind.DOCKER,
            enabled=True,
            update_policy=UpdatePolicy.MANUAL,
            metadata={
                "container": name,
                "image": image,
                "compose_project": compose_project,
                "compose_service": compose_service,
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
