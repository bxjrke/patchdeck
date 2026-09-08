let settingsLoaded = false;
let settingsSaveTimer = null;
let settingsSaveVersion = 0;
let settingsSaveField = null;
let mqttPasswordDirty = false;

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
  applyTheme(data.theme);
  await selectLanguage(data.language || 'en');
  applyI18n();
  await getServices();
  document.querySelector('#update-interval').value = data.update_interval_minutes;
  document.querySelector('#language').value = currentLanguage;
  document.querySelector('#mqtt-enabled').checked = Boolean(data.mqtt_enabled);
  document.querySelector('#mqtt-host').value = data.mqtt_host || '';
  document.querySelector('#mqtt-port').value = data.mqtt_port || 1883;
  document.querySelector('#mqtt-user').value = data.mqtt_user || '';
  document.querySelector('#mqtt-password').value = '';
  mqttPasswordDirty = false;
  document.querySelector('#mqtt-prefix').value = data.mqtt_discovery_prefix;
  document.querySelector('#mqtt-topic').value = data.mqtt_base_topic;
  document.querySelector('#base-url').value = data.base_url || '';
  document.querySelector('#theme').value = data.theme;
  updateMqttVisibility();
  refreshIcons();
}

function renderSaveButtons() {
  document.querySelector('[data-save-action="create-service"]').innerHTML = saveButton('create-service', 'add');
}

function wireAutosaveSettings() {
  document.querySelector('#language').addEventListener('change', async event => {
    await selectLanguage(event.target.value);
    applyI18n();
    updateMqttVisibility();
    renderSaveButtons();
    loadServiceSettings();
    saveSettingsSoon(0, event.target);
  });
  document.querySelector('#theme').addEventListener('change', event => {
    applyTheme(event.target.value);
    saveSettingsSoon(0, event.target);
  });
  document.querySelector('#mqtt-enabled').addEventListener('change', event => {
    updateMqttVisibility();
    saveSettingsSoon(0, event.target);
  });
  document.querySelectorAll('#update-interval, #base-url, #mqtt-host, #mqtt-port, #mqtt-user, #mqtt-prefix, #mqtt-topic').forEach(node => {
    node.addEventListener('input', event => saveSettingsSoon(500, event.target));
    node.addEventListener('change', event => saveSettingsSoon(0, event.target));
  });
  const mqttPassword = document.querySelector('#mqtt-password');
  mqttPassword.addEventListener('input', event => { mqttPasswordDirty = true; saveSettingsSoon(500, event.target); });
  mqttPassword.addEventListener('change', event => { mqttPasswordDirty = true; saveSettingsSoon(0, event.target); });
}

function updateMqttVisibility() {
  const enabled = document.querySelector('#mqtt-enabled').checked;
  document.querySelector('#mqtt-fields').hidden = !enabled;
  document.querySelector('#mqtt-state-label').textContent = enabled ? tr('active') : tr('inactive');
}

function saveSettingsSoon(delay = 500, field = null) {
  if (!settingsLoaded) return;
  clearTimeout(settingsSaveTimer);
  settingsSaveField = field || settingsSaveField;
  const version = ++settingsSaveVersion;
  showSaveStatus(document.querySelector('#settings-save-status'), 'saving');
  settingsSaveTimer = setTimeout(() => saveSettings(version), delay);
}

function readSettingsPayload() {
  const payload = {
    update_interval_minutes: Number(document.querySelector('#update-interval').value),
    language: document.querySelector('#language').value,
    mqtt_enabled: document.querySelector('#mqtt-enabled').checked,
    mqtt_host: document.querySelector('#mqtt-host').value.trim(),
    mqtt_port: Number(document.querySelector('#mqtt-port').value || 1883),
    mqtt_user: document.querySelector('#mqtt-user').value.trim(),
    mqtt_discovery_prefix: document.querySelector('#mqtt-prefix').value,
    mqtt_base_topic: document.querySelector('#mqtt-topic').value,
    base_url: document.querySelector('#base-url').value.trim(),
    theme: document.querySelector('#theme').value
  };
  if (mqttPasswordDirty) payload.mqtt_password = document.querySelector('#mqtt-password').value;
  return payload;
}

function showSaveFeedback(field) {
  const target = field?.closest('label') || field;
  if (!target) return;
  clearTimeout(target.saveFeedbackTimer);
  target.classList.remove('save-success');
  void target.offsetWidth;
  target.classList.add('save-success');
  target.saveFeedbackTimer = setTimeout(() => target.classList.remove('save-success'), 1900);
}

function showSaveStatus(target, state, field = null) {
  if (!target) return;
  clearTimeout(target.saveStatusTimer);
  target.hidden = false;
  target.dataset.state = state;
  if (state === 'error') {
    target.innerHTML = '<span>' + esc(tr('saveFailed')) + '</span><button type="button" class="secondary" data-action="retry-save">' + esc(tr('retry')) + '</button>';
    return;
  }
  if (state === 'saved') {
    target.innerHTML = '<span class="sr-only">' + esc(tr('changesSaved')) + '</span>';
    showSaveFeedback(field);
    target.saveStatusTimer = setTimeout(() => { target.hidden = true; }, 1900);
    return;
  }
  target.textContent = tr('saving');
}

function retrySave(target) {
  const id = target?.dataset.serviceSaveStatus;
  if (id) {
    saveExistingServiceSoon(id, 0);
    return;
  }
  saveSettingsSoon(0);
}

async function saveSettings(version = settingsSaveVersion) {
  try {
    const response = await api('/api/settings', {method: 'PATCH', body: JSON.stringify(readSettingsPayload())});
    if (!response.ok) throw new Error('Settings save failed');
    if (version === settingsSaveVersion) {
      document.querySelector('#mqtt-password').value = '';
      mqttPasswordDirty = false;
      showSaveStatus(document.querySelector('#settings-save-status'), 'saved', settingsSaveField);
    }
  } catch {
    if (version === settingsSaveVersion) showSaveStatus(document.querySelector('#settings-save-status'), 'error');
  }
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
        '<button type="button" class="secondary icon-only service-settings-toggle" data-i18n-title="edit" title="' + esc(tr('edit')) + '" aria-expanded="false" data-action="toggle-service-settings" data-service-id="' + esc(service.id) + '"><i data-lucide="settings" aria-hidden="true"></i></button>' +
        '<button type="button" class="danger icon-only" data-i18n-title="delete" title="' + esc(tr('delete')) + '" data-action="delete-service" data-service-id="' + esc(service.id) + '" ' + (service.id === 'patchdeck' ? 'disabled aria-disabled="true"' : '') + '><i data-lucide="trash-2" aria-hidden="true"></i></button>' +
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
        '<button type="button" class="secondary" data-action="refresh-service" data-service-id="' + esc(service.id) + '"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>' + esc(tr('refresh')) + '</span></button>' +
      '</div>' +
      '<div class="autosave-status service-save-status" data-service-save-status="' + esc(service.id) + '" role="status" aria-live="polite" hidden></div>' +
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

function previewReleaseNotes(selector) {
  const source = document.querySelector(selector)?.value.trim();
  if (!source) {
    window.alert(tr('releaseNotesPreviewMissing'));
    return;
  }
  const url = source === 'homeassistant'
    ? 'https://www.home-assistant.io/blog/categories/release-notes/'
    : source.replaceAll('{version_url}', encodeURIComponent('1.2.3')).replaceAll('{version}', '1.2.3').replaceAll('{major}', '1').replaceAll('{minor}', '2').replaceAll('{patch}', '3');
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('unsupported protocol');
    window.open(parsed.href, '_blank', 'noopener,noreferrer');
  } catch (_error) {
    window.alert(tr('releaseNotesPreviewInvalid'));
  }
}

const serviceSaveTimers = {};
const serviceSaveVersions = {};
const serviceSaveFields = {};

function wireServiceAutosave() {
  document.querySelectorAll('.service-config').forEach(section => {
    const id = section.dataset.serviceConfig;
    section.querySelectorAll('input').forEach(node => {
      node.addEventListener('input', event => saveExistingServiceSoon(id, 500, event.target));
      node.addEventListener('change', event => saveExistingServiceSoon(id, 0, event.target));
    });
  });
}

function saveExistingServiceSoon(id, delay = 500, field = null) {
  clearTimeout(serviceSaveTimers[id]);
  serviceSaveFields[id] = field || serviceSaveFields[id];
  const version = (serviceSaveVersions[id] || 0) + 1;
  serviceSaveVersions[id] = version;
  showSaveStatus(document.querySelector('[data-service-save-status="' + CSS.escape(id) + '"]'), 'saving');
  serviceSaveTimers[id] = setTimeout(() => saveExistingService(id, version), delay);
}

async function saveExistingService(id, version = serviceSaveVersions[id]) {
  try {
    const payload = readServicePayload(id, '#edit-', id);
    const response = await api('/api/services/' + encodeURIComponent(id), {method: 'PUT', body: JSON.stringify(payload)});
    if (!response.ok) throw new Error('Service save failed');
    const service = await response.json();
    const section = document.querySelector('.service-config[data-service-config="' + CSS.escape(id) + '"]');
    if (section) {
      section.dataset.iconSlug = service.icon_slug || '';
      section.dataset.image = service.image || '';
      section.dataset.composeFile = service.compose_file || '';
      section.dataset.composeProjectDir = service.compose_project_dir || '';
      section.dataset.composeService = service.compose_service || '';
    }
    if (version === serviceSaveVersions[id]) showSaveStatus(document.querySelector('[data-service-save-status="' + CSS.escape(id) + '"]'), 'saved', serviceSaveFields[id]);
  } catch {
    if (version === serviceSaveVersions[id]) showSaveStatus(document.querySelector('[data-service-save-status="' + CSS.escape(id) + '"]'), 'error');
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
  if (!candidates.length) {
    target.textContent = tr('noContainers');
    return;
  }
  target.innerHTML = candidates.map(candidate =>
    '<div class="candidate">' +
      '<div><span>' + esc(tr('container')) + '</span><strong>' + esc(candidate.name) + '</strong><code>' + esc(candidate.id) + '</code></div>' +
      '<div><span>' + esc(tr('image')) + '</span><strong>' + esc(candidate.image) + '</strong></div>' +
      '<div><span>' + esc(tr('compose')) + '</span><strong>' + esc(candidate.compose_project || '-') + '</strong><code>' + esc(candidate.compose_service || '-') + '</code></div>' +
      '<button type="button" ' + (candidate.already_configured ? 'disabled' : '') + ' data-action="import-candidate" data-service-id="' + esc(candidate.id) + '"><i data-lucide="' + (candidate.already_configured ? 'check' : 'download') + '" aria-hidden="true"></i><span>' + (candidate.already_configured ? esc(tr('imported')) : esc(tr('import'))) + '</span></button>' +
    '</div>'
  ).join('');
  refreshIcons();
}

async function importCandidate(id) {
  await api('/api/import/docker/' + encodeURIComponent(id), {method: 'POST'});
  await Promise.all([loadServiceSettings(), loadDockerCandidates()]);
}

loadSettingsPage();
