let homeServiceOrder = [];
let homeStatuses = [];
let homeQueue = {active: null, pending: [], recent: []};
let homeQueueSignature = '';
let homeUpdateBatch = null;
let homeQueueRequest = null;
let homePreferencesLoaded = false;
let homeSubmitting = false;

async function loadHome({preserveOrder = false} = {}) {
  const statusRequest = api('/api/status');
  const queueRequest = api('/api/update-queue').catch(() => null);
  if (!homePreferencesLoaded) {
    await loadLanguagePreference();
    homePreferencesLoaded = true;
  }
  const response = await statusRequest;
  if (!response.ok) throw new Error('Could not load service status');
  const statuses = await response.json();
  let queue = homeQueue;
  try {
    const queueResponse = await queueRequest;
    if (queueResponse?.ok) queue = await queueResponse.json();
  } catch {
    // Status cards still work when the queue endpoint is briefly unavailable.
  }
  applyHomeSnapshot(statuses, queue, preserveOrder);
}

function applyHomeSnapshot(statuses, queue = homeQueue, preserveOrder = false) {
  homeStatuses = orderHomeServices(statuses, preserveOrder);
  homeQueue = queue || {active: null, pending: [], recent: []};
  homeQueueSignature = queueSignature(homeQueue);
  document.querySelector('#summary-services').textContent = serviceCountText(homeStatuses.length);
  updateAllButton(homeStatuses, homeQueue);
  renderServiceCards(homeStatuses, homeQueue);
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

function queueSignature(queue) {
  const jobs = [queue?.active, ...(queue?.pending || [])].filter(Boolean);
  return JSON.stringify(jobs.map(job => [
    job.id,
    job.service_id,
    job.state,
    job.phase,
    job.update_percentage,
  ]));
}

function queueJobs(queue) {
  return [queue?.active, ...(queue?.pending || [])].filter(Boolean);
}

function updateAllButton(statuses, queue = homeQueue) {
  const button = document.querySelector('#update-all');
  if (!button) return;
  const activeJobs = queue?.active ? [queue.active] : [];
  const pendingJobs = queue?.pending || [];
  const runningServices = statuses.filter(service => service.update_in_progress);
  const busy = Boolean(homeSubmitting || homeUpdateBatch || activeJobs.length || pendingJobs.length || runningServices.length);

  if (busy) {
    const runningCount = Math.max(
      activeJobs.length + pendingJobs.length,
      runningServices.length,
      1,
    );
    const completed = homeUpdateBatch ? (queue.recent || []).filter(job => homeUpdateBatch.jobIds.includes(job.id)).length : 0;
    const label = homeSubmitting || homeUpdateBatch?.starting
      ? tr('updateStartingAll')
      : (homeUpdateBatch ? completed + '/' + homeUpdateBatch.total + ' ' + tr('updatesCompleted')
        : runningCount + ' ' + (runningCount === 1 ? tr('updateRunningSingular') : tr('updateRunningPlural')));
    button.hidden = false;
    button.disabled = true;
    button.classList.add('is-busy');
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-label', label);
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>' + esc(label) + '</span>';
    return;
  }

  button.classList.remove('is-busy');
  button.removeAttribute('aria-busy');
  const count = statuses.filter(service => service.update_available && service.update_enabled).length;
  button.hidden = count === 0;
  button.disabled = count === 0;
  if (count) {
    const label = count === 1 ? tr('updateInstallSingle') : count + ' ' + tr('updatesInstall');
    button.setAttribute('aria-label', label);
    button.innerHTML = '<i data-lucide="list-restart" aria-hidden="true"></i><span>' + esc(label) + '</span>';
  }
}

async function runAllUpdates() {
  if (homeSubmitting || homeUpdateBatch || queueJobs(homeQueue).length) return;
  const serviceIds = homeStatuses
    .filter(service => service.update_available && service.update_enabled && !service.update_in_progress)
    .map(service => service.service_id);
  if (!serviceIds.length) return loadHome({preserveOrder: true});

  homeUpdateBatch = {total: serviceIds.length, starting: true, jobIds: []};
  showHomeFeedback('');
  updateAllButton(homeStatuses, homeQueue);
  try {
    const response = await api('/api/updates', {
      method: 'POST',
      body: JSON.stringify({service_ids: serviceIds}),
    });
    if (!response.ok) throw new Error('Updates could not be queued');
    const payload = await response.json();
    homeUpdateBatch.starting = false;
    homeUpdateBatch.jobIds = (payload.jobs || []).map(job => job.id).filter(Boolean);
    homeUpdateBatch.total = homeUpdateBatch.jobIds.length;
    applyQueueSnapshot({...homeQueue, pending: [...(homeQueue.pending || []), ...(payload.jobs || []).filter(job => job.state === 'queued')]});
    await waitForUpdateJobs(homeUpdateBatch.jobIds);
  } catch (error) {
    showHomeFeedback(tr('updateFailed'));
    console.error('Patchdeck update-all failed', error);
  } finally {
    homeUpdateBatch = null;
    await loadHome({preserveOrder: true});
  }
}

function updateJobForService(serviceId, queue = homeQueue) {
  if (queue?.active?.service_id === serviceId) {
    return {...queue.active, position: 0};
  }
  const index = (queue?.pending || []).findIndex(job => job.service_id === serviceId);
  return index === -1 ? null : {...queue.pending[index], position: index + 1};
}

function updateProgressHtml(service, job, running, queued) {
  if (!running && !queued) return '';
  const rawPercentage = job?.update_percentage ?? service.update_percentage;
  const percentage = rawPercentage != null && Number.isFinite(Number(rawPercentage))
    ? Math.max(0, Math.min(100, Number(rawPercentage)))
    : null;
  const label = running ? tr('updateRunning') : tr('updateQueued');
  const meta = percentage === null ? '' : '<strong>' + percentage + '%</strong>';
  const queueLabel = queued && job?.position ? ' · ' + tr('queuePosition') + ' ' + job.position : '';
  const value = percentage === null || queued ? '' : ' value="' + percentage + '"';
  return '<div class="update-progress" role="status">' +
    '<div class="update-progress-label"><span>' + esc(label + queueLabel) + '</span>' + meta + '</div>' +
    '<progress class="progress-track" max="100"' + value + ' aria-label="' + esc(label) + '"></progress>' +
    '</div>';
}

function renderServiceCards(statuses, queue = homeQueue) {
  const target = document.querySelector('#services');
  const expanded = new Set([...target.querySelectorAll('.card details[open]')].map(node => node.closest('.card').dataset.service));
  if (!statuses.length) {
    target.innerHTML = '<section class="card"><div class="notice">' + esc(tr('noServices')) + '</div></section>';
    return;
  }
  target.innerHTML = statuses.map(service => {
    const job = updateJobForService(service.service_id, queue);
    const queued = job?.state === 'queued';
    const running = Boolean(service.update_in_progress || job?.state === 'running');
    const busy = queued || running;
    const incomplete = !service.latest_version;
    const badgeClass = running ? 'progress' : (queued ? 'queue' : (incomplete ? 'warn' : (service.update_available ? 'update' : 'ok')));
    const badgeLabel = running ? tr('updateRunning') : (queued ? tr('updateQueued') : (service.update_available ? tr('updateAvailable') : (incomplete ? tr('incomplete') : tr('upToDate'))));
    const badgeIcon = running
      ? '<span class="spinner" aria-hidden="true"></span>'
      : (queued ? '<i data-lucide="list-restart" aria-hidden="true"></i>' : '<i data-lucide="' + (service.update_available ? 'download' : (incomplete ? 'circle-alert' : 'check')) + '" aria-hidden="true"></i>');
    const badgeContent = badgeIcon + '<span>' + esc(badgeLabel) + '</span>';
    const badge = service.update_available && service.update_enabled && !busy
      ? '<button type="button" class="badge badge-action ' + badgeClass + '" data-action="run-update" data-service-id="' + esc(service.service_id) + '">' + badgeContent + '</button>'
      : '<span class="badge ' + badgeClass + '">' + badgeContent + '</span>';
    const availableVersion = versionHtml(service.latest_version || tr('notChecked'), service.release_notes_url);
    const lastRun = service.last_run
      ? '<div class="last-run"><span>' + esc(tr('lastUpdate')) + '</span><strong>' + esc(service.last_run.ok ? tr('success') : tr('error')) + ' · ' + esc(formatTs(service.last_run.ts)) + '</strong></div>'
      : '';
    const cardClass = ['card', running ? 'is-updating' : '', queued ? 'is-queued' : ''].filter(Boolean).join(' ');
    const state = queued ? tr('updateQueued') : (running ? updatePhaseText(job?.phase || service.state) : service.state);
    return '<section class="' + cardClass + '" data-service="' + esc(service.id || service.service_id) + '">' +
      '<div class="card-head service-card-head">' +
        '<div class="identity">' + logoHtml(service) + '<h2>' + esc(service.name) + '</h2></div>' +
        badge +
      '</div>' +
      updateProgressHtml(service, job, running, queued) +
      '<div class="grid">' +
        '<div><span>' + esc(tr('container')) + '</span><strong>' + esc(service.container || '—') + '</strong></div>' +
        '<div><span>' + esc(tr('status')) + '</span><strong data-role="container-state">' + esc(state || '—') + '</strong></div>' +
        '<div><span>' + esc(tr('installed')) + '</span><strong>' + esc(service.current_version || tr('notChecked')) + '</strong></div>' +
        '<div><span>' + esc(tr('available')) + '</span><strong>' + availableVersion + '</strong></div>' +
      '</div>' +
      '<details><summary>' + esc(tr('image')) + '</summary><code>' + esc(service.image || '—') + '</code></details>' +
      lastRun +
    '</section>';
  }).join('');
  target.querySelectorAll('.card').forEach(card => {
    if (expanded.has(card.dataset.service)) card.querySelector('details').open = true;
  });
}

function updatePhaseText(phase) {
  const keys = {'Preparing update': 'updatePreparing', 'Pulling image': 'updatePulling', 'Recreating': 'updateRecreating'};
  return keys[phase] ? tr(keys[phase]) : (phase || tr('updateRunning'));
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

function showHomeFeedback(message, state = 'error') {
  const feedback = document.querySelector('#home-feedback');
  if (!feedback) return;
  feedback.hidden = !message;
  feedback.dataset.state = state;
  feedback.textContent = message || '';
}

async function runUpdate(id) {
  if (homeSubmitting || homeUpdateBatch || updateJobForService(id)) return;
  homeSubmitting = true;
  updateAllButton(homeStatuses, homeQueue);
  const card = document.querySelector('.card[data-service="' + CSS.escape(id) + '"]');
  const badge = card?.querySelector('.badge-action');
  const state = card?.querySelector('[data-role="container-state"]');
  if (badge) {
    badge.disabled = true;
    badge.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>' + esc(tr('updateRunning')) + '</span>';
  }
  if (state) state.textContent = tr('updateStarting');
  showHomeFeedback('');
  try {
    const response = await api('/api/services/' + encodeURIComponent(id) + '/update', {method: 'POST', body: '{}'});
    if (!response.ok) throw new Error('Update could not be queued');
    const payload = await response.json();
    homeSubmitting = false;
    applyQueueSnapshot({...homeQueue, pending: [...(homeQueue.pending || []), ...(payload.job?.state === 'queued' ? [payload.job] : [])]});
    await waitForUpdateJob(payload.job?.id);
  } catch (error) {
    showHomeFeedback(tr('updateFailed'));
    throw error;
  } finally {
    homeSubmitting = false;
    await loadHome({preserveOrder: true});
  }
}

async function waitForUpdateJob(jobId) {
  await waitForUpdateJobs([jobId]);
}

async function loadQueueSnapshot() {
  if (homeQueueRequest) return homeQueueRequest;
  homeQueueRequest = (async () => {
    const response = await api('/api/update-queue');
    if (!response.ok) return null;
    const queue = await response.json();
    applyQueueSnapshot(queue);
    return queue;
  })();
  try { return await homeQueueRequest; }
  finally { homeQueueRequest = null; }
}

function applyQueueSnapshot(queue) {
  if (!queue) return;
  const previousJobIds = new Set(queueJobs(homeQueue).map(job => job.id));
  homeQueue = queue;
  const busyIds = new Set(queueJobs(queue).map(job => job.service_id));
  homeStatuses.forEach(service => {
    const completed = (queue.recent || []).filter(job => job.service_id === service.service_id && previousJobIds.has(job.id)).at(-1);
    if (!busyIds.has(service.service_id) && completed) {
      service.update_in_progress = false;
      if (completed.state === 'succeeded') service.update_available = false;
    }
  });
  updateAllButton(homeStatuses, homeQueue);
  const signature = queueSignature(homeQueue);
  if (signature === homeQueueSignature) return;
  homeQueueSignature = signature;
  if (homeStatuses.length) {
    renderServiceCards(homeStatuses, homeQueue);
    refreshIcons();
  }
}

async function waitForUpdateJobs(jobIds) {
  const pending = new Set(jobIds.filter(Boolean));
  if (!pending.size) {
    try { await loadQueueSnapshot(); } catch { /* Patchdeck may be restarting. */ }
    return;
  }
  const deadline = Date.now() + 600000;
  let failed = false;
  let delay = 250;
  while (pending.size && Date.now() < deadline) {
    try {
      const queue = await loadQueueSnapshot();
      if (queue) {
        queueJobs(queue).concat(queue.recent || []).forEach(job => {
          if (job && pending.has(job.id) && (job.state === 'succeeded' || job.state === 'failed')) {
            if (job.state === 'failed') failed = true;
            pending.delete(job.id);
          }
        });
      }
    } catch (error) {
      // Patchdeck may briefly restart itself during a self-update.
    }
    if (!pending.size) break;
    await new Promise(resolve => setTimeout(resolve, delay));
    delay = Math.min(1500, delay + 250);
  }
  if (failed) showHomeFeedback(tr('updateJobFailed'));
  else if (pending.size) showHomeFeedback(tr('updateStillRunning'));
  else showHomeFeedback(tr('updatesFinished'), 'success');
}

async function pollHomeQueue() {
  try {
    if (!document.hidden && !homeSubmitting && !homeUpdateBatch) {
      const previousIds = new Set(queueJobs(homeQueue).map(job => job.id));
      const queue = await loadQueueSnapshot();
      if (queue && (queue.recent || []).some(job => previousIds.has(job.id))) {
        await loadHome({preserveOrder: true});
      }
    }
  } catch {
    // Keep retrying through brief self-update restarts and network outages.
  } finally {
    setTimeout(pollHomeQueue, queueJobs(homeQueue).length ? 1500 : 15000);
  }
}

loadHome().then(() => setTimeout(pollHomeQueue, 1500)).catch(error => {
  showHomeFeedback(tr('statusLoadFailed'));
  console.error('Patchdeck status failed', error);
  setTimeout(pollHomeQueue, 1500);
});
