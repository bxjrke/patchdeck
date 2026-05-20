from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse

from .docker_import import list_container_candidates
from .models import DockerImportCandidate, ServiceConfig, ServiceStatus, Settings
from .store import JsonStore

app = FastAPI(title="Patchdeck", version="0.1.0")
store = JsonStore()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return page_html("services")


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
    services_active = "active" if active == "services" else ""
    settings_active = "active" if active == "settings" else ""
    services_view = "" if active == "services" else "hidden"
    settings_view = "" if active == "settings" else "hidden"
    script_boot = "loadServicesView();" if active == "services" else "loadSettingsView();"
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
    <header>
      <div>
        <p class="eyebrow">Homelab Update Control</p>
        <h1>Patchdeck</h1>
      </div>
      <nav class="tabs" aria-label="Patchdeck Navigation">
        <a class="{services_active}" href="/">Dienste</a>
        <a class="{settings_active}" href="/settings">Einstellungen</a>
      </nav>
      <div class="summary">
        <span id="summary-services">0 Dienste</span>
        <span id="summary-imports">Docker Scan bereit</span>
      </div>
    </header>

    <section id="services-view" {services_view}>
      <div class="toolbar">
        <div>
          <h2>Dienste</h2>
          <p>Konfigurierte Update-Ziele und Docker-Import-Kandidaten.</p>
        </div>
        <div class="actions compact">
          <button type="button" onclick="loadServicesView()">Aktualisieren</button>
          <button type="button" class="secondary" onclick="loadDockerCandidates()">Docker scannen</button>
        </div>
      </div>
      <div id="services" class="stack notice">Lade Dienste...</div>

      <section class="card form-card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">+</div>
            <h2>Dienst anlegen</h2>
          </div>
          <span class="badge warn">Manuell</span>
        </div>
        <div class="grid form-grid">
          <label><span>ID</span><input id="service-id" placeholder="homeassistant"></label>
          <label><span>Name</span><input id="service-name" placeholder="Home Assistant"></label>
          <label><span>Policy</span><select id="service-policy"><option>manual</option><option>auto</option><option>disabled</option></select></label>
          <label><span>Aktiv</span><select id="service-enabled"><option value="true">true</option><option value="false">false</option></select></label>
        </div>
        <div class="actions"><button type="button" onclick="saveService()">Dienst speichern</button></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">~</div>
            <h2>Docker Import</h2>
          </div>
          <span class="badge ok">Read-only</span>
        </div>
        <div id="docker-candidates" class="notice import-list">Docker Scan starten, um Container zu importieren.</div>
      </section>
    </section>

    <section id="settings-view" {settings_view}>
      <section class="card">
        <div class="card-head">
          <div class="identity">
            <div class="logo placeholder" aria-hidden="true">S</div>
            <h2>Einstellungen</h2>
          </div>
          <span class="badge ok">Global</span>
        </div>
        <div class="grid form-grid settings-grid">
          <label><span>Update-Intervall Minuten</span><input id="update-interval" type="number" min="1"></label>
          <label><span>MQTT aktiv</span><select id="mqtt-enabled"><option value="false">false</option><option value="true">true</option></select></label>
          <label><span>MQTT Discovery Prefix</span><input id="mqtt-prefix"></label>
          <label><span>MQTT Base Topic</span><input id="mqtt-topic"></label>
          <label><span>Docker Auto Import</span><select id="docker-import"><option value="true">true</option><option value="false">false</option></select></label>
          <label><span>Farbschema</span><select id="theme"><option>system</option><option>dark</option><option>light</option></select></label>
        </div>
        <div class="actions"><button type="button" onclick="saveSettings()">Einstellungen speichern</button></div>
      </section>
    </section>

    <footer>Testversion. Noch kein echter Update-Executor.</footer>
  </main>
  <script>{JS}
  {script_boot}
  </script>
</body>
</html>'''


CSS = r'''
:root { color-scheme: dark; --bg:#0f172a; --panel:#111c31; --panel2:#15233b; --text:#e5edf7; --muted:#9fb0c8; --line:#263750; --purple:#8b5cf6; --blue:#2563eb; --danger:#b42318; }
* { box-sizing:border-box; }
body { margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:radial-gradient(circle at top left,#1e3a8a55,transparent 34rem),var(--bg); color:var(--text); }
.shell { max-width:980px; margin:0 auto; padding:34px 16px 48px; }
header { margin-bottom:20px; }
.eyebrow { margin:0 0 5px; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
h1 { margin:0; font-size:clamp(34px,5vw,54px); letter-spacing:0; }
h2 { margin:0; font-size:22px; letter-spacing:0; overflow-wrap:anywhere; }
p { margin:6px 0 0; color:var(--muted); }
.tabs { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
.tabs a { display:inline-flex; align-items:center; min-height:38px; padding:8px 12px; border-radius:999px; border:1px solid var(--line); color:var(--muted); background:#0b1222aa; text-decoration:none; font-weight:900; font-size:13px; }
.tabs a.active { color:#fff; background:linear-gradient(135deg,var(--purple),var(--blue)); border-color:#60a5fa66; box-shadow:0 8px 30px #2563eb44; }
.summary { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.summary span { display:inline-flex; margin:0; padding:7px 10px; border:1px solid var(--line); border-radius:999px; background:#0b1222aa; color:var(--muted); font-weight:800; font-size:12px; }
.toolbar { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin:0 0 14px; }
.stack { display:grid; gap:14px; }
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
.grid div, .field, label { background:#0b1222aa; border:1px solid #24344d; border-radius:14px; padding:12px; min-width:0; }
span { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
strong { display:block; overflow-wrap:anywhere; }
code { display:block; margin-top:8px; padding:10px; border-radius:12px; background:#0b1222aa; border:1px solid #24344d; color:#cbd5e1; overflow-wrap:anywhere; }
.actions { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-top:18px; }
.actions.compact { margin-top:0; }
button { appearance:none; border:0; cursor:pointer; border-radius:12px; padding:11px 14px; color:white; background:linear-gradient(135deg,var(--purple),var(--blue)); font-weight:800; box-shadow:0 8px 30px #2563eb44; }
button:hover { filter:brightness(1.08); }
button:disabled { cursor:not-allowed; opacity:.65; filter:saturate(.6); }
button.secondary { background:#0b1222aa; border:1px solid var(--line); box-shadow:none; color:#dbeafe; }
button.danger { background:linear-gradient(135deg,#b42318,#dc2626); box-shadow:0 8px 30px #dc262644; }
input, select { width:100%; min-height:38px; border:1px solid #30445f; border-radius:10px; padding:9px 10px; background:#090f1dcc; color:var(--text); font:inherit; }
label { display:grid; gap:5px; color:var(--muted); font-size:13px; }
.form-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
.settings-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
.notice { color:var(--muted); }
.import-list { margin-top:14px; }
.candidate { display:grid; grid-template-columns:minmax(170px,1fr) minmax(220px,1.2fr) minmax(130px,.7fr) auto; gap:10px; align-items:center; border-top:1px solid var(--line); padding:12px 0; }
.candidate:first-child { border-top:0; }
footer { color:#718096; margin-top:22px; font-size:12px; }
[hidden] { display:none !important; }
@media (max-width:760px) {
  .toolbar, .card-head { align-items:flex-start; flex-direction:column; }
  .identity { gap:10px; }
  .logo { width:38px; height:38px; flex-basis:38px; }
  h2 { font-size:20px; }
  .grid, .form-grid, .settings-grid { grid-template-columns:1fr; }
  .candidate { grid-template-columns:1fr; }
}
'''


JS = r'''
const api = (path, options = {}) => fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
const text = value => String(value ?? '');
const esc = value => text(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

async function refreshSummary() {
  const services = await (await api('/api/services')).json();
  document.querySelector('#summary-services').textContent = services.length + (services.length === 1 ? ' Dienst' : ' Dienste');
  return services;
}

async function loadServicesView() {
  const services = await refreshSummary();
  renderServices(services);
}

function renderServices(services) {
  const target = document.querySelector('#services');
  if (!services.length) {
    target.innerHTML = '<section class="card"><div class="notice">Noch keine Dienste konfiguriert.</div></section>';
    return;
  }
  target.innerHTML = services.map(service => {
    const badgeClass = service.enabled ? 'ok' : 'warn';
    const badgeText = service.enabled ? 'Aktiv' : 'Deaktiviert';
    const metadata = service.metadata || {};
    return '<section class="card">' +
      '<div class="card-head">' +
        '<div class="identity"><div class="logo placeholder" aria-hidden="true">~</div><h2>' + esc(service.name) + '</h2></div>' +
        '<span class="badge ' + badgeClass + '">' + badgeText + '</span>' +
      '</div>' +
      '<div class="grid">' +
        '<div><span>ID</span><strong>' + esc(service.id) + '</strong></div>' +
        '<div><span>Adapter</span><strong>' + esc(service.adapter) + '</strong></div>' +
        '<div><span>Policy</span><strong>' + esc(service.update_policy) + '</strong></div>' +
        '<div><span>Container</span><strong>' + esc(metadata.container || '—') + '</strong></div>' +
      '</div>' +
      '<code>' + esc(JSON.stringify(metadata)) + '</code>' +
      '<div class="actions">' +
        '<button type="button" class="secondary" onclick="fillService(\'' + esc(service.id) + '\')">Bearbeiten</button>' +
        '<button type="button" class="danger" onclick="deleteService(\'' + esc(service.id) + '\')">Löschen</button>' +
      '</div>' +
    '</section>';
  }).join('');
}

async function fillService(id) {
  const services = await (await api('/api/services')).json();
  const service = services.find(item => item.id === id);
  if (!service) return;
  document.querySelector('#service-id').value = service.id;
  document.querySelector('#service-name').value = service.name;
  document.querySelector('#service-policy').value = service.update_policy;
  document.querySelector('#service-enabled').value = String(service.enabled);
}

async function saveService() {
  const id = document.querySelector('#service-id').value.trim();
  const payload = {
    id,
    name: document.querySelector('#service-name').value.trim(),
    adapter: 'docker',
    enabled: document.querySelector('#service-enabled').value === 'true',
    update_policy: document.querySelector('#service-policy').value,
    metadata: {}
  };
  await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
  await loadServicesView();
}

async function deleteService(id) {
  await api('/api/services/' + encodeURIComponent(id), {method: 'DELETE'});
  await loadServicesView();
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
  document.querySelector('#summary-imports').textContent = candidates.length + ' Docker Kandidaten';
  if (!candidates.length) {
    target.textContent = 'Keine Docker Container gefunden.';
    return;
  }
  target.innerHTML = candidates.map(candidate =>
    '<div class="candidate">' +
      '<div><span>Container</span><strong>' + esc(candidate.name) + '</strong><code>' + esc(candidate.id) + '</code></div>' +
      '<div><span>Image</span><strong>' + esc(candidate.image) + '</strong></div>' +
      '<div><span>Compose</span><strong>' + esc(candidate.compose_project || '—') + '</strong><code>' + esc(candidate.compose_service || '—') + '</code></div>' +
      '<button type="button" ' + (candidate.already_configured ? 'disabled' : '') + ' onclick="importCandidate(\'' + esc(candidate.id) + '\')">' + (candidate.already_configured ? 'Importiert' : 'Import') + '</button>' +
    '</div>'
  ).join('');
}

async function importCandidate(id) {
  await api('/api/import/docker/' + encodeURIComponent(id), {method: 'POST'});
  await Promise.all([loadServicesView(), loadDockerCandidates()]);
}

async function loadSettingsView() {
  await refreshSummary();
  const data = await (await api('/api/settings')).json();
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
  await loadSettingsView();
}
'''
