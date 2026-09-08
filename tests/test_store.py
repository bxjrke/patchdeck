from __future__ import annotations

import stat

import pytest

from patchdeck import store as store_module
from patchdeck.models import ServiceConfig, Settings
from patchdeck.store import JsonStore, StoreCorruptionError


def test_invalid_settings_fail_loudly_without_overwriting_file(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    invalid_content = "{not-json"
    settings_path.write_text(invalid_content, encoding="utf-8")

    with pytest.raises(StoreCorruptionError, match="settings.json"):
        JsonStore(tmp_path)

    assert settings_path.read_text(encoding="utf-8") == invalid_content


def test_invalid_services_fail_loudly_without_overwriting_file(tmp_path) -> None:
    services_path = tmp_path / "services.json"
    invalid_content = '{"unexpected": "object"}'
    services_path.write_text(invalid_content, encoding="utf-8")

    with pytest.raises(StoreCorruptionError, match="services.json"):
        JsonStore(tmp_path)

    assert services_path.read_text(encoding="utf-8") == invalid_content


def test_settings_and_services_are_persisted_independently(tmp_path) -> None:
    store = JsonStore(tmp_path)
    store.upsert_service(ServiceConfig(id="first-service", name="First"))
    services_path = tmp_path / "services.json"
    services_before = services_path.read_bytes()
    services_mtime = services_path.stat().st_mtime_ns

    store.update_settings(Settings(theme="dark"))

    assert services_path.read_bytes() == services_before
    assert services_path.stat().st_mtime_ns == services_mtime

    settings_path = tmp_path / "settings.json"
    settings_before = settings_path.read_bytes()
    settings_mtime = settings_path.stat().st_mtime_ns

    store.upsert_service(ServiceConfig(id="second-service", name="Second"))

    assert settings_path.read_bytes() == settings_before
    assert settings_path.stat().st_mtime_ns == settings_mtime


def test_persisted_state_files_are_owner_only(tmp_path) -> None:
    store = JsonStore(tmp_path)
    store.update_settings(Settings())
    store.upsert_service(ServiceConfig(id="demo-service", name="Demo"))

    assert stat.S_IMODE((tmp_path / "settings.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "services.json").stat().st_mode) == 0o600


def test_failed_writes_do_not_change_in_memory_state(tmp_path, monkeypatch) -> None:
    store = JsonStore(tmp_path)
    original_settings = Settings(theme="light")
    original_service = ServiceConfig(id="stable-service", name="Stable")
    store.update_settings(original_settings)
    store.upsert_service(original_service)

    def fail_write(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store_module, "atomic_write_text", fail_write)

    with pytest.raises(OSError, match="disk full"):
        store.update_settings(Settings(theme="dark"))
    with pytest.raises(OSError, match="disk full"):
        store.upsert_service(ServiceConfig(id="new-service", name="New"))

    assert store.get_settings() == original_settings
    assert store.get_service("stable-service") == original_service
    assert store.get_service("new-service") is None
