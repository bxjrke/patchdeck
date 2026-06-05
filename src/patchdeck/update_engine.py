from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from urllib.parse import quote
from pathlib import Path
from typing import Any

from .models import ServiceConfig, ServiceStatus, Settings, UpdatePolicy
from .store import JsonStore

DOCKER_BIN = os.environ.get("PATCHDECK_DOCKER_BIN", "/usr/bin/docker")
COMPOSE_BIN = os.environ.get("PATCHDECK_COMPOSE_BIN", "/usr/libexec/docker/cli-plugins/docker-compose")


class UpdateEngine:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.state_dir = store.data_dir
        self.audit_log = self.state_dir / "audit.log"
        self.lock_file = self.state_dir / "update.lock"
        self.last_run_file = self.state_dir / "last-runs.json"
        self.release_cache_file = self.state_dir / "release-notes-cache.json"
        self.registry_cache_file = self.state_dir / "registry-cache.json"
        self._active_updates: dict[str, dict[str, Any]] = {}
        self._active_lock = threading.Lock()
        self._mqtt_started = False
        self._mqtt_start_lock = threading.Lock()

    def audit(self, event: str, **fields: object) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
        with self.audit_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def statuses(self) -> list[ServiceStatus]:
        return sort_statuses([self.service_status(service) for service in self.store.list_services() if service.enabled])

    def service_status(self, service: ServiceConfig) -> ServiceStatus:
        service_id = service.id
        mock = service.metadata.get("mock_status") if service.metadata else None
        if isinstance(mock, dict):
            current = mock.get("current_version")
            latest = mock.get("latest_version")
            running = bool(mock.get("update_in_progress"))
            return ServiceStatus(
                service_id=service_id,
                id=service_id,
                name=service.name,
                container=service_container(service),
                image=service_image(service),
                state=mock.get("state", "demo"),
                current_version=current,
                latest_version=latest,
                release_notes_url=mock.get("release_notes_url"),
                update_available=bool(mock.get("update_available", current != latest)),
                update_enabled=False,
                update_in_progress=running,
                update_started_at=mock.get("update_started_at"),
                update_source=mock.get("update_source", "demo") if running else None,
                last_run=mock.get("last_run"),
                checked_at=int(time.time()),
            )

        image = service_image(service)
        labels, details = docker_labels_for_container(service_container(service))
        current_label = label_version(labels)
        current_digest = comparable_image_digest(details, image)
        latest_label, latest_digest = (None, None)
        if image:
            local_latest_labels, local_latest_details = docker_image_details(image)
            latest_label = label_version(local_latest_labels)
            latest_digest = comparable_image_digest(local_latest_details, image)
            arch = (details or {}).get("Architecture") or (local_latest_details or {}).get("Architecture") or "amd64"
            os_name = (details or {}).get("Os") or (local_latest_details or {}).get("Os") or "linux"
            remote_label, remote_digest = self.cached_latest_image_info(image, arch, os_name, latest_digest)
            if remote_label:
                latest_label = remote_label
            if remote_digest and current_repo_digest(details, image):
                latest_digest = remote_digest

        update_available = False
        if current_digest and latest_digest:
            update_available = current_digest != latest_digest
        elif current_label and latest_label:
            update_available = current_label != latest_label
        current_display = current_label or short_digest(current_digest)
        latest_display = latest_version_display(current_label, latest_label, update_available)
        running = self.active_update(service_id)
        return ServiceStatus(
            service_id=service_id,
            id=service_id,
            name=service.name,
            container=service_container(service),
            logo_url=service.logo_url or service.metadata.get("logo_url"),
            icon_slug=service.icon_slug or service.metadata.get("icon_slug"),
            image=image,
            state=(running or {}).get("phase") or docker_container_state(service_container(service)),
            current_version=current_display,
            latest_version=latest_display,
            current_digest=current_digest,
            latest_digest=latest_digest,
            release_notes_url=self.release_notes_url(service.release_notes or service.metadata.get("release_notes"), latest_label),
            update_available=update_available,
            update_enabled=service_update_enabled(service),
            update_in_progress=bool(running),
            update_started_at=(running or {}).get("started_at"),
            update_source=(running or {}).get("source"),
            last_run=self.load_last_runs().get(service_id),
            checked_at=int(time.time()),
        )

    def perform_update(self, service: ServiceConfig, source: str) -> tuple[bool, str]:
        service_id = service.id
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_file.open("a+") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.audit("update_busy", service=service_id, source=source)
                self.publish_service_state(service, in_progress=True)
                return False, "An update is already running. Please wait."
            self.mark_update_active(service_id, True, source)
            self.audit("update_start", service=service_id, source=source)
            self.publish_service_state(service, in_progress=True, update_percentage=0)
            code, output = self.run_update(service)
            ok = code == 0
            self.save_last_run(service_id, {"ts": int(time.time()), "ok": ok, "exit_code": code, "source": source, "output": output[-2000:]})
            self.audit("update_done", service=service_id, source=source, ok=ok, exit_code=code, output=output[-1200:])
            self.mark_update_active(service_id, False)
            self.publish_service_state(service, in_progress=False)
            return ok, "Update completed." if ok else "Update failed. Details are available in the audit log."

    def run_update(self, service: ServiceConfig) -> tuple[int, str]:
        service_id = service.id
        compose_file = service.compose_file or service.metadata.get("compose_file") or ""
        project_dir = service.compose_project_dir or service.metadata.get("compose_project_dir") or service.metadata.get("compose_project") or ""
        compose_service = service.compose_service or service.metadata.get("compose_service") or service.id
        if not compose_file and project_dir and Path(project_dir).is_dir():
            for name in ("docker-compose.yml", "compose.yaml", "compose.yml"):
                candidate = Path(project_dir) / name
                if candidate.exists():
                    compose_file = str(candidate)
                    break
        if not project_dir and compose_file:
            project_dir = str(Path(compose_file).parent)
        if not compose_file or not compose_service:
            return 1, "Service is not fully configured."
        pull = [DOCKER_BIN, "compose", "-f", compose_file, "pull", compose_service]
        up = [DOCKER_BIN, "compose", "-f", compose_file, "up", "-d", "--no-deps", compose_service]
        self.mark_update_active(service_id, True, phase="Pulling Image")
        code1, out1 = run_cmd(pull, cwd=project_dir, timeout=300)
        if code1 != 0:
            return code1, "$ " + " ".join(pull) + "\n" + out1
        self.mark_update_active(service_id, True, phase="Recreating")
        if service_id == "patchdeck":
            try:
                subprocess.Popen(up, cwd=project_dir or None, env=docker_command_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except Exception as exc:
                return 1, "$ " + " ".join(pull) + "\n" + out1 + "\n$ " + " ".join(up) + "\n" + str(exc)
            return 0, "$ " + " ".join(pull) + "\n" + out1 + "\n$ " + " ".join(up) + "\nSelf-update recreate started in the background."
        code2, out2 = run_cmd(up, cwd=project_dir, timeout=300)
        return code2, "$ " + " ".join(pull) + "\n" + out1 + "\n$ " + " ".join(up) + "\n" + out2

    def load_last_runs(self) -> dict[str, Any]:
        return load_json(self.last_run_file, {})

    def save_last_run(self, service_id: str, payload: dict[str, Any]) -> None:
        data = self.load_last_runs()
        data[service_id] = payload
        atomic_json(self.last_run_file, data)

    def mark_update_active(self, service_id: str, active: bool, source: str = "unknown", phase: str = "Starting update") -> None:
        with self._active_lock:
            if active:
                existing = self._active_updates.get(service_id) or {}
                self._active_updates[service_id] = {
                    "source": existing.get("source", source) if source == "unknown" else source,
                    "started_at": existing.get("started_at", int(time.time())),
                    "phase": phase,
                }
            else:
                self._active_updates.pop(service_id, None)

    def active_update(self, service_id: str) -> dict[str, Any] | None:
        with self._active_lock:
            state = self._active_updates.get(service_id)
            return dict(state) if state else None

    def cached_latest_image_info(self, image: str, arch: str = "amd64", os_name: str = "linux", known_local_digest: str | None = None) -> tuple[str | None, str | None]:
        settings = effective_settings(self.store.get_settings())
        cache = load_json(self.registry_cache_file, {})
        key = f"{image}|{os_name}|{arch}"
        cached = cache.get(key) if isinstance(cache, dict) else None
        today = time.strftime("%Y-%m-%d", time.localtime())
        cached_digest = cached.get("digest") if isinstance(cached, dict) else None
        cache_matches_local = bool(known_local_digest and cached_digest == known_local_digest)
        cache_mismatches_local = bool(known_local_digest and cached_digest and cached_digest != known_local_digest)
        if isinstance(cached, dict) and cached.get("refresh_day") == today and not cache_mismatches_local:
            return cached.get("label"), cached.get("digest")
        if isinstance(cached, dict) and not registry_refresh_allowed(settings) and not cache_mismatches_local:
            return cached.get("label"), cached.get("digest")
        if cache_mismatches_local:
            self.audit("registry_cache_stale", image=image, arch=arch, os=os_name, cached_digest=cached_digest, local_digest=known_local_digest)
        label, digest = latest_registry_version(image, self.audit, arch, os_name)
        if label or digest:
            if not isinstance(cache, dict):
                cache = {}
            cache[key] = {
                "image": image,
                "arch": arch,
                "os": os_name,
                "label": label,
                "digest": digest,
                "refresh_day": today,
                "refreshed_at": int(time.time()),
            }
            atomic_json(self.registry_cache_file, cache)
            self.audit("registry_cache_refreshed", image=image, arch=arch, os=os_name, label=label, digest=digest)
            return label, digest
        self.audit("registry_cache_refresh_failed", image=image, arch=arch, os=os_name)
        if isinstance(cached, dict) and not cache_mismatches_local:
            return cached.get("label"), cached.get("digest")
        if cache_matches_local:
            return cached.get("label"), cached.get("digest")
        return None, None

    def release_notes_url(self, source: str | None, version: str | None) -> str | None:
        if not source:
            return None
        source = source.strip()
        if source == "homeassistant":
            return self.homeassistant_release_notes_url(version) if version else None
        if source.startswith(("https://", "http://")):
            if version:
                return format_release_notes_url(source, version)
            if "{" not in source and "}" not in source:
                return source
        return None

    def homeassistant_release_notes_url(self, version: str) -> str | None:
        match = re.match(r"^(\d{4})\.(\d+)(?:\.\d+)?$", version)
        if not match:
            return None
        year, month = match.group(1), int(match.group(2))
        slug = f"release-{year}{month}"
        cache_key = f"homeassistant:{year}.{month}"
        cache = load_json(self.release_cache_file, {})
        cached = cache.get(cache_key) if isinstance(cache, dict) else None
        if cached and int(time.time()) - int(cached.get("ts", 0)) < 7 * 24 * 3600:
            return cached.get("url")
        category_url = "https://www.home-assistant.io/blog/categories/release-notes/"
        url = category_url
        try:
            req = urllib.request.Request(category_url, headers={"User-Agent": "Mozilla/5.0 patchdeck/0.1"})
            with urllib.request.urlopen(req, timeout=12) as response:
                page_text = response.read().decode("utf-8", "replace")
            found = re.search(rf'href="(?P<path>/blog/{year}/\d{{2}}/\d{{2}}/{slug}/)"', page_text)
            if not found:
                found = re.search(rf"(?P<path>/blog/{year}/\d{{2}}/\d{{2}}/{slug}/)", page_text)
            if found:
                url = f"https://www.home-assistant.io{found.group('path')}"
        except Exception as exc:
            self.audit("release_notes_lookup_failed", kind="homeassistant", version=version, error=str(exc))
        if not isinstance(cache, dict):
            cache = {}
        cache[cache_key] = {"ts": int(time.time()), "url": url}
        atomic_json(self.release_cache_file, cache)
        return url

    def start_background_tasks(self) -> None:
        with self._mqtt_start_lock:
            if self._mqtt_started:
                return
            self._mqtt_started = True
        threading.Thread(target=self._mqtt_publish_loop, daemon=True).start()
        threading.Thread(target=self._mqtt_command_loop, daemon=True).start()
        settings = self.effective_settings()
        if not mqtt_enabled(settings) and settings.mqtt_host:
            self.clear_mqtt_entities(force_mqtt_enabled(settings))
        self.audit("mqtt_background_tasks_started")

    def effective_settings(self) -> Settings:
        return effective_settings(self.store.get_settings())

    def clear_mqtt_entities(self, settings: Settings) -> None:
        statuses = [
            ServiceStatus(service_id=service.id, id=service.id, name=service.name)
            for service in self.store.list_services()
        ]
        ok = mqtt_publish_cleanup(settings, statuses, self.audit)
        self.audit("mqtt_entities_cleared", ok=ok, count=len(statuses))

    def publish_service_state(self, service: ServiceConfig, in_progress: bool | None = None, update_percentage: int | float | None = None) -> None:
        settings = effective_settings(self.store.get_settings())
        if not mqtt_enabled(settings):
            return
        try:
            mqtt_publish_discovery(settings, [self.service_status(service)], self.audit, in_progress=in_progress, update_percentage=update_percentage)
        except Exception as exc:
            self.audit("mqtt_state_publish_failed", service=service.id, error=str(exc))

    def _mqtt_publish_loop(self) -> None:
        time.sleep(15)
        while True:
            try:
                settings = effective_settings(self.store.get_settings())
                if mqtt_enabled(settings):
                    mqtt_publish_discovery(settings, self.statuses(), self.audit)
            except Exception as exc:
                self.audit("mqtt_loop_error", error=str(exc))
            time.sleep(300)

    def _mqtt_command_loop(self) -> None:
        while True:
            settings = effective_settings(self.store.get_settings())
            sock = mqtt_connect(settings, "patchdeck-sub", self.audit, keepalive=0)
            if not sock:
                time.sleep(30)
                continue
            try:
                if not mqtt_subscribe(sock, f"{settings.mqtt_base_topic}/+/command", self.audit):
                    sock.close()
                    time.sleep(30)
                    continue
                self.audit("mqtt_command_subscribed", topic=f"{settings.mqtt_base_topic}/+/command")
                while True:
                    if not mqtt_enabled(effective_settings(self.store.get_settings())):
                        self.audit("mqtt_command_unsubscribed", reason="disabled")
                        try:
                            sock.close()
                        except Exception:
                            pass
                        break
                    packet = _mqtt_read_packet(sock)
                    if packet is None:
                        raise ConnectionError("MQTT connection closed")
                    packet_type = packet[0] >> 4
                    body = packet[1]
                    if packet_type == 3 and len(body) >= 2:
                        topic_len = struct.unpack("!H", body[:2])[0]
                        topic = body[2:2 + topic_len].decode("utf-8", "replace")
                        msg = body[2 + topic_len:]
                        self.handle_mqtt_command(topic, msg)
            except Exception as exc:
                self.audit("mqtt_command_loop_error", error=str(exc))
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(30)

    def handle_mqtt_command(self, topic: str, payload: bytes) -> None:
        settings = effective_settings(self.store.get_settings())
        if not mqtt_enabled(settings):
            self.audit("mqtt_command_rejected", reason="mqtt_disabled")
            return
        text = payload.decode("utf-8", "replace").strip()
        match = re.fullmatch(rf"{re.escape(settings.mqtt_base_topic)}/([^/]+)/command", topic)
        if not match:
            return
        service_id = match.group(1)
        service = self.store.get_service(service_id)
        if text != "install":
            self.audit("mqtt_command_ignored", service=service_id, payload=text)
            return
        if not service or not service_update_enabled(service):
            self.audit("mqtt_command_rejected", service=service_id, reason="not_enabled")
            return
        threading.Thread(target=self.perform_update, args=(service, "mqtt"), daemon=True).start()
        self.audit("mqtt_command_accepted", service=service_id)


def service_container(service: ServiceConfig) -> str:
    return service.container or service.metadata.get("container") or service.id


def service_image(service: ServiceConfig) -> str:
    return service.image or service.metadata.get("image") or ""


def service_update_enabled(service: ServiceConfig) -> bool:
    return bool(service.enabled and (service.update_enabled or service.metadata.get("update_action_enabled") or service.update_policy == UpdatePolicy.MANUAL))


def sort_statuses(statuses: list[ServiceStatus]) -> list[ServiceStatus]:
    return sorted(statuses, key=lambda service: not service.update_available)


def docker_command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DOCKER_CONFIG"] = "/tmp/docker-empty-config"
    env["DOCKER_CLI_PLUGIN_EXTRA_DIRS"] = str(Path(COMPOSE_BIN).parent)
    return env


def run_cmd(args: list[str], cwd: str | None = None, timeout: int = 45) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, cwd=cwd or None, env=docker_command_env(), capture_output=True, text=True, timeout=timeout)
        return proc.returncode, "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
    except Exception as exc:
        return 1, str(exc)


def format_release_notes_url(template: str, version: str) -> str:
    parts = version.split(".")
    values = {
        "version": version,
        "version_url": quote(version, safe=""),
        "major": parts[0] if len(parts) > 0 else "",
        "minor": parts[1] if len(parts) > 1 else "",
        "patch": parts[2] if len(parts) > 2 else "",
    }
    url = template
    for key, value in values.items():
        url = url.replace("{" + key + "}", value)
    return url


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def docker_labels_for_container(container: str) -> tuple[dict[str, str], dict[str, Any] | None]:
    code, image_id = run_cmd([DOCKER_BIN, "inspect", container, "--format", "{{.Image}}"])
    if code != 0 or not image_id.strip():
        return {}, None
    code, raw = run_cmd([DOCKER_BIN, "image", "inspect", image_id.strip()])
    if code != 0:
        return {}, None
    try:
        details = json.loads(raw)[0]
    except Exception:
        return {}, None
    return details.get("Config", {}).get("Labels") or {}, details


def docker_image_details(image: str) -> tuple[dict[str, str], dict[str, Any] | None]:
    if not image:
        return {}, None
    code, raw = run_cmd([DOCKER_BIN, "image", "inspect", image])
    if code != 0:
        return {}, None
    try:
        details = json.loads(raw)[0]
    except Exception:
        return {}, None
    return details.get("Config", {}).get("Labels") or {}, details


def image_id_digest(details: dict[str, Any] | None) -> str | None:
    image_id = (details or {}).get("Id")
    return image_id if isinstance(image_id, str) and image_id else None


def comparable_image_digest(details: dict[str, Any] | None, image: str) -> str | None:
    return current_repo_digest(details, image) or image_id_digest(details)


def label_version(labels: dict[str, str]) -> str | None:
    return labels.get("io.hass.version") or labels.get("io.patchdeck.version") or labels.get("org.opencontainers.image.version")


def docker_container_state(container: str) -> str:
    code, out = run_cmd([DOCKER_BIN, "inspect", container, "--format", "{{.State.Status}}"])
    return out.strip() if code == 0 and out.strip() else "unbekannt"


def image_ref_parts(image: str) -> tuple[str, str, str]:
    image = image.split("@", 1)[0]
    tag = "latest"
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        image, tag = image.rsplit(":", 1)
    parts = image.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, repo = parts[0], parts[1]
    else:
        registry = "registry-1.docker.io"
        repo = image if "/" in image else f"library/{image}"
    return registry, repo, tag


def registry_token(registry: str, repo: str, audit: Any) -> str | None:
    try:
        if registry == "ghcr.io":
            url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repo}:pull"
        elif registry == "registry-1.docker.io":
            url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
        else:
            return None
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "patchdeck/0.1"}), timeout=15) as response:
            return json.load(response).get("token")
    except Exception as exc:
        audit("registry_token_failed", registry=registry, repo=repo, error=str(exc))
        return None


def registry_json(registry: str, repo: str, path: str, token: str | None, audit: Any, accept: str | None = None) -> tuple[Any | None, str | None]:
    headers = {"User-Agent": "patchdeck/0.1"}
    if accept:
        headers["Accept"] = accept
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(f"https://{registry}/v2/{repo}/{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            digest = response.headers.get("Docker-Content-Digest")
            return json.load(response), digest
    except Exception as exc:
        audit("registry_json_failed", registry=registry, repo=repo, path=path, error=str(exc))
        return None, None


def latest_registry_version(image: str, audit: Any, arch: str = "amd64", os_name: str = "linux") -> tuple[str | None, str | None]:
    registry, repo, tag = image_ref_parts(image)
    token = registry_token(registry, repo, audit)
    accept = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
    manifest, top_digest = registry_json(registry, repo, f"manifests/{tag}", token, audit, accept)
    if not isinstance(manifest, dict):
        return None, top_digest
    selected = manifest
    media_type = str(manifest.get("mediaType") or "")
    if "index" in media_type or "manifest.list" in media_type or manifest.get("manifests"):
        digest = None
        for item in manifest.get("manifests") or []:
            platform = item.get("platform") or {}
            if platform.get("architecture") == arch and platform.get("os") == os_name:
                digest = item.get("digest")
                break
        if not digest and manifest.get("manifests"):
            digest = manifest["manifests"][0].get("digest")
        if not digest:
            return None, top_digest
        selected, _selected_digest = registry_json(registry, repo, f"manifests/{digest}", token, audit, accept)
        if not isinstance(selected, dict):
            return None, top_digest
    config_digest = ((selected or {}).get("config") or {}).get("digest")
    if not config_digest:
        return None, top_digest
    config, _config_digest = registry_json(registry, repo, f"blobs/{config_digest}", token, audit)
    labels = (((config or {}).get("config") or {}).get("Labels") or {})
    return label_version(labels), top_digest


def registry_refresh_allowed(settings: Settings, now: float | None = None) -> bool:
    local = time.localtime(now or time.time())
    current_minute = local.tm_hour * 60 + local.tm_min
    start_minute = settings.registry_refresh_hour * 60 + settings.registry_refresh_minute
    return start_minute <= current_minute < start_minute + settings.registry_refresh_window_minutes


def current_repo_digest(details: dict[str, Any] | None, image: str) -> str | None:
    if not details:
        return None
    registry, repo, _tag = image_ref_parts(image)
    candidates = {repo, f"{registry}/{repo}"}
    if registry == "registry-1.docker.io":
        candidates.add(repo.removeprefix("library/"))
    for item in details.get("RepoDigests") or []:
        if "@" not in item:
            continue
        name, digest = item.split("@", 1)
        if name in candidates or name.endswith("/" + repo) or name.endswith("/" + repo.removeprefix("library/")):
            return digest
    digests = details.get("RepoDigests") or []
    if digests and "@" in digests[0]:
        return digests[0].split("@", 1)[1]
    return None


def short_digest(digest: str | None) -> str | None:
    if not digest:
        return None
    return digest.replace("sha256:", "sha256:")[:19]


def latest_version_display(current_label: str | None, latest_label: str | None, update_available: bool) -> str | None:
    if latest_label:
        return latest_label
    if current_label and not update_available:
        return current_label
    return "Unbekannt" if update_available else current_label


def mqtt_enabled(settings: Settings) -> bool:
    return bool(settings.mqtt_enabled and settings.mqtt_host)


def force_mqtt_enabled(settings: Settings) -> Settings:
    data = settings.model_dump()
    data["mqtt_enabled"] = bool(settings.mqtt_host)
    return Settings.model_validate(data)


def env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def effective_settings(settings: Settings) -> Settings:
    data = settings.model_dump()
    env_map = {
        "mqtt_enabled": ("PATCHDECK_MQTT_ENABLED", "UPDATE_HUB_MQTT_ENABLED"),
        "mqtt_host": ("PATCHDECK_MQTT_HOST", "UPDATE_HUB_MQTT_HOST"),
        "mqtt_port": ("PATCHDECK_MQTT_PORT", "UPDATE_HUB_MQTT_PORT"),
        "mqtt_user": ("PATCHDECK_MQTT_USER", "UPDATE_HUB_MQTT_USER"),
        "mqtt_password": ("PATCHDECK_MQTT_PASSWORD", "UPDATE_HUB_MQTT_PASSWORD"),
        "mqtt_discovery_prefix": ("PATCHDECK_MQTT_DISCOVERY_PREFIX", "UPDATE_HUB_MQTT_DISCOVERY_PREFIX"),
        "mqtt_base_topic": ("PATCHDECK_MQTT_BASE_TOPIC", "UPDATE_HUB_MQTT_BASE_TOPIC"),
        "base_url": ("PATCHDECK_BASE_URL", "UPDATE_HUB_BASE_URL"),
    }
    for key, names in env_map.items():
        for name in names:
            value = os.environ.get(name)
            if value not in (None, ""):
                if key == "mqtt_port":
                    data[key] = int(value)
                elif key == "mqtt_enabled":
                    data[key] = env_bool(value)
                else:
                    data[key] = value
                break
    cleanup = os.environ.get("PATCHDECK_MQTT_RETAINED_CLEANUP_TOPICS") or os.environ.get("UPDATE_HUB_MQTT_RETAINED_CLEANUP_TOPICS")
    if cleanup:
        data["mqtt_retained_cleanup_topics"] = [topic.strip() for topic in cleanup.split(",") if topic.strip()]
    return Settings.model_validate(data)


def mqtt_update_state_payload(s: ServiceStatus, in_progress: bool | None = None, update_percentage: int | float | None = None) -> str:
    payload: dict[str, Any] = {
        "installed_version": s.current_version or "",
        "latest_version": (s.latest_version if s.update_available else s.current_version) or s.current_version or "",
        "title": s.name or s.id or "Update",
    }
    if s.release_notes_url:
        payload["release_url"] = s.release_notes_url
    if in_progress is None:
        in_progress = bool(s.update_in_progress)
    payload["in_progress"] = bool(in_progress)
    payload["update_percentage"] = update_percentage if update_percentage is not None else None
    return json.dumps(payload, separators=(",", ":"))


def mqtt_publish_discovery(
    settings: Settings,
    statuses: list[ServiceStatus],
    audit: Any,
    in_progress: bool | None = None,
    update_percentage: int | float | None = None,
) -> None:
    if not mqtt_enabled(settings):
        return
    messages: list[tuple[str, str | bytes, bool]] = []
    for topic in settings.mqtt_retained_cleanup_topics:
        messages.append((topic, b"", True))
    for s in statuses:
        sid = s.id or s.service_id
        current = s.current_version or ""
        latest = (s.latest_version if s.update_available else current) or current
        base_topic = f"{settings.mqtt_base_topic}/{sid}"
        discovery_topic = f"{settings.mqtt_discovery_prefix}/update/patchdeck_{sid}/config"
        discovery_payload: dict[str, Any] = {
            "name": "Container Update",
            "unique_id": f"patchdeck_{sid}",
            "object_id": f"patchdeck_{sid}",
            "state_topic": f"{base_topic}/state",
            "latest_version_topic": f"{base_topic}/latest_version",
            "command_topic": f"{base_topic}/command",
            "payload_install": "install",
            "device_class": "firmware",
            "entity_category": "diagnostic",
            "display_precision": 0,
            "device": {
                "identifiers": [f"patchdeck_{sid}"],
                "name": s.name or sid,
                "manufacturer": "Patchdeck",
            },
        }
        if settings.base_url:
            discovery_payload["configuration_url"] = settings.base_url
        if s.release_notes_url:
            discovery_payload["release_url"] = s.release_notes_url
        messages.append((f"{base_topic}/installed_version", b"", True))
        messages.append((discovery_topic, json.dumps(discovery_payload), True))
        messages.append((f"{base_topic}/state", current, True))
        messages.append((f"{base_topic}/json", mqtt_update_state_payload(s, in_progress, update_percentage), True))
        messages.append((f"{base_topic}/latest_version", latest or "", True))
    ok = mqtt_publish_batch(settings, messages, audit)
    audit("mqtt_discovery_published", ok=ok, count=len(statuses), cleanup_topics=len(settings.mqtt_retained_cleanup_topics))


def mqtt_cleanup_messages(settings: Settings, statuses: list[ServiceStatus]) -> list[tuple[str, str | bytes, bool]]:
    messages: list[tuple[str, str | bytes, bool]] = []
    for topic in settings.mqtt_retained_cleanup_topics:
        messages.append((topic, b"", True))
    for s in statuses:
        sid = s.id or s.service_id
        base_topic = f"{settings.mqtt_base_topic}/{sid}"
        discovery_topic = f"{settings.mqtt_discovery_prefix}/update/patchdeck_{sid}/config"
        legacy_discovery_topic = f"{settings.mqtt_discovery_prefix}/update/{sid}/config"
        messages.extend([
            (discovery_topic, b"", True),
            (legacy_discovery_topic, b"", True),
            (f"{base_topic}/state", b"", True),
            (f"{base_topic}/json", b"", True),
            (f"{base_topic}/latest_version", b"", True),
            (f"{base_topic}/installed_version", b"", True),
        ])
    return messages


def mqtt_publish_cleanup(settings: Settings, statuses: list[ServiceStatus], audit: Any) -> bool:
    if not mqtt_enabled(settings):
        return False
    messages = mqtt_cleanup_messages(settings, statuses)
    ok = mqtt_publish_batch(settings, messages, audit)
    audit("mqtt_cleanup_published", ok=ok, count=len(statuses), messages=len(messages))
    return ok


def _mqtt_encode_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _mqtt_remaining_length(length: int) -> bytes:
    out = b""
    while True:
        byte = length & 0x7F
        length >>= 7
        if length:
            byte |= 0x80
        out += bytes([byte])
        if not length:
            break
    return out


def mqtt_publish_batch(settings: Settings, messages: list[tuple[str, str | bytes, bool]], audit: Any) -> bool:
    if not mqtt_enabled(settings):
        return False
    try:
        sock = socket.create_connection((settings.mqtt_host, settings.mqtt_port), timeout=10)
    except Exception as exc:
        audit("mqtt_connect_failed", error=str(exc))
        return False
    try:
        client_id = b"patchdeck-pub"
        payload = _mqtt_encode_str("MQTT") + bytes([4, 0xC2, 0, 60])
        payload += _mqtt_encode_str(client_id.decode())
        payload += _mqtt_encode_str(settings.mqtt_user)
        payload += _mqtt_encode_str(settings.mqtt_password)
        sock.sendall(bytes([0x10]) + _mqtt_remaining_length(len(payload)) + payload)
        connack = sock.recv(4)
        if len(connack) < 4 or connack[0] != 0x20 or connack[3] != 0:
            audit("mqtt_connack_failed", code=list(connack))
            return False
        for topic, msg, retain in messages:
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            flags = 0x31 if retain else 0x30
            pkt_payload = _mqtt_encode_str(topic) + msg
            sock.sendall(bytes([flags]) + _mqtt_remaining_length(len(pkt_payload)) + pkt_payload)
        sock.sendall(b"\xe0\x00")
        return True
    except Exception as exc:
        audit("mqtt_publish_failed", error=str(exc))
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _mqtt_read_packet(sock: socket.socket) -> tuple[int, bytes] | None:
    first = sock.recv(1)
    if not first:
        return None
    multiplier = 1
    remaining = 0
    while True:
        raw = sock.recv(1)
        if not raw:
            return None
        encoded = raw[0]
        remaining += (encoded & 127) * multiplier
        if not encoded & 128:
            break
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("Malformed MQTT remaining length")
    payload = b""
    while len(payload) < remaining:
        chunk = sock.recv(remaining - len(payload))
        if not chunk:
            return None
        payload += chunk
    return first[0], payload


def mqtt_connect(settings: Settings, client_id: str, audit: Any, keepalive: int = 60) -> socket.socket | None:
    if not mqtt_enabled(settings):
        return None
    try:
        sock = socket.create_connection((settings.mqtt_host, settings.mqtt_port), timeout=15)
        sock.settimeout(max(15, keepalive + 10) if keepalive else None)
        payload = _mqtt_encode_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", keepalive)
        payload += _mqtt_encode_str(client_id)
        payload += _mqtt_encode_str(settings.mqtt_user)
        payload += _mqtt_encode_str(settings.mqtt_password)
        sock.sendall(bytes([0x10]) + _mqtt_remaining_length(len(payload)) + payload)
        packet = _mqtt_read_packet(sock)
        if not packet or packet[0] != 0x20 or len(packet[1]) < 2 or packet[1][1] != 0:
            audit("mqtt_connack_failed", client_id=client_id, code=list(packet[1]) if packet else [])
            sock.close()
            return None
        return sock
    except Exception as exc:
        audit("mqtt_connect_failed", client_id=client_id, error=str(exc))
        return None


def mqtt_subscribe(sock: socket.socket, topic: str, audit: Any) -> bool:
    packet_id = 1
    payload = struct.pack("!H", packet_id) + _mqtt_encode_str(topic) + bytes([0])
    sock.sendall(bytes([0x82]) + _mqtt_remaining_length(len(payload)))
    sock.sendall(payload)
    packet = _mqtt_read_packet(sock)
    ok = bool(packet and packet[0] == 0x90 and len(packet[1]) >= 3 and packet[1][-1] != 0x80)
    if not ok:
        audit("mqtt_subscribe_failed", topic=topic, packet=list(packet[1]) if packet else [])
    return ok
