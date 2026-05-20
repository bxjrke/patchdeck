from __future__ import annotations

from threading import Lock
import json
import os
from pathlib import Path

from .models import ServiceConfig, Settings


class JsonStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir or os.environ.get("PATCHDECK_DATA_DIR", "data"))
        self._settings_path = self._data_dir / "settings.json"
        self._services_path = self._data_dir / "services.json"
        self._lock = Lock()
        self._settings = self._load_settings()
        self._services = self._load_services()

    def _load_settings(self) -> Settings:
        try:
            return Settings.model_validate_json(self._settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except Exception:
            return Settings()

    def _load_services(self) -> dict[str, ServiceConfig]:
        try:
            raw = json.loads(self._services_path.read_text(encoding="utf-8"))
            services = [ServiceConfig.model_validate(item) for item in raw]
            return {service.id: service for service in services}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_locked(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        settings_tmp = self._settings_path.with_suffix(".tmp")
        services_tmp = self._services_path.with_suffix(".tmp")
        settings_tmp.write_text(self._settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
        services_tmp.write_text(
            json.dumps([service.model_dump(mode="json") for service in self._services.values()], indent=2) + "\n",
            encoding="utf-8",
        )
        settings_tmp.replace(self._settings_path)
        services_tmp.replace(self._services_path)

    def get_settings(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update_settings(self, settings: Settings) -> Settings:
        with self._lock:
            self._settings = settings
            self._save_locked()
            return self._settings.model_copy(deep=True)

    def list_services(self) -> list[ServiceConfig]:
        with self._lock:
            return [service.model_copy(deep=True) for service in self._services.values()]

    def upsert_service(self, service: ServiceConfig) -> ServiceConfig:
        with self._lock:
            self._services[service.id] = service
            self._save_locked()
            return service.model_copy(deep=True)

    def delete_service(self, service_id: str) -> bool:
        with self._lock:
            deleted = self._services.pop(service_id, None) is not None
            if deleted:
                self._save_locked()
            return deleted
