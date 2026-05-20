from fastapi.testclient import TestClient

from patchdeck.main import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_html_pages() -> None:
    index_response = client.get("/")
    settings_response = client.get("/settings")

    assert index_response.status_code == 200
    assert "Docker Import" not in index_response.text
    assert settings_response.status_code == 200
    assert "Update-Check-Intervall Minuten" in settings_response.text
    assert "Docker Import" in settings_response.text
    assert "Keine Auto-Updates" in settings_response.text


def test_service_crud() -> None:
    payload = {
        "id": "homeassistant",
        "name": "Home Assistant",
        "adapter": "docker",
        "enabled": True,
        "update_policy": "manual",
    }

    put_response = client.put("/api/services/homeassistant", json=payload)
    assert put_response.status_code == 200

    list_response = client.get("/api/services")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == "homeassistant"

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()[0]["state"] == "configured"


def test_settings_roundtrip() -> None:
    payload = {
        "update_interval_minutes": 30,
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
