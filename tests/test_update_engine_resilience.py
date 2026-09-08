from __future__ import annotations

import json
import threading
import time

import pytest

from patchdeck.models import ServiceConfig
from patchdeck.store import JsonStore
from patchdeck.update_engine import UpdateEngine


def test_queue_worker_survives_an_unexpected_job_failure(tmp_path, monkeypatch) -> None:
    store = JsonStore(tmp_path)
    engine = UpdateEngine(store)
    first = ServiceConfig(id="first-service", name="First", update_enabled=True)
    second = ServiceConfig(id="second-service", name="Second", update_enabled=True)
    store.upsert_service(first)
    store.upsert_service(second)
    second_started = threading.Event()
    calls: list[str] = []

    def flaky_update(service: ServiceConfig, _source: str) -> tuple[bool, str]:
        calls.append(service.id)
        if service.id == first.id:
            raise RuntimeError("simulated adapter crash")
        second_started.set()
        return True, "Update completed."

    monkeypatch.setattr(engine, "perform_update", flaky_update)

    try:
        engine.enqueue_update(first, "test")
        engine.enqueue_update(second, "test")

        assert second_started.wait(2)
        deadline = time.monotonic() + 2
        snapshot = engine.queue_snapshot()
        while len(snapshot["recent"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = engine.queue_snapshot()

        assert calls == ["first-service", "second-service"]
        assert [job["state"] for job in snapshot["recent"][-2:]] == ["failed", "succeeded"]
        assert "unexpected internal error" in snapshot["recent"][-2]["phase"].lower()
        assert engine._queue_worker_thread is not None
        assert engine._queue_worker_thread.is_alive()

        events = [
            json.loads(line)["event"]
            for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
        ]
        assert "update_worker_error" in events
    finally:
        engine.stop_background_tasks(join_timeout=1)


def test_active_update_is_cleared_when_setup_audit_fails(tmp_path, monkeypatch) -> None:
    engine = UpdateEngine(JsonStore(tmp_path))
    service = ServiceConfig(id="demo-service", name="Demo", update_enabled=True)

    def fail_audit(*_args, **_kwargs) -> None:
        raise OSError("audit disk full")

    monkeypatch.setattr(engine, "audit", fail_audit)

    with pytest.raises(OSError, match="audit disk full"):
        engine.perform_update(service, "test")

    assert engine.active_update(service.id) is None
