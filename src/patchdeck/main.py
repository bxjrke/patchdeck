from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .docker_import import list_container_candidates, service_from_container
from .icon_cache import cache_service_icon
from .models import DockerImportCandidate, ServiceConfig, ServiceStatus, Settings
from .store import JsonStore
from .update_engine import UpdateEngine, service_update_enabled

store = JsonStore()
engine = UpdateEngine(store)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine.start_background_tasks()
    yield


app = FastAPI(title="Patchdeck", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(packages=[("patchdeck", "static")]), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return page_html("home")


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    return page_html("settings")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings() -> Settings:
    return store.get_settings()


@app.put("/api/settings")
def put_settings(settings: Settings) -> Settings:
    return store.update_settings(settings)


@app.get("/api/services")
def list_services() -> list[ServiceConfig]:
    return sort_services(store.list_services())


@app.put("/api/services/{service_id}")
def put_service(service_id: str, service: ServiceConfig) -> ServiceConfig:
    if service.id != service_id:
        raise HTTPException(status_code=400, detail="service id mismatch")
    service = enrich_service_from_docker(service)
    return persist_service(service)


@app.delete("/api/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str) -> Response:
    deleted = store.delete_service(service_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="service not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/status")
def get_status() -> list[ServiceStatus]:
    return engine.statuses()


@app.post("/api/services/{service_id}/update")
def update_service(service_id: str) -> dict[str, bool | str]:
    service = store.get_service(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="service not found")
    if not service_update_enabled(service):
        raise HTTPException(status_code=403, detail="service is not enabled for updates")
    ok, message = engine.perform_update(service, "web")
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


@app.post("/api/services/{service_id}/refresh")
def refresh_service(service_id: str) -> ServiceConfig:
    service = store.get_service(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="service not found")
    if not service.container:
        raise HTTPException(status_code=400, detail="service has no container configured")
    try:
        refreshed = service_from_container(service.container, service)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker refresh unavailable: {exc}") from exc
    return persist_service(refreshed)


@app.get("/api/icons/{filename}")
def get_icon(filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="icon not found")
    path = store.data_dir / "icons" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="icon not found")
    return FileResponse(path)


@app.get("/api/import/docker")
def get_docker_import_candidates() -> list[DockerImportCandidate]:
    configured_ids = {service.id for service in store.list_services()}
    try:
        return list_container_candidates(configured_ids)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker import unavailable: {exc}") from exc


@app.post("/api/import/docker/{candidate_id}")
def import_docker_candidate(candidate_id: str) -> ServiceConfig:
    configured_ids = {service.id for service in store.list_services()}
    for candidate in list_container_candidates(configured_ids):
        if candidate.id == candidate_id:
            return persist_service(candidate.suggested_service)
    raise HTTPException(status_code=404, detail="candidate not found")



def persist_service(service: ServiceConfig) -> ServiceConfig:
    return store.upsert_service(cache_service_icon(service, store.data_dir))


def enrich_service_from_docker(service: ServiceConfig) -> ServiceConfig:
    if not service.container:
        return service
    try:
        detected = service_from_container(service.container, service)
    except Exception:
        return service
    data = service.model_dump()
    detected_data = detected.model_dump()
    for key in ("image", "compose_file", "compose_project_dir", "compose_service"):
        if data.get(key) in (None, "") and detected_data.get(key) not in (None, ""):
            data[key] = detected_data[key]
    if detected.icon_slug and data.get("icon_slug") in (None, "", "docker", "linuxserver"):
        data["icon_slug"] = detected.icon_slug
    data["container"] = detected.container
    return ServiceConfig.model_validate(data)


def sort_services(services: list[ServiceConfig]) -> list[ServiceConfig]:
    statuses = {status.service_id: status for status in engine.statuses()}
    return sorted(services, key=lambda service: not bool(statuses.get(service.id) and statuses[service.id].update_available))


def service_update_available(service: ServiceConfig) -> bool:
    status_item = next((item for item in engine.statuses() if item.service_id == service.id), None)
    return bool(status_item and status_item.update_available)


def page_html(active: str) -> str:
    boot = "loadHome();" if active == "home" else "loadSettingsPage();"
    content = HOME_VIEW if active == "home" else SETTINGS_VIEW
    script = COMMON_JS + (HOME_JS if active == "home" else SETTINGS_JS)
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Patchdeck</title>
  <style>{CSS}</style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Homelab Update Control</p>
        <a class="title-link" href="/" aria-label="Patchdeck home"><h1>Patchdeck</h1></a>
      </div>
      <a class="settings-link icon-button" href="/settings" aria-label="Settings" title="Settings"><i data-lucide="settings" aria-hidden="true"></i></a>
      <div class="summary">
        <span id="summary-services">0 services</span>
        <span id="summary-state">Ready</span>
      </div>
    </header>

    {content}

    <footer><span data-i18n="footer">Preview build. Updates run only when triggered for a configured service.</span> <span>Version {__version__}</span></footer>
  </main>
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
  <script>{script}
  {boot}
  </script>
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
          <label><span data-i18n="language">Language</span><select id="language"><option value="de">Deutsch</option><option value="en">English</option></select></label>
        </div>
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
          <label><span data-i18n="theme">Color scheme</span><select id="theme"><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select></label>
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
          <label class="wide"><span data-i18n="releaseNotesField">Release notes source</span><input id="service-release-notes" placeholder="homeassistant"><small data-i18n="releaseNotesHelp">Optional. Use homeassistant for the built-in Home Assistant lookup, or enter a URL. URLs may include {version}, which is replaced with the detected version.</small></label>
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
          <span class="badge ok">Read-only</span>
        </div>
        <p data-i18n="dockerImportIntro">The scan is always available manually. Patchdeck only reads containers, images, and Compose labels, and creates a service only after you click Import.</p>
        <div class="actions compact"><button type="button" onclick="loadDockerCandidates()"><i data-lucide="scan-line" aria-hidden="true"></i><span data-i18n="scanDocker">Scan Docker</span></button></div>
        <div id="docker-candidates" class="notice import-list" data-i18n="dockerScanStart">Start a Docker scan to import containers.</div>
      </section>
    </section>
'''


CSS = r'''
:root { color-scheme: dark; --bg:#0f172a; --panel:#111c31; --panel2:#15233b; --field:#0b1222aa; --text:#e5edf7; --muted:#9fb0c8; --line:#263750; --purple:#8b5cf6; --blue:#2563eb; --danger:#b42318; --icon-tile:#0b1222aa; --icon-accent:#7dd3fc; }
html[data-theme="light"] { color-scheme: light; --bg:#f6f8fb; --panel:#ffffff; --panel2:#f2f6fb; --field:#ffffff; --text:#132033; --muted:#5d6d82; --line:#d7e0ec; --purple:#6d3fdc; --blue:#155bd5; --danger:#b42318; --icon-tile:#ffffff; --icon-accent:#155bd5; }
html[data-theme="system"] { color-scheme: light dark; }
@media (prefers-color-scheme: light) {
  html[data-theme="system"] { --bg:#f6f8fb; --panel:#ffffff; --panel2:#f2f6fb; --field:#ffffff; --text:#132033; --muted:#5d6d82; --line:#d7e0ec; --purple:#6d3fdc; --blue:#155bd5; --danger:#b42318; --icon-tile:#ffffff; --icon-accent:#155bd5; }
}
* { box-sizing:border-box; }
body { margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }
.shell { max-width:980px; margin:0 auto; padding:34px 16px 48px; }
.topbar { position:relative; margin-bottom:20px; padding-right:64px; }
.eyebrow { margin:0 0 5px; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
.title-link { color:inherit; text-decoration:none; display:inline-block; }
h1 { margin:0; font-size:clamp(34px,5vw,54px); letter-spacing:0; }
h2 { margin:0; font-size:22px; letter-spacing:0; overflow-wrap:anywhere; }
p { margin:6px 0 0; color:var(--muted); }
.settings-link { position:absolute; top:50%; right:0; transform:translateY(-50%); width:46px; height:46px; display:grid; place-items:center; border-radius:50%; color:var(--text); background:var(--field); border:1px solid var(--line); text-decoration:none; box-shadow:0 8px 24px #0002; }
.icon-button svg, button svg, .logo svg { width:20px; height:20px; display:block; flex:0 0 auto; }
.settings-link:hover { filter:brightness(1.12); }
.summary { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.summary span { display:inline-flex; margin:0; padding:7px 10px; border:1px solid var(--line); border-radius:999px; background:var(--field); color:var(--muted); font-weight:800; font-size:12px; }
.stack, .details-stack { display:grid; gap:10px; }
.card { background:linear-gradient(180deg,var(--panel),var(--panel2)); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 12px 34px #0002; margin:10px 0; }
.compact-card { padding:12px 14px; }
.compact-card .grid { margin-top:10px; }
.card-head { display:flex; justify-content:space-between; gap:14px; align-items:center; }
.identity { display:flex; align-items:center; gap:10px; min-width:0; flex:1 1 auto; }
.logo { width:38px; height:38px; flex:0 0 38px; border-radius:8px; object-fit:contain; background:var(--field); border:1px solid var(--line); padding:7px; }
.logo.placeholder { display:grid; place-items:center; color:var(--icon-accent); font-weight:900; font-size:22px; }
.logo.service-icon { display:grid; place-items:center; background:var(--icon-tile); }
.service-icon-image { width:100%; height:100%; object-fit:contain; }
.badge { white-space:nowrap; border-radius:999px; padding:8px 11px; font-weight:800; font-size:12px; border:1px solid var(--line); display:inline-flex; align-items:center; gap:8px; }
.badge.ok { color:#bbf7d0; background:#14532d88; border-color:#166534; }
.badge.warn { color:#fef3c7; background:#78350f88; border-color:#92400e; }
.badge.update { color:#ffedd5; background:#9a341288; border-color:#c2410c; }
.grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:12px; }
.grid div, label { background:var(--field); border:1px solid var(--line); border-radius:8px; padding:10px; min-width:0; }
span { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
strong { display:block; overflow-wrap:anywhere; }
code { display:block; margin-top:8px; padding:10px; border-radius:8px; background:var(--field); border:1px solid var(--line); color:var(--text); overflow-wrap:anywhere; }
.actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:12px; }
.actions.compact { margin-top:14px; }
button { appearance:none; border:0; cursor:pointer; border-radius:8px; min-height:40px; padding:10px 14px; color:#fff; background:linear-gradient(135deg,var(--purple),var(--blue)); font-weight:800; box-shadow:0 8px 24px #2563eb33; display:inline-flex; align-items:center; gap:8px; justify-content:center; text-align:center; line-height:1.1; }
button span { color:#fff; margin:0; font-size:13px; }
button:hover { filter:brightness(1.08); }
button:disabled { cursor:not-allowed; opacity:.65; filter:saturate(.6); }
button.secondary { background:var(--field); border:1px solid var(--line); box-shadow:none; color:var(--text); }
button.secondary span { color:var(--text); }
button.danger { background:linear-gradient(135deg,#b42318,#dc2626); box-shadow:0 8px 30px #dc262644; }
button.save-button { min-width:150px; color:#fff; justify-content:center; }
button.save-button span, button.save-button svg { color:#fff; }
input, select { width:100%; min-height:38px; border:1px solid var(--line); border-radius:8px; padding:9px 10px; background:var(--bg); color:var(--text); font:inherit; }
label { display:grid; gap:5px; color:var(--muted); font-size:13px; }
.settings-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
.card-head + .details-stack { margin-top:12px; }
.input-suffix { display:flex; align-items:center; gap:8px; margin:0; }
.input-suffix input { flex:1 1 auto; min-width:0; }
.input-suffix span { margin:0; color:var(--muted); font-weight:800; }
.wide { grid-column:1 / -1; }
small { color:var(--muted); line-height:1.4; }
.field-help { display:grid; align-content:start; }
.toggle-row { display:flex; align-items:center; justify-content:space-between; gap:14px; }
.inline-toggle { background:var(--field); border:1px solid var(--line); border-radius:999px; padding:8px 10px; flex:0 0 auto; }
.toggle-row span { margin:0; }
input[type="checkbox"][role="switch"] { appearance:none; width:46px; min-height:26px; height:26px; flex:0 0 46px; border-radius:999px; padding:2px; background:#111827; border:1px solid #30445f; cursor:pointer; transition:background .15s ease,border-color .15s ease; }
input[type="checkbox"][role="switch"]::before { content:""; display:block; width:20px; height:20px; border-radius:50%; background:#94a3b8; transition:transform .15s ease,background .15s ease; }
input[type="checkbox"][role="switch"]:checked { background:#2563eb; border-color:#60a5fa; }
input[type="checkbox"][role="switch"]:checked::before { transform:translateX(20px); background:#fff; }
.notice { color:var(--muted); }
.import-list { margin-top:14px; }
.candidate { display:grid; grid-template-columns:minmax(170px,1fr) minmax(220px,1.2fr) minmax(130px,.7fr) auto; gap:10px; align-items:center; border-top:1px solid var(--line); padding:12px 0; }
.candidate:first-child { border-top:0; }
details { margin-top:10px; color:var(--muted); }
details summary { cursor:pointer; font-size:12px; font-weight:800; }
.link { color:#bae6fd; text-decoration:none; font-weight:800; }
.link:hover { text-decoration:underline; }
.last-run { background:var(--field); border:1px solid var(--line); border-radius:8px; padding:12px; margin-top:12px; }
.service-config { background:var(--field); border:1px solid var(--line); border-radius:8px; padding:0; overflow:hidden; }
details.service-config summary { cursor:pointer; list-style:none; padding:14px 16px; display:flex; align-items:center; justify-content:space-between; gap:12px; }
details.service-config summary::-webkit-details-marker { display:none; }
.service-summary { padding:14px 16px; display:flex; align-items:center; justify-content:space-between; gap:12px; }
.service-actions { display:flex; gap:8px; flex:0 0 auto; }
.icon-only { width:38px; height:38px; padding:0; }
.service-settings-toggle[aria-expanded="true"] { background:#1d4ed8; }
.summary-title { display:flex; flex-direction:column; min-width:0; }
.summary-title strong { font-size:16px; }
.details-body { padding:0 12px 12px; }
.technical-details { margin-top:10px; }
.technical-details summary { color:var(--muted); }
.docker-detail-list { display:grid; grid-template-columns:1fr; gap:8px; margin-top:10px; }
.docker-detail-list div { background:var(--field); border:1px solid var(--line); border-radius:8px; padding:10px; }
footer { color:#718096; margin-top:22px; font-size:12px; }
[hidden] { display:none !important; }
@media (max-width:760px) {
  .topbar { padding-right:56px; }
  .card-head { align-items:flex-start; flex-direction:column; }
  .identity { gap:10px; }
  .logo { width:38px; height:38px; flex-basis:38px; }
  h2 { font-size:20px; }
  .grid, .settings-grid { grid-template-columns:1fr; }
  .candidate { grid-template-columns:1fr; }
}
'''


COMMON_JS = r'''
const api = (path, options = {}) => fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
const text = value => String(value ?? '');
const esc = value => text(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let currentLanguage = 'de';
const I18N = {
  de: {
    footer: 'Vorschauversion. Updates werden nur gezielt pro Dienst ausgeführt.', serviceSingular: 'Dienst', servicePlural: 'Dienste',
    settingsGeneral: 'Allgemein', global: 'Global', updateInterval: 'Update-Check-Intervall', baseUrl: 'Basis-URL', language: 'Sprache',
    mqttEnabled: 'MQTT', mqttHost: 'MQTT Host', mqttPort: 'MQTT Port', mqttUser: 'MQTT User', mqttPassword: 'MQTT Passwort', mqttPrefix: 'MQTT Discovery Prefix', mqttTopic: 'MQTT Base Topic',
    display: 'Darstellung', theme: 'Farbschema',
    saveSettings: 'Speichern', services: 'Dienste', configuration: 'Konfiguration', createService: 'Dienst anlegen', manual: 'Manuell', name: 'Anzeigename', manualUpdateAction: 'Update-Aktion anzeigen',
    container: 'Container Name', image: 'Image', composeFile: 'Compose-Datei', composeProject: 'Compose Projektordner', composeService: 'Compose Service', iconSlug: 'Icon-Name', iconPath: 'Icon Pfad', iconHelpTitle: 'Icons', iconHelp: 'Patchdeck erkennt Icons automatisch aus Container und Image und speichert gefundene Dateien lokal. Bei Bedarf kann ein Icon Pfad gesetzt werden.', releaseNotesField: 'Release Notes Quelle',
    releaseNotesHelp: 'Optional. Nutze homeassistant für die eingebaute Home-Assistant-Erkennung oder trage eine URL ein. In URLs kann {version} durch die gefundene Version ersetzt werden.',
    saveService: 'Dienst speichern', dockerImport: 'Docker Import', dockerImportIntro: 'Der Scan ist immer manuell möglich. Patchdeck liest Container, Image und Compose-Labels nur aus und legt erst nach Klick auf Import einen Dienst an.', scanDocker: 'Docker scannen', dockerScanStart: 'Docker Scan starten, um Container zu importieren.',
    loadingServices: 'Lade Dienste...', noServices: 'Noch keine Dienste konfiguriert.', settings: 'Einstellungen', overview: 'Übersicht', releaseNotes: 'Release Notes', installed: 'Installiert', available: 'Verfügbar', notChecked: 'Noch nicht geprüft', updateRunning: 'Update läuft', incomplete: 'Unvollständig', updateAvailable: 'Update verfügbar', upToDate: 'Aktuell', startUpdate: 'Update starten', repullCurrent: 'Aktuelle Version neu ziehen', lastUpdate: 'Letztes Update', success: 'Erfolg', error: 'Fehler', updateStarting: 'Update wird gestartet', updateAllowed: 'Update erlaubt', save: 'Speichern', delete: 'Löschen', add: 'Hinzufügen', edit: 'Einstellungen öffnen', refresh: 'Aus Docker aktualisieren', technicalDetails: 'Erkannte Docker-Details',
    active: 'Aktiv', inactive: 'Inaktiv', dockerScanning: 'Docker wird gescannt...', dockerScanFailed: 'Docker Scan fehlgeschlagen.', dockerCandidates: ' Docker Kandidaten', noContainers: 'Keine Docker Container gefunden.', compose: 'Compose', imported: 'Importiert', import: 'Import'
  },
  en: {
    footer: 'Preview build. Updates run only when triggered for a configured service.', serviceSingular: 'service', servicePlural: 'services',
    settingsGeneral: 'General', global: 'Global', updateInterval: 'Update check interval', baseUrl: 'Base URL', language: 'Language',
    mqttEnabled: 'MQTT', mqttHost: 'MQTT host', mqttPort: 'MQTT port', mqttUser: 'MQTT user', mqttPassword: 'MQTT password', mqttPrefix: 'MQTT discovery prefix', mqttTopic: 'MQTT base topic',
    display: 'Display', theme: 'Color scheme',
    saveSettings: 'Save', services: 'Services', configuration: 'Configuration', createService: 'Create service', manual: 'Manual', name: 'Display name', manualUpdateAction: 'Show update action',
    container: 'Container name', image: 'Image', composeFile: 'Compose file', composeProject: 'Compose project folder', composeService: 'Compose service', iconSlug: 'Icon name', iconPath: 'Icon path', iconHelpTitle: 'Icons', iconHelp: 'Patchdeck detects icons from container and image automatically and stores found files locally. Set an icon path when you want to override it.', releaseNotesField: 'Release notes source',
    releaseNotesHelp: 'Optional. Use homeassistant for the built-in Home Assistant lookup, or enter a URL. URLs may include {version}, which is replaced with the detected version.',
    saveService: 'Save service', dockerImport: 'Docker import', dockerImportIntro: 'The scan is always available manually. Patchdeck only reads containers, images, and Compose labels, and creates a service only after you click Import.', scanDocker: 'Scan Docker', dockerScanStart: 'Start a Docker scan to import containers.',
    loadingServices: 'Loading services...', noServices: 'No services configured yet.', settings: 'Settings', overview: 'Overview', releaseNotes: 'Release notes', installed: 'Installed', available: 'Available', notChecked: 'Not checked yet', updateRunning: 'Update running', incomplete: 'Incomplete', updateAvailable: 'Update available', upToDate: 'Up to date', startUpdate: 'Start update', repullCurrent: 'Pull current version again', lastUpdate: 'Last update', success: 'Success', error: 'Error', updateStarting: 'Starting update', updateAllowed: 'Updates allowed', save: 'Save', delete: 'Delete', add: 'Add', edit: 'Open settings', refresh: 'Refresh from Docker', technicalDetails: 'Detected Docker details',
    active: 'Active', inactive: 'Inactive', dockerScanning: 'Scanning Docker...', dockerScanFailed: 'Docker scan failed.', dockerCandidates: ' Docker candidates', noContainers: 'No Docker containers found.', compose: 'Compose', imported: 'Imported', import: 'Import'
  }
};
function tr(key) {
  return (I18N[currentLanguage] && I18N[currentLanguage][key]) || I18N.de[key] || key;
}

function applyI18n() {
  document.documentElement.lang = currentLanguage;
  document.querySelectorAll('[data-i18n]').forEach(node => node.textContent = tr(node.dataset.i18n));
  document.querySelectorAll('[data-i18n-title]').forEach(node => node.title = tr(node.dataset.i18nTitle));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme || 'system';
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function serviceCountText(count) {
  return count + ' ' + (count === 1 ? tr('serviceSingular') : tr('servicePlural'));
}

async function getServices() {
  const services = await (await api('/api/services')).json();
  document.querySelector('#summary-services').textContent = serviceCountText(services.length);
  return services;
}

async function loadLanguagePreference() {
  try {
    const settings = await (await api('/api/settings')).json();
    currentLanguage = settings.language || 'de';
    applyTheme(settings.theme);
    applyI18n();
  } catch {
    applyI18n();
  }
}

function logoHtml(service) {
  if (service.logo_url) {
    return '<span class="logo service-icon"><img class="service-icon-image" src="' + esc(service.logo_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer"></span>';
  }
  return '<div class="logo placeholder" aria-hidden="true"><i data-lucide="package"></i></div>';
}

function saveButton(onclick, labelKey = 'save') {
  const icon = labelKey === 'add' ? 'plus' : 'save';
  return '<button type="button" class="save-button" onclick="' + onclick + '"><i data-lucide="' + icon + '" aria-hidden="true"></i><span>' + esc(tr(labelKey)) + '</span></button>';
}
'''


HOME_JS = r'''
async function loadHome() {
  await loadLanguagePreference();
  const response = await api('/api/status');
  const statuses = await response.json();
  document.querySelector('#summary-services').textContent = serviceCountText(statuses.length);
  renderServiceCards(statuses);
  refreshIcons();
}

function renderServiceCards(statuses) {
  const target = document.querySelector('#services');
  document.querySelector('#summary-state').textContent = tr('overview');
  if (!statuses.length) {
    target.innerHTML = '<section class="card"><div class="notice">' + esc(tr('noServices')) + '</div></section>';
    return;
  }
  target.innerHTML = statuses.map(service => {
    const incomplete = !service.latest_version;
    const badgeClass = service.update_in_progress ? 'progress' : (incomplete ? 'warn' : (service.update_available ? 'update' : 'ok'));
    const badgeText = service.update_in_progress ? tr('updateRunning') : (incomplete ? tr('incomplete') : (service.update_available ? tr('updateAvailable') : tr('upToDate')));
    const releaseLink = service.release_notes_url ? '<a class="link" href="' + esc(service.release_notes_url) + '" target="_blank" rel="noreferrer">Release Notes</a>' : '';
    const action = service.update_enabled
      ? '<button type="button" onclick="runUpdate(\'' + esc(service.service_id) + '\')" ' + (service.update_in_progress ? 'disabled' : '') + ' data-idle-label="' + esc(tr('startUpdate')) + '">' + (service.update_available ? esc(tr('startUpdate')) : esc(tr('repullCurrent')) ) + '</button>'
      : '';
    const lastRun = service.last_run
      ? '<div class="last-run"><span>' + esc(tr('lastUpdate')) + '</span><strong>' + esc(service.last_run.ok ? tr('success') : tr('error')) + ' · ' + esc(formatTs(service.last_run.ts)) + '</strong></div>'
      : '';
    return '<section class="card" data-service="' + esc(service.id) + '">' +
      '<div class="card-head">' +
        '<div class="identity">' + logoHtml(service) + '<h2>' + esc(service.name) + '</h2></div>' +
        '<span class="badge ' + badgeClass + '">' + badgeText + '</span>' +
      '</div>' +
      '<div class="grid">' +
        '<div><span>' + esc(tr('container')) + '</span><strong>' + esc(service.container) + '</strong></div>' +
        '<div><span>Status</span><strong data-role="container-state">' + esc(service.state) + '</strong></div>' +
        '<div><span>' + esc(tr('installed')) + '</span><strong>' + esc(service.current_version || tr('notChecked')) + '</strong></div>' +
        '<div><span>' + esc(tr('available')) + '</span><strong>' + esc(service.latest_version || tr('notChecked')) + '</strong></div>' +
      '</div>' +
      '<details><summary>Image</summary><code>' + esc(service.image || '—') + '</code></details>' +
      '<div class="actions">' + action + releaseLink + '</div>' +
      lastRun +
    '</section>';
  }).join('');
}

function formatTs(value) {
  if (!value) return '—';
  return new Date(Number(value) * 1000).toLocaleString('de-DE', {dateStyle: 'short', timeStyle: 'short'});
}

async function runUpdate(id) {
  const card = document.querySelector('.card[data-service="' + CSS.escape(id) + '"]');
  const button = card?.querySelector('button');
  const state = card?.querySelector('[data-role="container-state"]');
  if (button) button.disabled = true;
  if (state) state.textContent = tr('updateStarting');
  try {
    await api('/api/services/' + encodeURIComponent(id) + '/update', {method: 'POST', body: '{}'});
  } finally {
    await loadHome();
  }
}
'''


SETTINGS_JS = r'''
let settingsLoaded = false;
let settingsSaveTimer = null;

async function loadSettingsPage() {
  await loadSettings();
  await loadServiceSettings();
  renderSaveButtons();
  wireAutosaveSettings();
  settingsLoaded = true;
  refreshIcons();
}

async function loadSettings() {
  const data = await (await api('/api/settings')).json();
  currentLanguage = data.language || 'de';
  applyTheme(data.theme);
  applyI18n();
  await getServices();
  document.querySelector('#summary-state').textContent = tr('settings');
  document.querySelector('#update-interval').value = data.update_interval_minutes;
  document.querySelector('#language').value = currentLanguage;
  document.querySelector('#mqtt-enabled').checked = Boolean(data.mqtt_enabled);
  document.querySelector('#mqtt-host').value = data.mqtt_host || '';
  document.querySelector('#mqtt-port').value = data.mqtt_port || 1883;
  document.querySelector('#mqtt-user').value = data.mqtt_user || '';
  document.querySelector('#mqtt-password').value = data.mqtt_password || '';
  document.querySelector('#mqtt-prefix').value = data.mqtt_discovery_prefix;
  document.querySelector('#mqtt-topic').value = data.mqtt_base_topic;
  document.querySelector('#base-url').value = data.base_url || '';
  document.querySelector('#theme').value = data.theme;
  updateMqttVisibility();
  refreshIcons();
}

function renderSaveButtons() {
  document.querySelector('[data-save-action="create-service"]').innerHTML = saveButton('createService()', 'add');
}

function wireAutosaveSettings() {
  document.querySelector('#language').addEventListener('change', event => {
    currentLanguage = event.target.value;
    applyI18n();
    updateMqttVisibility();
    renderSaveButtons();
    loadServiceSettings();
    saveSettingsSoon(0);
  });
  document.querySelector('#theme').addEventListener('change', event => {
    applyTheme(event.target.value);
    saveSettingsSoon(0);
  });
  document.querySelector('#mqtt-enabled').addEventListener('change', () => {
    updateMqttVisibility();
    saveSettingsSoon(0);
  });
  document.querySelectorAll('#update-interval, #base-url, #mqtt-host, #mqtt-port, #mqtt-user, #mqtt-password, #mqtt-prefix, #mqtt-topic').forEach(node => {
    node.addEventListener('input', () => saveSettingsSoon());
    node.addEventListener('change', () => saveSettingsSoon(0));
  });
}

function updateMqttVisibility() {
  const enabled = document.querySelector('#mqtt-enabled').checked;
  document.querySelector('#mqtt-fields').hidden = !enabled;
  document.querySelector('#mqtt-state-label').textContent = enabled ? tr('active') : tr('inactive');
}

function saveSettingsSoon(delay = 500) {
  if (!settingsLoaded) return;
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveSettings, delay);
}

function readSettingsPayload() {
  return {
    update_interval_minutes: Number(document.querySelector('#update-interval').value),
    language: document.querySelector('#language').value,
    mqtt_enabled: document.querySelector('#mqtt-enabled').checked,
    mqtt_host: document.querySelector('#mqtt-host').value.trim(),
    mqtt_port: Number(document.querySelector('#mqtt-port').value || 1883),
    mqtt_user: document.querySelector('#mqtt-user').value.trim(),
    mqtt_password: document.querySelector('#mqtt-password').value,
    mqtt_discovery_prefix: document.querySelector('#mqtt-prefix').value,
    mqtt_base_topic: document.querySelector('#mqtt-topic').value,
    base_url: document.querySelector('#base-url').value.trim(),
    theme: document.querySelector('#theme').value
  };
}

async function saveSettings() {
  await api('/api/settings', {method: 'PUT', body: JSON.stringify(readSettingsPayload())});
}

async function loadServiceSettings() {
  const services = await getServices();
  const target = document.querySelector('#service-settings');
  if (!services.length) {
    target.textContent = tr('noServices');
    return;
  }
  target.innerHTML = services.map(service => serviceDetails(service)).join('');
  wireServiceAutosave();
  refreshIcons();
}

function serviceDetails(service) {
  return '<section class="service-config" data-service-config="' + esc(service.id) + '" data-icon-slug="' + esc(service.icon_slug || '') + '" data-image="' + esc(service.image || '') + '" data-compose-file="' + esc(service.compose_file || '') + '" data-compose-project-dir="' + esc(service.compose_project_dir || '') + '" data-compose-service="' + esc(service.compose_service || '') + '">' +
    '<div class="service-summary">' +
      '<div class="identity">' + logoHtml(service) + '<span class="summary-title"><strong>' + esc(service.name) + '</strong><span>' + esc(service.id) + '</span></span></div>' +
      '<div class="service-actions">' +
        '<button type="button" class="secondary icon-only service-settings-toggle" data-i18n-title="edit" title="' + esc(tr('edit')) + '" aria-expanded="false" onclick="toggleServiceSettings(\'' + esc(service.id) + '\')"><i data-lucide="settings" aria-hidden="true"></i></button>' +
        '<button type="button" class="danger icon-only" data-i18n-title="delete" title="' + esc(tr('delete')) + '" onclick="deleteService(\'' + esc(service.id) + '\')"><i data-lucide="trash-2" aria-hidden="true"></i></button>' +
      '</div>' +
    '</div>' +
    '<div class="details-body" hidden>' +
      '<div class="grid settings-grid">' +
        '<label><span>' + esc(tr('name')) + '</span><input id="edit-name-' + esc(service.id) + '" value="' + esc(service.name) + '"></label>' +
        '<label class="toggle-row"><span>' + esc(tr('updateAllowed')) + '</span><input id="edit-update-action-' + esc(service.id) + '" type="checkbox" role="switch" ' + checked(Boolean(service.update_enabled)) + '></label>' +
        '<label><span>' + esc(tr('container')) + '</span><input id="edit-container-' + esc(service.id) + '" value="' + esc(service.container || '') + '"></label>' +
        '<label class="wide"><span>' + esc(tr('iconPath')) + '</span><input id="edit-logo-url-' + esc(service.id) + '" value="' + esc(service.logo_url || '') + '"></label>' +
        '<label class="wide"><span>' + esc(tr('releaseNotesField')) + '</span><input id="edit-release-notes-' + esc(service.id) + '" value="' + esc(service.release_notes || '') + '"><small>' + esc(tr('releaseNotesHelp')) + '</small></label>' +
      '</div>' +
      '<details class="technical-details"><summary>' + esc(tr('technicalDetails')) + '</summary>' +
        '<div class="docker-detail-list">' +
          dockerDetail(tr('iconSlug'), service.icon_slug || '-') +
          dockerDetail(tr('image'), service.image || '-') +
          dockerDetail(tr('composeFile'), service.compose_file || '-') +
          dockerDetail(tr('composeProject'), service.compose_project_dir || '-') +
          dockerDetail(tr('composeService'), service.compose_service || '-') +
        '</div>' +
      '</details>' +
      '<div class="actions">' +
        '<button type="button" class="secondary" onclick="refreshService(\'' + esc(service.id) + '\')"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>' + esc(tr('refresh')) + '</span></button>' +
      '</div>' +
    '</div>' +
  '</section>';
}

function checked(value) {
  return value ? 'checked' : '';
}

function dockerDetail(label, value) {
  return '<div><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
}

function toggleServiceSettings(id) {
  const section = document.querySelector('.service-config[data-service-config="' + CSS.escape(id) + '"]');
  const body = section?.querySelector('.details-body');
  const button = section?.querySelector('.service-settings-toggle');
  if (!body || !button) return;
  const expanded = body.hasAttribute('hidden');
  body.toggleAttribute('hidden', !expanded);
  button.setAttribute('aria-expanded', String(expanded));
}

function readServicePayload(id, prefix, existingId) {
  const section = existingId ? document.querySelector('.service-config[data-service-config="' + CSS.escape(existingId) + '"]') : null;
  return {
    id: existingId || document.querySelector('#service-id').value.trim(),
    name: document.querySelector(prefix + 'name-' + id).value.trim(),
    adapter: 'docker',
    enabled: true,
    update_policy: document.querySelector(prefix + 'update-action-' + id).checked ? 'manual' : 'disabled',
    update_enabled: document.querySelector(prefix + 'update-action-' + id).checked,
    container: document.querySelector(prefix + 'container-' + id).value.trim(),
    icon_slug: section?.dataset.iconSlug || '',
    image: section?.dataset.image || '',
    compose_file: section?.dataset.composeFile || '',
    compose_project_dir: section?.dataset.composeProjectDir || '',
    compose_service: section?.dataset.composeService || '',
    logo_url: document.querySelector(prefix + 'logo-url-' + id)?.value.trim() || '',
    release_notes: document.querySelector(prefix + 'release-notes-' + id)?.value.trim() || '',
    metadata: {}
  };
}

const serviceSaveTimers = {};

function wireServiceAutosave() {
  document.querySelectorAll('.service-config').forEach(section => {
    const id = section.dataset.serviceConfig;
    section.querySelectorAll('input').forEach(node => {
      node.addEventListener('input', () => saveExistingServiceSoon(id));
      node.addEventListener('change', () => saveExistingServiceSoon(id, 0));
    });
  });
}

function saveExistingServiceSoon(id, delay = 500) {
  clearTimeout(serviceSaveTimers[id]);
  serviceSaveTimers[id] = setTimeout(() => saveExistingService(id), delay);
}

async function saveExistingService(id) {
  const payload = readServicePayload(id, '#edit-', id);
  const response = await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
  if (response.ok) {
    const service = await response.json();
    const section = document.querySelector('.service-config[data-service-config="' + CSS.escape(id) + '"]');
    if (section) {
      section.dataset.iconSlug = service.icon_slug || '';
      section.dataset.image = service.image || '';
      section.dataset.composeFile = service.compose_file || '';
      section.dataset.composeProjectDir = service.compose_project_dir || '';
      section.dataset.composeService = service.compose_service || '';
    }
  }
}

async function createService() {
  const id = document.querySelector('#service-id').value.trim();
  const payload = {
    id,
    name: document.querySelector('#service-name').value.trim(),
    adapter: 'docker',
    enabled: true,
    update_policy: document.querySelector('#service-update-action').checked ? 'manual' : 'disabled',
    update_enabled: document.querySelector('#service-update-action').checked,
    container: document.querySelector('#service-container').value.trim(),
    release_notes: document.querySelector('#service-release-notes').value.trim(),
    logo_url: document.querySelector('#service-logo-url').value.trim(),
    metadata: {}
  };
  await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
  await loadServiceSettings();
}

async function refreshService(id) {
  await api('/api/services/' + encodeURIComponent(id) + '/refresh', {method: 'POST', body: '{}'});
  await loadServiceSettings();
}

async function deleteService(id) {
  await api('/api/services/' + encodeURIComponent(id), {method: 'DELETE'});
  await loadServiceSettings();
}

async function loadDockerCandidates() {
  const target = document.querySelector('#docker-candidates');
  target.textContent = tr('dockerScanning');
  const response = await api('/api/import/docker');
  if (!response.ok) {
    target.textContent = (await response.json()).detail || tr('dockerScanFailed');
    return;
  }
  const candidates = await response.json();
  document.querySelector('#summary-state').textContent = candidates.length + tr('dockerCandidates');
  if (!candidates.length) {
    target.textContent = tr('noContainers');
    return;
  }
  target.innerHTML = candidates.map(candidate =>
    '<div class="candidate">' +
      '<div><span>' + esc(tr('container')) + '</span><strong>' + esc(candidate.name) + '</strong><code>' + esc(candidate.id) + '</code></div>' +
      '<div><span>Image</span><strong>' + esc(candidate.image) + '</strong></div>' +
      '<div><span>' + esc(tr('compose')) + '</span><strong>' + esc(candidate.compose_project || '-') + '</strong><code>' + esc(candidate.compose_service || '-') + '</code></div>' +
      '<button type="button" ' + (candidate.already_configured ? 'disabled' : '') + ' onclick="importCandidate(\'' + esc(candidate.id) + '\')"><i data-lucide="' + (candidate.already_configured ? 'check' : 'download') + '" aria-hidden="true"></i><span>' + (candidate.already_configured ? esc(tr('imported')) : esc(tr('import'))) + '</span></button>' +
    '</div>'
  ).join('');
  refreshIcons();
}

async function importCandidate(id) {
  await api('/api/import/docker/' + encodeURIComponent(id), {method: 'POST'});
  await Promise.all([loadServiceSettings(), loadDockerCandidates()]);
}
'''
