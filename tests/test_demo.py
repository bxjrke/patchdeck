from fastapi.testclient import TestClient

from patchdeck import demo, docker_import, update_engine


def test_demo_is_isolated_and_simulates_serial_updates(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo must never contact Docker or start background workers")

    monkeypatch.setattr(docker_import, "docker_get", forbidden)
    monkeypatch.setattr(update_engine, "run_cmd", forbidden)
    monkeypatch.setattr(update_engine.UpdateEngine, "start_background_tasks", forbidden)
    now = [100.0]
    monkeypatch.setattr(demo, "monotonic", lambda: now[0])
    with TestClient(demo.create_demo_app(), headers={"X-Patchdeck-Request": "1"}) as client:
        assert client.get("/healthz").json() == {"status": "ok", "mode": "demo"}
        assert "demo-banner" in client.get("/").text
        assert "demo-banner" in client.get("/settings").text
        assert client.get("/static/theme.js").status_code == 200
        assert client.get("/api/import/docker").json() == []
        initial = {item["service_id"]: item for item in client.get("/api/status").json()}
        assert initial["homeassistant"]["update_available"]
        response = client.post("/api/updates", json={"service_ids": ["grocy", "homeassistant"]})
        assert response.status_code == 202
        assert len(response.json()["jobs"]) == 2
        queue = client.get("/api/update-queue").json()
        assert queue["active"]["service_id"] == "grocy"
        assert queue["pending"][0]["service_id"] == "homeassistant"
        now[0] += 3
        assert client.get("/api/update-queue").json()["active"]["update_percentage"] == 50
        now[0] += 4
        queue = client.get("/api/update-queue").json()
        assert queue["active"]["service_id"] == "homeassistant"
        now[0] += 6
        assert len(client.get("/api/update-queue").json()["recent"]) == 2
        assert not any(item["update_available"] for item in client.get("/api/status").json())
        assert client.post("/api/services/mosquitto/update").status_code == 403


def test_demo_settings_are_disposable_and_passwords_are_never_returned() -> None:
    with TestClient(demo.create_demo_app(), headers={"X-Patchdeck-Request": "1"}) as client:
        response = client.patch("/api/settings", json={"theme": "light", "mqtt_password": "test-secret"})
        assert response.status_code == 200
        assert response.json()["mqtt_password"] == ""
        assert client.get("/api/settings").json()["theme"] == "light"
        assert client.delete("/api/services/patchdeck").status_code == 403
        assert client.delete("/api/services/grocy").status_code == 204
    with TestClient(demo.create_demo_app()) as fresh:
        assert fresh.get("/api/settings").json()["theme"] == "system"
        assert len(fresh.get("/api/services").json()) == 4
        assert fresh.patch("/api/settings", json={"theme": "light"}).status_code == 403


def test_demo_partial_service_edits_preserve_hidden_configuration() -> None:
    with TestClient(demo.create_demo_app(), headers={"X-Patchdeck-Request": "1"}) as client:
        fixture = {
            "id": "grocy", "name": "Grocy", "compose_file": "/demo/compose.yaml",
            "metadata": {"note": "retain this field"},
        }
        assert client.put("/api/services/grocy", json=fixture).status_code == 200
        response = client.put("/api/services/grocy", json={"id": "grocy", "name": "Grocy edited"})
        assert response.status_code == 200
        assert response.json()["compose_file"] == fixture["compose_file"]
        assert response.json()["metadata"] == fixture["metadata"]
