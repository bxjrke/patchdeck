"""Disposable, in-memory UI demo. No production API, Docker or MQTT runtime."""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from threading import RLock
from time import monotonic
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .assets import PATCHDECK_LOGO_URL
from .models import ServiceConfig, ServiceStatus, Settings, SettingsPatch, UpdateAllRequest


def create_demo_app() -> FastAPI:
    # Import only the shared renderer. The production app's lifespan is never run.
    from .main import WRITE_REQUEST_HEADER, add_security_headers, page_response

    app = FastAPI(title="Patchdeck UI Demo")
    app.mount("/static", StaticFiles(packages=[("patchdeck", "static")]), name="static")
    lock = RLock()
    settings = Settings(language="de")
    services = {
        service.id: service
        for service in [
            ServiceConfig(id="homeassistant", name="Home Assistant", container="homeassistant",
                          image="ghcr.io/home-assistant/home-assistant:stable", update_enabled=True),
            ServiceConfig(id="grocy", name="Grocy", container="grocy", image="lscr.io/linuxserver/grocy:latest",
                          logo_url="/static/grocy.svg", update_enabled=True),
            ServiceConfig(id="patchdeck", name="Patchdeck", container="patchdeck", image=f"ghcr.io/bxjrke/patchdeck:{__version__}",
                          logo_url=PATCHDECK_LOGO_URL, update_enabled=True),
            ServiceConfig(id="mosquitto", name="Mosquitto", container="mosquitto", image="eclipse-mosquitto:2"),
        ]
    }
    versions: dict[str, list[str | None]] = {
        "homeassistant": ["2026.10.1", "2026.10.3"],
        "grocy": ["4.4.0", "4.5.0"],
        "patchdeck": [__version__, __version__],
        "mosquitto": [None, None],
    }
    jobs: list[dict[str, Any]] = []

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get(WRITE_REQUEST_HEADER) != "1":
                return add_security_headers(Response(status_code=403))
        return add_security_headers(await call_next(request), no_store=True)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        response = page_response("settings" if request.url.path == "/settings" else "home")
        banner = (
            '<aside class="demo-banner" aria-label="Demo">'
            '<strong data-i18n="demoTitle">Interactive demo</strong>'
            '<span data-i18n="demoHint">Sample data · Updates are simulated · Changes reset on restart</span>'
            '</aside>'
        )
        response.body = bytes(response.body).replace(b"<body>", ("<body>" + banner).encode())
        response.headers["content-length"] = str(len(response.body))
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": "demo"}

    @app.get("/api/settings")
    def get_settings() -> Settings:
        with lock:
            return settings.model_copy(deep=True)

    @app.patch("/api/settings")
    def save_settings(patch: SettingsPatch) -> Settings:
        nonlocal settings
        with lock:
            data = settings.model_dump()
            data.update(patch.model_dump(exclude_unset=True, exclude_none=True))
            data["mqtt_password"] = ""
            settings = Settings.model_validate(data)
            return settings.model_copy(deep=True)

    @app.get("/api/services")
    def list_services() -> list[ServiceConfig]:
        with lock:
            return list(services.values())

    @app.put("/api/services/{service_id}")
    def save_service(service_id: str, service: ServiceConfig) -> ServiceConfig:
        if service.id != service_id:
            raise HTTPException(400, "Service ID mismatch")
        with lock:
            existing = services.get(service_id)
            if existing:
                data = existing.model_dump()
                data.update(service.model_dump(include=service.model_fields_set))
                service = ServiceConfig.model_validate(data)
            services[service_id] = service
            versions.setdefault(service_id, [None, None])
            return service

    @app.delete("/api/services/{service_id}", status_code=204)
    def delete_service(service_id: str) -> Response:
        if service_id == "patchdeck":
            raise HTTPException(403, "Patchdeck cannot be removed")
        with lock:
            if not services.pop(service_id, None):
                raise HTTPException(404, "Service not found")
        return Response(status_code=204)

    def snapshot() -> dict[str, Any]:
        # Advancing time changes only these in-memory records. No worker is started.
        with lock:
            now = monotonic()
            for job in jobs:
                if job["state"] in {"succeeded", "failed"}:
                    continue
                progress = min(100, max(0, int((now - job["demo_start"]) / 6 * 100)))
                job.update(state="queued" if now < job["demo_start"] else "running",
                           update_percentage=progress, phase="Pulling image" if progress < 75 else "Recreating")
                if progress == 100:
                    versions[job["service_id"]][0] = versions[job["service_id"]][1]
                    job.update(state="succeeded", phase="Complete", finished_at=int(time.time()))
            public = [{key: value for key, value in job.items() if key != "demo_start"} for job in jobs]
            return {
                "active": next((job for job in public if job["state"] == "running"), None),
                "pending": [job for job in public if job["state"] == "queued"],
                "recent": [job for job in public if job["state"] == "succeeded"],
            }

    @app.get("/api/update-queue")
    def queue() -> dict[str, Any]:
        return snapshot()

    @app.get("/api/status")
    def statuses() -> list[ServiceStatus]:
        with lock:
            state = snapshot()
            active = state["active"]
            result = []
            for service in services.values():
                if not service.enabled:
                    continue
                current, latest = versions.get(service.id, [None, None])
                running = bool(active and active["service_id"] == service.id)
                result.append(ServiceStatus(
                    service_id=service.id, id=service.id, name=service.name, container=service.container,
                    image=service.image, logo_url=service.logo_url, state="running",
                    current_version=current, latest_version=latest, update_available=current != latest,
                    update_enabled=service.update_enabled, update_in_progress=running,
                    update_percentage=active["update_percentage"] if running else None,
                ))
            return sorted(result, key=lambda item: (not item.update_available, item.name or ""))

    def enqueue(service_id: str) -> dict[str, Any]:
        with lock:
            service = services.get(service_id)
            if not service:
                raise HTTPException(404, "Service not found")
            if not service.update_enabled:
                raise HTTPException(403, "Updates disabled")
            snapshot()
            pending = [job for job in jobs if job["state"] in {"queued", "running"}]
            existing = next((job for job in pending if job["service_id"] == service_id), None)
            if existing:
                return existing
            now = monotonic()
            job = {
                "id": f"demo-{len(jobs) + 1}", "service_id": service_id, "state": "queued",
                "phase": "Preparing update", "update_percentage": 0,
                "demo_start": max([now] + [item["demo_start"] + 6 for item in pending]),
            }
            jobs.append(job)
            return job

    @app.post("/api/services/{service_id}/update", status_code=202)
    def update(service_id: str) -> dict[str, Any]:
        return {"ok": True, "job": enqueue(service_id)}

    @app.post("/api/updates", status_code=202)
    def update_all(payload: UpdateAllRequest) -> dict[str, Any]:
        with lock:
            selected = payload.service_ids if payload.service_ids is not None else list(services)
            pending = [enqueue(item.service_id) for item in statuses()
                       if item.service_id in selected and item.update_enabled and item.update_available]
            return {"ok": True, "jobs": pending}

    @app.get("/api/import/docker")
    def candidates() -> list[dict[str, Any]]:
        return []

    @app.post("/api/services/{service_id}/refresh")
    def refresh(service_id: str) -> ServiceConfig:
        with lock:
            if service_id not in services:
                raise HTTPException(404, "Service not found")
            return services[service_id]

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn

    with tempfile.TemporaryDirectory(prefix="patchdeck-demo-") as directory:
        os.environ["PATCHDECK_DATA_DIR"] = directory
        uvicorn.run(create_demo_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
