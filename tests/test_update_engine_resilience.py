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


def test_queue_snapshot_reports_live_phase_without_status_lookup(tmp_path, monkeypatch) -> None:
    engine = UpdateEngine(JsonStore(tmp_path))
    engine._queue_jobs = [{"id": "job-1", "service_id": "demo-service", "state": "running"}]
    engine.mark_update_active("demo-service", True, phase="Pulling image", update_percentage=50)

    def fail_status_lookup(*_args, **_kwargs):
        raise AssertionError("queue polling must not contact Docker registries")

    monkeypatch.setattr(engine, "statuses", fail_status_lookup)
    snapshot = engine.queue_snapshot()

    assert snapshot["active"]["phase"] == "Pulling image"
    assert snapshot["active"]["update_percentage"] == 50


def test_bulk_queue_uses_candidates_and_keeps_self_update_last(tmp_path, monkeypatch) -> None:
    store = JsonStore(tmp_path)
    engine = UpdateEngine(store)
    for service_id in ("patchdeck", "grocy", "disabled"):
        store.upsert_service(ServiceConfig(id=service_id, name=service_id, update_enabled=service_id != "disabled", update_policy="disabled"))
    queued = []

    def fail_status_lookup(*_args, **_kwargs):
        raise AssertionError("enqueue must not recompute the dashboard status")

    def capture_enqueue(service, source):
        queued.append(service.id)
        return {"id": service.id, "state": "queued"}, True

    monkeypatch.setattr(engine, "statuses", fail_status_lookup)
    monkeypatch.setattr(engine, "enqueue_update", capture_enqueue)
    jobs = engine.enqueue_all_updates("web", ["patchdeck", "grocy", "grocy", "missing", "disabled"])

    assert queued == ["grocy", "patchdeck"]
    assert [job["id"] for job in jobs] == ["grocy", "patchdeck"]


def test_queue_keeps_detached_self_update_active_until_helper_finishes(tmp_path, monkeypatch) -> None:
    engine = UpdateEngine(JsonStore(tmp_path))
    engine._queue_jobs = [{"id": "job-self", "service_id": "patchdeck", "state": "succeeded", "started_at": 100}]
    engine.save_self_update_state({"service_id": "patchdeck", "started_at": 101, "in_progress": True})
    monkeypatch.setattr(engine, "active_update", lambda _id: {"phase": "Recreating", "update_percentage": 90})

    snapshot = engine.queue_snapshot()
    assert snapshot["active"]["id"] == "job-self"
    assert snapshot["active"]["state"] == "running"
    assert snapshot["recent"] == []

    engine.save_self_update_state({"started_at": 101, "in_progress": False, "ok": False, "finished_at": 110})
    snapshot = engine.queue_snapshot()
    assert snapshot["active"] is None
    assert snapshot["recent"][0]["state"] == "failed"
