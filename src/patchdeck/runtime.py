from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .store import JsonStore
from .update_engine import UpdateEngine


@dataclass(slots=True)
class AppRuntime:
    """Application-owned services shared by API handlers and lifecycle hooks."""

    store: JsonStore
    engine: UpdateEngine

    @classmethod
    def create(cls, data_dir: str | Path | None = None) -> "AppRuntime":
        store = JsonStore(data_dir)
        return cls(store=store, engine=UpdateEngine(store))
