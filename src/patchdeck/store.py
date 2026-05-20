from __future__ import annotations

from threading import Lock

from .models import ServiceConfig, Settings


class MemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._settings = Settings()
        self._services: dict[str, ServiceConfig] = {}

    def get_settings(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update_settings(self, settings: Settings) -> Settings:
        with self._lock:
            self._settings = settings
            return self._settings.model_copy(deep=True)

    def list_services(self) -> list[ServiceConfig]:
        with self._lock:
            return [service.model_copy(deep=True) for service in self._services.values()]

    def upsert_service(self, service: ServiceConfig) -> ServiceConfig:
        with self._lock:
            self._services[service.id] = service
            return service.model_copy(deep=True)

    def delete_service(self, service_id: str) -> bool:
        with self._lock:
            return self._services.pop(service_id, None) is not None

