from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class UpdatePolicy(StrEnum):
    MANUAL = "manual"
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
    logo_url: str | None = None
    icon_slug: str | None = None
    container: str | None = None
    image: str | None = None
    repo: str | None = None
    compose_file: str | None = None
    compose_project_dir: str | None = None
    compose_service: str | None = None
    release_notes: str | None = None
    update_enabled: bool = False
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
    schema_version: int = 1
    update_interval_minutes: int = Field(default=60, ge=1, le=10080)
    language: str = Field(default="de", pattern=r"^(de|en)$")
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_base_topic: str = "patchdeck"
    mqtt_retained_cleanup_topics: list[str] = Field(default_factory=lambda: [
        "homeassistant/update/demo-service/config",
        "update-hub/demo-service/state",
        "update-hub/demo-service/latest_version",
        "update-hub/homeassistant/installed_version",
    ])
    theme: str = "system"
    base_url: str = ""
    registry_refresh_hour: int = Field(default=3, ge=0, le=23)
    registry_refresh_minute: int = Field(default=45, ge=0, le=59)
    registry_refresh_window_minutes: int = Field(default=20, ge=1, le=1440)


class ServiceStatus(BaseModel):
    service_id: str
    id: str | None = None
    name: str | None = None
    container: str | None = None
    logo_url: str | None = None
    icon_slug: str | None = None
    image: str | None = None
    current_version: str | None = None
    latest_version: str | None = None
    current_digest: str | None = None
    latest_digest: str | None = None
    release_notes_url: str | None = None
    update_available: bool = False
    update_enabled: bool = False
    update_in_progress: bool = False
    update_started_at: int | None = None
    update_source: str | None = None
    last_run: dict[str, Any] | None = None
    checked_at: int | None = None
    state: str = "unknown"
