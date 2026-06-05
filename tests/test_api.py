import json
from pathlib import Path

from fastapi.testclient import TestClient

from patchdeck import docker_import, icon_cache, main, update_engine
from patchdeck.docker_import import icon_slug_for_service, preferred_icon_slug
from patchdeck.main import app
from patchdeck.models import ServiceConfig, ServiceStatus, Settings
from patchdeck.store import JsonStore
from patchdeck.update_engine import UpdateEngine, effective_settings, format_release_notes_url, mqtt_cleanup_messages, mqtt_enabled


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
    assert "Update check interval" in settings_response.text
    assert "Update-Check-Intervall Minuten" not in settings_response.text
    assert "min" in settings_response.text
    assert 'id="mqtt-enabled" type="checkbox" role="switch"' in settings_response.text
    assert 'id="mqtt-fields"' in settings_response.text
    assert 'id="language"' in settings_response.text
    assert "Release notes source" in settings_response.text
    assert "Docker-Scan Importvorschläge" not in settings_response.text
    assert "Icon path" in settings_response.text
    assert "stores found files locally" in settings_response.text
    assert "Hinzufügen" in settings_response.text
    assert "{version}" in settings_response.text
    assert "saveButton(\"saveExistingService" not in settings_response.text
    assert "cdn.simpleicons.org" not in settings_response.text
    assert "save-button" in settings_response.text
    assert 'data-save-action="settings"' not in settings_response.text
    assert 'id="mqtt-state-label"' in settings_response.text
    assert "lucide" in settings_response.text
    assert "Docker Import" in settings_response.text
    assert "The scan is always available manually" in settings_response.text
    assert "Preview build. Updates run only when triggered for a configured service." in settings_response.text
    assert 'class="footer"' in settings_response.text
    assert 'aria-label="Patchdeck version"' in settings_response.text
    assert "Patchdeck 0.2.1" in settings_response.text
    assert '/static/favicon.png?v0.2.1-logo4' in index_response.text
    assert '/static/favicon.svg?v0.2.1-logo4' in index_response.text
    assert '/static/apple-touch-icon.png?v0.2.1-logo4' in index_response.text
    assert '<img class="brand-logo"' not in index_response.text
    assert 'data-i18n="settings">Settings</span>' in index_response.text
    assert 'badge-action' in index_response.text
    assert 'version-link' in index_response.text
    assert 'Release Notes</a>' not in index_response.text
    assert 'repullCurrent' not in index_response.text
    assert "service-policy" not in settings_response.text
    assert "Konfigurieren" not in index_response.text


def test_static_icons() -> None:
    for path in ("/static/settings.svg", "/static/patchdeck.svg", "/static/favicon.svg"):
        response = client.get(path)

        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]


def test_png_favicons() -> None:
    for path in ("/static/favicon.png", "/static/apple-touch-icon.png"):
        response = client.get(path)

        assert response.status_code == 200
        assert "image/png" in response.headers["content-type"]


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
            compose_file="/srv/patchdeck/examples/media/docker-compose.yml",
            compose_project_dir="/srv/patchdeck/examples/media",
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


def test_self_service_is_created_from_current_container(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    monkeypatch.setenv("HOSTNAME", "abc123")

    def fake_service_from_container(container: str, base: ServiceConfig | None = None) -> ServiceConfig:
        assert container == "abc123"
        assert base is not None
        return ServiceConfig(
            id=base.id,
            name=base.name,
            container="patchdeck",
            image="ghcr.io/bxjrke/patchdeck:main",
            compose_file="/srv/patchdeck/docker-compose.yml",
            compose_project_dir="/srv/patchdeck",
            compose_service="patchdeck",
            update_enabled=base.update_enabled,
            update_policy=base.update_policy,
        )

    monkeypatch.setattr(main, "service_from_container", fake_service_from_container)

    main.ensure_self_service()

    service = test_store.get_service("patchdeck")
    assert service is not None
    assert service.name == "Patchdeck"
    assert service.logo_url == "/static/patchdeck.svg?v0.2.1-logo4"
    assert service.icon_slug is None
    assert service.update_enabled is True
    assert service.update_policy == "manual"
    assert service.compose_service == "patchdeck"
    assert service.release_notes == "https://github.com/bxjrke/patchdeck/releases"


def test_patchdeck_service_cannot_be_deleted(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    test_store.upsert_service(ServiceConfig(id="patchdeck", name="Patchdeck"))

    response = client.delete("/api/services/patchdeck")

    assert response.status_code == 403
    assert test_store.get_service("patchdeck") is not None


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


def test_registry_cache_refreshes_when_local_digest_changed(tmp_path, monkeypatch) -> None:
    test_store = JsonStore(tmp_path)
    test_store.update_settings(Settings(registry_refresh_hour=23, registry_refresh_minute=59, registry_refresh_window_minutes=1))
    engine = UpdateEngine(test_store)
    engine.registry_cache_file.write_text(json.dumps({
        "example/demo:latest|linux|amd64": {
            "image": "example/demo:latest",
            "arch": "amd64",
            "os": "linux",
            "label": "main",
            "digest": "sha256:old",
            "refresh_day": "2026-06-05",
            "refreshed_at": 1780631276,
        }
    }), encoding="utf-8")

    monkeypatch.setattr(update_engine, "latest_registry_version", lambda image, audit, arch="amd64", os_name="linux": ("0.2.0", "sha256:new"))

    label, digest = engine.cached_latest_image_info("example/demo:latest", "amd64", "linux", "sha256:new")

    assert label == "0.2.0"
    assert digest == "sha256:new"
    cache = json.loads(engine.registry_cache_file.read_text(encoding="utf-8"))
    assert cache["example/demo:latest|linux|amd64"]["label"] == "0.2.0"
    assert cache["example/demo:latest|linux|amd64"]["digest"] == "sha256:new"


def test_registry_cache_refreshes_after_update_interval(tmp_path, monkeypatch) -> None:
    test_store = JsonStore(tmp_path)
    test_store.update_settings(Settings(update_interval_minutes=1))
    engine = UpdateEngine(test_store)
    monkeypatch.setattr(update_engine.time, "time", lambda: 1780659600)
    engine.registry_cache_file.write_text(json.dumps({
        "ghcr.io/bxjrke/patchdeck:main|linux|amd64": {
            "image": "ghcr.io/bxjrke/patchdeck:main",
            "arch": "amd64",
            "os": "linux",
            "label": "0.1.1",
            "digest": "sha256:current",
            "refresh_day": "2026-06-05",
            "refreshed_at": 1780659300,
        }
    }), encoding="utf-8")

    monkeypatch.setattr(update_engine, "latest_registry_version", lambda image, audit, arch="amd64", os_name="linux": ("0.2.0", "sha256:new"))

    label, digest = engine.cached_latest_image_info("ghcr.io/bxjrke/patchdeck:main", "amd64", "linux", "sha256:current")

    assert label == "0.2.0"
    assert digest == "sha256:new"
    cache = json.loads(engine.registry_cache_file.read_text(encoding="utf-8"))
    assert cache["ghcr.io/bxjrke/patchdeck:main|linux|amd64"]["label"] == "0.2.0"
    assert cache["ghcr.io/bxjrke/patchdeck:main|linux|amd64"]["digest"] == "sha256:new"


def test_registry_cache_is_reused_within_update_interval(tmp_path, monkeypatch) -> None:
    test_store = JsonStore(tmp_path)
    test_store.update_settings(Settings(update_interval_minutes=5))
    engine = UpdateEngine(test_store)
    monkeypatch.setattr(update_engine.time, "time", lambda: 1780659600)
    engine.registry_cache_file.write_text(json.dumps({
        "ghcr.io/bxjrke/patchdeck:main|linux|amd64": {
            "image": "ghcr.io/bxjrke/patchdeck:main",
            "arch": "amd64",
            "os": "linux",
            "label": "0.1.1",
            "digest": "sha256:current",
            "refresh_day": "2026-06-05",
            "refreshed_at": 1780659500,
        }
    }), encoding="utf-8")
    calls = []

    def fake_latest_registry_version(image, audit, arch="amd64", os_name="linux"):
        calls.append(image)
        return "0.2.0", "sha256:new"

    monkeypatch.setattr(update_engine, "latest_registry_version", fake_latest_registry_version)

    label, digest = engine.cached_latest_image_info("ghcr.io/bxjrke/patchdeck:main", "amd64", "linux", "sha256:current")

    assert label == "0.1.1"
    assert digest == "sha256:current"
    assert calls == []


def test_release_notes_url_templates(tmp_path, monkeypatch) -> None:
    use_test_store(tmp_path, monkeypatch)
    engine = UpdateEngine(main.store)

    assert format_release_notes_url("https://example.test/releases/{version}", "1.2.3") == "https://example.test/releases/1.2.3"
    assert format_release_notes_url("https://example.test/{major}/{minor}/{patch}", "1.2.3") == "https://example.test/1/2/3"
    assert engine.release_notes_url("https://example.test/releases/{version_url}", "2026.6 beta") == "https://example.test/releases/2026.6%20beta"
    assert engine.release_notes_url("https://example.test/changelog", "1.2.3") == "https://example.test/changelog"
    assert engine.release_notes_url("https://example.test/changelog", None) == "https://example.test/changelog"
    assert engine.release_notes_url("unsupported", "1.2.3") is None


def test_status_detects_update_when_local_tag_points_to_newer_image(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    engine = UpdateEngine(test_store)
    old_image = {
        "Id": "sha256:old",
        "RepoDigests": [],
        "Config": {"Labels": {"org.opencontainers.image.version": "1.0.0"}},
    }
    new_image = {
        "Id": "sha256:new",
        "RepoDigests": [],
        "Config": {"Labels": {"org.opencontainers.image.version": "1.1.0"}},
    }

    def fake_run_cmd(args: list[str], cwd: str | None = None, timeout: int = 45) -> tuple[int, str]:
        if args == [update_engine.DOCKER_BIN, "inspect", "demo", "--format", "{{.Image}}"]:
            return 0, "sha256:old"
        if args == [update_engine.DOCKER_BIN, "image", "inspect", "sha256:old"]:
            return 0, json.dumps([old_image])
        if args == [update_engine.DOCKER_BIN, "image", "inspect", "example/demo:latest"]:
            return 0, json.dumps([new_image])
        if args == [update_engine.DOCKER_BIN, "inspect", "demo", "--format", "{{.State.Status}}"]:
            return 0, "running"
        return 1, "unexpected command"

    monkeypatch.setattr(update_engine, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(engine, "cached_latest_image_info", lambda image, arch="amd64", os_name="linux", known_local_digest=None: (None, None))

    status = engine.service_status(ServiceConfig(id="demo", name="Demo", container="demo", image="example/demo:latest"))

    assert status.current_version == "1.0.0"
    assert status.latest_version == "1.1.0"
    assert status.current_digest == "sha256:old"
    assert status.latest_digest == "sha256:new"
    assert status.update_available is True



def test_patchdeck_image_version_label_is_used_for_display(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    engine = UpdateEngine(test_store)
    image_details = {
        "Id": "sha256:current",
        "RepoDigests": ["ghcr.io/bxjrke/patchdeck@sha256:current"],
        "Config": {"Labels": {"org.opencontainers.image.version": "0.2.0"}},
    }

    def fake_run_cmd(args: list[str], cwd: str | None = None, timeout: int = 45) -> tuple[int, str]:
        if args == [update_engine.DOCKER_BIN, "inspect", "patchdeck", "--format", "{{.Image}}"]:
            return 0, "sha256:current"
        if args == [update_engine.DOCKER_BIN, "image", "inspect", "sha256:current"]:
            return 0, json.dumps([image_details])
        if args == [update_engine.DOCKER_BIN, "image", "inspect", "ghcr.io/bxjrke/patchdeck:main"]:
            return 0, json.dumps([image_details])
        if args == [update_engine.DOCKER_BIN, "inspect", "patchdeck", "--format", "{{.State.Status}}"]:
            return 0, "running"
        return 1, "unexpected command"

    monkeypatch.setattr(update_engine, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(engine, "cached_latest_image_info", lambda image, arch="amd64", os_name="linux", known_local_digest=None: ("0.2.0", "sha256:current"))

    status = engine.service_status(ServiceConfig(id="patchdeck", name="Patchdeck", container="patchdeck", image="ghcr.io/bxjrke/patchdeck:main", release_notes="https://github.com/bxjrke/patchdeck/releases"))

    assert status.current_version == "0.2.0"
    assert status.latest_version == "0.2.0"
    assert status.release_notes_url == "https://github.com/bxjrke/patchdeck/releases"


def test_patchdeck_self_update_recreate_runs_detached(tmp_path, monkeypatch) -> None:
    engine = UpdateEngine(JsonStore(tmp_path))
    popen_calls = []

    def fake_run_cmd(args: list[str], cwd: str | None = None, timeout: int = 45) -> tuple[int, str]:
        assert args == [update_engine.DOCKER_BIN, "compose", "-f", "/srv/patchdeck/docker-compose.yml", "pull", "patchdeck"]
        assert cwd == "/srv/patchdeck"
        return 0, "pulled"

    def fake_popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(update_engine, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(update_engine.subprocess, "Popen", fake_popen)

    code, output = engine.run_update(
        ServiceConfig(
            id="patchdeck",
            name="Patchdeck",
            compose_file="/srv/patchdeck/docker-compose.yml",
            compose_project_dir="/srv/patchdeck",
            compose_service="patchdeck",
        )
    )

    assert code == 0
    assert "Self-update recreate started" in output
    assert popen_calls[0][0] == [update_engine.DOCKER_BIN, "compose", "-f", "/srv/patchdeck/docker-compose.yml", "up", "-d", "--no-deps", "patchdeck"]
    assert popen_calls[0][1]["cwd"] == "/srv/patchdeck"
    assert popen_calls[0][1]["start_new_session"] is True


def test_mqtt_host_env_does_not_enable_mqtt_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("PATCHDECK_MQTT_HOST", "mosquitto")

    settings = effective_settings(Settings(mqtt_enabled=False))

    assert settings.mqtt_host == "mosquitto"
    assert settings.mqtt_enabled is False
    assert mqtt_enabled(settings) is False


def test_mqtt_can_be_enabled_explicitly_from_env(monkeypatch) -> None:
    monkeypatch.setenv("PATCHDECK_MQTT_ENABLED", "true")
    monkeypatch.setenv("PATCHDECK_MQTT_HOST", "mosquitto")

    settings = effective_settings(Settings(mqtt_enabled=False))

    assert settings.mqtt_enabled is True
    assert mqtt_enabled(settings) is True


def test_mqtt_command_is_rejected_when_disabled(tmp_path) -> None:
    test_store = JsonStore(tmp_path)
    test_store.update_settings(Settings(mqtt_enabled=False, mqtt_host="mosquitto"))
    test_store.upsert_service(ServiceConfig(id="homeassistant", name="Home Assistant", update_enabled=True))
    engine = UpdateEngine(test_store)
    calls = []

    def fake_perform_update(service: ServiceConfig, source: str) -> tuple[bool, str]:
        calls.append((service.id, source))
        return True, "ok"

    engine.perform_update = fake_perform_update  # type: ignore[method-assign]

    engine.handle_mqtt_command("patchdeck/homeassistant/command", b"install")

    assert calls == []


def test_mqtt_cleanup_messages_clear_home_assistant_discovery() -> None:
    settings = Settings(mqtt_enabled=True, mqtt_host="mosquitto")
    messages = mqtt_cleanup_messages(settings, [ServiceStatus(service_id="homeassistant", id="homeassistant", name="Home Assistant")])

    assert ("homeassistant/update/patchdeck_homeassistant/config", b"", True) in messages
    assert ("homeassistant/update/homeassistant/config", b"", True) in messages
    assert ("patchdeck/homeassistant/state", b"", True) in messages
    assert ("patchdeck/homeassistant/json", b"", True) in messages
    assert ("patchdeck/homeassistant/latest_version", b"", True) in messages


def test_disabling_mqtt_clears_retained_entities(tmp_path, monkeypatch) -> None:
    test_store = use_test_store(tmp_path, monkeypatch)
    test_store.update_settings(Settings(mqtt_enabled=True, mqtt_host="mosquitto"))
    test_store.upsert_service(ServiceConfig(id="homeassistant", name="Home Assistant"))
    cleared = []

    def fake_clear(settings: Settings) -> None:
        cleared.append(settings)

    monkeypatch.setattr(main.engine, "clear_mqtt_entities", fake_clear)

    response = client.put(
        "/api/settings",
        json={
            "update_interval_minutes": 60,
            "language": "de",
            "mqtt_enabled": False,
            "mqtt_host": "mosquitto",
            "mqtt_port": 1883,
            "mqtt_discovery_prefix": "homeassistant",
            "mqtt_base_topic": "patchdeck",
            "theme": "system",
        },
    )

    assert response.status_code == 200
    assert len(cleared) == 1
    assert cleared[0].mqtt_enabled is True
    assert cleared[0].mqtt_host == "mosquitto"


def test_settings_roundtrip() -> None:
    payload = {
        "update_interval_minutes": 30,
        "language": "en",
        "mqtt_enabled": True,
        "mqtt_discovery_prefix": "homeassistant",
        "mqtt_base_topic": "patchdeck",
        "theme": "dark",
    }

    put_response = client.put("/api/settings", json=payload)
    assert put_response.status_code == 200

    get_response = client.get("/api/settings")
    assert get_response.status_code == 200
    assert get_response.json()["theme"] == "dark"
    assert get_response.json()["language"] == "en"


def test_container_workflow_overrides_branch_version_label() -> None:
    workflow = Path(".github/workflows/container.yml").read_text(encoding="utf-8")

    assert "Read project version" in workflow
    assert "pyproject.toml" in workflow
    assert "org.opencontainers.image.version=${{ steps.project.outputs.version }}" in workflow
    assert "io.patchdeck.version=${{ steps.project.outputs.version }}" in workflow
