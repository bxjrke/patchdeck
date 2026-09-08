from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import ensure_self_service as ensure_runtime_self_service
from .api import router as api_router
from .assets import (
    PATCHDECK_APPLE_ICON_URL,
    PATCHDECK_FAVICON_URL,
    PATCHDECK_SVG_FAVICON_URL,
    STATIC_ASSET_VERSION,
)
from .runtime import AppRuntime

UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
WRITE_REQUEST_HEADER = "X-Patchdeck-Request"


def add_security_headers(response: Response, *, no_store: bool = False) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if no_store:
        response.headers["Cache-Control"] = "no-store"
    return response


def create_app(
    runtime_instance: AppRuntime | None = None,
    *,
    start_background_tasks: bool = True,
) -> FastAPI:
    runtime_instance = runtime_instance or AppRuntime.create()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        ensure_runtime_self_service(runtime_instance)
        if start_background_tasks:
            runtime_instance.engine.start_background_tasks()
        try:
            yield
        finally:
            runtime_instance.engine.stop_background_tasks()

    application = FastAPI(title="Patchdeck", version=__version__, lifespan=lifespan)
    application.state.runtime = runtime_instance
    application.include_router(api_router)
    application.mount("/static", StaticFiles(packages=[("patchdeck", "static")]), name="static")

    @application.middleware("http")
    async def security_boundary(request: Request, call_next):
        is_api_request = request.url.path.startswith("/api/")
        if (
            is_api_request
            and request.method in UNSAFE_HTTP_METHODS
            and request.headers.get(WRITE_REQUEST_HEADER) != "1"
        ):
            return add_security_headers(
                JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"{WRITE_REQUEST_HEADER}: 1 is required for "
                            "state-changing API requests."
                        )
                    },
                ),
                no_store=True,
            )
        return add_security_headers(await call_next(request), no_store=is_api_request)

    @application.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return page_response("home")

    @application.get("/settings", response_class=HTMLResponse)
    def settings_page() -> HTMLResponse:
        return page_response("settings")

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return application


def page_response(active: str) -> HTMLResponse:
    response = HTMLResponse(page_html(active))
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return response


runtime = AppRuntime.create()
store = runtime.store
engine = runtime.engine
app = create_app(runtime)


def ensure_self_service() -> None:
    """Backward-compatible helper for callers that use the module runtime."""

    ensure_runtime_self_service(AppRuntime(store=store, engine=engine))


def page_html(active: str) -> str:
    if active not in {"home", "settings"}:
        raise ValueError(f"Unknown page: {active}")
    content = HOME_VIEW if active == "home" else SETTINGS_VIEW
    script_name = "home.js" if active == "home" else "settings.js"
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Patchdeck</title>
  <link rel="icon" type="image/png" sizes="32x32" href="{PATCHDECK_FAVICON_URL}">
  <link rel="icon" type="image/svg+xml" href="{PATCHDECK_SVG_FAVICON_URL}">
  <link rel="apple-touch-icon" sizes="180x180" href="{PATCHDECK_APPLE_ICON_URL}">
  <link rel="stylesheet" href="/static/app.css?{STATIC_ASSET_VERSION}">
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <p class="eyebrow" data-i18n="tagline">Homelab Update Control</p>
        <div class="brand-row">
          <a class="title-link" href="/" aria-label="Patchdeck home" data-i18n-aria-label="patchdeckHome"><h1>Patchdeck</h1></a>
          <a class="settings-link icon-button" href="/settings" aria-label="Settings" title="Settings"><i data-lucide="settings" aria-hidden="true"></i><span data-i18n="settings">Settings</span></a>
        </div>
      </div>
      <div class="summary" aria-label="Service overview actions" data-i18n-aria-label="serviceOverviewActions">
        <span id="summary-services" class="summary-pill">0 services</span>
        <button type="button" id="update-all" class="badge badge-action update summary-action" data-action="run-all-updates" hidden><i data-lucide="list-restart" aria-hidden="true"></i><span></span></button>
        <button type="button" id="refresh-status" class="badge badge-action neutral summary-action" data-action="refresh-all-services" title="Refresh"><i data-lucide="refresh-cw" aria-hidden="true"></i><span data-i18n="refreshUpdates">Refresh</span></button>
      </div>
    </header>

    {content}

    <footer class="footer"><span class="version" aria-label="Patchdeck version">Patchdeck {__version__}</span></footer>
  </main>
  <script defer src="/static/common.js?{STATIC_ASSET_VERSION}"></script>
  <script defer src="/static/{script_name}?{STATIC_ASSET_VERSION}"></script>
</body>
</html>'''


HOME_VIEW = '''
    <section id="home-view">
      <div id="services" class="stack notice">Loading services...</div>
    </section>
'''


SETTINGS_VIEW = '''
    <section id="settings-view">
      <section class="card compact-card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="sliders-horizontal"></i></div>
            <h2 data-i18n="settingsGeneral">General</h2>
          </div>
          <span class="badge ok" data-i18n="global">Global</span>
        </div>
        <div class="grid settings-grid">
          <label><span data-i18n="updateInterval">Update check interval</span><span class="input-suffix"><input id="update-interval" type="number" min="1"><span>min</span></span></label>
          <label><span data-i18n="baseUrl">Base URL</span><input id="base-url" placeholder="https://patchdeck.example"></label>
          <label><span data-i18n="language">Language</span><select id="language"><option value="en">English</option><option value="de">German</option></select></label>
        </div>
        <div id="settings-save-status" class="autosave-status" role="status" aria-live="polite" hidden></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="radio-tower"></i></div>
            <h2>MQTT</h2>
          </div>
          <label class="toggle-row inline-toggle"><span id="mqtt-state-label" data-state-label="mqtt">Inactive</span><input id="mqtt-enabled" type="checkbox" role="switch"></label>
        </div>
        <div id="mqtt-fields" class="grid settings-grid">
          <label><span data-i18n="mqttHost">MQTT Host</span><input id="mqtt-host" placeholder="mosquitto"></label>
          <label><span data-i18n="mqttPort">MQTT Port</span><input id="mqtt-port" type="number" min="1" max="65535"></label>
          <label><span data-i18n="mqttUser">MQTT User</span><input id="mqtt-user"></label>
          <label><span data-i18n="mqttPassword">MQTT password</span><input id="mqtt-password" type="password"></label>
          <label><span data-i18n="mqttPrefix">MQTT Discovery Prefix</span><input id="mqtt-prefix"></label>
          <label><span data-i18n="mqttTopic">MQTT Base Topic</span><input id="mqtt-topic"></label>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="palette"></i></div>
            <h2 data-i18n="display">Display</h2>
          </div>
        </div>
        <div class="grid settings-grid">
          <label><span data-i18n="theme">Color scheme</span><select id="theme"><option value="system" data-i18n="themeSystem">System</option><option value="dark" data-i18n="themeDark">Dark</option><option value="light" data-i18n="themeLight">Light</option></select></label>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="server"></i></div>
            <h2 data-i18n="services">Services</h2>
          </div>
          <span class="badge warn" data-i18n="configuration">Configuration</span>
        </div>
        <div id="service-settings" class="details-stack notice">Loading services...</div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="plus"></i></div>
            <h2 data-i18n="createService">Create service</h2>
          </div>
          <span class="badge warn" data-i18n="manual">Manual</span>
        </div>
        <div class="grid settings-grid">
          <label><span>ID</span><input id="service-id" placeholder="homeassistant"></label>
          <label><span data-i18n="name">Display name</span><input id="service-name" placeholder="Home Assistant"></label>
          <label class="toggle-row"><span data-i18n="manualUpdateAction">Show update action</span><input id="service-update-action" type="checkbox" role="switch"></label>
          <label><span data-i18n="container">Container name</span><input id="service-container" placeholder="homeassistant"></label>
          <label class="wide"><span data-i18n="iconPath">Icon path</span><input id="service-logo-url" placeholder="/data/icons/homeassistant.svg or https://example/icon.svg"></label>
          <label class="wide"><span data-i18n="releaseNotesField">Release notes source</span><input id="service-release-notes" placeholder="homeassistant"><small data-i18n="releaseNotesHelp">Optional. Use homeassistant for the built-in Home Assistant lookup, or enter a URL. URLs may include {version}, which is replaced with the detected version.</small><button type="button" class="secondary release-notes-preview" data-action="preview-release-notes" data-selector="#service-release-notes"><i data-lucide="external-link" aria-hidden="true"></i><span data-i18n="previewReleaseNotes">Preview link</span></button></label>
          <div class="field-help wide"><span data-i18n="iconHelpTitle">Icons</span><strong data-i18n="iconHelp">Patchdeck detects icons from container and image automatically and stores found files locally. Set an icon path when you want to override it.</strong></div>
        </div>
        <div class="actions" data-save-action="create-service"></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true"><i data-lucide="container"></i></div>
            <h2 data-i18n="dockerImport">Docker Import</h2>
          </div>
          <span class="badge ok" data-i18n="readOnly">Read-only</span>
        </div>
        <p data-i18n="dockerImportIntro">The scan is always available manually. Patchdeck only reads containers, images, and Compose labels, and creates a service only after you click Import.</p>
        <div class="actions compact"><button type="button" data-action="scan-docker"><i data-lucide="scan-line" aria-hidden="true"></i><span data-i18n="scanDocker">Scan Docker</span></button></div>
        <div id="docker-candidates" class="notice import-list" data-i18n="dockerScanStart">Start a Docker scan to import containers.</div>
      </section>
    </section>
'''
