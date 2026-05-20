from fastapi.testclient import TestClient

from patchdeck.main import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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

