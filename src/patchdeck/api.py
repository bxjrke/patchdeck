from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from .assets import PATCHDECK_LOGO_URL
from .docker_import import list_container_candidates, service_from_container
from .icon_cache import cache_service_icon
from .models import DockerImportCandidate, ServiceConfig, ServiceStatus, Settings, SettingsPatch, UpdatePolicy
from .runtime import AppRuntime
from .update_engine import mqtt_enabled, service_update_enabled

router = APIRouter(prefix="/api")


def get_runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


RuntimeDependency = Annotated[AppRuntime, Depends(get_runtime)]


@router.get("/settings")
def get_settings(runtime: RuntimeDependency) -> Settings:
    return public_settings(runtime.store.get_settings())


@router.put("/settings")
def put_settings(settings: Settings, runtime: RuntimeDependency) -> Settings:
    # Preserve fields omitted by older clients instead of resetting them to
    # whatever defaults the currently running server happens to use.
    changes = settings.model_dump(include=settings.model_fields_set)
    return update_settings(runtime, changes)


@router.patch("/settings")
def patch_settings(settings: SettingsPatch, runtime: RuntimeDependency) -> Settings:
    changes = settings.model_dump(exclude_unset=True, exclude_none=True)
    return update_settings(runtime, changes)


@router.get("/services")
def list_services(runtime: RuntimeDependency) -> list[ServiceConfig]:
    # Configuration reads must stay cheap. Runtime/update ordering belongs to
    # /status and must not make this endpoint contact Docker registries.
    return sorted(runtime.store.list_services(), key=lambda service: (service.name.casefold(), service.id))


@router.put("/services/{service_id}")
def put_service(service_id: str, service: ServiceConfig, runtime: RuntimeDependency) -> ServiceConfig:
    if service.id != service_id:
        raise HTTPException(status_code=400, detail="service id mismatch")
    existing = runtime.store.get_service(service_id)
    if existing:
        merged = existing.model_dump()
        merged.update(service.model_dump(include=service.model_fields_set))
        service = ServiceConfig.model_validate(merged)
    service = enrich_service_from_docker(service)
    return persist_service(service, runtime)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str, runtime: RuntimeDependency) -> Response:
    if service_id == "patchdeck":
        raise HTTPException(status_code=403, detail="patchdeck service cannot be deleted")
    deleted = runtime.store.delete_service(service_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="service not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/status")
def get_status(runtime: RuntimeDependency, refresh: bool = False) -> list[ServiceStatus]:
    return runtime.engine.statuses(force_registry_refresh=refresh)


@router.post("/services/{service_id}/update", status_code=status.HTTP_202_ACCEPTED)
def update_service(service_id: str, runtime: RuntimeDependency) -> dict[str, object]:
    service = runtime.store.get_service(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="service not found")
    if not service_update_enabled(service):
        raise HTTPException(status_code=403, detail="service is not enabled for updates")
    job, added = runtime.engine.enqueue_update(service, "web")
    return {"ok": True, "queued": added, "job": job}


@router.post("/updates", status_code=status.HTTP_202_ACCEPTED)
def update_all_services(runtime: RuntimeDependency) -> dict[str, object]:
    jobs = runtime.engine.enqueue_all_updates("web")
    return {"ok": True, "queued": len(jobs), "jobs": jobs}


@router.get("/update-queue")
def get_update_queue(runtime: RuntimeDependency) -> dict[str, object]:
    return runtime.engine.queue_snapshot()


@router.post("/services/{service_id}/refresh")
def refresh_service(service_id: str, runtime: RuntimeDependency) -> ServiceConfig:
    service = runtime.store.get_service(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="service not found")
    if not service.container:
        raise HTTPException(status_code=400, detail="service has no container configured")
    try:
        refreshed = service_from_container(service.container, service)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker refresh unavailable: {exc}") from exc
    return persist_service(refreshed, runtime)


@router.get("/icons/{filename}")
def get_icon(filename: str, runtime: RuntimeDependency) -> FileResponse:
    icon_directory = (runtime.store.data_dir / "icons").resolve()
    path = (icon_directory / filename).resolve()
    if path.parent != icon_directory or not path.is_file():
        raise HTTPException(status_code=404, detail="icon not found")
    return FileResponse(path)


@router.get("/import/docker")
def get_docker_import_candidates(runtime: RuntimeDependency) -> list[DockerImportCandidate]:
    configured_ids = {service.id for service in runtime.store.list_services()}
    try:
        return list_container_candidates(configured_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker import unavailable: {exc}") from exc


@router.post("/import/docker/{candidate_id}")
def import_docker_candidate(candidate_id: str, runtime: RuntimeDependency) -> ServiceConfig:
    configured_ids = {service.id for service in runtime.store.list_services()}
    try:
        candidates = list_container_candidates(configured_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker import unavailable: {exc}") from exc
    for candidate in candidates:
        if candidate.id == candidate_id:
            return persist_service(candidate.suggested_service, runtime)
    raise HTTPException(status_code=404, detail="candidate not found")


def update_settings(runtime: AppRuntime, changes: dict[str, Any]) -> Settings:
    previous = runtime.engine.effective_settings()
    data = runtime.store.get_settings().model_dump()
    data.update(changes)
    updated = runtime.store.update_settings(Settings.model_validate(data))
    current = runtime.engine.effective_settings()
    if mqtt_enabled(previous) and not mqtt_enabled(current):
        runtime.engine.clear_mqtt_entities(previous)
    return public_settings(updated)


def public_settings(settings: Settings) -> Settings:
    # The effective secret can still be supplied through the environment. A
    # stored password is write-only over HTTP and never rendered into the page.
    return settings.model_copy(update={"mqtt_password": ""})


def persist_service(service: ServiceConfig, runtime: AppRuntime) -> ServiceConfig:
    return runtime.store.upsert_service(cache_service_icon(service, runtime.store.data_dir))


def ensure_self_service(runtime: AppRuntime) -> None:
    store = runtime.store
    existing = store.get_service("patchdeck")
    container = (
        (existing.container if existing and existing.container else "")
        or os.environ.get("PATCHDECK_CONTAINER")
        or os.environ.get("HOSTNAME")
        or "patchdeck"
    )
    base = existing or ServiceConfig(
        id="patchdeck",
        name="Patchdeck",
        enabled=True,
        update_policy=UpdatePolicy.MANUAL,
        update_enabled=True,
        container=container,
        release_notes="https://github.com/bxjrke/patchdeck/releases",
    )
    try:
        service = service_from_container(container, base)
    except Exception:
        if container == "patchdeck":
            return
        try:
            service = service_from_container("patchdeck", base)
        except Exception:
            return
    data = service.model_dump()
    data.update({
        "id": "patchdeck",
        "name": "Patchdeck",
        "enabled": True,
        "update_policy": "manual",
        "update_enabled": True,
        "logo_url": PATCHDECK_LOGO_URL,
        "icon_slug": None,
        "release_notes": "https://github.com/bxjrke/patchdeck/releases",
    })
    store.upsert_service(ServiceConfig.model_validate(data))


def enrich_service_from_docker(service: ServiceConfig) -> ServiceConfig:
    runtime_container = (
        os.environ.get("PATCHDECK_CONTAINER") or os.environ.get("HOSTNAME")
        if service.id == "patchdeck"
        else None
    )
    container = runtime_container or service.container
    if not container:
        return service
    try:
        detected = service_from_container(container, service)
    except Exception:
        return service
    data = service.model_dump()
    detected_data = detected.model_dump()
    for key in ("image", "compose_file", "compose_project_dir", "compose_service"):
        if data.get(key) in (None, "") and detected_data.get(key) not in (None, ""):
            data[key] = detected_data[key]
    if detected.icon_slug and data.get("icon_slug") in (None, "", "docker", "linuxserver"):
        data["icon_slug"] = detected.icon_slug
    data["container"] = detected.container
    return ServiceConfig.model_validate(data)
