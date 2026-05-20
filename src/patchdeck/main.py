from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response, status

from .models import ServiceConfig, ServiceStatus, Settings
from .store import MemoryStore

app = FastAPI(title="Patchdeck", version="0.1.0")
store = MemoryStore()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings() -> Settings:
    return store.get_settings()


@app.put("/api/settings")
def put_settings(settings: Settings) -> Settings:
    return store.update_settings(settings)


@app.get("/api/services")
def list_services() -> list[ServiceConfig]:
    return store.list_services()


@app.put("/api/services/{service_id}")
def put_service(service_id: str, service: ServiceConfig) -> ServiceConfig:
    if service.id != service_id:
        raise HTTPException(status_code=400, detail="service id mismatch")
    return store.upsert_service(service)


@app.delete("/api/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str) -> Response:
    deleted = store.delete_service(service_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="service not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/status")
def get_status() -> list[ServiceStatus]:
    return [
        ServiceStatus(
            service_id=service.id,
            state="configured" if service.enabled else "disabled",
        )
        for service in store.list_services()
    ]


@app.post("/api/import/docker")
def import_docker_containers() -> dict[str, str]:
    # Placeholder endpoint. The first real implementation should use the Docker
    # API socket and return import candidates, not silently mutate config.
    return {"status": "not_implemented"}

