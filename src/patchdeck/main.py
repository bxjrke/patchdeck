from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .docker_import import list_container_candidates
from .models import DockerImportCandidate, ServiceConfig, ServiceStatus, Settings
from .store import JsonStore

app = FastAPI(title="Patchdeck", version="0.1.0")
app.mount("/static", StaticFiles(packages=[("patchdeck", "static")]), name="static")
store = JsonStore()


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
    return store.list_services()


@app.put("/api/services/{service_id}")
def put_service(service_id: str, service: ServiceConfig) -> ServiceConfig:
    if service.id != service_id:
        raise HTTPException(status_code=400, detail="service id mismatch")
    return store.upsert_service(service)


@app.delete("/api/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str) -> Response:
    deleted = store.delete_service(service_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="service not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/status")
def get_status() -> list[ServiceStatus]:
    return [
        ServiceStatus(
            service_id=service.id,
            state="configured" if service.enabled else "disabled",
        )
        for service in store.list_services()
    ]


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
            return store.upsert_service(candidate.suggested_service)
    raise HTTPException(status_code=404, detail="candidate not found")


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
        <a class="title-link" href="/" aria-label="Patchdeck Hauptseite"><h1>Patchdeck</h1></a>
      </div>
      <a class="settings-link" href="/settings" aria-label="Einstellungen" title="Einstellungen"><img src="/static/settings.svg" alt=""></a>
      <div class="summary">
        <span id="summary-services">0 Dienste</span>
        <span id="summary-state">Bereit</span>
      </div>
    </header>

    {content}

    <footer>Testversion. Keine Auto-Updates. Update-Ausführung wird später gezielt pro geeignetem Dienst geplant.</footer>
  </main>
  <script>{script}
  {boot}
  </script>
</body>
</html>'''


HOME_VIEW = '''
    <section id="home-view">
      <div id="services" class="stack notice">Lade Dienste...</div>
    </section>
'''


SETTINGS_VIEW = '''
    <section id="settings-view">
      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">S</div>
            <h2>Einstellungen</h2>
          </div>
          <span class="badge ok">Global</span>
        </div>
        <div class="grid settings-grid">
          <label><span>Update-Check-Intervall Minuten</span><input id="update-interval" type="number" min="1"></label>
          <label><span>MQTT aktiv</span><select id="mqtt-enabled"><option value="false">false</option><option value="true">true</option></select></label>
          <label><span>MQTT Discovery Prefix</span><input id="mqtt-prefix"></label>
          <label><span>MQTT Base Topic</span><input id="mqtt-topic"></label>
          <label><span>Docker Auto Import</span><select id="docker-import"><option value="true">true</option><option value="false">false</option></select></label>
          <label><span>Farbschema</span><select id="theme"><option>system</option><option>dark</option><option>light</option></select></label>
        </div>
        <div class="actions"><button type="button" onclick="saveSettings()">Einstellungen speichern</button></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">D</div>
            <h2>Dienste</h2>
          </div>
          <span class="badge warn">Konfiguration</span>
        </div>
        <div id="service-settings" class="details-stack notice">Lade Dienste...</div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">+</div>
            <h2>Dienst anlegen</h2>
          </div>
          <span class="badge warn">Manuell</span>
        </div>
        <div class="grid settings-grid">
          <label><span>ID</span><input id="service-id" placeholder="homeassistant"></label>
          <label><span>Name</span><input id="service-name" placeholder="Home Assistant"></label>
          <label><span>Aktiv</span><select id="service-enabled"><option value="true">true</option><option value="false">false</option></select></label>
          <label><span>Manuelle Update-Aktion anzeigen</span><select id="service-update-action"><option value="false">false</option><option value="true">true</option></select></label>
          <label><span>Container</span><input id="service-container" placeholder="homeassistant"></label>
          <label><span>Image</span><input id="service-image" placeholder="ghcr.io/example/app:latest"></label>
        </div>
        <div class="actions"><button type="button" onclick="createService()">Dienst speichern</button></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">~</div>
            <h2>Docker Import</h2>
          </div>
          <span class="badge ok">Read-only</span>
        </div>
        <div class="actions compact"><button type="button" onclick="loadDockerCandidates()">Docker scannen</button></div>
        <div id="docker-candidates" class="notice import-list">Docker Scan starten, um Container zu importieren.</div>
      </section>
    </section>
'''


CSS = r'''
:root { color-scheme: dark; --bg:#0f172a; --panel:#111c31; --panel2:#15233b; --text:#e5edf7; --muted:#9fb0c8; --line:#263750; --purple:#8b5cf6; --blue:#2563eb; --danger:#b42318; }
* { box-sizing:border-box; }
body { margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:radial-gradient(circle at top left,#1e3a8a55,transparent 34rem),var(--bg); color:var(--text); }
.shell { max-width:980px; margin:0 auto; padding:34px 16px 48px; }
.topbar { position:relative; margin-bottom:20px; padding-right:64px; }
.eyebrow { margin:0 0 5px; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
.title-link { color:inherit; text-decoration:none; display:inline-block; }
h1 { margin:0; font-size:clamp(34px,5vw,54px); letter-spacing:0; }
h2 { margin:0; font-size:22px; letter-spacing:0; overflow-wrap:anywhere; }
p { margin:6px 0 0; color:var(--muted); }
.settings-link { position:absolute; top:50%; right:0; transform:translateY(-50%); width:46px; height:46px; display:grid; place-items:center; border-radius:50%; color:#dbeafe; background:#0b1222aa; border:1px solid var(--line); text-decoration:none; box-shadow:0 8px 30px #0004; }
.settings-link img { width:22px; height:22px; display:block; }
.settings-link:hover { filter:brightness(1.12); }
.summary { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.summary span { display:inline-flex; margin:0; padding:7px 10px; border:1px solid var(--line); border-radius:999px; background:#0b1222aa; color:var(--muted); font-weight:800; font-size:12px; }
.stack, .details-stack { display:grid; gap:14px; }
.card { background:linear-gradient(180deg,var(--panel),var(--panel2)); border:1px solid var(--line); border-radius:22px; padding:22px; box-shadow:0 18px 60px #0005; margin:14px 0; }
.card-head { display:flex; justify-content:space-between; gap:18px; align-items:center; }
.identity { display:flex; align-items:center; gap:14px; min-width:0; flex:1 1 auto; }
.logo { width:42px; height:42px; flex:0 0 42px; border-radius:12px; object-fit:contain; background:#0b1222aa; border:1px solid #24344d; padding:7px; }
.logo.placeholder { display:grid; place-items:center; color:#bae6fd; font-weight:900; font-size:22px; }
.badge { white-space:nowrap; border-radius:999px; padding:8px 11px; font-weight:800; font-size:12px; border:1px solid var(--line); display:inline-flex; align-items:center; gap:8px; }
.badge.ok { color:#bbf7d0; background:#14532d88; border-color:#166534; }
.badge.warn { color:#fef3c7; background:#78350f88; border-color:#92400e; }
.badge.update { color:#ffedd5; background:#9a341288; border-color:#c2410c; }
.grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:18px; }
.grid div, label { background:#0b1222aa; border:1px solid #24344d; border-radius:14px; padding:12px; min-width:0; }
span { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
strong { display:block; overflow-wrap:anywhere; }
code { display:block; margin-top:8px; padding:10px; border-radius:12px; background:#0b1222aa; border:1px solid #24344d; color:#cbd5e1; overflow-wrap:anywhere; }
.actions { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-top:18px; }
.actions.compact { margin-top:14px; }
button { appearance:none; border:0; cursor:pointer; border-radius:12px; padding:11px 14px; color:white; background:linear-gradient(135deg,var(--purple),var(--blue)); font-weight:800; box-shadow:0 8px 30px #2563eb44; }
button:hover { filter:brightness(1.08); }
button:disabled { cursor:not-allowed; opacity:.65; filter:saturate(.6); }
button.secondary { background:#0b1222aa; border:1px solid var(--line); box-shadow:none; color:#dbeafe; }
button.danger { background:linear-gradient(135deg,#b42318,#dc2626); box-shadow:0 8px 30px #dc262644; }
input, select { width:100%; min-height:38px; border:1px solid #30445f; border-radius:10px; padding:9px 10px; background:#090f1dcc; color:var(--text); font:inherit; }
label { display:grid; gap:5px; color:var(--muted); font-size:13px; }
.settings-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
.notice { color:var(--muted); }
.import-list { margin-top:14px; }
.candidate { display:grid; grid-template-columns:minmax(170px,1fr) minmax(220px,1.2fr) minmax(130px,.7fr) auto; gap:10px; align-items:center; border-top:1px solid var(--line); padding:12px 0; }
.candidate:first-child { border-top:0; }
details { margin-top:10px; color:var(--muted); }
details summary { cursor:pointer; font-size:12px; font-weight:800; }
.link { color:#bae6fd; text-decoration:none; font-weight:800; }
.link:hover { text-decoration:underline; }
.last-run { background:#0b1222aa; border:1px solid #24344d; border-radius:14px; padding:12px; margin-top:12px; }
details.service-config { background:#0b1222aa; border:1px solid #24344d; border-radius:16px; padding:0; overflow:hidden; }
details.service-config summary { cursor:pointer; list-style:none; padding:14px 16px; display:flex; align-items:center; justify-content:space-between; gap:12px; }
details.service-config summary::-webkit-details-marker { display:none; }
.summary-title { display:flex; flex-direction:column; min-width:0; }
.summary-title strong { font-size:16px; }
.details-body { padding:0 16px 16px; }
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

async function getServices() {
  const services = await (await api('/api/services')).json();
  document.querySelector('#summary-services').textContent = services.length + (services.length === 1 ? ' Dienst' : ' Dienste');
  return services;
}
'''


HOME_JS = r'''
async function loadHome() {
  const services = await getServices();
  renderServiceCards(services);
}

function serviceInfo(service) {
  const metadata = service.metadata || {};
  const current = metadata.current_version || metadata.installed_version || 'Noch nicht geprüft';
  const latest = metadata.latest_version || 'Noch nicht geprüft';
  const updateAvailable = Boolean(metadata.update_available) && current !== latest;
  return {
    container: metadata.container || service.id,
    image: metadata.image || '—',
    state: service.enabled ? (metadata.state || 'Konfiguriert') : 'Deaktiviert',
    current,
    latest,
    updateAvailable,
    releaseNotesUrl: metadata.release_notes_url || '',
    updateActionEnabled: Boolean(metadata.update_action_enabled),
    lastRun: metadata.last_run || null
  };
}

function renderServiceCards(services) {
  const target = document.querySelector('#services');
  document.querySelector('#summary-state').textContent = 'Übersicht';
  if (!services.length) {
    target.innerHTML = '<section class="card"><div class="notice">Noch keine Dienste konfiguriert.</div></section>';
    return;
  }
  target.innerHTML = services.map(service => {
    const info = serviceInfo(service);
    const incomplete = !info.latest || info.latest === 'Noch nicht geprüft';
    const badgeClass = !service.enabled || incomplete ? 'warn' : (info.updateAvailable ? 'update' : 'ok');
    const badgeText = !service.enabled ? 'Deaktiviert' : (incomplete ? 'Unvollständig' : (info.updateAvailable ? 'Update verfügbar' : 'Aktuell'));
    const releaseLink = info.releaseNotesUrl ? '<a class="link" href="' + esc(info.releaseNotesUrl) + '" target="_blank" rel="noreferrer">Release Notes</a>' : '';
    const action = info.updateActionEnabled
      ? '<button type="button" disabled data-idle-label="Update starten">Update noch nicht implementiert</button>'
      : '<a class="link" href="/settings">Konfigurieren</a>';
    const lastRun = info.lastRun
      ? '<div class="last-run"><span>Letztes Update</span><strong>' + esc(info.lastRun) + '</strong></div>'
      : '';
    return '<section class="card" data-service="' + esc(service.id) + '">' +
      '<div class="card-head">' +
        '<div class="identity"><div class="logo placeholder" aria-hidden="true">~</div><h2>' + esc(service.name) + '</h2></div>' +
        '<span class="badge ' + badgeClass + '">' + badgeText + '</span>' +
      '</div>' +
      '<div class="grid">' +
        '<div><span>Container</span><strong>' + esc(info.container) + '</strong></div>' +
        '<div><span>Status</span><strong data-role="container-state">' + esc(info.state) + '</strong></div>' +
        '<div><span>Installiert</span><strong>' + esc(info.current) + '</strong></div>' +
        '<div><span>Verfügbar</span><strong>' + esc(info.latest) + '</strong></div>' +
      '</div>' +
      '<details><summary>Image</summary><code>' + esc(info.image) + '</code></details>' +
      '<div class="actions">' + action + releaseLink + '</div>' +
      lastRun +
    '</section>';
  }).join('');
}
'''


SETTINGS_JS = r'''
async function loadSettingsPage() {
  await Promise.all([loadSettings(), loadServiceSettings()]);
}

async function loadSettings() {
  await getServices();
  const data = await (await api('/api/settings')).json();
  document.querySelector('#summary-state').textContent = 'Einstellungen';
  document.querySelector('#update-interval').value = data.update_interval_minutes;
  document.querySelector('#mqtt-enabled').value = String(data.mqtt_enabled);
  document.querySelector('#mqtt-prefix').value = data.mqtt_discovery_prefix;
  document.querySelector('#mqtt-topic').value = data.mqtt_base_topic;
  document.querySelector('#docker-import').value = String(data.docker_auto_import_enabled);
  document.querySelector('#theme').value = data.theme;
}

async function saveSettings() {
  const payload = {
    update_interval_minutes: Number(document.querySelector('#update-interval').value),
    mqtt_enabled: document.querySelector('#mqtt-enabled').value === 'true',
    mqtt_discovery_prefix: document.querySelector('#mqtt-prefix').value,
    mqtt_base_topic: document.querySelector('#mqtt-topic').value,
    docker_auto_import_enabled: document.querySelector('#docker-import').value === 'true',
    theme: document.querySelector('#theme').value
  };
  await api('/api/settings', {method: 'PUT', body: JSON.stringify(payload)});
  await loadSettings();
}

async function loadServiceSettings() {
  const services = await getServices();
  const target = document.querySelector('#service-settings');
  if (!services.length) {
    target.textContent = 'Noch keine Dienste konfiguriert.';
    return;
  }
  target.innerHTML = services.map(service => serviceDetails(service)).join('');
}

function serviceDetails(service) {
  const metadata = service.metadata || {};
  return '<details class="service-config">' +
    '<summary><span class="summary-title"><strong>' + esc(service.name) + '</strong><span>' + esc(service.id) + '</span></span><span class="badge ' + (service.enabled ? 'ok' : 'warn') + '">' + (service.enabled ? 'Aktiv' : 'Aus') + '</span></summary>' +
    '<div class="details-body">' +
      '<div class="grid settings-grid">' +
        '<label><span>Name</span><input id="edit-name-' + esc(service.id) + '" value="' + esc(service.name) + '"></label>' +
        '<label><span>Aktiv</span><select id="edit-enabled-' + esc(service.id) + '"><option value="true"' + selected(service.enabled, true) + '>true</option><option value="false"' + selected(service.enabled, false) + '>false</option></select></label>' +
        '<label><span>Manuelle Update-Aktion anzeigen</span><select id="edit-update-action-' + esc(service.id) + '"><option value="false"' + selected(Boolean(metadata.update_action_enabled), false) + '>false</option><option value="true"' + selected(Boolean(metadata.update_action_enabled), true) + '>true</option></select></label>' +
        '<label><span>Container</span><input id="edit-container-' + esc(service.id) + '" value="' + esc(metadata.container || '') + '"></label>' +
        '<label><span>Image</span><input id="edit-image-' + esc(service.id) + '" value="' + esc(metadata.image || '') + '"></label>' +
        '<label><span>Compose Projekt</span><input id="edit-compose-project-' + esc(service.id) + '" value="' + esc(metadata.compose_project || '') + '"></label>' +
        '<label><span>Compose Service</span><input id="edit-compose-service-' + esc(service.id) + '" value="' + esc(metadata.compose_service || '') + '"></label>' +
      '</div>' +
      '<div class="actions">' +
        '<button type="button" onclick="saveExistingService(\'' + esc(service.id) + '\')">Speichern</button>' +
        '<button type="button" class="danger" onclick="deleteService(\'' + esc(service.id) + '\')">Löschen</button>' +
      '</div>' +
    '</div>' +
  '</details>';
}

function selected(actual, expected) {
  return actual === expected ? ' selected' : '';
}

function readServicePayload(id, prefix, existingId) {
  return {
    id: existingId || document.querySelector('#service-id').value.trim(),
    name: document.querySelector(prefix + 'name-' + id).value.trim(),
    adapter: 'docker',
    enabled: document.querySelector(prefix + 'enabled-' + id).value === 'true',
    update_policy: document.querySelector(prefix + 'update-action-' + id).value === 'true' ? 'manual' : 'disabled',
    metadata: {
      container: document.querySelector(prefix + 'container-' + id).value.trim(),
      image: document.querySelector(prefix + 'image-' + id).value.trim(),
      compose_project: document.querySelector(prefix + 'compose-project-' + id)?.value.trim() || '',
      compose_service: document.querySelector(prefix + 'compose-service-' + id)?.value.trim() || '',
      update_action_enabled: document.querySelector(prefix + 'update-action-' + id).value === 'true'
    }
  };
}

async function saveExistingService(id) {
  const payload = readServicePayload(id, '#edit-', id);
  await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
  await loadServiceSettings();
}

async function createService() {
  const id = document.querySelector('#service-id').value.trim();
  const payload = {
    id,
    name: document.querySelector('#service-name').value.trim(),
    adapter: 'docker',
    enabled: document.querySelector('#service-enabled').value === 'true',
    update_policy: document.querySelector('#service-update-action').value === 'true' ? 'manual' : 'disabled',
    metadata: {
      container: document.querySelector('#service-container').value.trim(),
      image: document.querySelector('#service-image').value.trim(),
      update_action_enabled: document.querySelector('#service-update-action').value === 'true'
    }
  };
  await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
  await loadServiceSettings();
}

async function deleteService(id) {
  await api('/api/services/' + encodeURIComponent(id), {method: 'DELETE'});
  await loadServiceSettings();
}

async function loadDockerCandidates() {
  const target = document.querySelector('#docker-candidates');
  target.textContent = 'Docker wird gescannt...';
  const response = await api('/api/import/docker');
  if (!response.ok) {
    target.textContent = (await response.json()).detail || 'Docker Scan fehlgeschlagen.';
    return;
  }
  const candidates = await response.json();
  document.querySelector('#summary-state').textContent = candidates.length + ' Docker Kandidaten';
  if (!candidates.length) {
    target.textContent = 'Keine Docker Container gefunden.';
    return;
  }
  target.innerHTML = candidates.map(candidate =>
    '<div class="candidate">' +
      '<div><span>Container</span><strong>' + esc(candidate.name) + '</strong><code>' + esc(candidate.id) + '</code></div>' +
      '<div><span>Image</span><strong>' + esc(candidate.image) + '</strong></div>' +
      '<div><span>Compose</span><strong>' + esc(candidate.compose_project || '-') + '</strong><code>' + esc(candidate.compose_service || '-') + '</code></div>' +
      '<button type="button" ' + (candidate.already_configured ? 'disabled' : '') + ' onclick="importCandidate(\'' + esc(candidate.id) + '\')">' + (candidate.already_configured ? 'Importiert' : 'Import') + '</button>' +
    '</div>'
  ).join('');
}

async function importCandidate(id) {
  await api('/api/import/docker/' + encodeURIComponent(id), {method: 'POST'});
  await Promise.all([loadServiceSettings(), loadDockerCandidates()]);
}
'''
