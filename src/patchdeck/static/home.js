let homeServiceOrder = [];

async function loadHome({preserveOrder = false} = {}) {
  const settingsRequest = api('/api/settings');
  const statusRequest = api('/api/status');
  let settings = null;
  try {
    settings = await (await settingsRequest).json();
  } catch {
    // Fall back to English while the status request continues in parallel.
  }
  await loadLanguagePreference(settings);
  const response = await statusRequest;
  const statuses = await response.json();
  document.querySelector('#summary-services').textContent = serviceCountText(statuses.length);
  updateAllButton(statuses);
  renderServiceCards(orderHomeServices(statuses, preserveOrder));
  refreshIcons();
}

function orderHomeServices(statuses, preserveOrder) {
  if (!preserveOrder || !homeServiceOrder.length) {
    homeServiceOrder = statuses.map(service => service.service_id);
    return statuses;
  }
  const byId = new Map(statuses.map(service => [service.service_id, service]));
  const ordered = homeServiceOrder.map(id => byId.get(id)).filter(Boolean);
  const newServices = statuses.filter(service => !homeServiceOrder.includes(service.service_id));
  homeServiceOrder.push(...newServices.map(service => service.service_id));
  return [...ordered, ...newServices];
}

function updateAllButton(statuses) {
  const button = document.querySelector('#update-all');
  if (!button) return;
  const count = statuses.filter(service => service.update_available && service.update_enabled).length;
  button.hidden = count === 0;
  button.disabled = count === 0;
  if (count) button.querySelector('span').textContent = count + ' ' + tr('updatesInstall');
}

async function runAllUpdates() {
  const button = document.querySelector('#update-all');
  if (button) button.disabled = true;
  try {
    const response = await api('/api/updates', {method: 'POST', body: '{}'});
    if (!response.ok) throw new Error('Updates could not be queued');
    const payload = await response.json();
    await loadHome({preserveOrder: true});
    await waitForUpdateJobs((payload.jobs || []).map(job => job.id));
  } finally {
    await loadHome({preserveOrder: true});
  }
}

function renderServiceCards(statuses) {
  const target = document.querySelector('#services');
  if (!statuses.length) {
    target.innerHTML = '<section class="card"><div class="notice">' + esc(tr('noServices')) + '</div></section>';
    return;
  }
  target.innerHTML = statuses.map(service => {
    const incomplete = !service.latest_version;
    const badgeClass = service.update_in_progress ? 'progress' : (incomplete ? 'warn' : (service.update_available ? 'update' : 'ok'));
    const badgeLabel = service.update_in_progress ? tr('updateRunning') : (service.update_available ? tr('updateAvailable') : (incomplete ? tr('incomplete') : tr('upToDate')));
    const badgeIcon = service.update_in_progress ? '<span class="spinner" aria-hidden="true"></span>' : '<i data-lucide="' + (service.update_available ? 'download' : (incomplete ? 'circle-alert' : 'check')) + '" aria-hidden="true"></i>';
    const badgeContent = badgeIcon + '<span>' + esc(badgeLabel) + '</span>';
    const badge = service.update_available && service.update_enabled && !service.update_in_progress
      ? '<button type="button" class="badge badge-action ' + badgeClass + '" data-action="run-update" data-service-id="' + esc(service.service_id) + '">' + badgeContent + '</button>'
      : '<span class="badge ' + badgeClass + '">' + badgeContent + '</span>';
    const availableVersion = versionHtml(service.latest_version || tr('notChecked'), service.release_notes_url);
    const lastRun = service.last_run
      ? '<div class="last-run"><span>' + esc(tr('lastUpdate')) + '</span><strong>' + esc(service.last_run.ok ? tr('success') : tr('error')) + ' · ' + esc(formatTs(service.last_run.ts)) + '</strong></div>'
      : '';
    return '<section class="card" data-service="' + esc(service.id) + '">' +
      '<div class="card-head service-card-head">' +
        '<div class="identity">' + logoHtml(service) + '<h2>' + esc(service.name) + '</h2></div>' +
        badge +
      '</div>' +
      '<div class="grid">' +
        '<div><span>' + esc(tr('container')) + '</span><strong>' + esc(service.container) + '</strong></div>' +
        '<div><span>' + esc(tr('status')) + '</span><strong data-role="container-state">' + esc(service.state) + '</strong></div>' +
        '<div><span>' + esc(tr('installed')) + '</span><strong>' + esc(service.current_version || tr('notChecked')) + '</strong></div>' +
        '<div><span>' + esc(tr('available')) + '</span><strong>' + availableVersion + '</strong></div>' +
      '</div>' +
      '<details><summary>' + esc(tr('image')) + '</summary><code>' + esc(service.image || '—') + '</code></details>' +
      lastRun +
    '</section>';
  }).join('');
}

function formatTs(value) {
  if (!value) return '—';
  const locale = currentLanguage === 'de' ? 'de-DE' : 'en-US';
  return new Date(Number(value) * 1000).toLocaleString(locale, {dateStyle: 'short', timeStyle: 'short'});
}

function versionHtml(value, releaseUrl) {
  if (!releaseUrl) return esc(value);
  return '<a class="version-link" href="' + esc(releaseUrl) + '" target="_blank" rel="noreferrer">' + esc(value) + '</a>';
}

async function runUpdate(id) {
  const card = document.querySelector('.card[data-service="' + CSS.escape(id) + '"]');
  const badge = card?.querySelector('.badge-action');
  const state = card?.querySelector('[data-role="container-state"]');
  if (badge) {
    badge.disabled = true;
    badge.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>' + esc(tr('updateRunning')) + '</span>';
  }
  if (state) state.textContent = tr('updateStarting');
  try {
    const response = await api('/api/services/' + encodeURIComponent(id) + '/update', {method: 'POST', body: '{}'});
    if (!response.ok) throw new Error('Update could not be queued');
    const payload = await response.json();
    await waitForUpdateJob(payload.job?.id);
  } finally {
    await loadHome({preserveOrder: true});
  }
}

async function waitForUpdateJob(jobId) {
  await waitForUpdateJobs([jobId]);
}

async function waitForUpdateJobs(jobIds) {
  const pending = new Set(jobIds.filter(Boolean));
  if (!pending.size) return;
  const deadline = Date.now() + 600000;
  while (pending.size && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 2000));
    try {
      const response = await api('/api/update-queue');
      if (!response.ok) continue;
      const queue = await response.json();
      [queue.active, ...(queue.pending || []), ...(queue.recent || [])].forEach(job => {
        if (job && pending.has(job.id) && (job.state === 'succeeded' || job.state === 'failed')) pending.delete(job.id);
      });
    } catch (error) {
      // Patchdeck may briefly restart itself during a self-update.
    }
  }
}

loadHome();
