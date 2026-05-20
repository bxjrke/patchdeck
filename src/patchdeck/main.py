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
    return HTML


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


HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Patchdeck</title>
  <style>
    :root { color-scheme: light dark; --bg:#f6f7f9; --panel:#fff; --text:#16181d; --muted:#606876; --line:#d8dde6; --accent:#1768ac; --danger:#b42318; }
    @media (prefers-color-scheme: dark) { :root { --bg:#101216; --panel:#181b21; --text:#f3f5f8; --muted:#9ca3af; --line:#303642; --accent:#58a6ff; --danger:#ff7b72; } }
    * { box-sizing: border-box; }
    body { margin: 0; font: 15px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 22px 24px 12px; border-bottom: 1px solid var(--line); background: var(--panel); }
    main { max-width: 1180px; margin: 0 auto; padding: 20px 16px 40px; display: grid; gap: 18px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 18px; }
    p { margin: 6px 0 0; color: var(--muted); }
    section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
    label { display: grid; gap: 5px; color: var(--muted); font-size: 13px; }
    input, select { width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 9px 10px; background: transparent; color: var(--text); font: inherit; }
    button { border: 1px solid var(--line); border-radius: 6px; background: var(--accent); color: white; padding: 9px 12px; font: inherit; cursor: pointer; }
    button.secondary { background: transparent; color: var(--text); }
    button.danger { background: var(--danger); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
    code { color: var(--muted); overflow-wrap: anywhere; }
    .pill { display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--muted); font-size: 12px; }
    .split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 360px); gap: 18px; }
    .notice { color: var(--muted); }
    @media (max-width: 860px) { .split { grid-template-columns: 1fr; } table { font-size: 13px; } }
  </style>
</head>
<body>
  <header>
    <h1>Patchdeck</h1>
    <p>Service-oriented update control for the homelab.</p>
  </header>
  <main>
    <div class="split">
      <section>
        <h2>Services</h2>
        <div class="actions">
          <button onclick="loadAll()">Refresh</button>
          <button class="secondary" onclick="loadDockerCandidates()">Scan Docker</button>
        </div>
        <div id="services" class="notice">Loading...</div>
      </section>
      <section>
        <h2>Add / Edit Service</h2>
        <div class="grid">
          <label>ID <input id="service-id" placeholder="homeassistant"></label>
          <label>Name <input id="service-name" placeholder="Home Assistant"></label>
          <label>Policy <select id="service-policy"><option>manual</option><option>auto</option><option>disabled</option></select></label>
          <label>Enabled <select id="service-enabled"><option value="true">true</option><option value="false">false</option></select></label>
        </div>
        <div class="actions"><button onclick="saveService()">Save Service</button></div>
      </section>
    </div>

    <section>
      <h2>Settings</h2>
      <div class="grid">
        <label>Update interval minutes <input id="update-interval" type="number" min="1"></label>
        <label>MQTT enabled <select id="mqtt-enabled"><option value="false">false</option><option value="true">true</option></select></label>
        <label>MQTT discovery prefix <input id="mqtt-prefix"></label>
        <label>MQTT base topic <input id="mqtt-topic"></label>
        <label>Docker auto import <select id="docker-import"><option value="true">true</option><option value="false">false</option></select></label>
        <label>Theme <select id="theme"><option>system</option><option>light</option><option>dark</option></select></label>
      </div>
      <div class="actions"><button onclick="saveSettings()">Save Settings</button></div>
    </section>

    <section>
      <h2>Docker Import Candidates</h2>
      <div id="docker-candidates" class="notice">Run a Docker scan to import containers.</div>
    </section>
  </main>
  <script>
    const api = (path, options = {}) => fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
    const text = value => String(value ?? '');

    async function loadAll() {
      await Promise.all([loadSettings(), loadServices()]);
    }

    async function loadSettings() {
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
      await loadSettings();
    }

    async function loadServices() {
      const data = await (await api('/api/services')).json();
      const target = document.querySelector('#services');
      if (!data.length) { target.textContent = 'No services configured yet.'; return; }
      target.innerHTML = '<table><thead><tr><th>Name</th><th>Policy</th><th>State</th><th>Metadata</th><th></th></tr></thead><tbody>' +
        data.map(s => '<tr><td><strong>' + text(s.name) + '</strong><br><code>' + text(s.id) + '</code></td><td><span class="pill">' + text(s.update_policy) + '</span></td><td>' + (s.enabled ? 'enabled' : 'disabled') + '</td><td><code>' + text(JSON.stringify(s.metadata || {})) + '</code></td><td><button class="danger" onclick="deleteService(\'' + s.id + '\')">Delete</button></td></tr>').join('') +
        '</tbody></table>';
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
      await loadServices();
    }

    async function deleteService(id) {
      await api('/api/services/' + encodeURIComponent(id), {method: 'DELETE'});
      await loadServices();
    }

    async function loadDockerCandidates() {
      const target = document.querySelector('#docker-candidates');
      target.textContent = 'Scanning Docker...';
      const response = await api('/api/import/docker');
      if (!response.ok) { target.textContent = (await response.json()).detail || 'Docker scan failed.'; return; }
      const data = await response.json();
      if (!data.length) { target.textContent = 'No Docker containers found.'; return; }
      target.innerHTML = '<table><thead><tr><th>Container</th><th>Image</th><th>Compose</th><th>Status</th><th></th></tr></thead><tbody>' +
        data.map(c => '<tr><td><strong>' + text(c.name) + '</strong><br><code>' + text(c.id) + '</code></td><td><code>' + text(c.image) + '</code></td><td>' + text(c.compose_project || '') + '<br><code>' + text(c.compose_service || '') + '</code></td><td>' + text(c.state) + (c.already_configured ? '<br><span class="pill">configured</span>' : '') + '</td><td><button ' + (c.already_configured ? 'disabled' : '') + ' onclick="importCandidate(\'' + c.id + '\')">Import</button></td></tr>').join('') +
        '</tbody></table>';
    }

    async function importCandidate(id) {
      await api('/api/import/docker/' + encodeURIComponent(id), {method: 'POST'});
      await Promise.all([loadServices(), loadDockerCandidates()]);
    }

    loadAll();
  </script>
</body>
</html>'''
