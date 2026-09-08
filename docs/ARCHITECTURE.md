# Patchdeck Architecture

This document describes the architecture that the code is expected to preserve. It is deliberately small: Patchdeck is a host-local control plane, not a distributed deployment platform.

## Goals and Constraints

Patchdeck optimizes for:

- reliable, explicit updates of selected Docker Compose services;
- simple operation on one Linux host;
- data integrity across crashes and restarts;
- clear module boundaries and testable dependencies;
- predictable builds and upgrades.

One Patchdeck instance owns one Docker daemon and one data directory. Running several replicas against the same Docker socket and JSON directory is intentionally unsupported. A horizontally scaled edition would first need shared durable storage, a distributed queue, and distributed leases.

## Module Boundaries

| Module | Responsibility | Must not own |
| --- | --- | --- |
| `main.py` | Application factory, lifespan, middleware, HTML shell | Business rules, persistence, Docker calls |
| `api.py` | HTTP routes, request merging, response redaction | Global runtime construction, UI assets |
| `runtime.py` | Dependency composition for store and engine | Request handling |
| `models.py` | Validated API and persistence contracts | I/O |
| `store.py` | Atomic JSON persistence and migrations | Docker, MQTT, HTTP |
| `update_engine.py` | Status orchestration, serialized update queue, lifecycle | HTML and route definitions |
| `docker_import.py` | Docker discovery and configuration suggestions | Persistent state |
| `icon_cache.py` | Local icon acquisition and caching | API routing |
| `static/*.js` and `static/app.css` | Browser behavior and presentation | Server-side state |

The dependency direction is:

```text
main -> api -> runtime -> store
                    \-> update engine -> Docker / registries / MQTT
api  -> models
UI   -> /api contracts
```

The FastAPI application stores one `AppRuntime` on `app.state`. Routes receive it through dependency injection. Tests replace that runtime with a temporary one instead of mutating production data.

## Core Flows

### Configuration read

1. `GET /api/services` reads validated configuration from `JsonStore`.
2. It sorts by display name only.
3. It never contacts Docker or a registry.

Runtime status is a separate `GET /api/status` operation. Keeping these flows separate prevents a settings page request from unexpectedly performing slow network I/O.

### Update request

1. The browser sends a state-changing request with `X-Patchdeck-Request: 1`.
2. The API validates the service and its update policy.
3. `UpdateEngine` adds an idempotent job to the persisted queue.
4. One worker processes jobs sequentially under a host file lock.
5. A failure is recorded on that job; unexpected failures do not terminate the worker.
6. Last-run state and the audit log are persisted before the active state is cleared.

Patchdeck updates itself through a detached helper because the application process cannot safely recreate its own container inline.

## Persistence Invariants

`settings.json` and `services.json` are authoritative state.

- Missing files mean a new installation and use model defaults.
- Existing but invalid files fail startup with `StoreCorruptionError`; Patchdeck never silently replaces them with defaults.
- Settings and services are written independently.
- A new value is written before the in-memory value is committed.
- Files are replaced atomically using a unique temporary file, `fsync`, and `os.replace`.
- State files containing configuration or secrets use mode `0600`.
- The settings model carries `schema_version` for explicit future migrations.

Queue, cache, and last-run files are recoverable operational state. An interrupted `running` queue job is changed back to `queued` when the engine starts.

Operators must still back up the complete data directory before upgrades. Atomic writes protect consistency, not against disk loss or an unwanted valid change.

## Concurrency and Lifecycle

- The update queue is serialized because concurrent Compose changes on one host are unsafe.
- The queue condition protects queue state; dedicated locks protect active updates, audit writes, last-run data, registry cache, and MQTT startup.
- Background threads are created during the application lifespan and receive a shared stop event during shutdown.
- MQTT sockets have finite timeouts so shutdown and recovery cannot block forever.
- Registry results are cached to keep ordinary dashboard requests bounded after the first lookup.

## HTTP and Browser Security

Patchdeck has no built-in identity provider. It must remain on a trusted network or behind an authenticated reverse proxy.

Defense-in-depth provided by the application:

- state-changing API methods require a non-simple custom request header;
- the browser never receives a stored MQTT password; that field is write-only;
- settings autosave uses partial updates, so hidden and newer fields are preserved;
- scripts, styles, translations, and icons are packaged locally;
- Content Security Policy allows scripts and styles only from the same origin;
- API responses are not cached and all responses receive baseline browser security headers;
- icon file access is constrained to the configured icon directory.

The custom request header reduces drive-by cross-origin form attacks. It is not authentication and does not replace access control at the reverse proxy.

## Scaling Model

| Scale | Current design | Change required beyond it |
| --- | --- | --- |
| One host, tens of services | Supported; local snapshot plus registry cache | Measure status latency and tune cache intervals |
| Several independent hosts | Run one isolated Patchdeck instance per host | Central read-only aggregation can be added separately |
| Multiple workers on one host | Not supported or useful for Compose mutations | Durable broker plus explicit per-host leases |
| Multiple replicas sharing state | Not supported | Database, migrations, distributed locks, secret manager |
| Public or multi-user service | Not supported | Authentication, authorization, audit identity, rate limits |

This boundary is intentional. Adding replicas before replacing the file store and host-local locks would create the appearance of scalability while reducing correctness.

## Quality Gates

The repository uses `uv.lock` as the resolved dependency graph. CI runs on every pull request and push with Python 3.11 and 3.12:

```bash
uv sync --locked --extra dev
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync mypy src/patchdeck
```

Container builds use pinned base-image digests and the lockfile. Published builds also emit SBOM and provenance attestations. GitHub Actions are pinned to commits and Dependabot proposes controlled updates for Python, Docker, and workflow dependencies.

## Extension Rules

When adding a feature:

1. Put transport concerns in `api.py`, validated data in `models.py`, and durable writes in `store.py`.
2. Pass dependencies through `AppRuntime`; do not introduce a second module-global store or engine.
3. Keep configuration endpoints free from status/network work.
4. Add a regression test for every recovered failure mode.
5. Add schema migration logic before changing persisted shapes.
6. Keep update execution serial unless the ownership model changes.

The next useful extraction, once new adapters are added, is to split registry, MQTT, and Compose execution behind small protocols while retaining `UpdateEngine` as the orchestration facade. That refactor should be driven by a second implementation, not by file size alone.
