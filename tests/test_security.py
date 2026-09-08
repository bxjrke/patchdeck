from __future__ import annotations

from fastapi.testclient import TestClient

from patchdeck import main
from patchdeck.models import ServiceConfig, Settings

WRITE_HEADERS = {"X-Patchdeck-Request": "1"}


def test_state_changes_require_an_explicit_browser_header() -> None:
    browser = TestClient(main.app)

    response = browser.patch("/api/settings", json={"theme": "dark"})

    assert response.status_code == 403
    assert "X-Patchdeck-Request" in response.json()["detail"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert main.store.get_settings().theme == "system"
    assert browser.get("/api/settings").status_code == 200


def test_security_headers_and_local_assets_are_enforced() -> None:
    browser = TestClient(main.app)

    page_response = browser.get("/")
    api_response = browser.get("/api/settings")

    assert page_response.headers["x-content-type-options"] == "nosniff"
    assert page_response.headers["referrer-policy"] == "no-referrer"
    assert page_response.headers["x-frame-options"] == "DENY"
    csp = page_response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unpkg.com" not in page_response.text
    assert "onclick=" not in page_response.text
    assert "/static/common.js" in page_response.text
    assert "/static/home.js" in page_response.text
    assert api_response.headers["cache-control"] == "no-store"


def test_settings_secret_is_write_only_and_partial_updates_preserve_fields() -> None:
    client = TestClient(main.app, headers=WRITE_HEADERS)
    original = Settings(
        mqtt_host="broker.internal",
        mqtt_password="top-secret",
        mqtt_retained_cleanup_topics=["custom/topic"],
        registry_refresh_hour=7,
    )
    main.store.update_settings(original)

    get_response = client.get("/api/settings")
    patch_response = client.patch("/api/settings", json={"theme": "dark"})
    put_response = client.put("/api/settings", json={"update_interval_minutes": 15})

    assert get_response.status_code == 200
    assert get_response.json()["mqtt_password"] == ""
    assert patch_response.status_code == 200
    assert patch_response.json()["mqtt_password"] == ""
    assert put_response.status_code == 200

    persisted = main.store.get_settings()
    assert persisted.mqtt_password == "top-secret"
    assert persisted.mqtt_retained_cleanup_topics == ["custom/topic"]
    assert persisted.registry_refresh_hour == 7
    assert persisted.theme == "dark"
    assert persisted.update_interval_minutes == 15


def test_partial_service_put_preserves_server_managed_fields() -> None:
    client = TestClient(main.app, headers=WRITE_HEADERS)
    main.store.upsert_service(
        ServiceConfig(
            id="demo-service",
            name="Original",
            description="Keep this",
            image="example/demo:latest",
            repo="https://example.test/repo",
            metadata={"owner": "platform"},
        )
    )

    response = client.put(
        "/api/services/demo-service",
        json={"id": "demo-service", "name": "Renamed"},
    )

    assert response.status_code == 200
    persisted = main.store.get_service("demo-service")
    assert persisted is not None
    assert persisted.name == "Renamed"
    assert persisted.description == "Keep this"
    assert persisted.image == "example/demo:latest"
    assert persisted.repo == "https://example.test/repo"
    assert persisted.metadata == {"owner": "platform"}


def test_service_configuration_listing_never_computes_runtime_status(monkeypatch) -> None:
    client = TestClient(main.app)
    main.store.upsert_service(ServiceConfig(id="zulu-service", name="Zulu"))
    main.store.upsert_service(ServiceConfig(id="alpha-service", name="Alpha"))

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("configuration listing must not query runtime status")

    monkeypatch.setattr(main.engine, "statuses", fail_if_called)

    response = client.get("/api/services")

    assert response.status_code == 200
    assert [service["id"] for service in response.json()] == ["alpha-service", "zulu-service"]
