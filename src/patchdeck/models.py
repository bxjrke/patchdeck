from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class UpdatePolicy(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"
    DISABLED = "disabled"


class AdapterKind(StrEnum):
    DOCKER = "docker"
    CUSTOM = "custom"


class ServiceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str
    adapter: AdapterKind = AdapterKind.DOCKER
    enabled: bool = True
    update_policy: UpdatePolicy = UpdatePolicy.MANUAL
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DockerImportCandidate(BaseModel):
    id: str
    name: str
    image: str
    state: str
    compose_project: str | None = None
    compose_service: str | None = None
    already_configured: bool = False
    suggested_service: ServiceConfig


class Settings(BaseModel):
    update_interval_minutes: int = Field(default=60, ge=1, le=10080)
    mqtt_enabled: bool = False
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_base_topic: str = "patchdeck"
    docker_auto_import_enabled: bool = True
    theme: str = "system"


class ServiceStatus(BaseModel):
    service_id: str
    current_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    state: str = "unknown"
