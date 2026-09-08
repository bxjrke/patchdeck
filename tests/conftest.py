from __future__ import annotations

import os
import tempfile

import pytest

# Pytest imports this file before test modules. Set a disposable data directory
# before patchdeck.main creates its default application runtime.
_SESSION_DATA = tempfile.TemporaryDirectory(prefix="patchdeck-tests-")
os.environ["PATCHDECK_DATA_DIR"] = _SESSION_DATA.name

from patchdeck import main  # noqa: E402
from patchdeck.runtime import AppRuntime  # noqa: E402
from patchdeck.store import JsonStore  # noqa: E402
from patchdeck.update_engine import UpdateEngine  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """No test may read or write the developer's ./data directory."""

    test_store = JsonStore(tmp_path)
    test_engine = UpdateEngine(test_store)
    test_runtime = AppRuntime(store=test_store, engine=test_engine)
    monkeypatch.setattr(main, "store", test_store)
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "runtime", test_runtime)
    monkeypatch.setattr(main.app.state, "runtime", test_runtime)
    yield
    test_engine.stop_background_tasks(join_timeout=0.1)
