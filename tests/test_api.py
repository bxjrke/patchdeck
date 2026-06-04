from pathlib import Path

from fastapi.testclient import TestClient

from patchdeck import docker_import, icon_cache, main
from patchdeck.docker_import import icon_slug_for_service, preferred_icon_slug
from patchdeck.main import app
from patchdeck.models import ServiceConfig
from patchdeck.store import JsonStore
from patchdeck.update_engine import UpdateEngine, format_release_notes_url


client = TestClient(app)


def use_test_store(tmp_path, monkeypatch) -> JsonStore:
    test_store = JsonStore(tmp_path)
    monkeypatch.setattr(main, "store", test_store)
    monkeypatch.setattr(main, "engine", UpdateEngine(test_store))
    return test_store


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_html_pages() -> None:
    index_response = client.get("/")
    settings_response = client.get("/settings")

    assert index_response.status_code == 200
    assert 'id="docker-candidates"' not in index_response.text
    assert settings_response.status_code == 200
    assert "Update-Check-Intervall" in settings_response.text
    assert "Update-Check-Intervall Minuten" not in settings_response.text
    assert "min" in settings_response.text
    assert 'id="mqtt-enabled" type="checkbox" role="switch"' in settings_response.text
    assert 'id="mqtt-fields"' in settings_response.text
    assert 'id="language"' in settings_response.text
    assert "Release Notes Quelle" in settings_response.text
    assert "Docker-Scan Importvorschläge" not in settings_response.text
    assert "Icon Pfad" in settings_response.text
    assert "speichert gefundene Dateien lokal" in settings_response.text
    assert "Hinzufügen" in settings_response.text
    assert "{version}" in settings_response.text
    assert "saveButton(\"saveExistingService" not in settings_response.text
    assert "cdn.simpleicons.org" not in settings_response.text
    assert "save-button" in settings_response.text
    assert 'data-save-action="settings"' not in settings_response.text
    assert 'id="mqtt-state-label"' in settings_response.text
    assert "lucide" in settings_response.text
    assert "Docker Import" in settings_response.text
    assert "Der Scan ist immer manuell möglich" in settings_response.text
    assert "Updates werden nur pro geeignetem Dienst gezielt ausgeführt" in settings_response.text
    assert "service-policy" not in settings_response.text
    assert "Konfigurieren" not in index_response.text


def test_settings_icon() -> None:
    response = client.get("/static/settings.svg")

    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]


def test_service_crud(tmp_path, monkeypatch) -> None:
    use_test_store(tmp_path, monkeypatch)
    payload = {
        "id": "homeassistant",
        "name": "Home Assistant",
        "adapter": "docker",
        "enabled": True,
        "update_policy": "manual",
        "container": "homeassistant",
        "icon_slug": "homeassistant",
        "logo_url": "https://example.test/homeassistant.svg",
    }

    put_response = client.put("/api/services/homeassistant", json=payload)
    assert put_response.status_code == 200

    list_response = client.get("/api/services")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == "homeassistant"

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()[0]["service_id"] == "homeassistant"
    assert status_response.json()[0]["icon_slug"] == "homeassistant"


def test_service_refresh_from_docker(tmp_path, monkeypatch) -> None:
    use_test_store(tmp_path, monkeypatch)

    def fake_download_icon(icon_dir: Path, slug: str) -> Path:
        icon_dir.mkdir(parents=True, exist_ok=True)
        target = icon_dir / f"{slug}.svg"
        target.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        return target

    monkeypatch.setattr(icon_cache, "download_icon", fake_download_icon)
    main.store.upsert_service(ServiceConfig(id="bazarr", name="Bazarr", container="bazarr"))

    def fake_service_from_container(container: str, base: ServiceConfig | None = None) -> ServiceConfig:
        assert container == "bazarr"
        assert base is not None
        return ServiceConfig(
            id=base.id,
            name=base.name,
            container="bazarr",
            image="lscr.io/linuxserver/bazarr:latest",
            compose_file="/opt/stacks/media/docker-compose.yml",
            compose_project_dir="/opt/stacks/media",
            compose_service="bazarr",
            icon_slug="bazarr",
        )

    monkeypatch.setattr(main, "service_from_container", fake_service_from_container)

    response = client.post("/api/services/bazarr/refresh")

    assert response.status_code == 200
    assert response.json()["image"] == "lscr.io/linuxserver/bazarr:latest"
    assert response.json()["compose_service"] == "bazarr"
    assert response.json()["icon_slug"] == "bazarr"


def test_filebrowser_icon_is_detected() -> None:
    assert icon_slug_for_service("filebrowser", "filebrowser/filebrowser:s6") == "filebrowser"


def test_docker_import_enables_updates_by_default(monkeypatch) -> None:
    def fake_docker_get(path: str, socket_path: str = docker_import.DOCKER_SOCKET):
        assert path == "/containers/json?all=1"
        return [
            {
                "Id": "abcdef1234567890",
                "Names": ["/filebrowser"],
                "Image": "filebrowser/filebrowser:s6",
                "State": "running",
                "Labels": {"com.docker.compose.service": "filebrowser"},
            }
        ]

    monkeypatch.setattr(docker_import, "docker_get", fake_docker_get)

    candidates = docker_import.list_container_candidates(set())

    assert candidates[0].suggested_service.update_enabled is True
    assert candidates[0].suggested_service.update_policy == "disabled"
    assert candidates[0].suggested_service.icon_slug == "filebrowser"


def test_service_icon_is_cached_on_save(tmp_path, monkeypatch) -> None:
    use_test_store(tmp_path, monkeypatch)

    def fake_download_icon(icon_dir: Path, slug: str) -> Path:
        icon_dir.mkdir(parents=True, exist_ok=True)
        target = icon_dir / f"{slug}.svg"
        target.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        return target

    monkeypatch.setattr(icon_cache, "download_icon", fake_download_icon)
    payload = {"id": "filebrowser", "name": "Filebrowser", "icon_slug": "filebrowser"}

    put_response = client.put("/api/services/filebrowser", json=payload)
    icon_response = client.get("/api/icons/filebrowser.svg")

    assert put_response.status_code == 200
    assert put_response.json()["logo_url"] == "/api/icons/filebrowser.svg"
    assert icon_response.status_code == 200


def test_generic_icon_slug_is_replaced_by_specific_detection() -> None:
    base = ServiceConfig(id="bazarr", name="Bazarr", container="bazarr", icon_slug="linuxserver")

    assert preferred_icon_slug(base, "bazarr") == "bazarr"


def test_services_with_updates_are_sorted_first(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    test_store.upsert_service(
        ServiceConfig(
            id="stable-service",
            name="Stable Service",
            metadata={
                "mock_status": {
                    "current_version": "1.0.0",
                    "latest_version": "1.0.0",
                    "update_available": False,
                },
            },
        )
    )
    test_store.upsert_service(
        ServiceConfig(
            id="needs-update",
            name="Needs Update",
            metadata={
                "mock_status": {
                    "current_version": "1.0.0",
                    "latest_version": "1.1.0",
                    "update_available": True,
                },
            },
        )
    )

    list_response = client.get("/api/services")
    status_response = client.get("/api/status")

    assert list_response.status_code == 200
    assert [service["id"] for service in list_response.json()] == ["needs-update", "stable-service"]
    assert status_response.status_code == 200
    assert [service["service_id"] for service in status_response.json()] == ["needs-update", "stable-service"]


def test_release_notes_url_templates(tmp_path, monkeypatch) -> None:
    use_test_store(tmp_path, monkeypatch)
    engine = UpdateEngine(main.store)

    assert format_release_notes_url("https://example.test/releases/{version}", "1.2.3") == "https://example.test/releases/1.2.3"
    assert format_release_notes_url("https://example.test/{major}/{minor}/{patch}", "1.2.3") == "https://example.test/1/2/3"
    assert engine.release_notes_url("https://example.test/releases/{version_url}", "2026.6 beta") == "https://example.test/releases/2026.6%20beta"
    assert engine.release_notes_url("https://example.test/changelog", "1.2.3") == "https://example.test/changelog"
    assert engine.release_notes_url("unsupported", "1.2.3") is None


def test_settings_roundtrip() -> None:
    payload = {
        "update_interval_minutes": 30,
        "language": "en",
        "mqtt_enabled": True,
        "mqtt_discovery_prefix": "homeassistant",
        "mqtt_base_topic": "patchdeck",
        "docker_auto_import_enabled": False,
        "theme": "dark",
    }

    put_response = client.put("/api/settings", json=payload)
    assert put_response.status_code == 200

    get_response = client.get("/api/settings")
    assert get_response.status_code == 200
    assert get_response.json()["theme"] == "dark"
    assert get_response.json()["language"] == "en"
