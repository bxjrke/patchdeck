from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

from .models import ServiceConfig, Settings


class StoreError(RuntimeError):
    """Base exception for persistent state failures."""


class StoreCorruptionError(StoreError):
    """Raised when persisted state exists but cannot be validated."""


class JsonStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir or os.environ.get("PATCHDECK_DATA_DIR", "data"))
        self._settings_path = self._data_dir / "settings.json"
        self._services_path = self._data_dir / "services.json"
        self._lock = Lock()
        self._settings = self._load_settings()
        self._services = self._load_services()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def _load_settings(self) -> Settings:
        try:
            return Settings.model_validate_json(self._settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except Exception as exc:
            raise StoreCorruptionError(
                f"Settings file {self._settings_path} is invalid; refusing to replace it with defaults."
            ) from exc

    def _load_services(self) -> dict[str, ServiceConfig]:
        try:
            raw = json.loads(self._services_path.read_text(encoding="utf-8"))
            services = [ServiceConfig.model_validate(migrate_service_item(item)) for item in raw]
            return {service.id: service for service in services}
        except FileNotFoundError:
            return {}
        except Exception as exc:
            raise StoreCorruptionError(
                f"Services file {self._services_path} is invalid; refusing to replace it with an empty list."
            ) from exc

    def _save_settings_locked(self, settings: Settings) -> None:
        atomic_write_text(
            self._settings_path,
            settings.model_dump_json(indent=2) + "\n",
        )

    def _save_services_locked(self, services: dict[str, ServiceConfig]) -> None:
        atomic_write_text(
            self._services_path,
            json.dumps([service.model_dump(mode="json") for service in services.values()], indent=2) + "\n",
        )

    def get_settings(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update_settings(self, settings: Settings) -> Settings:
        with self._lock:
            self._save_settings_locked(settings)
            self._settings = settings
            return settings.model_copy(deep=True)

    def list_services(self) -> list[ServiceConfig]:
        with self._lock:
            return [service.model_copy(deep=True) for service in self._services.values()]

    def get_service(self, service_id: str) -> ServiceConfig | None:
        with self._lock:
            service = self._services.get(service_id)
            return service.model_copy(deep=True) if service else None

    def upsert_service(self, service: ServiceConfig) -> ServiceConfig:
        with self._lock:
            services = dict(self._services)
            services[service.id] = service
            self._save_services_locked(services)
            self._services = services
            return service.model_copy(deep=True)

    def delete_service(self, service_id: str) -> bool:
        with self._lock:
            if service_id not in self._services:
                return False
            services = dict(self._services)
            del services[service_id]
            self._save_services_locked(services)
            self._services = services
            return True


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Durably replace a text file without sharing a predictable temp name."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
        path.chmod(mode)
        _fsync_directory(path.parent)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def migrate_service_item(item: dict[str, object]) -> dict[str, object]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return item
    migrated = dict(item)
    mapping = {
        "logo_url": "logo_url",
        "icon_slug": "icon_slug",
        "container": "container",
        "image": "image",
        "repo": "repo",
        "compose_file": "compose_file",
        "compose_project_dir": "compose_project_dir",
        "compose_service": "compose_service",
        "release_notes": "release_notes",
        "update_action_enabled": "update_enabled",
    }
    for old_key, new_key in mapping.items():
        if migrated.get(new_key) in (None, "") and metadata.get(old_key) not in (None, ""):
            migrated[new_key] = metadata[old_key]
    if migrated.get("compose_project_dir") in (None, "") and metadata.get("compose_project") not in (None, ""):
        migrated["compose_project_dir"] = metadata["compose_project"]
    if metadata.get("update_action_enabled") and migrated.get("update_policy") == "disabled":
        migrated["update_policy"] = "manual"
    return migrated
